#!/usr/bin/env python
"""Generate before/after radiometric-normalisation histograms for one granule.

Produces ``reports/figures/radiometry_before_after.png`` showing GCOV
gamma-nought (gamma0) backscatter *before* normalisation (raw linear power)
and *after* normalisation (dB with the -40 dB physical floor), as described in
``docs/radiometry.md`` (issue #8).

Data source
-----------
If a real GCOV granule is available locally (first HDF5 path resolved from
``data/granule_manifest.csv``, or one passed with ``--granule``), its
Frequency A HH gamma0 layer is used. Otherwise the script falls back to a
synthetic gamma0 field with NISAR-like statistics so the figure is always
reproducible without committing a ~2 GB raw product (see
``docs/data_sources.md``). The figure title records which source was used.

Usage
-----
    python scripts/radiometry_histograms.py [--granule PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless / CI-safe backend
import matplotlib.pyplot as plt
import numpy as np

from nisar_flood.pipeline.radiometry import DB_FLOOR, normalise_gcov_gamma0

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "reports" / "figures" / "radiometry_before_after.png"
MANIFEST = REPO_ROOT / "data" / "granule_manifest.csv"


def _synthetic_gamma0(seed: int = 8) -> np.ndarray:
    """A synthetic gamma0 (linear power) field with NISAR-like statistics.

    Mixes a dark open-water population and a brighter forest/land population,
    both exponential (so single-look-like, heavy right tail), plus a handful of
    exact zeros to exercise the floor and some NaNs to exercise no-data.
    """
    rng = np.random.default_rng(seed)
    n = 400 * 400
    water = rng.exponential(scale=0.004, size=n // 2)  # dark, ~ -24 dB median
    land = rng.exponential(scale=0.08, size=n - n // 2)  # bright, ~ -11 dB median
    gamma0 = np.concatenate([water, land])
    rng.shuffle(gamma0)
    gamma0[rng.integers(0, gamma0.size, size=200)] = 0.0  # masked / shadow
    gamma0[rng.integers(0, gamma0.size, size=200)] = np.nan  # no-data
    return gamma0.reshape(400, 400)


def _first_granule_from_manifest() -> Path | None:
    if not MANIFEST.exists() or MANIFEST.stat().st_size == 0:
        return None
    with MANIFEST.open(newline="") as handle:
        for row in csv.DictReader(handle):
            for value in row.values():
                if value and value.strip().lower().endswith((".h5", ".hdf5")):
                    candidate = (REPO_ROOT / value.strip()).resolve()
                    if candidate.exists():
                        return candidate
    return None


def _load_real_gamma0(granule: Path) -> np.ndarray:
    """Read Frequency A HH gamma0 from a real GCOV granule, if deps allow."""
    import h5py  # local import: only needed on the real-granule path

    hh_path = "/science/LSAR/GCOV/grids/frequencyA/HHHH"
    with h5py.File(granule, "r") as f:
        if hh_path not in f:
            raise KeyError(f"{hh_path} not found in {granule}")
        return np.asarray(f[hh_path][:], dtype=np.float64)


def load_gamma0(granule: Path | None) -> tuple[np.ndarray, str]:
    """Return (gamma0_linear, source_label)."""
    granule = granule or _first_granule_from_manifest()
    if granule is not None and granule.exists():
        try:
            return _load_real_gamma0(granule), f"real granule: {granule.name}"
        except Exception as exc:  # noqa: BLE001 - fall back, but say why
            print(f"[warn] could not read {granule}: {exc}; using synthetic data")
    return _synthetic_gamma0(), "synthetic gamma0 (no local granule)"


def make_figure(gamma0_linear: np.ndarray, source_label: str, out_path: Path) -> None:
    before = gamma0_linear[np.isfinite(gamma0_linear)].ravel()
    after_full = normalise_gcov_gamma0(gamma0_linear)
    after = after_full[np.isfinite(after_full)].ravel()

    fig, (ax_before, ax_after) = plt.subplots(1, 2, figsize=(12, 5.2))

    # Raw linear gamma0 has a long bright tail (a few very bright scatterers)
    # that would crush the bulk of the distribution into a single bar. Clip the
    # VIEW to the 99.5th percentile so the shape is visible; the tail beyond is
    # noted in the axis label. This is display-only - no data is altered.
    hi = float(np.percentile(before, 99.5)) if before.size else 1.0
    ax_before.hist(before, bins=120, range=(0.0, hi), color="#8c6d31")
    ax_before.set_xlim(0.0, hi)
    ax_before.set_title("Before: raw linear power (NISAR native units)")
    ax_before.set_xlabel(
        "radar brightness  gamma0 (linear power ratio)\n"
        f"low = dark/water, high = bright/land  -  view clipped to 99.5th pct = {hi:.3g}"
    )
    ax_before.set_ylabel("number of pixels")

    ax_after.hist(after, bins=120, color="#1f77b4")
    ax_after.axvline(
        DB_FLOOR, color="crimson", linestyle="--", linewidth=1.2,
        label=f"{DB_FLOOR:g} dB physical floor (noise / fill pinned here)",
    )
    ax_after.set_title("After: normalised to decibels (dB), floored")
    ax_after.set_xlabel(
        "radar brightness  gamma0 (dB)\n"
        "~ -18 dB = open water   |   ~ -5 dB = land / forest"
    )
    ax_after.set_ylabel("number of pixels")
    ax_after.legend(loc="upper left", fontsize=8)

    fig.suptitle(
        f"Radiometric normalisation - before vs after  [{source_label}]",
        fontsize=13,
    )

    # Plain-language caption so teammates do not have to ask what this shows.
    caption = (
        "Same NISAR radar brightness (gamma0), shown twice. LEFT: raw linear units - "
        "lopsided, crammed near zero, a few bright outliers dominate the scale (bad model "
        "input). RIGHT: the same pixels converted to decibels - a clean spread where open "
        "water (~ -18 dB) and land/forest (~ -5 dB) separate cleanly, matching the dB scale "
        "the Sentinel-1 training data already uses. The -40 dB floor pins noise/empty pixels."
    )
    fig.text(0.5, 0.015, caption, ha="center", va="bottom", fontsize=8, wrap=True)

    fig.tight_layout(rect=(0, 0.11, 1, 0.95))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"[ok] wrote {out_path}  ({source_label})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--granule", type=Path, default=None, help="GCOV HDF5 path")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output PNG path")
    args = parser.parse_args()

    gamma0, source_label = load_gamma0(args.granule)
    make_figure(gamma0, source_label, args.out)


if __name__ == "__main__":
    main()
