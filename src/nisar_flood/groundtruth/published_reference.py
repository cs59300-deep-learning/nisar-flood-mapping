"""Published reference layers for ground truth (Ticket #15).

Two external products are used as an independent cross-check of the
HAND + gauge labels:

* JERS-1 dual-season Amazon wetland masks (Hess et al., ORNL DAAC):
  flooded-forest / wetland extent for the central Amazon basin.
* JRC Global Surface Water ``seasonality`` layer: number of months per
  year with surface water (0-12, 255 = no data). Used to separate
  permanent water from flood water, following DeepSARFlood, which treats
  seasonality > 5 months as permanent.

Categorical rasters are never interpolated: clipping keeps source values and
alignment uses nearest-neighbour resampling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.warp import reproject

# AOI used for the HAND layer (NISAR GCOV footprint + 0.02 deg margin),
# as (min_lon, min_lat, max_lon, max_lat). See docs/hand_methods.md.
AOI_BOUNDS_LONLAT = (-62.705702, -4.58547, -59.648457, -1.585526)

# JRC seasonality: months with water per year.
JRC_NODATA = 255
PERMANENT_MONTHS_THRESHOLD = 5  # permanent if seasonality > 5 (DeepSARFlood)

# Output classes of the permanent / flood separation.
CLASS_LAND = 0
CLASS_PERMANENT_WATER = 1
CLASS_FLOOD_WATER = 2
CLASS_NODATA = 255


def clip_raster_to_aoi(
    raster_paths: Path | str | Sequence[Path | str],
    aoi_bounds: tuple[float, float, float, float],
    output_path: Path | str,
) -> Path:
    """Clip one raster (or mosaic several tiles) to an AOI bounding box.

    Source dtype, nodata and CRS are preserved, so categorical products keep
    their class codes. ``aoi_bounds`` must be in the rasters' own CRS
    (lon/lat for JRC GSW tiles).
    """

    if isinstance(raster_paths, (str, Path)):
        raster_paths = [raster_paths]
    paths = [Path(p) for p in raster_paths]
    if not paths:
        raise ValueError("No input rasters given.")
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"Raster not found: {p}")

    min_x, min_y, max_x, max_y = aoi_bounds
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("Invalid AOI bounds.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sources = [rasterio.open(p) for p in paths]
    try:
        first = sources[0]
        if any(s.crs != first.crs for s in sources):
            raise ValueError("All tiles must share one CRS.")
        data, transform = merge(
            sources, bounds=aoi_bounds, nodata=first.nodata, method="first"
        )
        profile = first.profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[1],
            width=data.shape[2],
            transform=transform,
            compress="deflate",
            tiled=False,
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
    finally:
        for s in sources:
            s.close()

    if data.shape[1] == 0 or data.shape[2] == 0:
        raise ValueError("AOI does not overlap the input raster(s).")

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data)
    return output_path


def align_categorical_to_reference(
    raster_path: Path | str,
    reference_path: Path | str,
    output_path: Path | str,
    fill_value: int = CLASS_NODATA,
) -> Path:
    """Reproject a categorical raster onto the exact grid of a reference.

    Nearest-neighbour only. Pixels outside the source are ``fill_value``.
    """

    raster_path, reference_path = Path(raster_path), Path(reference_path)
    output_path = Path(output_path)
    for p in (raster_path, reference_path):
        if not p.exists():
            raise FileNotFoundError(f"Raster not found: {p}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(reference_path) as ref, rasterio.open(raster_path) as src:
        dtype = src.dtypes[0]
        out = np.full((ref.height, ref.width), fill_value, dtype=dtype)
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=ref.transform,
            dst_crs=ref.crs,
            dst_nodata=fill_value,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
        profile = {
            "driver": "GTiff",
            "height": ref.height,
            "width": ref.width,
            "count": 1,
            "dtype": dtype,
            "crs": ref.crs,
            "transform": ref.transform,
            "nodata": fill_value,
            "compress": "deflate",
            "tiled": False,
        }
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(out, 1)
    return output_path


def jrc_permanent_water(
    seasonality: np.ndarray,
    months_threshold: int = PERMANENT_MONTHS_THRESHOLD,
) -> np.ndarray:
    """Boolean mask of permanent water: seasonality strictly > threshold."""

    s = np.asarray(seasonality)
    return (s != JRC_NODATA) & (s > months_threshold)


def jers1_wetland_mask(
    jers1: np.ndarray,
    wetland_values: Iterable[int],
    nodata: int | None = None,
) -> np.ndarray:
    """Boolean mask of JERS-1 pixels whose class is in ``wetland_values``.

    The class codes come from the ORNL DAAC dataset guide and are passed
    explicitly rather than hard-coded here. Use ``unique_values`` on the
    clipped raster to check them against the guide.
    """

    j = np.asarray(jers1)
    mask = np.isin(j, list(wetland_values))
    if nodata is not None:
        mask &= j != nodata
    return mask


def separate_permanent_and_flood_water(
    seasonality: np.ndarray,
    jers1: np.ndarray,
    wetland_values: Iterable[int],
    jers1_nodata: int | None = None,
    months_threshold: int = PERMANENT_MONTHS_THRESHOLD,
) -> np.ndarray:
    """Classify each pixel as land, permanent water or flood water.

    Both inputs must already be on the same grid.

    * permanent water: JRC seasonality > ``months_threshold`` months.
    * flood water: JERS-1 wetland/flooded class and *not* permanent water.
    * land: everything else.
    * nodata (255): JRC no-data (permanent status unknown) or JERS-1 no-data
      where the pixel is not already permanent water.
    """

    seasonality = np.asarray(seasonality)
    jers1 = np.asarray(jers1)
    if seasonality.shape != jers1.shape:
        raise ValueError(
            f"Grids differ: {seasonality.shape} vs {jers1.shape}. "
            "Align them first (align_categorical_to_reference)."
        )

    permanent = jrc_permanent_water(seasonality, months_threshold)
    wetland = jers1_wetland_mask(jers1, wetland_values, jers1_nodata)

    out = np.full(seasonality.shape, CLASS_LAND, dtype=np.uint8)
    out[wetland & ~permanent] = CLASS_FLOOD_WATER
    out[permanent] = CLASS_PERMANENT_WATER

    unknown = seasonality == JRC_NODATA
    if jers1_nodata is not None:
        unknown |= (jers1 == jers1_nodata) & ~permanent
    out[unknown & ~permanent] = CLASS_NODATA
    return out


def unique_values(raster_path: Path | str) -> dict[int, int]:
    """Class code -> pixel count, for checking codes against a dataset guide."""

    with rasterio.open(raster_path) as src:
        vals, counts = np.unique(src.read(1), return_counts=True)
    return {int(v): int(c) for v, c in zip(vals, counts)}


def build_reference_layers(
    jrc_tiles: Sequence[Path | str],
    jers1_path: Path | str,
    reference_path: Path | str,
    output_dir: Path | str,
    wetland_values: Iterable[int],
    aoi_bounds: tuple[float, float, float, float] = AOI_BOUNDS_LONLAT,
    months_threshold: int = PERMANENT_MONTHS_THRESHOLD,
) -> dict[str, Path]:
    """Run the full ticket #15 workflow and return the written files.

    Steps: clip JERS-1 and JRC seasonality to the AOI, align both to the NISAR
    reference grid, then write the permanent / flood / land classification.
    """

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    jrc_clip = clip_raster_to_aoi(jrc_tiles, aoi_bounds, out / "jrc_seasonality_aoi.tif")

    with rasterio.open(jers1_path) as src:
        jers_crs, jers_nodata = src.crs, src.nodata
        if jers_crs is not None and not jers_crs.is_geographic:
            raise ValueError(
                "JERS-1 raster is projected; reproject to lon/lat first or "
                "clip with bounds in its own CRS."
            )
    jers_clip = clip_raster_to_aoi(jers1_path, aoi_bounds, out / "jers1_wetland_aoi.tif")

    jrc_grid = align_categorical_to_reference(
        jrc_clip, reference_path, out / "jrc_seasonality_aligned.tif", JRC_NODATA
    )
    jers_fill = int(jers_nodata) if jers_nodata is not None else CLASS_NODATA
    jers_grid = align_categorical_to_reference(
        jers_clip, reference_path, out / "jers1_wetland_aligned.tif", jers_fill
    )

    with rasterio.open(jrc_grid) as a, rasterio.open(jers_grid) as b:
        classes = separate_permanent_and_flood_water(
            a.read(1), b.read(1), wetland_values, jers_fill, months_threshold
        )
        profile = a.profile.copy()
    profile.update(dtype="uint8", nodata=CLASS_NODATA)
    sep = out / "permanent_vs_flood_water.tif"
    with rasterio.open(sep, "w", **profile) as dst:
        dst.write(classes, 1)

    return {
        "jrc_clip": jrc_clip,
        "jers1_clip": jers_clip,
        "jrc_aligned": jrc_grid,
        "jers1_aligned": jers_grid,
        "separation": sep,
    }
