"""Score the stage0 terrain rule against the hand-labelled gold set (#14, #30).

The terrain rule predicts water from topography and a river gauge alone, with no
radar input:

    h(date) = stage(date) - stage0        wet = {HAND <= h(date)}

HAND is each pixel's height above the stream it drains into, so the rule floods
whatever sits lower than the river stands above its banks. It is the baseline the
learned models have to beat, and this scores it on the same chips, against the
same labels, with the same metric the models are scored on.

Scoring follows the labelling protocol: class 2 (suspected flooded vegetation) and
-1 (unusable) are dropped from both sides, as are pixels where HAND has no value.
The headline is the per-chip mean water IoU, matching metrics.iou.HEADLINE_METRIC,
so one enormous chip cannot carry the average.

    python scripts/score_stage0_gold.py --hand data/reference/hand_aoi.tif \
        --out docs/evidence/stage0_vs_gold.json
"""
import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT

WATER, NON_WATER, EXCLUDED, NO_DATA = 1, 0, 2, -1
DATE_IN_CHIP_ID = re.compile(r"_(\d{8})_")


def water_heights(path: Path) -> dict[str, float]:
    """Calibrated metres of water above bank level, per acquisition date."""
    with path.open() as handle:
        return {row["acquisition_date"]: float(row["water_height_m"])
                for row in csv.DictReader(handle) if row.get("water_height_m")}


def chip_date(chip_id: str) -> str:
    match = DATE_IN_CHIP_ID.search(chip_id)
    if not match:
        raise ValueError(f"no date in chip id {chip_id!r}")
    stamp = match.group(1)
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def hand_on_chip(hand: rasterio.DatasetReader, chip: rasterio.DatasetReader) -> np.ndarray:
    """HAND resampled onto one chip's grid, as float with NaN where it has no value."""
    with WarpedVRT(hand, crs=chip.crs, transform=chip.transform,
                   width=chip.width, height=chip.height, resampling=0) as vrt:
        values = vrt.read(1, masked=True).astype("float32").filled(np.nan)
    return values


def open_hand(source: Path, chip_id: str):
    """The HAND source for one chip.

    `source` is either the whole-AOI GeoTIFF, read window by window, or a
    directory of per-chip cut-outs named `<chip_id>_hand.tif`, which is what
    scripts/cut_hand_windows.py writes when the AOI file is too large to move.
    """
    if source.is_dir():
        path = source / f"{chip_id}_hand.tif"
        if not path.exists():
            raise SystemExit(f"no HAND cut-out for {chip_id} in {source}")
        return rasterio.open(path)
    return rasterio.open(source)


def score(predicted: np.ndarray, labels: np.ndarray) -> dict:
    """Water IoU and its parts over the pixels both sides are willing to score."""
    scored = np.isin(labels, (WATER, NON_WATER)) & np.isfinite(predicted)
    truth = (labels == WATER) & scored
    guess = (predicted > 0) & scored
    intersection, union = int((truth & guess).sum()), int((truth | guess).sum())
    hits = int((truth & guess).sum())
    return {
        "water_iou": intersection / union if union else None,
        "precision": hits / int(guess.sum()) if guess.any() else None,
        "recall": hits / int(truth.sum()) if truth.any() else None,
        "label_water_fraction": float(truth.sum() / scored.sum()) if scored.any() else None,
        "predicted_wet_fraction": float(guess.sum() / scored.sum()) if scored.any() else None,
        "scored_px": int(scored.sum()),
    }


def mean_of(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return float(np.mean(present)) if present else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hand", type=Path, required=True,
                        help="HAND GeoTIFF covering the chips, or a directory of per-chip cut-outs")
    parser.add_argument("--masks", type=Path, default=Path("data/labels/masks"))
    parser.add_argument("--inundation", type=Path,
                        default=Path("docs/evidence/hand_inundation_by_date.csv"),
                        help="per-date water height from the stage0 calibration")
    parser.add_argument("--sweep", type=float, nargs=3, metavar=("LO", "HI", "STEP"),
                        default=[0.0, 16.0, 0.25],
                        help="water heights to try, to show whether the calibrated one is best")
    parser.add_argument("--out", type=Path, help="write the report as JSON here")
    args = parser.parse_args()

    heights = water_heights(args.inundation)
    masks = sorted(args.masks.glob("*_label.tif"))
    if not masks:
        raise SystemExit(f"no label masks in {args.masks}")

    grid = np.arange(*args.sweep[:2], args.sweep[2])
    per_chip, sweep_rows = {}, {h: [] for h in grid}

    whole_aoi = rasterio.open(args.hand) if args.hand.is_file() else None
    try:
        for path in masks:
            chip_id = path.stem.removesuffix("_label")
            height = heights.get(chip_date(chip_id))
            if height is None:
                raise SystemExit(f"no water height for {chip_date(chip_id)} in {args.inundation}")
            with rasterio.open(path) as chip:
                labels = chip.read(1)
                hand = whole_aoi or open_hand(args.hand, chip_id)
                try:
                    elevation = hand_on_chip(hand, chip)
                finally:
                    if whole_aoi is None:
                        hand.close()
            valid = np.where(np.isfinite(elevation), 1.0, np.nan)
            per_chip[chip_id] = score(np.where(elevation <= height, 1.0, 0.0) * valid, labels)
            for trial in grid:
                row = score(np.where(elevation <= trial, 1.0, 0.0) * valid, labels)
                sweep_rows[trial].append(row["water_iou"])
    finally:
        if whole_aoi is not None:
            whole_aoi.close()

    calibrated = heights[chip_date(next(iter(per_chip)))]
    sweep = {round(float(h), 3): mean_of(v) for h, v in sweep_rows.items()}
    best = max((v, k) for k, v in sweep.items() if v is not None)

    report = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "what": "stage0 terrain rule (HAND <= water height) scored against the hand labels",
        "headline": {
            "iou_water_per_chip_mean": round(mean_of([c["water_iou"] for c in per_chip.values()]), 4),
            "chips": len(per_chip),
            "water_height_m": calibrated,
        },
        "pooled": {
            "precision": round(mean_of([c["precision"] for c in per_chip.values()]), 4),
            "recall": round(mean_of([c["recall"] for c in per_chip.values()]), 4),
            "label_water_fraction": round(mean_of([c["label_water_fraction"] for c in per_chip.values()]), 4),
            "predicted_wet_fraction": round(mean_of([c["predicted_wet_fraction"] for c in per_chip.values()]), 4),
        },
        "best_height_in_sweep": {"water_height_m": best[1], "iou_water_per_chip_mean": round(best[0], 4)},
        "sweep_iou_by_water_height": {k: (round(v, 4) if v is not None else None) for k, v in sorted(sweep.items())},
        "per_chip": {k: {m: (round(v, 4) if isinstance(v, float) else v) for m, v in c.items()}
                     for k, c in sorted(per_chip.items())},
        "hand": str(args.hand),
    }

    print(json.dumps(report["headline"], indent=2))
    print(json.dumps(report["pooled"], indent=2))
    print("best height in sweep:", report["best_height_in_sweep"])
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
