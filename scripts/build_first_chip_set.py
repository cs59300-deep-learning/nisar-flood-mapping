"""Build the first chip set (issue #10): at least 300 chips in data/chips/.

Chips are cut with the existing ``make_chips`` pipeline at randomly chosen
positions on a 512-pixel grid, so new chips never overlap each other. A chip is
also skipped if it overlaps one already in the manifest (the hand-labelled
chips sit on a different, 400-pixel grid). Non-overlapping chips mean a
train/val split cannot leak pixels between the two sets.

Example (from the project root):
    python scripts/build_first_chip_set.py
    python scripts/build_first_chip_set.py --count 320 --seed 0
"""

import argparse
import csv
import random
import sys
from pathlib import Path

import h5py

from nisar_flood.pipeline.chipping import _starts
from nisar_flood.pipeline.make_chips import make_chips

GRID = "/science/LSAR/GCOV/grids/frequencyA/HHHH"
SIZE = STRIDE = 512
MAX_MB = 500
BATCH = 40  # positions tried per make_chips call


def chip_position(chip_id: str) -> tuple[int, int]:
    """``N023_20260618_002000_008000`` -> (2000, 8000)."""
    row, col = chip_id.split("_")[-2:]
    return int(row), int(col)


def existing_positions(manifest: Path) -> list[tuple[int, int]]:
    """Positions already indexed, including chips other people hold locally."""
    if not manifest.exists():
        return []
    with manifest.open(newline="", encoding="utf-8") as stream:
        return [chip_position(row["chip_id"]) for row in csv.DictReader(stream)]


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return abs(a[0] - b[0]) < SIZE and abs(a[1] - b[1]) < SIZE


def count_chips(out_dir: Path) -> tuple[int, float]:
    """Number of chip GeoTIFFs and their total size in MB."""
    files = list(out_dir.glob("*.tif"))
    return len(files), sum(f.stat().st_size for f in files) / 1e6


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--granule", help="NISAR GCOV .h5 (default: the 023_068 granule in data/raw)")
    p.add_argument("--granule-id", default="N023_20260618")
    p.add_argument("--date", default="2026-06-18")
    p.add_argument("--out", default="data/chips")
    p.add_argument("--count", type=int, default=320,
                   help="stop once this many chips are in --out (default 320)")
    p.add_argument("--min-valid", type=float, default=0.90,
                   help="minimum valid-pixel fraction of a new chip")
    p.add_argument("--round-db", type=float, default=1 / 64,
                   help="round dB values to this step to keep chips small")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    granule = args.granule or next(iter(sorted(Path("data/raw").glob("NISAR_*_GCOV_023_*.h5"))), None)
    if granule is None or not Path(granule).exists():
        sys.exit("No granule found. Pass --granule path/to/NISAR_..._GCOV_....h5")

    out_dir = Path(args.out)
    with h5py.File(granule, "r") as f:
        rows, cols = f[GRID].shape

    taken = existing_positions(out_dir / "manifest.csv")
    candidates = [(r, c) for r in _starts(rows, SIZE, STRIDE) for c in _starts(cols, SIZE, STRIDE)]
    random.Random(args.seed).shuffle(candidates)

    n_chips, _ = count_chips(out_dir)
    cursor = 0
    while n_chips < args.count and cursor < len(candidates):
        batch = []
        while cursor < len(candidates) and len(batch) < min(BATCH, args.count - n_chips):
            pos = candidates[cursor]
            cursor += 1
            if not any(overlaps(pos, other) for other in taken + batch):
                batch.append(pos)
        written = make_chips(granule, out_dir, granule_id=args.granule_id,
                             acquisition_date=args.date, size=SIZE, stride=STRIDE,
                             min_valid_fraction=args.min_valid, only=batch,
                             round_db=args.round_db)
        # Rejected positions (too much no-data) stay out of `taken` so they are not
        # counted twice; accepted ones block their neighbours from now on.
        taken += [chip_position(row["chip_id"]) for row in written]
        n_chips, size_mb = count_chips(out_dir)
        print(f"  {n_chips} chips so far ({size_mb:.0f} MB)")

    n_chips, size_mb = count_chips(out_dir)
    print(f"\nGenerated chips: {n_chips}")
    print(f"Total dataset size: {size_mb:.0f} MB")
    ok = n_chips >= 300 and size_mb < MAX_MB
    print(f"Dataset check (>= 300 chips, < {MAX_MB} MB): {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
