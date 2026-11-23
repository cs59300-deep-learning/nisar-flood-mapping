"""Draw a visual QA sheet of random chips from data/chips/ (issue #10).

Each tile shows the HH band in dB with one fixed grey stretch, so chips can be
compared with each other: dark is smooth/open water, bright is rough or built
surface. Pixels outside the acquisition (no-data) are drawn red.

Example (from the project root):
    python scripts/make_chip_qa_sheet.py
    python scripts/make_chip_qa_sheet.py --n 20 --seed 1 --out data/qa/chip_qa_20_samples.png
"""

import argparse
import random
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write a PNG; no display needed
import matplotlib.pyplot as plt
import numpy as np
import rasterio

DB_RANGE = (-25.0, 0.0)  # grey stretch for HH gamma0 in dB
COLUMNS = 5
PREVIEW_PX = 256  # tiles are downsampled; the sheet is for eyeballing, not measuring


def read_hh_preview(path: Path) -> tuple[np.ndarray, float]:
    """HH band (band 1) downsampled for display, and the chip's valid-pixel fraction."""
    with rasterio.open(path) as chip:
        hh = chip.read(1, out_shape=(PREVIEW_PX, PREVIEW_PX))
        valid = float((chip.dataset_mask() > 0).mean())
    return hh, valid


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chips", default="data/chips")
    p.add_argument("--out", default="data/qa/chip_qa_20_samples.png")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--seed", type=int, default=0, help="same seed -> same 20 chips")
    args = p.parse_args()

    files = sorted(Path(args.chips).glob("*.tif"))
    if len(files) < args.n:
        sys.exit(f"Need {args.n} chips in {args.chips}, found {len(files)}. "
                 "Run scripts/build_first_chip_set.py first.")
    picked = sorted(random.Random(args.seed).sample(files, args.n))

    rows = -(-args.n // COLUMNS)
    fig, axes = plt.subplots(rows, COLUMNS, figsize=(3 * COLUMNS, 3.2 * rows))
    cmap = plt.get_cmap("gray").copy()
    cmap.set_bad("red")

    for ax, path in zip(axes.flat, picked):
        hh, valid = read_hh_preview(path)
        ax.imshow(np.ma.masked_invalid(hh), cmap=cmap, vmin=DB_RANGE[0], vmax=DB_RANGE[1])
        # chip_id is long; the row/column suffix is what locates it in the granule.
        ax.set_title(f"{path.stem[-13:]}\nvalid {valid:.0%}", fontsize=8)
        ax.axis("off")
    for ax in list(axes.flat)[len(picked):]:
        ax.axis("off")

    fig.suptitle(f"{args.n} random chips from {args.chips} (HH dB, seed {args.seed}, "
                 f"{DB_RANGE[0]:.0f} to {DB_RANGE[1]:.0f} dB; red = no data)")
    fig.tight_layout(rect=(0, 0, 1, 0.96))  # leave room for the title
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=80)
    print(f"{len(picked)} chips visualised -> {out} ({out.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
