from pathlib import Path

import h5py
import numpy as np
from pyproj import CRS

from nisar_flood.pipeline.gcov import read_gcov


def test_read_gcov_frequency_a_hh_hv_in_windows(tmp_path):
    granule_path = tmp_path / "synthetic_gcov.h5"
    expected_hh = np.arange(30, dtype=np.float32).reshape(5, 6)
    expected_hv = expected_hh + 100

    with h5py.File(granule_path, "w") as granule:
        frequency_a = granule.create_group("/science/LSAR/GCOV/grids/frequencyA")
        frequency_a.create_dataset("HHHH", data=expected_hh, chunks=(2, 6))
        frequency_a.create_dataset("HVHV", data=expected_hv, chunks=(2, 6))
        frequency_a.create_dataset("xCoordinates", data=np.array([100, 110, 120, 130, 140, 150]))
        frequency_a.create_dataset("yCoordinates", data=np.array([200, 190, 180, 170, 160]))
        frequency_a.create_dataset("projection", data=np.uint32(32615))
        frequency_a.create_dataset("xCoordinateSpacing", data=np.float64(10))
        frequency_a.create_dataset("yCoordinateSpacing", data=np.float64(10))

        # Ensure the reader selects Frequency A rather than a lower resolution grid.
        frequency_b = granule.create_group("/science/LSAR/GCOV/grids/frequencyB")
        frequency_b.create_dataset("HHHH", data=np.full((1, 1), -1, dtype=np.float32))
        frequency_b.create_dataset("HVHV", data=np.full((1, 1), -1, dtype=np.float32))

    output_dir = tmp_path / "mapped"
    output_dir.mkdir()
    with read_gcov(granule_path, output_dir, window_rows=2) as result:
        assert isinstance(result.hh, np.memmap)
        assert isinstance(result.hv, np.memmap)
        np.testing.assert_array_equal(result.hh, expected_hh)
        np.testing.assert_array_equal(result.hv, expected_hv)
        assert result.geotransform == (95.0, 10.0, 0.0, 205.0, 0.0, -10.0)
        assert result.crs == CRS.from_epsg(32615)
        mapped_directory = Path(result.hh.filename).parent

    assert not mapped_directory.exists()
