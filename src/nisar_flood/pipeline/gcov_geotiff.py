"""Write a NISAR GCOV granule's Frequency A layers as a chippable GeoTIFF.

``gcov.read_gcov`` loads the HDF5 covariance terms and ``chipping.chip_raster``
cuts chips from a GeoTIFF, but nothing joined the two: the chipper needs a
raster on disk carrying the CRS, the geotransform and a validity mask. This
module is that step.

The output is **gamma0 in decibels**, one band per polarisation, float32, with
the product's validity layer written as the GeoTIFF mask band rather than as a
sentinel pixel value. Backscatter in dB has no spare value to reserve: 0 dB is
real data, so validity has to live somewhere other than the pixels.

Conversion runs in row blocks so a full-resolution granule (16344 x 16740 for
the Amazon frames) never has to be resident in memory at once.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import rasterio
from rasterio.transform import from_origin

__all__ = ["POLARISATIONS", "granule_to_geotiff"]

_FREQUENCY_A = "/science/LSAR/GCOV/grids/frequencyA"

#: Diagonal covariance terms, in band order. These are the co- and cross-polarised
#: gamma0 power terms; the off-diagonal terms are complex and not used here.
POLARISATIONS = ("HHHH", "HVHV")

#: Mask code marking a sample as usable. 0 is partially focused data and 255 is
#: outside the acquisition, so ``mask != 0`` would wrongly admit 255.
VALID_CODE = 1


def granule_to_geotiff(
    granule_path: str | Path,
    destination_path: str | Path,
    *,
    block_rows: int = 1024,
    floor_db: float | None = None,
    window: tuple[int, int, int, int] | None = None,
) -> Path:
    """Convert one GCOV granule to a float32 dB GeoTIFF with a validity mask.

    Parameters
    ----------
    granule_path:
        NISAR L2 GCOV ``.h5`` product.
    destination_path:
        GeoTIFF to write. Parent directories are created.
    block_rows:
        Number of raster rows converted per iteration. Bounds peak memory.
    floor_db:
        Optional lower clamp, in dB. ``None`` (the default) stores the measured
        values unclamped, so the choice of floor stays a model-input decision in
        ``datasets.transforms`` instead of being baked into the chips, where
        changing it would mean re-cutting every chip.
    window:
        Optional ``(row_off, col_off, height, width)`` sub-region to convert.
        Converting one chip-sized window reads only that part of the HDF5, which
        is what makes cutting a handful of assigned chips cheap compared with
        converting a full 1.8 GB granule first.

    Returns
    -------
    pathlib.Path
        The written GeoTIFF.
    """
    granule_path = Path(granule_path)
    destination_path = Path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with h5py.File(granule_path, "r") as granule:
        grid = granule[_FREQUENCY_A]
        for name in (*POLARISATIONS, "mask", "xCoordinates", "yCoordinates", "projection"):
            if name not in grid:
                raise KeyError(f"Frequency A grid is missing {name!r}")

        bands = [grid[name] for name in POLARISATIONS]
        rows, columns = bands[0].shape
        if any(band.shape != (rows, columns) for band in bands):
            raise ValueError("polarisation layers must share one shape")

        x = np.asarray(grid["xCoordinates"][:], dtype=np.float64)
        y = np.asarray(grid["yCoordinates"][:], dtype=np.float64)
        if x.size != columns or y.size != rows:
            raise ValueError("coordinate lengths do not match the raster shape")

        row_off, col_off = 0, 0
        if window is not None:
            row_off, col_off, height, width = window
            if row_off < 0 or col_off < 0 or row_off + height > rows or col_off + width > columns:
                raise ValueError(f"window {window} falls outside the {rows}x{columns} grid")
            rows, columns = height, width
            x = x[col_off:col_off + width]
            y = y[row_off:row_off + height]

        # The coordinate arrays give pixel centres; a geotransform locates the
        # upper-left pixel corner, half a pixel out in each direction.
        x_step = float(x[1] - x[0])
        y_step = float(y[0] - y[1])
        transform = from_origin(float(x[0]) - x_step / 2, float(y[0]) + y_step / 2,
                                x_step, y_step)
        epsg = int(np.asarray(grid["projection"][()]).item())

        profile = {
            "driver": "GTiff", "width": columns, "height": rows,
            "count": len(POLARISATIONS), "dtype": "float32", "nodata": float("nan"),
            "crs": f"EPSG:{epsg}", "transform": transform, "compress": "deflate",
            "tiled": True, "blockxsize": 512, "blockysize": 512, "BIGTIFF": "IF_SAFER",
        }

        mask_layer = grid["mask"]
        validity = np.zeros((rows, columns), dtype="uint8")

        with rasterio.open(destination_path, "w", **profile) as destination:
            for index, name in enumerate(POLARISATIONS, start=1):
                destination.set_band_description(index, f"{name[:2]} gamma0 dB")

            for start in range(0, rows, block_rows):
                stop = min(start + block_rows, rows)
                window = rasterio.windows.Window(0, start, columns, stop - start)

                source = slice(row_off + start, row_off + stop)
                span = slice(col_off, col_off + columns)
                block_mask = mask_layer[source, span] == VALID_CODE
                validity[start:stop, :] = block_mask * 255

                for index, band in enumerate(bands, start=1):
                    power = np.asarray(band[source, span], dtype=np.float64)
                    # log10 is defined only for strictly positive power. Zeros and
                    # negatives are masked fill or numerical artefacts, not signal.
                    decibels = np.full(power.shape, np.nan, dtype=np.float64)
                    positive = power > 0.0
                    np.log10(power, out=decibels, where=positive)
                    decibels[positive] *= 10.0
                    if floor_db is not None:
                        np.maximum(decibels, floor_db, out=decibels, where=positive)
                    decibels[~block_mask] = np.nan
                    destination.write(decibels.astype("float32"), index, window=window)

            destination.write_mask(validity)

    return destination_path
