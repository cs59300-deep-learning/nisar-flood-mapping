"""Cover the granule -> GeoTIFF -> chip path (#9, #10)."""

import csv

import h5py
import numpy as np
import pytest
import rasterio

from nisar_flood.pipeline.gcov_geotiff import granule_to_geotiff
from nisar_flood.pipeline.make_chips import make_chips, parse_positions

ROWS, COLUMNS = 40, 36
ORIGIN_X, ORIGIN_Y, PIXEL = 500000.0, 9800000.0, 20.0
EPSG = 32720


def write_granule(path, *, hh=None, hv=None, mask=None):
    """Build a minimal GCOV product with the layers the converter reads."""
    hh = np.full((ROWS, COLUMNS), 0.1, dtype="float32") if hh is None else hh
    hv = np.full((ROWS, COLUMNS), 0.01, dtype="float32") if hv is None else hv
    mask = np.ones((ROWS, COLUMNS), dtype="uint8") if mask is None else mask
    with h5py.File(path, "w") as granule:
        grid = granule.create_group("/science/LSAR/GCOV/grids/frequencyA")
        grid["HHHH"], grid["HVHV"], grid["mask"] = hh, hv, mask
        # Coordinate arrays give pixel centres, half a pixel inside the corner.
        grid["xCoordinates"] = ORIGIN_X + PIXEL / 2 + PIXEL * np.arange(COLUMNS)
        grid["yCoordinates"] = ORIGIN_Y - PIXEL / 2 - PIXEL * np.arange(ROWS)
        grid["projection"] = EPSG
    return path


def test_converter_writes_decibels_with_the_grid_from_the_product(tmp_path):
    granule = write_granule(tmp_path / "g.h5")
    raster = granule_to_geotiff(granule, tmp_path / "g.tif")

    with rasterio.open(raster) as output:
        assert output.count == 2
        assert output.crs.to_epsg() == EPSG
        assert output.transform.c == ORIGIN_X and output.transform.f == ORIGIN_Y
        assert output.transform.a == PIXEL and output.transform.e == -PIXEL
        # 10 * log10(0.1) = -10 dB, 10 * log10(0.01) = -20 dB.
        assert output.read(1) == pytest.approx(-10.0)
        assert output.read(2) == pytest.approx(-20.0)


def test_only_mask_code_one_counts_as_valid(tmp_path):
    mask = np.ones((ROWS, COLUMNS), dtype="uint8")
    mask[:10, :] = 255        # outside the acquisition
    mask[10:14, :] = 0        # partially focused
    granule = write_granule(tmp_path / "g.h5", mask=mask)
    raster = granule_to_geotiff(granule, tmp_path / "g.tif")

    with rasterio.open(raster) as output:
        valid = output.dataset_mask() > 0
        assert not valid[:14].any()
        assert valid[14:].all()
        assert np.isnan(output.read(1)[:14]).all()


def test_non_positive_power_becomes_no_data_not_minus_infinity(tmp_path):
    hh = np.full((ROWS, COLUMNS), 0.1, dtype="float32")
    hh[0, 0] = 0.0
    granule = write_granule(tmp_path / "g.h5", hh=hh)
    raster = granule_to_geotiff(granule, tmp_path / "g.tif")

    with rasterio.open(raster) as output:
        band = output.read(1)
    assert np.isnan(band[0, 0])
    assert np.isfinite(band[1:]).all()


def test_a_window_matches_the_same_region_of_the_full_conversion(tmp_path):
    rng = np.random.default_rng(0)
    hh = rng.uniform(0.01, 1.0, (ROWS, COLUMNS)).astype("float32")
    granule = write_granule(tmp_path / "g.h5", hh=hh)

    full = granule_to_geotiff(granule, tmp_path / "full.tif")
    part = granule_to_geotiff(granule, tmp_path / "part.tif", window=(8, 12, 16, 16))

    with rasterio.open(full) as a, rasterio.open(part) as b:
        assert np.array_equal(a.read(1)[8:24, 12:28], b.read(1))
        assert b.transform.c == ORIGIN_X + 12 * PIXEL
        assert b.transform.f == ORIGIN_Y - 8 * PIXEL


def test_a_window_outside_the_grid_is_rejected(tmp_path):
    granule = write_granule(tmp_path / "g.h5")
    with pytest.raises(ValueError, match="outside"):
        granule_to_geotiff(granule, tmp_path / "part.tif", window=(0, 0, ROWS + 1, COLUMNS))


def test_block_size_does_not_change_the_result(tmp_path):
    rng = np.random.default_rng(1)
    hh = rng.uniform(0.01, 1.0, (ROWS, COLUMNS)).astype("float32")
    granule = write_granule(tmp_path / "g.h5", hh=hh)

    one = granule_to_geotiff(granule, tmp_path / "a.tif", block_rows=ROWS)
    many = granule_to_geotiff(granule, tmp_path / "b.tif", block_rows=7)
    with rasterio.open(one) as a, rasterio.open(many) as b:
        assert np.array_equal(a.read(), b.read())


def test_selected_positions_and_a_whole_granule_agree(tmp_path):
    rng = np.random.default_rng(2)
    hh = rng.uniform(0.01, 1.0, (ROWS, COLUMNS)).astype("float32")
    granule = write_granule(tmp_path / "g.h5", hh=hh)
    shared = {"granule_id": "G1", "acquisition_date": "2026-06-18",
              "size": 16, "stride": 8, "min_valid_fraction": 0.7}

    whole = make_chips(granule, tmp_path / "whole", **shared)
    picked = make_chips(granule, tmp_path / "picked", only=["8,8"], **shared)

    assert len(picked) == 1
    assert picked[0]["chip_id"] == "G1_000008_000008"
    assert picked[0]["chip_id"] in {row["chip_id"] for row in whole}
    with rasterio.open(tmp_path / "whole" / "G1_000008_000008.tif") as a, \
         rasterio.open(tmp_path / "picked" / "G1_000008_000008.tif") as b:
        assert np.array_equal(a.read(), b.read())
        assert a.transform == b.transform


def test_a_position_below_the_valid_threshold_is_not_written(tmp_path):
    mask = np.ones((ROWS, COLUMNS), dtype="uint8")
    mask[:12, :] = 255
    granule = write_granule(tmp_path / "g.h5", mask=mask)

    rows = make_chips(granule, tmp_path / "out", granule_id="G1",
                      acquisition_date="2026-06-18", size=16, stride=8,
                      min_valid_fraction=0.7, only=["0,0", "16,0"])

    assert [row["chip_id"] for row in rows] == ["G1_000016_000000"]
    assert not (tmp_path / "out" / "G1_000000_000000.tif").exists()


def test_cutting_more_positions_later_keeps_the_rows_already_indexed(tmp_path):
    granule = write_granule(tmp_path / "g.h5")
    shared = {"granule_id": "G1", "acquisition_date": "2026-06-18",
              "size": 16, "stride": 8, "min_valid_fraction": 0.7}

    make_chips(granule, tmp_path / "out", only=["0,0"], **shared)
    make_chips(granule, tmp_path / "out", only=["8,8"], **shared)

    with (tmp_path / "out" / "manifest.csv").open(newline="") as stream:
        indexed = [row["chip_id"] for row in csv.DictReader(stream)]
    assert sorted(indexed) == ["G1_000000_000000", "G1_000008_000008"]


def test_recutting_a_position_updates_its_row_instead_of_duplicating_it(tmp_path):
    granule = write_granule(tmp_path / "g.h5")
    shared = {"granule_id": "G1", "acquisition_date": "2026-06-18",
              "size": 16, "stride": 8, "min_valid_fraction": 0.7}

    make_chips(granule, tmp_path / "out", only=["0,0"], **shared)
    make_chips(granule, tmp_path / "out", only=["0,0"], **shared)

    with (tmp_path / "out" / "manifest.csv").open(newline="") as stream:
        indexed = [row["chip_id"] for row in csv.DictReader(stream)]
    assert indexed == ["G1_000000_000000"]


def test_positions_are_parsed_and_bad_input_is_reported(tmp_path):
    assert parse_positions(["8800,13200", " 7600 , 5600 "]) == [(8800, 13200), (7600, 5600)]
    assert parse_positions(None) is None
    with pytest.raises(ValueError, match="ROW,COL"):
        parse_positions(["8800"])
