"""Round-trip checks for the labelling export (issue #28, acceptance criterion 3)."""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from nisar_flood.labelling.chip_export import (
    EXCLUDED,
    NO_DATA,
    NON_WATER,
    WATER,
    label_summary,
    rasterise_directory,
    rasterise_labels,
    start_annotations,
    start_annotations_directory,
)

# A chip small enough to assert on pixel by pixel, on a grid whose cells are a
# whole number of degrees so polygon corners land exactly on cell boundaries.
SIZE = 8
ORIGIN_X, ORIGIN_Y, CELL = 10.0, 20.0, 1.0


def write_chip(path, *, invalid=None):
    """An 8x8 EPSG:4326 chip, optionally with a block marked invalid."""
    mask = np.full((SIZE, SIZE), 255, dtype="uint8")
    if invalid is not None:
        mask[invalid] = 0
    with rasterio.open(path, "w", driver="GTiff", width=SIZE, height=SIZE, count=1,
                       dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(ORIGIN_X, ORIGIN_Y, CELL, CELL)) as chip:
        chip.write(np.ones((1, SIZE, SIZE), dtype="uint8"))
        chip.write_mask(mask)
    return path


def box(col, row, width, height):
    """Polygon covering a block of cells, in the chip's own coordinates."""
    west, east = ORIGIN_X + col * CELL, ORIGIN_X + (col + width) * CELL
    north, south = ORIGIN_Y - row * CELL, ORIGIN_Y - (row + height) * CELL
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south],
                                                [east, north], [west, north], [west, south]]]}


def write_annotations(path, features):
    """A FeatureCollection in the chip's CRS, declared so no reprojection is guessed."""
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [{"type": "Feature", "geometry": geometry,
                      "properties": {"class": value, "chip_id": "G1", "labeller": "varun",
                                     "labelled_on": "2026-10-24", "evidence_tier": 1,
                                     "notes": ""}}
                     for geometry, value in features],
    }), encoding="utf-8")
    return path


def test_label_matches_chip_grid_and_polygons_land_on_the_right_pixels(tmp_path):
    chip = write_chip(tmp_path / "G1.tif")
    annotations = write_annotations(tmp_path / "G1.geojson",
                                    [(box(0, 0, 3, 2), WATER), (box(5, 5, 2, 2), EXCLUDED)])

    output, summary = rasterise_labels(chip, annotations)

    with rasterio.open(output) as label, rasterio.open(chip) as source:
        assert (label.width, label.height) == (source.width, source.height)
        assert label.transform == source.transform
        assert label.crs == source.crs
        assert label.nodata == NO_DATA
        values = label.read(1)

    assert (values[0:2, 0:3] == WATER).all()
    assert (values[5:7, 5:7] == EXCLUDED).all()
    assert values[4, 0] == NON_WATER          # nothing drawn here
    assert summary["water_px"] == 6
    assert summary["excluded_px"] == 4
    assert summary["polygons"] == 2


def test_unlabelled_chip_is_all_non_water(tmp_path):
    """An empty annotation file means nobody drew anything, not that the chip is wrong."""
    chip = write_chip(tmp_path / "G2.tif")
    annotations = write_annotations(tmp_path / "G2.geojson", [])

    _, summary = rasterise_labels(chip, annotations)

    assert summary["non_water_px"] == SIZE * SIZE
    assert summary["water_px"] == 0


def test_template_placeholder_is_not_a_label(tmp_path):
    """start_annotations seeds a classless polygon so QGIS sees a polygon layer."""
    chip = write_chip(tmp_path / "G3.tif")
    annotations = start_annotations(chip)

    collection = json.loads(annotations.read_text(encoding="utf-8"))
    assert len(collection["features"]) == 1
    assert collection["features"][0]["properties"]["class"] is None

    _, summary = rasterise_labels(chip, annotations)
    assert summary["polygons"] == 0
    assert summary["water_px"] == 0


def test_invalid_chip_pixels_win_over_whatever_was_drawn(tmp_path):
    """A hole in the swath cannot be water, and the override is reported, not hidden."""
    chip = write_chip(tmp_path / "G4.tif", invalid=(slice(0, 2), slice(0, 2)))
    annotations = write_annotations(tmp_path / "G4.geojson", [(box(0, 0, 3, 2), WATER)])

    output, summary = rasterise_labels(chip, annotations)

    values = rasterio.open(output).read(1)
    assert (values[0:2, 0:2] == NO_DATA).all()
    assert (values[0:2, 2] == WATER).all()     # the part over valid pixels survives
    assert summary["no_data_px"] == 4
    assert summary["invalid_overridden_px"] == 4


def test_abstention_wins_where_polygons_overlap(tmp_path):
    """Water drawn under a no-data polygon loses: the cautious claim takes the pixel."""
    chip = write_chip(tmp_path / "G5.tif")
    annotations = write_annotations(tmp_path / "G5.geojson",
                                    [(box(0, 0, 4, 4), WATER), (box(2, 2, 2, 2), NO_DATA)])

    output, _ = rasterise_labels(chip, annotations)

    values = rasterio.open(output).read(1)
    assert (values[2:4, 2:4] == NO_DATA).all()
    assert values[0, 0] == WATER


def test_annotations_in_another_crs_are_reprojected_onto_the_chip(tmp_path):
    """QGIS writes GeoJSON in WGS84 by default even when the chip is projected."""
    chip = write_chip(tmp_path / "G6.tif")
    annotations = tmp_path / "G6.geojson"
    annotations.write_text(json.dumps({
        "type": "FeatureCollection",          # no crs member: WGS84 per RFC 7946
        "features": [{"type": "Feature", "geometry": box(0, 0, 3, 2),
                      "properties": {"class": WATER}}],
    }), encoding="utf-8")

    _, summary = rasterise_labels(chip, annotations)

    assert summary["water_px"] == 6           # chip is already WGS84, so this is a no-op


def test_water_fraction_ignores_the_classes_that_are_never_scored(tmp_path):
    labels = np.array([[WATER, WATER], [NON_WATER, EXCLUDED]])
    summary = label_summary(labels)
    assert summary["water_px"] == 2 and summary["non_water_px"] == 1
    assert summary["water_fraction"] == pytest.approx(2 / 3)


def test_directory_pass_indexes_only_the_chips_someone_labelled(tmp_path):
    chips, annotations, labels = tmp_path / "chips", tmp_path / "ann", tmp_path / "labels"
    chips.mkdir()
    annotations.mkdir()
    write_chip(chips / "A.tif")
    write_chip(chips / "B.tif")               # deliberately left unlabelled
    write_annotations(annotations / "A.geojson", [(box(0, 0, 2, 2), WATER)])

    rows = rasterise_directory(chips, annotations, labels)

    assert [row["chip_id"] for row in rows] == ["A"]
    assert (labels / "A_label.tif").exists()
    assert not (labels / "B_label.tif").exists()
    assert (labels / "labels_manifest.csv").read_text(encoding="utf-8").startswith("chip_id")


def test_seeding_a_directory_never_overwrites_work_already_done(tmp_path):
    chips, annotations = tmp_path / "chips", tmp_path / "ann"
    chips.mkdir()
    write_chip(chips / "A.tif")
    write_chip(chips / "B.tif")

    assert len(start_annotations_directory(chips, annotations, labeller="varun")) == 2
    write_annotations(annotations / "A.geojson", [(box(0, 0, 2, 2), WATER)])

    assert start_annotations_directory(chips, annotations) == []   # both already exist
    _, summary = rasterise_labels(chips / "A.tif", annotations / "A.geojson")
    assert summary["water_px"] == 4


def test_a_null_crs_member_falls_back_to_wgs84(tmp_path):
    """Some writers emit "crs": null rather than leaving the member out."""
    chip = write_chip(tmp_path / "G7.tif")
    annotations = tmp_path / "G7.geojson"
    annotations.write_text(json.dumps({
        "type": "FeatureCollection", "crs": None,
        "features": [{"type": "Feature", "geometry": box(0, 0, 2, 2),
                      "properties": {"class": WATER}}],
    }), encoding="utf-8")

    _, summary = rasterise_labels(chip, annotations)
    assert summary["water_px"] == 4
