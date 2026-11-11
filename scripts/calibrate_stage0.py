#!/usr/bin/env python
"""Calibrate stage0 against an independent flood reference and write per-date HAND inundation (#14).

    h(date) = stage(date) - stage0        wet(date) = {HAND <= h(date)}

Inputs
  --hand        HAND GeoTIFF on the NISAR chip grid (the #13 output; float32, NaN = no data)
  --reference   DATE=PATH, repeatable (use one or two). A binary water mask from a source that is
                independent of NISAR and HAND: 1 = water, 0 = not water, nodata = unknown. Any grid;
                it is resampled (nearest) onto the HAND grid.
  --check       DATE=PATH, repeatable, optional. Extra references NOT used for fitting, scored with
                the calibrated stage0: this is the out-of-sample agreement figure.

The fit runs on a decimated grid (--max-pixels) because the full 20 m AOI is ~274 M pixels and the
fit only needs the HAND/reference relationship. The per-date masks are written at full resolution.

Example
    python scripts/calibrate_stage0.py --hand data/reference/hand_aoi.tif \
        --reference 2026-09-22=data/reference/water_2026-09-22.tif \
        --check 2026-06-18=data/reference/water_2026-06-18.tif
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject

from nisar_flood.groundtruth.stage_calibration import (
    GAUGE_CM_TO_M,
    ReferenceScene,
    agreement_metrics,
    calibrate_stage0,
    inundation_mask,
    match_nisar_dates_to_stage,
    predict_inundation_by_date,
    stage_to_metres,
    write_inundation_masks,
)

NO_DATA = 255


def read_hand(path: Path, factor: int = 1) -> tuple[np.ndarray, dict]:
    """HAND as float32 metres (NaN = no data), optionally decimated by ``factor``."""
    with rasterio.open(path) as src:
        shape = (max(src.height // factor, 1), max(src.width // factor, 1))
        hand = src.read(1, out_shape=shape, resampling=Resampling.nearest).astype("float32")
        if src.nodata is not None and not np.isnan(src.nodata):
            hand[hand == np.float32(src.nodata)] = np.nan
        grid = {
            "crs": src.crs,
            "transform": src.transform * Affine.scale(src.width / shape[1], src.height / shape[0]),
        }
    hand[~np.isfinite(hand) | (hand < -100.0)] = np.nan
    return hand, grid


def read_reference(path: Path, grid: dict, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Binary water mask resampled onto ``grid``. Returns ``(water, known)``."""
    out = np.full(shape, NO_DATA, dtype="uint8")
    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_nodata=src.nodata,
            dst_nodata=NO_DATA,
            dst_transform=grid["transform"],
            dst_crs=grid["crs"],
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
    return out == 1, out != NO_DATA


def parse_pairs(items: list[str] | None) -> list[tuple[str, Path]]:
    pairs = []
    for item in items or []:
        date, sep, path = item.partition("=")
        if not sep or not path:
            raise SystemExit(f"expected DATE=PATH, got {item!r}")
        pairs.append((pd.Timestamp(date).date().isoformat(), Path(path)))
    return pairs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hand", type=Path, required=True)
    p.add_argument("--reference", action="append", metavar="DATE=PATH", required=True)
    p.add_argument("--check", action="append", metavar="DATE=PATH")
    p.add_argument("--gauge", type=Path, default=Path("data/gauge/manaus_daily_stage_2026.csv"))
    p.add_argument("--manifest", type=Path, default=Path("data/granule_manifest.csv"))
    p.add_argument("--out-dir", type=Path, default=Path("data/reference/hand_inundation"))
    p.add_argument("--report-dir", type=Path, default=Path("docs/evidence"))
    p.add_argument("--step", type=float, default=0.05, help="stage0 search step in metres")
    p.add_argument("--max-pixels", type=int, default=20_000_000, help="decimate the fit above this")
    p.add_argument("--gauge-unit-to-m", type=float, default=GAUGE_CM_TO_M, help="ANA Nivel is cm")
    p.add_argument("--no-masks", action="store_true", help="skip writing the per-date GeoTIFFs")
    args = p.parse_args()

    refs, checks = parse_pairs(args.reference), parse_pairs(args.check)
    if len(refs) > 2:
        raise SystemExit("calibrate on one or two reference dates; pass the rest with --check")

    gauge = pd.read_csv(args.gauge, parse_dates=["datetime"])
    manifest = pd.read_csv(args.manifest, parse_dates=["acquisition_date"])
    stage_m = {
        d.date().isoformat(): float(stage_to_metres(s, args.gauge_unit_to_m))
        for d, s in zip(gauge["datetime"], gauge["mean_stage"])
        if pd.notna(s)
    }

    def stage_on(date: str) -> float:
        if date not in stage_m:
            raise SystemExit(f"no gauge value for {date} in {args.gauge}")
        return stage_m[date]

    with rasterio.open(args.hand) as src:
        n_pixels = src.width * src.height
    factor = max(1, math.ceil(math.sqrt(n_pixels / args.max_pixels)))
    hand_fit, grid_fit = read_hand(args.hand, factor)
    print(f"HAND {n_pixels:,} px; fitting on every {factor}-th pixel ({hand_fit.size:,} px)")

    scenes = []
    for date, path in refs:
        water, known = read_reference(path, grid_fit, hand_fit.shape)
        scenes.append(ReferenceScene(date, stage_on(date), water, known))
    result = calibrate_stage0(hand_fit, scenes, step_m=args.step)

    check_rows = []
    for date, path in checks:
        water, known = read_reference(path, grid_fit, hand_fit.shape)
        s = stage_on(date)
        wet, hand_ok = inundation_mask(hand_fit, s - result.stage0_m)
        check_rows.append(
            {"date": date, "stage_m": s, "water_height_m": s - result.stage0_m,
             **agreement_metrics(wet, water, known & hand_ok)}
        )

    # Per-date prediction at full resolution, for every granule in the manifest.
    hand_full, grid_full = read_hand(args.hand, 1)
    matched = match_nisar_dates_to_stage(gauge, manifest)
    masks, summary = predict_inundation_by_date(
        hand_full, matched, result.stage0_m, unit_to_m=args.gauge_unit_to_m
    )
    written = [] if args.no_masks else write_inundation_masks(masks, summary, hand_full, grid_full, args.out_dir)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.report_dir / "hand_inundation_by_date.csv", index=False)
    result.curve.to_csv(args.report_dir / "stage0_calibration_curve.csv", index=False)
    report = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": "h(date) = stage(date) - stage0; wet = HAND <= h(date)",
        "stage0_m": result.stage0_m,
        "stage0_range_m": list(result.stage0_range_m),
        "mean_iou": result.mean_iou,
        "plateau_reaches_search_edge": result.at_edge,
        "gauge_unit_to_m": args.gauge_unit_to_m,
        "fit_decimation_factor": factor,
        "hand": str(args.hand),
        "calibration_dates": result.per_date.to_dict("records"),
        "out_of_sample_checks": check_rows,
        "masks_written": [str(w) for w in written],
    }
    (args.report_dir / "stage_calibration_report.json").write_text(json.dumps(report, indent=2, default=float))

    lo, hi = result.stage0_range_m
    print(f"stage0 = {result.stage0_m:.2f} m  (near-optimal range {lo:.2f} to {hi:.2f} m), mean IoU {result.mean_iou:.3f}")
    if result.at_edge:
        print("WARNING: the near-optimal range reaches the edge of the search grid; stage0 is not pinned down.")
    print(result.per_date[["date", "stage_m", "water_height_m", "iou", "precision", "recall"]].to_string(index=False))
    if check_rows:
        print("out-of-sample:")
        print(pd.DataFrame(check_rows)[["date", "water_height_m", "iou", "precision", "recall"]].to_string(index=False))
    print(summary[["acquisition_date", "stage_m", "water_height_m", "wet_fraction", "status"]].to_string(index=False))


if __name__ == "__main__":
    main()
