"""Create georeferenced, overlapping chips and a CSV index for each granule."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window


@dataclass(frozen=True)
class ChipConfig:
    size: int = 512
    stride: int = 400
    min_valid_fraction: float = 0.70

    def __post_init__(self) -> None:
        if self.size <= 0 or self.stride <= 0:
            raise ValueError("size and stride must be positive")
        if not 0 <= self.min_valid_fraction <= 1:
            raise ValueError("min_valid_fraction must be between 0 and 1")


def _starts(length: int, size: int, stride: int) -> list[int]:
    """Cover the far edge too, even when the stride does not land exactly on it."""
    if length < size:
        return []
    starts = list(range(0, length - size + 1, stride))
    last = length - size
    if starts[-1] != last:
        starts.append(last)
    return starts


def chip_raster(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    granule_id: str,
    acquisition_date: str | date,
    config: ChipConfig = ChipConfig(),
) -> list[dict[str, str | float]]:
    """Write chips with at least the configured valid-pixel fraction.

    The source must already be reprojected to the common grid. Valid pixels are
    determined from the source dataset's mask/nodata metadata.
    """
    source_path, output_dir = Path(source_path), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    day = acquisition_date.isoformat() if isinstance(acquisition_date, date) else str(acquisition_date)
    rows: list[dict[str, str | float]] = []

    with rasterio.open(source_path) as src:
        for row in _starts(src.height, config.size, config.stride):
            for col in _starts(src.width, config.size, config.stride):
                window = Window(col, row, config.size, config.size)
                valid = src.dataset_mask(window=window) > 0
                fraction = float(valid.mean())
                if fraction < config.min_valid_fraction:
                    continue

                chip_id = f"{granule_id}_{row:06d}_{col:06d}"
                chip_path = output_dir / f"{chip_id}.tif"
                profile = src.profile.copy()
                profile.update(
                    driver="GTiff", width=config.size, height=config.size,
                    transform=src.window_transform(window), compress="deflate",
                )
                with rasterio.open(chip_path, "w", **profile) as dst:
                    dst.write(src.read(window=window))
                    dst.write_mask(valid.astype("uint8") * 255)

                # Pixel-corner bounds: left, bottom, right, top in source CRS.
                bounds = rasterio.windows.bounds(window, src.transform)
                rows.append({
                    "chip_id": chip_id, "source_granule": granule_id,
                    "date": day,
                    "bbox": ",".join(f"{value:.12g}" for value in bounds),
                    "valid_fraction": fraction,
                    "path": str(chip_path),
                })

    manifest = output_dir / "manifest.csv"
    fields = ["chip_id", "source_granule", "date", "bbox", "valid_fraction", "path"]
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows
