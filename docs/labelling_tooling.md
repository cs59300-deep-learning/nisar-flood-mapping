# Labelling tooling

Issue #28. `docs/labelling_protocol.md` defines *what* the four class values
mean; this file defines the tool, the file formats and the burn rules, so that
four people drawing on four laptops produce the same thing.

---

## The tool: QGIS

**QGIS 3.34 or newer** (any current long-term release). Install from
<https://qgis.org/download/> — there are macOS and Windows builds, both free.

The alternative was a browser annotator such as Label Studio or CVAT. QGIS wins
for this project because the protocol's evidence hierarchy is a GIS problem,
not an image problem:

- Tier 2 is **HAND + river gauge**, and tier 3 is **JERS-1 and JRC reference
  layers**. Those are georeferenced rasters and vectors that have to sit
  underneath the chip, at the right place, while you draw. Browser annotators
  work on flat PNGs and throw the georeferencing away.
- Chips are GeoTIFFs with a real CRS and transform. QGIS reads them directly,
  so there is no export-to-PNG step where a half-pixel shift can creep in.
- The dB stretch can be set once and reused, so a dark patch looks the same to
  all four of us.

Nothing in the export depends on QGIS specifically. Any tool that writes
GeoJSON polygons will work.

---

## File formats

| What | Format | Where |
|---|---|---|
| Chip | GeoTIFF, 512x512, from #9 | `data/nisar/chips/{chip_id}.tif` |
| Annotations (what you draw) | GeoJSON polygons | `data/labels/annotations/{chip_id}.geojson` |
| Label raster (what the model reads) | GeoTIFF, int16, nodata -1 | `data/labels/masks/{chip_id}_label.tif` |
| Index of finished labels | CSV | `data/labels/masks/labels_manifest.csv` |

Annotations are GeoJSON rather than GeoPackage for two reasons: it needs no
vector-reader dependency beyond the GDAL rasterio already bundles, and it is
plain text, so a label set can live in git and be reviewed in a pull request
like any other change. If you prefer drawing into a GeoPackage, do that and
use **Export > Save Features As... > GeoJSON** when you are done.

### Annotation fields

Every polygon carries these properties. `class` is the only one the exporter
reads; the rest are the per-chip record the protocol's workflow step 2 asks for.

| Field | Type | Meaning |
|---|---|---|
| `chip_id` | text | the chip this polygon belongs to |
| `class` | integer | `1` water, `2` excluded, `-1` no-data (see below) |
| `labeller` | text | who drew it |
| `labelled_on` | text | ISO date, e.g. `2026-10-24` |
| `evidence_tier` | integer | `1` SAR, `2` HAND + gauge, `3` reference layers |
| `notes` | text | why, for anything ambiguous |

---

## The mask format, stated exactly

Class values are Sen1Floods11's, plus our excluded value
(`docs/labelling_protocol.md`):

| Value | Class | Scored? |
|---:|---|---|
| `1` | Water | yes |
| `0` | Non-water | yes |
| `2` | Excluded - suspected flooded vegetation | no |
| `-1` | No-data | no |

Four rules decide what ends up in a pixel:

1. **You draw water, excluded and no-data. You do not draw non-water.**
   Every pixel nobody painted is `0`. This is how Sen1Floods11's own hand
   labels are built, and painting every dry hillside by hand would cost days
   for no extra information.
2. **Where polygons overlap, the cautious claim wins.** Burn order is water,
   then excluded, then no-data. If you marked a region water and later decided
   part of it was unreadable, the no-data takes those pixels.
3. **The chip's own validity mask beats anything you drew.** A pixel outside
   the swath becomes `-1` even if a water polygon covers it. The export counts
   these as `invalid_overridden_px` rather than discarding them silently, so a
   polygon drawn across a hole in the data shows up instead of hiding.
4. **The label raster matches its chip exactly** — same width, height,
   transform and CRS — so a chip and its label stack with no resampling.

The raster is `int16`. GDAL only gained `Int8` GeoTIFF support in 3.7 and the
four values cost nothing to widen; what has to match Sen1Floods11 is the
values, not the dtype.

---

## Workflow

**Once, per person:**

1. Install QGIS and clone this repo.
2. Pull the chips (they are not in git — see `docs/data_sources.md`).

**Per batch of chips:**

1. Seed an annotation file for every chip:

   ```bash
   nisar-flood label-init --chips data/nisar/chips \
                          --out data/labels/annotations \
                          --labeller varun
   ```

   Each file starts with one placeholder polygon that has no class. It is
   there because GDAL works out a layer's geometry type from the features it
   finds, and a completely empty file opens as a typeless layer that QGIS will
   not let you draw polygons into. The exporter ignores it; delete it or leave
   it alone.

2. In QGIS, open the chip (`Layer > Add Layer > Add Raster Layer`) and the
   matching `.geojson` (`Add Vector Layer`). Add HAND, the gauge-derived
   layers and the reference layers underneath as context.

3. Set the raster stretch once and reuse it, so the same backscatter looks the
   same every session: `Layer Properties > Symbology`, min -40 dB, max 0 dB.

4. Toggle editing on the GeoJSON layer (the pencil icon), draw your polygons,
   and fill in `class`, `labeller`, `labelled_on`, `evidence_tier` and `notes`
   for each. Save.

5. Burn them to label rasters:

   ```bash
   nisar-flood label-export --chips data/nisar/chips \
                            --annotations data/labels/annotations \
                            --out data/labels/masks
   ```

   It prints a per-chip line and writes `labels_manifest.csv`. A chip with no
   annotation file is skipped, not written out as an all-dry label.

6. Commit the `.geojson` files. The rasters are regenerated from them, so they
   do not need to be in git.

---

## Checking a chip round-trips

`tests/test_chip_export.py` is the automated version of acceptance criterion 3:
it builds a chip with a known geotransform, draws polygons at known cell
boundaries, exports, and asserts the label raster has the chip's exact
dimensions, transform, CRS and nodata value, with each class on the pixels it
was drawn over. Run it with:

```bash
pytest tests/test_chip_export.py
```

To check a real chip by eye, load the chip and its `_label.tif` in QGIS. The
label should sit exactly on top with no offset, and the no-data areas should
line up with the chip's blank edges.

---

## What this does not cover

Inter-labeller agreement is issue #29, and the gold set itself is #30. This
ticket stops at: a tool everyone can install, a format that is written down,
and an export that lands on the chip grid.
