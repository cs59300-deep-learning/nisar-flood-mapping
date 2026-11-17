"""Inter-annotator agreement on the #29 calibration chips.

Each labeller draws the same five chips independently. This script rasterises
every labeller's polygons onto the chip grid and reports, for each pair, the
IoU of the water class and the fraction of pixels given the same class.

Pixels either labeller marked -1 are dropped before comparison: -1 means "I
cannot tell", so counting it as a disagreement would penalise abstention, and
counting it as agreement would reward two people for both giving up.

Annotations are read straight from git refs, so one person's working copy can
score branches they have never checked out. A ref of "." reads the working
tree instead.

    python scripts/calibration_agreement.py --out docs/evidence/calibration_agreement_report.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio import features, warp

CALIBRATION_CHIPS = [
    "N023_20260618_008000_013600",
    "N023_20260618_004400_010400",
    "N023_20260618_006400_012400",
    "N023_20260618_007600_011200",
    "N023_20260618_012000_004400",
]

# Ref each labeller's annotations are read from. "." means the working tree.
SOURCES = {
    "varunteja99": ".",
    "pushanverma": "origin/feature/labelling-pushanverma",
    "NidhiMusale": "origin/Nidhi-handlabelled-chips",
    "Yashada7": "origin/Yashada7/hand-labelled-chips",
}

# Chips where a labeller's polygons live under a non-standard filename.
FILENAME_OVERRIDES: dict[tuple[str, str], str] = {}

# Chips read from a commit other than the labeller's branch head.
REF_OVERRIDES: dict[tuple[str, str], str] = {}

ANNOTATION_DIR = "data/labels/annotations"
CHIP_DIR = "data/chips"
WATER, EXCLUDED, NO_DATA = 1, 2, -1


def _read_annotations(ref: str, path: str) -> dict | None:
    """Return the parsed GeoJSON at `path` in `ref`, or None if absent."""
    if ref == ".":
        file = Path(path)
        return json.loads(file.read_text()) if file.exists() else None
    done = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    return json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None


def _rasterise(collection: dict, chip_path: Path) -> np.ndarray:
    """Burn a labeller's polygons onto the chip's pixel grid.

    Classes are burned least-authoritative first so that water drawn over an
    excluded area wins, matching how label-export resolves overlaps.
    """
    with rasterio.open(chip_path) as chip:
        transform, crs, height, width = chip.transform, chip.crs, chip.height, chip.width
    out = np.zeros((height, width), dtype="int8")
    for value in (EXCLUDED, NO_DATA, WATER):
        shapes = [
            warp.transform_geom("EPSG:4326", crs, feature["geometry"])
            for feature in collection["features"]
            if str(feature["properties"].get("class")) == str(value)
        ]
        if shapes:
            hit = features.rasterize(
                ((shape, 1) for shape in shapes),
                out_shape=(height, width),
                transform=transform,
                dtype="uint8",
            ).astype(bool)
            out[hit] = value
    return out


def _compare(a: np.ndarray, b: np.ndarray) -> dict:
    scored = (a != NO_DATA) & (b != NO_DATA)
    water_a, water_b = (a == WATER) & scored, (b == WATER) & scored
    union = int((water_a | water_b).sum())
    return {
        "water_iou": float((water_a & water_b).sum() / union) if union else None,
        "pixel_agreement": float((a == b)[scored].mean()),
        "scored_px": int(scored.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write the report as JSON here")
    args = parser.parse_args()

    labelled: dict[str, dict[str, np.ndarray]] = {}
    missing: dict[str, list[str]] = {}
    for who, ref in SOURCES.items():
        for chip_id in CALIBRATION_CHIPS:
            name = FILENAME_OVERRIDES.get((who, chip_id), f"{chip_id}.geojson")
            source = REF_OVERRIDES.get((who, chip_id), ref)
            collection = _read_annotations(source, f"{ANNOTATION_DIR}/{name}")
            drawn = [
                feature
                for feature in (collection or {"features": []})["features"]
                if feature["properties"].get("class") not in (None, "")
            ]
            if not drawn:
                missing.setdefault(who, []).append(chip_id)
                continue
            labelled.setdefault(chip_id, {})[who] = _rasterise(collection, Path(CHIP_DIR) / f"{chip_id}.tif")

    pairs: list[dict] = []
    for chip_id in CALIBRATION_CHIPS:
        for first, second in itertools.combinations(sorted(labelled.get(chip_id, {})), 2):
            pairs.append(
                {"chip_id": chip_id, "labellers": [first, second]}
                | _compare(labelled[chip_id][first], labelled[chip_id][second])
            )

    scores = [pair["water_iou"] for pair in pairs if pair["water_iou"] is not None]
    participating = sorted({who for chip in labelled.values() for who in chip})
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "issue": 29,
        "headline": {
            "mean_pairwise_water_iou": round(float(np.mean(scores)), 4) if scores else None,
            "pair_count": len(scores),
            "labellers": participating,
            "complete": sorted(SOURCES) == participating,
        },
        "sources": {
            who: {"ref": ref, "commit": _resolve(ref)} for who, ref in SOURCES.items()
        },
        "labellers_with_nothing_drawn": missing,
        "ref_overrides": {f"{who}|{chip}": ref for (who, chip), ref in REF_OVERRIDES.items()},
        "per_pair_mean": {
            f"{first}|{second}": round(
                float(np.mean([p["water_iou"] for p in pairs if p["labellers"] == [first, second]])), 4
            )
            for first, second in itertools.combinations(participating, 2)
            if any(p["labellers"] == [first, second] for p in pairs)
        },
        "per_chip": pairs,
    }

    print(json.dumps(report["headline"], indent=2))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nwrote {args.out}")


def _resolve(ref: str) -> str:
    if ref == ".":
        ref = "HEAD"
    done = subprocess.run(["git", "rev-parse", "--short", ref], capture_output=True, text=True)
    return done.stdout.strip() or "unknown"


if __name__ == "__main__":
    main()
