"""Fetch the HAND window for each chip from Earth Engine (#13, #14).

The project's HAND raster came from MERIT Hydro v1.0.1, clipped to the AOI and
resampled onto the 20 m NISAR grid (docs/hand_methods.md). The source tiles are
behind a registration form, but the same v1.0.1 product is published in Earth
Engine as MERIT/Hydro/v1_0_1, band `hnd`, so the windows can be pulled directly.

One request per chip, each a 512x512 float32 GeoTIFF of about 1 MB, which stays
well inside the getDownloadURL size limit and avoids rebuilding the 945 MB
whole-AOI raster to score 55 chips.

MERIT Hydro's native pixel is ~92.77 m, so resampling to 20 m interpolates
rather than adds detail; bilinear matches what the original build used.

    earthengine authenticate          # once, opens a browser
    python scripts/fetch_hand_from_gee.py --project <your-gee-project>
    python scripts/score_stage0_gold.py --hand data/reference/hand_chips \
        --out docs/evidence/stage0_vs_gold.json
"""
import argparse
import csv
import io
import zipfile
from pathlib import Path

import ee
import requests

ASSET = "MERIT/Hydro/v1_0_1"
BAND = "hnd"
CHIP_PX = 512
RES_M = 20.0


def chip_region(bbox: str) -> list[list[float]]:
    left, bottom, right, top = (float(v) for v in bbox.split(","))
    return [[left, bottom], [right, bottom], [right, top], [left, top]]


def fetch(image: "ee.Image", crs: str, bbox: str) -> bytes:
    """The HAND window for one chip, as the bytes of a GeoTIFF."""
    url = image.getDownloadURL({
        "bands": [BAND],
        "region": ee.Geometry.Polygon([chip_region(bbox)], proj=crs, evenOdd=False),
        "crs": crs,
        "scale": RES_M,
        "format": "GEO_TIFF",
    })
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    body = response.content
    if body[:2] == b"PK":                      # a zip when GEE bundles per-band files
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".tif"))
            return archive.read(name)
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="your Earth Engine cloud project")
    parser.add_argument("--manifest", type=Path, default=Path("data/chips/manifest.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/reference/hand_chips"))
    args = parser.parse_args()

    ee.Initialize(project=args.project)
    image = ee.Image(ASSET).select(BAND).resample("bilinear")

    rows = list(csv.DictReader(args.manifest.open()))
    args.out.mkdir(parents=True, exist_ok=True)

    for index, row in enumerate(rows, start=1):
        path = args.out / f"{row['chip_id']}_hand.tif"
        if path.exists():
            continue
        path.write_bytes(fetch(image, row["crs"], row["bbox"]))
        print(f"  [{index:>2}/{len(rows)}] {row['chip_id']}  {path.stat().st_size / 1e6:.2f} MB")

    total = sum(p.stat().st_size for p in args.out.glob("*_hand.tif"))
    print(f"\n{len(list(args.out.glob('*_hand.tif')))} windows -> {args.out}  ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
