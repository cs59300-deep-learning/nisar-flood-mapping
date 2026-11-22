"""Cut per-chip HAND windows out of the whole-AOI raster (#14).

hand_aoi.tif is ~945 MB and lives on Google Drive, which makes it awkward to pull
onto a laptop just to score 55 chips. The chips cover a small, scattered part of
the AOI, so the HAND values that actually matter are about 58 MB before
compression. This cuts exactly those windows, reading only what it needs.

Run it where the big file already is (Colab with Drive mounted), then move the
output directory to data/reference/hand_chips and point the scorer at it:

    python scripts/cut_hand_windows.py --hand /content/drive/MyDrive/nisar_ticket13_hand/hand_aoi.tif
    python scripts/score_stage0_gold.py --hand data/reference/hand_chips \
        --out docs/evidence/stage0_vs_gold.json

Only data/chips/manifest.csv is needed to place the windows, not the chips
themselves, so this runs without the imagery present.
"""
import argparse
import csv
from pathlib import Path

import rasterio
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

CHIP_PX = 512
RES_M = 20.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hand", type=Path, required=True, help="whole-AOI HAND GeoTIFF")
    parser.add_argument("--manifest", type=Path, default=Path("data/chips/manifest.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/reference/hand_chips"))
    args = parser.parse_args()

    rows = list(csv.DictReader(args.manifest.open()))
    args.out.mkdir(parents=True, exist_ok=True)

    with rasterio.open(args.hand) as hand:
        for row in rows:
            left, _, _, top = (float(v) for v in row["bbox"].split(","))
            transform = from_origin(left, top, RES_M, RES_M)
            with WarpedVRT(hand, crs=row["crs"], transform=transform,
                           width=CHIP_PX, height=CHIP_PX, resampling=0) as vrt:
                values = vrt.read(1, masked=True)
            profile = {
                "driver": "GTiff", "height": CHIP_PX, "width": CHIP_PX, "count": 1,
                "dtype": "float32", "crs": row["crs"], "transform": transform,
                "nodata": float("nan"), "compress": "deflate", "predictor": 3, "tiled": True,
            }
            path = args.out / f"{row['chip_id']}_hand.tif"
            with rasterio.open(path, "w", **profile) as dst:
                dst.write(values.astype("float32").filled(float("nan")), 1)

    total = sum(p.stat().st_size for p in args.out.glob("*_hand.tif"))
    print(f"{len(rows)} windows -> {args.out}  ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
