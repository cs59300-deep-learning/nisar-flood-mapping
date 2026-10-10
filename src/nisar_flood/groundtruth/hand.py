from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask
from rasterio.warp import reproject
from shapely.geometry import box, mapping


def clip_hand_to_aoi(
    hand_path: str | Path,
    aoi_bounds: tuple[float, float, float, float],
    output_path: str | Path,
) -> Path:
    """Clip a HAND raster to an AOI bounding box."""

    hand_path = Path(hand_path)
    output_path = Path(output_path)

    if not hand_path.exists():
        raise FileNotFoundError(f"HAND raster not found: {hand_path}")

    min_x, min_y, max_x, max_y = aoi_bounds
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("Invalid AOI bounds.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    aoi = box(min_x, min_y, max_x, max_y)

    with rasterio.open(hand_path) as src:
        clipped, transform = mask(
            src,
            [mapping(aoi)],
            crop=True,
            filled=False,
        )

        # Convert masked pixels and source nodata pixels to NaN.
        clipped_data = clipped.filled(np.nan).astype(np.float32)

        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=clipped_data.shape[1],
            width=clipped_data.shape[2],
            transform=transform,
            dtype="float32",
            count=1,
            nodata=np.nan,
            compress="deflate",
            tiled=False,
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(clipped_data[0], 1)

    return output_path


def align_hand_to_reference(
    hand_path: str | Path,
    reference_path: str | Path,
    output_path: str | Path,
    resampling: Resampling = Resampling.bilinear,
) -> Path:
    """Reproject HAND onto the exact grid of a reference raster."""

    hand_path = Path(hand_path)
    reference_path = Path(reference_path)
    output_path = Path(output_path)

    if not hand_path.exists():
        raise FileNotFoundError(f"HAND raster not found: {hand_path}")
    if not reference_path.exists():
        raise FileNotFoundError(
            f"Reference raster not found: {reference_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(reference_path) as reference:
        destination = np.full(
            (reference.height, reference.width),
            np.nan,
            dtype=np.float32,
        )

        with rasterio.open(hand_path) as hand:
            reproject(
                source=rasterio.band(hand, 1),
                destination=destination,
                src_transform=hand.transform,
                src_crs=hand.crs,
                src_nodata=hand.nodata,
                dst_transform=reference.transform,
                dst_crs=reference.crs,
                dst_nodata=np.nan,
                resampling=resampling,
                init_dest_nodata=True,
            )

        profile = {
            "driver": "GTiff",
            "height": reference.height,
            "width": reference.width,
            "count": 1,
            "dtype": "float32",
            "crs": reference.crs,
            "transform": reference.transform,
            "nodata": np.nan,
            "compress": "deflate",
            "tiled": False,
        }

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(destination, 1)

    return output_path


def prepare_hand_for_chip(
    hand_path: str | Path,
    reference_path: str | Path,
    output_path: str | Path,
    resampling: Resampling = Resampling.bilinear,
) -> Path:
    """Prepare HAND on the exact NISAR chip grid."""

    return align_hand_to_reference(
        hand_path=hand_path,
        reference_path=reference_path,
        output_path=output_path,
        resampling=resampling,
    )
