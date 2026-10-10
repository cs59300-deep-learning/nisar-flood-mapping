
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from nisar_flood.groundtruth.hand import (
    align_hand_to_reference,
    clip_hand_to_aoi,
    prepare_hand_for_chip,
)


def create_test_raster(
    path: Path,
    width: int,
    height: int,
    transform,
    crs: str,
    value: float,
):
    data = np.full((height, width), value, dtype=np.float32)

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": -9999.0,
    }

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def test_clip_hand_to_aoi(tmp_path):
    hand_path = tmp_path / "hand.tif"
    output_path = tmp_path / "clipped_hand.tif"

    create_test_raster(
        hand_path,
        width=100,
        height=100,
        transform=from_origin(0, 2000, 20, 20),
        crs="EPSG:32621",
        value=10.0,
    )

    result = clip_hand_to_aoi(
        hand_path=hand_path,
        aoi_bounds=(200, 600, 1000, 1400),
        output_path=output_path,
    )

    assert result == output_path
    assert output_path.exists()

    with rasterio.open(output_path) as clipped:
        assert clipped.crs.to_string() == "EPSG:32621"
        assert clipped.width > 0
        assert clipped.height > 0
        assert np.isfinite(clipped.read(1)).any()


def test_align_hand_to_reference(tmp_path):
    hand_path = tmp_path / "hand.tif"
    reference_path = tmp_path / "reference.tif"
    output_path = tmp_path / "aligned_hand.tif"

    create_test_raster(
        hand_path,
        width=50,
        height=50,
        transform=from_origin(0, 1000, 20, 20),
        crs="EPSG:32621",
        value=10.0,
    )

    create_test_raster(
        reference_path,
        width=40,
        height=40,
        transform=from_origin(100, 900, 10, 10),
        crs="EPSG:32621",
        value=1.0,
    )

    result = align_hand_to_reference(
        hand_path=hand_path,
        reference_path=reference_path,
        output_path=output_path,
    )

    assert result == output_path
    assert output_path.exists()

    with rasterio.open(reference_path) as reference:
        with rasterio.open(output_path) as aligned_hand:
            assert aligned_hand.crs == reference.crs
            assert aligned_hand.width == reference.width
            assert aligned_hand.height == reference.height
            assert aligned_hand.transform == reference.transform

            data = aligned_hand.read(1)

            assert data.dtype == np.float32
            assert np.isfinite(data).any()


def test_prepare_hand_for_chip(tmp_path):
    hand_path = tmp_path / "hand.tif"
    chip_path = tmp_path / "chip.tif"
    output_path = tmp_path / "chip_hand.tif"

    create_test_raster(
        hand_path,
        width=100,
        height=100,
        transform=from_origin(0, 2000, 20, 20),
        crs="EPSG:32621",
        value=25.0,
    )

    create_test_raster(
        chip_path,
        width=32,
        height=32,
        transform=from_origin(200, 1400, 20, 20),
        crs="EPSG:32621",
        value=1.0,
    )

    result = prepare_hand_for_chip(
        hand_path=hand_path,
        reference_path=chip_path,
        output_path=output_path,
    )

    assert result == output_path

    with rasterio.open(chip_path) as chip:
        with rasterio.open(output_path) as hand:
            assert hand.crs == chip.crs
            assert hand.transform == chip.transform
            assert hand.width == chip.width
            assert hand.height == chip.height

            data = hand.read(1)
            assert np.isfinite(data).any()
