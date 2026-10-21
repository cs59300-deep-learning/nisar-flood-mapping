"""Build the published reference layers on the NISAR grid (Ticket #15).

Example:
    python scripts/build_reference_layers.py \
        --jrc seasonality_70W_0Nv1_4_2021.tif seasonality_60W_0Nv1_4_2021.tif \
        --jers1 jers1_wetland.tif --wetland-values 1 2 \
        --reference merit_hand_aligned.tif --out outputs/groundtruth/reference

Run `--inspect FILE` first on the JERS-1 raster to see its class codes and
confirm them against the ORNL DAAC dataset guide before choosing
--wetland-values.
"""

import argparse

from nisar_flood.groundtruth.published_reference import (
    PERMANENT_MONTHS_THRESHOLD,
    build_reference_layers,
    unique_values,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--inspect", help="Print class codes and counts of a raster, then exit.")
    p.add_argument("--jrc", nargs="+", help="JRC GSW seasonality tile(s).")
    p.add_argument("--jers1", help="JERS-1 wetland raster (lon/lat).")
    p.add_argument("--wetland-values", nargs="+", type=int,
                   help="JERS-1 class codes counted as flooded wetland.")
    p.add_argument("--reference", help="NISAR reference raster (exact output grid).")
    p.add_argument("--out", default="outputs/groundtruth/reference")
    p.add_argument("--months", type=int, default=PERMANENT_MONTHS_THRESHOLD)
    a = p.parse_args()

    if a.inspect:
        for code, n in unique_values(a.inspect).items():
            print(f"{code}\t{n}")
        return
    if not (a.jrc and a.jers1 and a.wetland_values and a.reference):
        p.error("--jrc, --jers1, --wetland-values and --reference are required")
    for name, path in build_reference_layers(
        a.jrc, a.jers1, a.reference, a.out, a.wetland_values, months_threshold=a.months
    ).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
