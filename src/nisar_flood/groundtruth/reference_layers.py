<<<<<<< HEAD
<<<<<<< HEAD
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
=======
=======
>>>>>>> b79a53e4a063078c10b56f1e69dc2e5f56d301a2
"""Independent water-extent reference layers, put on the HAND grid (#14, #15).

The calibration in ``stage_calibration`` needs a binary water mask that is independent of both NISAR
and HAND, on the same pixel grid as HAND. Products such as OPERA DSWx come as many MGRS tiles in
several UTM zones, with class codes that include cloud, snow and fill values. This module turns a
set of such tiles into one mask with a fixed convention:

    1   = water
    0   = not water
    255 = unknown (outside every tile, fill, cloud, or any class code we were not told how to read)

Unknown is never counted as water *or* as dry: the calibration drops those pixels from every metric.
A class code that is not listed is treated as unknown and reported, never silently guessed, because
guessing wrong here (for example reading "inundated vegetation" as open water) would bias ``stage0``.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np

WATER = 1
NOT_WATER = 0
UNKNOWN = 255

CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
# NASA CMR collection ids (PO.DAAC): OPERA Dynamic Surface Water Extent from Sentinel-1 / from HLS optical.
DSWX_S1_COLLECTION = "C2949811996-POCLOUD"
DSWX_HLS_COLLECTION = "C2617126679-POCLOUD"


def cmr_search(
    concept_id: str,
    date: str,
    bbox: tuple[float, float, float, float],
    page_size: int = 2000,
    timeout: int = 60,
) -> list[dict]:
    """Granules of a CMR collection acquired on ``date`` (YYYY-MM-DD, UTC) inside ``bbox`` (W, S, E, N)."""
    import requests

    params = {
        "collection_concept_id": concept_id,
        "temporal": f"{date}T00:00:00Z,{date}T23:59:59Z",
        "bounding_box": ",".join(str(v) for v in bbox),
        "page_size": page_size,
    }
    response = requests.get(CMR_GRANULES_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json().get("feed", {}).get("entry", [])


def select_layer_links(entries: list[dict], date: str, layer: str) -> list[tuple[str, str]]:
    """``(granule title, url)`` of the ``layer`` file (e.g. ``B01_WTR``) for granules acquired on ``date``.

    Matches the layer by the end of the file name (``..._B01_WTR.tif``) so ``B01_WTR`` does not also pick
    up ``B05_WTR-1``-style names. Duplicate granules are dropped. Only https download links are used.
    """
    wanted = f"_{layer}.tif"
    seen: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if not (entry.get("time_start") or "").startswith(date):
            continue
        for link in entry.get("links", []):
            href = link.get("href", "")
            if "data#" in link.get("rel", "") and href.startswith("https") and href.endswith(wanted):
                seen.setdefault(href, (entry.get("title", ""), href))
    return list(seen.values())


def list_layer_suffixes(entries: list[dict]) -> list[str]:
    """Distinct layer suffixes (``B01_WTR``, ...) offered by the first granule: for when a name is wrong."""
    for entry in entries:
        names = [
            link["href"].rsplit("/", 1)[-1]
            for link in entry.get("links", [])
            if "data#" in link.get("rel", "") and link.get("href", "").endswith(".tif")
        ]
        if names:
            return sorted({"_".join(n[:-4].split("_")[-2:]) for n in names})
    return []


def download_with_session(session, url: str, dest_dir: str | Path, chunk: int = 1 << 20) -> Path:
    """Stream ``url`` to ``dest_dir`` with an authenticated ``requests`` session. Skips a finished file."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    response = session.get(url, stream=True, timeout=120)
    if response.status_code in (401, 403):
        raise PermissionError(
            f"HTTP {response.status_code} for {url}. Log in to Earthdata, accept the PO.DAAC/ASF data "
            "terms (EULA) once in a browser, and retry."
        )
    response.raise_for_status()
    with open(tmp, "wb") as fh:
        fh.writelines(response.iter_content(chunk))
    tmp.replace(dest)
    return dest


def recode(
    codes: np.ndarray,
    water_codes: Iterable[int] = (1,),
    not_water_codes: Iterable[int] = (0,),
    unknown_codes: Iterable[int] = (255,),
) -> tuple[np.ndarray, dict[int, int]]:
    """Map product class codes onto 1 / 0 / 255.

    Returns ``(mask, unmapped)``. ``unmapped`` counts the pixels per code that were in none of the three
    lists; they come back as 255 (unknown). Codes listed as unknown (fill, cloud, ...) are not reported.
    """
    codes = np.asarray(codes)
    water, dry, unk = set(water_codes), set(not_water_codes), set(unknown_codes)
    overlap = (water & dry) | (water & unk) | (dry & unk)
    if overlap:
        raise ValueError(f"class codes listed under more than one meaning: {sorted(overlap)}")

    out = np.full(codes.shape, UNKNOWN, dtype="uint8")
    out[np.isin(codes, list(water))] = WATER
    out[np.isin(codes, list(dry))] = NOT_WATER

    unmapped: dict[int, int] = {}
    present, counts = np.unique(codes, return_counts=True)
    for value, count in zip(present.tolist(), counts.tolist()):
        if value not in water and value not in dry and value not in unk:
            unmapped[int(value)] = int(count)
    return out, unmapped


def mosaic_tiles_to_grid(
    tile_paths: Iterable[str | Path],
    grid_path: str | Path,
    out_path: str | Path,
    water_codes: Iterable[int] = (1,),
    not_water_codes: Iterable[int] = (0,),
    unknown_codes: Iterable[int] = (255,),
) -> dict:
    """Recode every tile, resample (nearest) onto the grid of ``grid_path`` and write one GeoTIFF.

    Where tiles overlap, a pixel known in any tile is kept (later tiles never overwrite a known pixel
    with unknown). Tiles may be in different CRSs. The output has the grid of ``grid_path`` exactly,
    dtype uint8, nodata 255, and is the file to pass to ``scripts/calibrate_stage0.py --reference``.

    Returns a summary: tiles used, the fraction of the grid that is known, the water fraction of the
    known pixels, and any unmapped class codes with pixel counts.
    """
    import rasterio
    from rasterio.warp import Resampling, reproject

    tile_paths = [Path(p) for p in tile_paths]
    if not tile_paths:
        raise ValueError("no tiles given")

    with rasterio.open(grid_path) as grid:
        crs, transform, height, width = grid.crs, grid.transform, grid.height, grid.width

    dest = np.full((height, width), UNKNOWN, dtype="uint8")
    unmapped_total: dict[int, int] = {}
    used = []

    for path in tile_paths:
        with rasterio.open(path) as src:
            mask, unmapped = recode(src.read(1), water_codes, not_water_codes, unknown_codes)
            for code, n in unmapped.items():
                unmapped_total[code] = unmapped_total.get(code, 0) + n
            # Reproject the recoded tile onto the grid. Source pixels equal to 255 are "no data" for the
            # warp, so they leave whatever the destination already holds (another tile's value, or 255).
            reproject(
                source=mask,
                destination=dest,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=UNKNOWN,
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=UNKNOWN,
                resampling=Resampling.nearest,
                init_dest_nodata=False,
            )
            used.append(path.name)

    known = dest != UNKNOWN
    n_known = int(known.sum())
    summary = {
        "tiles": used,
        "n_tiles": len(used),
        "known_fraction": n_known / dest.size,
        "water_fraction_of_known": float((dest[known] == WATER).mean()) if n_known else float("nan"),
        "unmapped_codes": unmapped_total,
    }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path, "w", driver="GTiff", height=height, width=width, count=1, dtype="uint8",
        crs=crs, transform=transform, nodata=UNKNOWN, compress="deflate", tiled=True,
        blockxsize=512, blockysize=512,
    ) as dst:
        dst.write(dest, 1)
    summary["out_path"] = str(out_path)
    return summary
<<<<<<< HEAD
>>>>>>> e1bf92b529b3ed2cf57c63eb31a132101bfdae04
=======
>>>>>>> b79a53e4a063078c10b56f1e69dc2e5f56d301a2
