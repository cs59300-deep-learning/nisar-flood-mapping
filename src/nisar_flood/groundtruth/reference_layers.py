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
