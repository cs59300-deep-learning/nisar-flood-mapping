"""One step from a GCOV granule to labelling-ready chips.

``granule_to_geotiff`` converts the HDF5 product and ``chipping.chip_raster``
cuts the grid; this joins them so a chip set is one command rather than a
sequence someone has to remember. Both paths write the same filenames, the same
manifest columns and the same geometry, so chips cut one at a time are
interchangeable with chips from a whole-granule run.

Two modes:

* **whole granule** - convert once, then cut every window that passes the
  valid-pixel filter.
* **selected positions** (``only``) - convert just those windows. Each person
  labelling a share of the chips reads a few megabytes of the granule instead
  of all of it, which is what makes the work divisible.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import rasterio

from .chipping import ChipConfig, _update_manifest, chip_raster
from .gcov_geotiff import granule_to_geotiff

__all__ = ["make_chips", "parse_positions"]


def parse_positions(only: list[str] | None) -> list[tuple[int, int]] | None:
    """Turn ``["8800,13200", "7600,5600"]`` into row/column pairs."""
    if not only:
        return None
    positions = []
    for item in only:
        try:
            row, column = (int(part) for part in item.replace(" ", "").split(","))
        except ValueError as error:
            raise ValueError(f"expected ROW,COL but got {item!r}") from error
        positions.append((row, column))
    return positions


def make_chips(
    granule_path: str | Path,
    output_dir: str | Path,
    *,
    granule_id: str,
    acquisition_date: str,
    geotiff_path: str | Path | None = None,
    size: int = 512,
    stride: int = 400,
    min_valid_fraction: float = 0.70,
    only: list[str] | list[tuple[int, int]] | None = None,
) -> list[dict[str, str | float]]:
    """Cut chips from a granule and index them in ``manifest.csv``.

    Parameters
    ----------
    granule_path:
        NISAR L2 GCOV ``.h5`` product.
    output_dir:
        Directory for the chips and the shared manifest.
    granule_id:
        Short prefix for chip filenames, e.g. ``N023_20260618``. Chips are named
        ``<granule_id>_<row>_<col>.tif`` with row and column zero-padded to six
        digits, so a chip's name locates it in the granule.
    geotiff_path:
        Where to keep the intermediate full-granule GeoTIFF. ``None`` uses a
        temporary file and deletes it. Ignored when ``only`` is given.
    only:
        Chip positions to write, as ``(row, column)`` pairs or ``"ROW,COL"``
        strings. ``None`` cuts the whole granule.

    Returns
    -------
    list of dict
        One manifest row per chip written.
    """
    granule_path, output_dir = Path(granule_path), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = ChipConfig(size=size, stride=stride, min_valid_fraction=min_valid_fraction)

    positions = only if only is None or isinstance(only[0], tuple) else parse_positions(only)
    if positions is None:
        return _whole_granule(granule_path, output_dir, granule_id, acquisition_date,
                              geotiff_path, config)
    return _selected(granule_path, output_dir, granule_id, acquisition_date,
                     positions, config)


def _whole_granule(granule_path, output_dir, granule_id, acquisition_date,
                   geotiff_path, config):
    if geotiff_path is not None:
        return chip_raster(
            granule_to_geotiff(granule_path, geotiff_path), output_dir,
            granule_id=granule_id, acquisition_date=acquisition_date, config=config,
        )
    with tempfile.TemporaryDirectory(prefix="nisar-granule-") as scratch:
        raster = granule_to_geotiff(granule_path, Path(scratch) / f"{granule_id}.tif")
        return chip_raster(raster, output_dir, granule_id=granule_id,
                           acquisition_date=acquisition_date, config=config)


def _selected(granule_path, output_dir, granule_id, acquisition_date, positions, config):
    rows: list[dict[str, str | float]] = []
    for row, column in positions:
        chip_id = f"{granule_id}_{row:06d}_{column:06d}"
        chip_path = output_dir / f"{chip_id}.tif"
        granule_to_geotiff(granule_path, chip_path,
                           window=(row, column, config.size, config.size))

        with rasterio.open(chip_path) as chip:
            fraction = float((chip.dataset_mask() > 0).mean())
            bounds = chip.bounds
            crs = chip.crs.to_string() if chip.crs else ""

        if fraction < config.min_valid_fraction:
            chip_path.unlink()
            continue

        rows.append({
            "chip_id": chip_id, "source_granule": granule_id,
            "date": acquisition_date, "crs": crs,
            "bbox": ",".join(f"{value:.12g}" for value in bounds),
            "valid_fraction": fraction, "path": str(chip_path),
        })

    # The manifest is shared by every granule and every run, so rows are merged
    # rather than rewritten. Writing only the selected positions would otherwise
    # drop the chips a previous run indexed.
    existing = []
    manifest_path = output_dir / "manifest.csv"
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as stream:
            existing = [item for item in csv.DictReader(stream)
                        if item.get("source_granule") == granule_id
                        and item.get("chip_id") not in {r["chip_id"] for r in rows}]
    _update_manifest(manifest_path, granule_id, existing + rows)
    return rows
