"""Windowed readers for NISAR Level-2 GCOV HDF5 products."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

import h5py
import numpy as np
from pyproj import CRS

_FREQUENCY_A = "/science/LSAR/GCOV/grids/frequencyA"


@dataclass
class GCOVData:
    """Frequency A HH/HV layers and georeferencing.

    The arrays are disk-backed ``numpy.memmap`` instances. Use this object as
    a context manager, or call :meth:`close`, to remove its temporary files.
    """

    hh: np.memmap
    hv: np.memmap
    geotransform: tuple[float, float, float, float, float, float]
    crs: CRS
    _temporary_directory: TemporaryDirectory[str]

    def close(self) -> None:
        """Close the mapped arrays and remove their temporary files."""
        for array in (self.hh, self.hv):
            array.flush()
            if array._mmap is not None:
                array._mmap.close()
        self._temporary_directory.cleanup()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def read_gcov(
    granule_path: str | Path,
    output_dir: str | Path,
    *,
    window_rows: int = 512,
) -> GCOVData:
    """Read Frequency A HHHH and HVHV from a NISAR GCOV granule.

    HDF5 data are copied in row windows into disk-backed float arrays to keep
    resident memory bounded for full-resolution products. ``output_dir`` must
    be an existing directory with enough free disk space. The returned object
    owns a unique temporary subdirectory and removes it when closed.

    The geotransform follows GDAL order and locates the upper-left pixel edge;
    the HDF5 coordinate axes describe pixel centers.
    """
    if window_rows <= 0:
        raise ValueError("window_rows must be a positive integer")

    destination = Path(output_dir)
    if not destination.is_dir():
        raise NotADirectoryError(f"output_dir is not an existing directory: {destination}")

    hh_path = f"{_FREQUENCY_A}/HHHH"
    hv_path = f"{_FREQUENCY_A}/HVHV"
    temp_dir = TemporaryDirectory(prefix="nisar-gcov-", dir=destination)

    try:
        with h5py.File(granule_path, "r") as granule:
            for dataset_path in (hh_path, hv_path):
                if dataset_path not in granule:
                    raise KeyError(f"Required Frequency A dataset is missing: {dataset_path}")

            hh_source = granule[hh_path]
            hv_source = granule[hv_path]
            if hh_source.ndim != 2 or hv_source.ndim != 2:
                raise ValueError("HHHH and HVHV datasets must be two-dimensional")
            if hh_source.shape != hv_source.shape:
                raise ValueError("HHHH and HVHV datasets must have matching shapes")

            grid = granule[_FREQUENCY_A]
            if "xCoordinates" not in grid or "yCoordinates" not in grid:
                raise KeyError("Frequency A grid must contain xCoordinates and yCoordinates")
            x = np.asarray(grid["xCoordinates"][:], dtype=np.float64)
            y = np.asarray(grid["yCoordinates"][:], dtype=np.float64)
            rows, columns = hh_source.shape
            if x.size != columns or y.size != rows:
                raise ValueError("Coordinate lengths do not match the covariance dataset shape")
            if x.size < 2 or y.size < 2:
                raise ValueError(
                    "At least two coordinates per axis are required for georeferencing"
                )

            if "projection" not in grid:
                raise KeyError("Frequency A grid is missing its projection dataset")
            epsg = int(np.asarray(grid["projection"][()]).item())
            crs = CRS.from_epsg(epsg)

            x_step = _grid_spacing(grid, "xCoordinateSpacing", x[1] - x[0])
            y_step = _grid_spacing(grid, "yCoordinateSpacing", y[1] - y[0])
            # Coordinate spacing metadata may be positive even when y decreases.
            if y[1] < y[0]:
                y_step = -abs(y_step)
            else:
                y_step = abs(y_step)
            if x[1] < x[0]:
                x_step = -abs(x_step)
            else:
                x_step = abs(x_step)

            geotransform = (
                float(x[0] - x_step / 2),
                x_step,
                0.0,
                float(y[0] - y_step / 2),
                0.0,
                y_step,
            )

            hh = np.lib.format.open_memmap(
                Path(temp_dir.name) / "HH.npy",
                mode="w+",
                dtype=hh_source.dtype,
                shape=hh_source.shape,
            )
            hv = np.lib.format.open_memmap(
                Path(temp_dir.name) / "HV.npy",
                mode="w+",
                dtype=hv_source.dtype,
                shape=hv_source.shape,
            )
            for row_start in range(0, rows, window_rows):
                row_stop = min(row_start + window_rows, rows)
                hh[row_start:row_stop, :] = hh_source[row_start:row_stop, :]
                hv[row_start:row_stop, :] = hv_source[row_start:row_stop, :]

        return GCOVData(hh, hv, geotransform, crs, temp_dir)
    except Exception:
        temp_dir.cleanup()
        raise


def _grid_spacing(grid: h5py.Group, name: str, fallback: float) -> float:
    """Read a scalar grid spacing value, with coordinate differences as fallback."""
    if name in grid:
        return float(np.asarray(grid[name][()]).item())
    return float(grid.attrs.get(name, fallback))
