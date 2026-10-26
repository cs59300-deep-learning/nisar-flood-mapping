import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from nisar_flood.groundtruth.published_reference import (
    CLASS_FLOOD_WATER,
    CLASS_LAND,
    CLASS_NODATA,
    CLASS_PERMANENT_WATER,
    align_categorical_to_reference,
    build_reference_layers,
    clip_raster_to_aoi,
    jrc_permanent_water,
    separate_permanent_and_flood_water,
    unique_values,
)


def write(path, data, transform, crs="EPSG:4326", nodata=None):
    data = np.asarray(data)
    with rasterio.open(
        path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
        count=1, dtype=data.dtype, crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


def test_permanent_threshold_is_strictly_greater_than_five():
    s = np.array([0, 5, 6, 12, 255], dtype=np.uint8)
    assert jrc_permanent_water(s).tolist() == [False, False, True, True, False]
    assert jrc_permanent_water(s, 3).tolist() == [False, True, True, True, False]


def test_separation_classes_and_nodata():
    seas = np.array([[12, 12, 2, 0], [255, 6, 5, 0]], dtype=np.uint8)
    jers = np.array([[1, 0, 1, 0], [1, 1, 1, 9]], dtype=np.uint8)
    out = separate_permanent_and_flood_water(seas, jers, wetland_values=[1], jers1_nodata=9)
    assert out.tolist() == [
        [CLASS_PERMANENT_WATER, CLASS_PERMANENT_WATER, CLASS_FLOOD_WATER, CLASS_LAND],
        [CLASS_NODATA, CLASS_PERMANENT_WATER, CLASS_FLOOD_WATER, CLASS_NODATA],
    ]


def test_separation_rejects_mismatched_grids():
    with pytest.raises(ValueError, match="Grids differ"):
        separate_permanent_and_flood_water(
            np.zeros((2, 2), np.uint8), np.zeros((3, 3), np.uint8), [1]
        )


def test_clip_mosaics_tiles_and_preserves_dtype_and_values(tmp_path):
    # Two adjacent 1x1 degree tiles, 0.1 deg pixels, different constant values.
    left = write(tmp_path / "a.tif", np.full((10, 10), 3, np.uint8),
                 from_origin(-61.0, -1.0, 0.1, 0.1), nodata=255)
    right = write(tmp_path / "b.tif", np.full((10, 10), 8, np.uint8),
                  from_origin(-60.0, -1.0, 0.1, 0.1), nodata=255)
    out = clip_raster_to_aoi([left, right], (-60.5, -1.5, -59.5, -1.0), tmp_path / "o.tif")
    with rasterio.open(out) as src:
        d = src.read(1)
        assert src.dtypes[0] == "uint8" and src.nodata == 255
        assert set(np.unique(d)) == {3, 8}
        left_b, bottom, right_b, top = src.bounds
        assert left_b >= -60.5 - 1e-6 and right_b <= -59.5 + 1e-6
        assert d.shape == (5, 10)


def test_clip_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        clip_raster_to_aoi(tmp_path / "nope.tif", (0, 0, 1, 1), tmp_path / "o.tif")
    p = write(tmp_path / "a.tif", np.zeros((4, 4), np.uint8), from_origin(0, 4, 1, 1))
    with pytest.raises(ValueError, match="Invalid AOI"):
        clip_raster_to_aoi(p, (1, 0, 0, 1), tmp_path / "o.tif")


def test_align_is_nearest_and_exact_grid(tmp_path):
    src = write(tmp_path / "s.tif", np.array([[1, 2], [3, 4]], np.uint8),
                from_origin(-60.0, 0.0, 0.5, 0.5), nodata=255)
    ref = write(tmp_path / "r.tif", np.zeros((4, 4), np.float32),
                from_origin(-60.0, 0.0, 0.25, 0.25))
    out = align_categorical_to_reference(src, ref, tmp_path / "o.tif")
    with rasterio.open(out) as a, rasterio.open(ref) as r:
        assert a.transform == r.transform and a.shape == r.shape
        assert set(np.unique(a.read(1))) == {1, 2, 3, 4}  # no interpolated values


def test_unique_values(tmp_path):
    p = write(tmp_path / "u.tif", np.array([[1, 1], [2, 255]], np.uint8), from_origin(0, 2, 1, 1))
    assert unique_values(p) == {1: 2, 2: 1, 255: 1}


def test_build_reference_layers_end_to_end(tmp_path):
    # Reference grid in UTM 20S covering part of the AOI near -61, -3.
    ref = write(tmp_path / "ref.tif", np.zeros((50, 50), np.float32),
                from_origin(700000.0, 9670000.0, 1000.0, 1000.0), crs="EPSG:32720")
    jrc = []
    for name, x0, val in [("t1", -62.0, 12), ("t2", -61.0, 0)]:
        seas = np.full((100, 100), val, np.uint8)
        jrc.append(write(tmp_path / f"{name}.tif", seas, from_origin(x0, -2.0, 0.01, 0.01), nodata=255))
    jers = write(tmp_path / "jers.tif", np.ones((20, 40), np.uint8),
                 from_origin(-62.0, -2.0, 0.05, 0.05), nodata=0)
    res = build_reference_layers(
        jrc, jers, ref, tmp_path / "out", wetland_values=[1],
        aoi_bounds=(-62.0, -3.0, -60.0, -2.0),
    )
    with rasterio.open(res["separation"]) as s, rasterio.open(ref) as r:
        assert s.crs == r.crs and s.transform == r.transform and s.dtypes[0] == "uint8"
        vals = set(np.unique(s.read(1)).tolist())
    assert vals <= {CLASS_LAND, CLASS_PERMANENT_WATER, CLASS_FLOOD_WATER, CLASS_NODATA}
    assert CLASS_PERMANENT_WATER in vals or CLASS_FLOOD_WATER in vals
