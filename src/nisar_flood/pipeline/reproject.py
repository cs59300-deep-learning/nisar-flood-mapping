"""Reproject raster bands and their validity mask onto a common grid."""

from __future__ import annotations

from pathlib import Path

import rasterio
import numpy as np
from rasterio.warp import calculate_default_transform, reproject, Resampling


def reproject_raster(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    dst_crs: str,
    resolution: float | tuple[float, float] | None = None,
    resampling: Resampling = Resampling.bilinear,
) -> Path:
    """Write a GeoTIFF in ``dst_crs`` while retaining nodata validity."""
    source_path, destination_path = Path(source_path), Path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=resolution
        )
        profile = src.profile.copy()
        profile.update(crs=dst_crs, transform=transform, width=width, height=height,
                       driver="GTiff", compress="deflate")
        with rasterio.open(destination_path, "w", **profile) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band), destination=rasterio.band(dst, band),
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=transform, dst_crs=dst_crs,
                    src_nodata=src.nodata, dst_nodata=src.nodata,
                    resampling=resampling,
                )
            # Write the mask separately; it describes pixel validity, not a data band.
            mask = np.zeros((height, width), dtype="uint8")
            reproject(source=src.dataset_mask(), destination=mask,
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=dst_crs,
                      resampling=Resampling.nearest)
            dst.write_mask(mask)
    return destination_path
