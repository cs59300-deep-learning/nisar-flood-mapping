"""Build the fixed RQ2 evaluation split and the nested fine-tuning subsets.

The 55 hand-labelled NISAR chips are the only labelled target-domain data, so the
same chips have to serve as both the fine-tuning pool and the test set. This
script fixes that division once and writes it to JSON, so that every arm of RQ2
and the RQ1 zero-shot run are scored on exactly the same chips.

Two properties matter for the fine-tuning curve:

Stratification. Per-chip water IoU rises with how wet a chip is, so an unlucky
random draw changes the score more than the treatment does. Chips are therefore
ranked by water fraction, cut into four strata of equal size, and drawn from each
stratum in turn.

Nesting. Within one seed, the n=5 subset is contained in n=10, which is contained
in n=20, and so on. The curve then shows the effect of adding chips rather than
the effect of drawing a different set of chips.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import rasterio

WATER, FLOODED_VEG, UNUSABLE = 1, 2, -1
N_STRATA = 4
DEFAULT_TEST_SIZE = 20
DEFAULT_SEEDS = (0, 1, 2)
DEFAULT_SIZES = (5, 10, 20, 35)


def chip_water_fractions(mask_dir: Path) -> dict[str, float]:
    """Water pixels over scoreable pixels, per chip.

    Flagged flooded vegetation and unusable pixels are left out of the
    denominator because neither is ever scored.
    """
    fractions = {}
    for path in sorted(mask_dir.glob("*_label.tif")):
        with rasterio.open(path) as src:
            y = src.read(1)
        scoreable = int(((y != FLOODED_VEG) & (y != UNUSABLE)).sum())
        water = int((y == WATER).sum())
        fractions[path.name.replace("_label.tif", "")] = water / scoreable if scoreable else 0.0
    return fractions


def strata(chip_ids: list[str], fractions: dict[str, float]) -> dict[str, int]:
    """Assign each chip to one of N_STRATA bins of equal count, driest bin first."""
    ordered = sorted(chip_ids, key=lambda c: (fractions[c], c))
    return {chip: (rank * N_STRATA) // len(ordered) for rank, chip in enumerate(ordered)}


def _by_stratum(chip_ids, stratum, rng):
    """Shuffle the chips of each stratum independently."""
    groups = [[] for _ in range(N_STRATA)]
    for chip in chip_ids:
        groups[stratum[chip]].append(chip)
    for group in groups:
        rng.shuffle(group)
    return groups


def stratified_order(chip_ids, stratum, rng) -> list[str]:
    """Order the chips so that any prefix is spread across the strata.

    Taking the first n of this ordering gives the n-chip subset, which makes the
    subsets nested by construction.
    """
    groups = _by_stratum(chip_ids, stratum, rng)
    order = []
    while any(groups):
        # Draw from the stratum that still has the largest share left, so the
        # prefix stays balanced even when the strata empty at different rates.
        largest = max(range(N_STRATA), key=lambda i: len(groups[i]))
        order.append(groups[largest].pop())
    return order


def build(mask_dir: Path, test_size: int, seeds, sizes, seed: int) -> dict:
    fractions = chip_water_fractions(mask_dir)
    chips = sorted(fractions)
    stratum = strata(chips, fractions)

    rng = np.random.default_rng(seed)
    test = sorted(stratified_order(chips, stratum, rng)[:test_size])
    pool = sorted(c for c in chips if c not in set(test))

    subsets = {}
    for s in seeds:
        order = stratified_order(pool, stratum, np.random.default_rng(1000 + s))
        subsets[str(s)] = {str(n): sorted(order[:n]) for n in sizes if n <= len(pool)}

    return {
        "n_chips": len(chips),
        "test_size": len(test),
        "pool_size": len(pool),
        "n_strata": N_STRATA,
        "split_seed": seed,
        "seeds": list(seeds),
        "sizes": [n for n in sizes if n <= len(pool)],
        "test": test,
        "pool": pool,
        "subsets": subsets,
        "water_fraction": {c: round(fractions[c], 6) for c in chips},
        "stratum": stratum,
        "method": (
            "Chips ranked by water fraction over scoreable pixels and cut into "
            f"{N_STRATA} equal strata. A fixed {test_size}-chip test set is drawn "
            "stratified; the rest form the fine-tuning pool. Per seed the pool is "
            "put in a stratum-balanced order and the n-chip subsets are its "
            "prefixes, so smaller subsets are contained in larger ones."
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--masks", type=Path, default=Path("data/labels/masks"))
    p.add_argument("--out", type=Path, default=Path("data/labels/rq2_splits.json"))
    p.add_argument("--test-size", type=int, default=DEFAULT_TEST_SIZE)
    p.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    p.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    p.add_argument("--seed", type=int, default=0, help="seed for the test-set draw")
    args = p.parse_args()

    split = build(args.masks, args.test_size, args.seeds, args.sizes, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(split, indent=2) + "\n")

    wf = split["water_fraction"]
    mean = lambda ids: sum(wf[c] for c in ids) / len(ids)
    print(f"wrote {args.out}")
    print(f"  test {split['test_size']} chips, mean water {mean(split['test']):.3f}")
    print(f"  pool {split['pool_size']} chips, mean water {mean(split['pool']):.3f}")
    for s, sub in split["subsets"].items():
        parts = " ".join(f"n={n}:{mean(ids):.3f}" for n, ids in sub.items())
        print(f"  seed {s}  {parts}")


if __name__ == "__main__":
    main()
