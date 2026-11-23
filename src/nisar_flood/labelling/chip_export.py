"""Turn QGIS polygon annotations into label rasters on the chip grid (issue #28).

``docs/labelling_protocol.md`` (#27) fixes what the four class values mean. This
module fixes the file formats and the burn rules, so that a polygon drawn in
QGIS lands on exactly the pixels the chip covers and nothing drifts by half a
cell between labellers.

Annotations are GeoJSON rather than GeoPackage. GeoJSON needs no vector reader
beyond the GDAL that rasterio already bundles, QGIS reads and writes it
natively, and because it is plain text a whole label set can live in git and be
reviewed in a pull request alongside the code.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_geom

# Class values, identical to Sen1Floods11 so a model trained there needs no
# relabelling, plus the project's own "excluded" value (docs/labelling_protocol.md).
WATER = 1
NON_WATER = 0
EXCLUDED = 2          # suspected flooded vegetation: flagged, never scored
NO_DATA = -1

# Painted last wins. A labeller only draws water, excluded and no-data; every
# unpainted pixel inside the chip is non-water, which is how Sen1Floods11's own
# hand labels are built. The order puts the cautious claim on top: where someone
# marked a region both water and no-data, the abstention takes the pixel.
BURN_ORDER = (WATER, EXCLUDED, NO_DATA)

# GeoJSON is defined in WGS84 (RFC 7946) and that is what QGIS writes unless
# told otherwise. A file carrying its own crs member overrides this.
DEFAULT_ANNOTATION_CRS = "EPSG:4326"

# int16 rather than int8: GDAL only gained Int8 GeoTIFF support in 3.7, and the
# four values cost nothing to widen. The values are what must match, not the dtype.
LABEL_DTYPE = "int16"


def _annotation_crs(collection):
    """CRS a FeatureCollection was written in, honouring a legacy crs member."""
    named = ((collection.get("crs") or {}).get("properties") or {}).get("name")
    return named or DEFAULT_ANNOTATION_CRS


def _load_features(annotations_path):
    """Read the drawn features, dropping the template placeholder.

    A feature with no class is the placeholder that `start_annotations` writes
    so QGIS can tell the layer holds polygons. It is not a label.
    """
    collection = json.loads(Path(annotations_path).read_text(encoding="utf-8"))
    features = [f for f in collection.get("features", [])
                if f.get("properties", {}).get("class") is not None
                and f.get("geometry") is not None]
    return features, _annotation_crs(collection)


def start_annotations(chip_path, output_path=None, *, labeller="", chip_id=None):
    """Write an empty annotation file for one chip, ready to open in QGIS.

    The file holds a single placeholder polygon at the centre of the chip with
    no class. GDAL infers a layer's geometry type from the features it finds, so
    an entirely empty file opens as a typeless layer that QGIS will not let
    anyone draw polygons into. The placeholder is ignored on export and can be
    deleted or left alone.
    """
    chip_path = Path(chip_path)
    chip_id = chip_id or chip_path.stem
    output_path = Path(output_path) if output_path else chip_path.with_suffix(".geojson")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(chip_path) as chip:
        west, south, east, north = chip.bounds
        chip_crs = chip.crs
    centre = {"type": "Polygon", "coordinates": [[
        [west + (east - west) * 0.49, south + (north - south) * 0.49],
        [west + (east - west) * 0.51, south + (north - south) * 0.49],
        [west + (east - west) * 0.51, south + (north - south) * 0.51],
        [west + (east - west) * 0.49, south + (north - south) * 0.51],
        [west + (east - west) * 0.49, south + (north - south) * 0.49],
    ]]}
    if chip_crs is not None:
        centre = transform_geom(chip_crs, DEFAULT_ANNOTATION_CRS, centre)

    collection = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": centre,
            "properties": {"chip_id": chip_id, "class": None, "labeller": labeller,
                           "labelled_on": "", "evidence_tier": None,
                           "notes": "placeholder so QGIS sees a polygon layer; ignored on export"},
        }],
    }
    output_path.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    return output_path


def start_annotations_directory(chip_dir, output_dir, *, labeller="", overwrite=False):
    """Seed an annotation file for every chip in a directory.

    An existing file is left alone unless `overwrite` is set, so re-running this
    after a few chips have been labelled cannot wipe somebody's afternoon.
    """
    chip_dir, output_dir = Path(chip_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    created = []
    for chip_path in sorted(chip_dir.glob("*.tif")):
        output_path = output_dir / f"{chip_path.stem}.geojson"
        if output_path.exists() and not overwrite:
            continue
        created.append(start_annotations(chip_path, output_path, labeller=labeller))
    return created


def rasterise_labels(chip_path, annotations_path, output_path=None):
    """Burn the drawn polygons onto the chip's own grid and write the label raster.

    The output matches the chip's width, height, transform and CRS exactly, so a
    label and its chip can be stacked without resampling. Pixels the chip itself
    marks invalid become no-data whatever was drawn over them, and the count of
    those overrides comes back in the summary: a labeller painting water across
    a hole in the swath is worth seeing rather than silently discarding.
    """
    chip_path, annotations_path = Path(chip_path), Path(annotations_path)
    output_path = (Path(output_path) if output_path
                   else chip_path.with_name(f"{chip_path.stem}_label.tif"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    features, source_crs = _load_features(annotations_path)

    with rasterio.open(chip_path) as chip:
        shape = (chip.height, chip.width)
        labels = np.full(shape, NON_WATER, dtype=LABEL_DTYPE)
        for value in BURN_ORDER:
            geometries = [transform_geom(source_crs, chip.crs, f["geometry"])
                          for f in features if int(f["properties"]["class"]) == value]
            if geometries:
                rasterize([(geometry, value) for geometry in geometries],
                          out=labels, transform=chip.transform, all_touched=False)

        invalid = chip.dataset_mask() == 0
        overridden = int(np.count_nonzero(invalid & (labels != NON_WATER)))
        labels[invalid] = NO_DATA

        profile = chip.profile.copy()
        profile.update(driver="GTiff", count=1, dtype=LABEL_DTYPE, nodata=NO_DATA,
                       compress="deflate")
        profile.pop("photometric", None)   # a chip's colour hint does not apply to classes
        with rasterio.open(output_path, "w", **profile) as destination:
            destination.write(labels, 1)

    # chip_id first so the manifest reads naturally as a table of chips.
    summary = {"chip_id": chip_path.stem, "label_path": str(output_path),
               "polygons": len(features), "invalid_overridden_px": overridden}
    summary.update(label_summary(labels))
    return output_path, summary


def label_summary(labels):
    """Pixel counts per class, plus the water fraction over the scorable pixels.

    Only water and non-water are scored, so the fraction is taken over those two
    and not over the whole chip; otherwise a chip that is mostly excluded canopy
    would look like it had almost no water in it.
    """
    labels = np.asarray(labels)
    counts = {name: int(np.count_nonzero(labels == value)) for name, value in
              (("water_px", WATER), ("non_water_px", NON_WATER),
               ("excluded_px", EXCLUDED), ("no_data_px", NO_DATA))}
    scorable = counts["water_px"] + counts["non_water_px"]
    counts["water_fraction"] = counts["water_px"] / scorable if scorable else 0.0
    return counts


def rasterise_directory(chip_dir, annotations_dir, output_dir):
    """Rasterise every chip that has an annotation file and index the results.

    Chips are matched to annotations by stem, so `G1_000400_000400.tif` pairs
    with `G1_000400_000400.geojson`. A chip nobody has labelled yet is skipped
    rather than written out as all non-water, which would look like a finished
    label of an empty scene.
    """
    chip_dir, annotations_dir, output_dir = Path(chip_dir), Path(annotations_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for chip_path in sorted(chip_dir.glob("*.tif")):
        annotations_path = annotations_dir / f"{chip_path.stem}.geojson"
        if not annotations_path.exists():
            continue
        _, summary = rasterise_labels(
            chip_path, annotations_path, output_dir / f"{chip_path.stem}_label.tif")
        rows.append(summary)

    manifest = output_dir / "labels_manifest.csv"
    if rows:
        with manifest.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return rows
