# Data

Heavy data (rasters, chips, HDF5 granules) is **not tracked in git**; see
`data/.gitignore`. Small CSVs, READMEs and the QA sheet are.

| Path | Contents |
|---|---|
| `raw/` | NISAR L2 GCOV granules (`.h5`, ~1.9 GB each). Not tracked. |
| `chips/` | The chip set (below). GeoTIFFs are not tracked; `manifest.csv` is. |
| `qa/` | `chip_qa_20_samples.png`, the visual QA sheet. Tracked. |
| `labels/` | Hand labels for the gold chips. See [`labels/README.md`](labels/README.md). |
| `gauge/` | Manaus river-stage record used to pick water regimes. |
| `granule_manifest.csv` | One row per granule: date, polarisations, water regime. |
| `labelling_assignments.csv` | Who labels which chip. |

## Chips

A chip is a 512 x 512 pixel tile cut from one NISAR granule. `data/chips/`
holds **320 chips (about 290 MB)** from granule `N023_20260618` (2026-06-18,
dual-pol, high water). New chips are non-overlapping, so a train/val split
cannot leak pixels.

**Format.** One GeoTIFF per chip, named `<granule_id>_<row>_<col>.tif`
(e.g. `N023_20260618_006400_011200.tif`). Row and column are the chip's
top-left pixel in the granule, so the name locates it.

| | |
|---|---|
| Size | 512 x 512 px, 20 m pixels (about 10 x 10 km) |
| Bands | 2, float32: **1 = HH gamma0 in dB, 2 = HV gamma0 in dB** |
| CRS | EPSG:32720 (UTM 20S), georeferenced |
| No-data | In the GeoTIFF mask band, **not** a pixel value (0 dB is real data). Invalid pixels read as `NaN`. |
| Compression | Deflate with float predictor (lossless) |

`chips/manifest.csv` has one row per chip: `chip_id, source_granule, date, crs,
bbox, valid_fraction, path`. It also lists the 55 hand-labelled chips, which
may not all be present locally.

**Preprocessing.** Power (gamma0) is converted to dB. Samples that are not
valid in the product's mask layer, and non-positive power, become no-data. No
other clamping or normalisation is applied (that happens in
`datasets/transforms`). In the 297 chips added for issue #10, dB values are also
**rounded to 1/64 dB** (0.016 dB, far below speckle noise), which halves their
size. The 23 hand-labelled chips predating this were cut unrounded. New chips
need at least 90% valid pixels (the labelled ones, 70%).

## Generating the chips

Needs the granule in `data/raw/` (`pip install -r requirements.txt`). From the
project root:

```bash
export PYTHONPATH=src            # or: pip install -e .
python scripts/build_first_chip_set.py                  # up to 320 chips
python scripts/build_first_chip_set.py --count 400 --seed 1   # more / different
```

It picks random non-overlapping positions, cuts them with the existing
`nisar-flood make-chips` code, **adds** them to `chips/` and `manifest.csv`
(existing chips are kept), and prints:

```text
Generated chips: 320
Total dataset size: 291 MB
Dataset check (>= 300 chips, < 500 MB): PASS
```

It exits non-zero if the check fails. To cut specific positions by hand use
`nisar-flood make-chips --only ROW,COL ...`.

## Visual QA

```bash
python scripts/make_chip_qa_sheet.py          # writes data/qa/chip_qa_20_samples.png
python scripts/make_chip_qa_sheet.py --seed 1 # a different random 20
```

The sheet is a 5 x 4 grid of 20 random chips. Each tile shows the **HH band in
dB** on one fixed grey stretch (-25 to 0 dB), so tiles are comparable: dark is
smooth surface (open water), bright is rough or built surface. Red marks no-data
pixels. Titles give each chip's `row_col` and valid-pixel percentage. Look for
all-black or all-white tiles or large red areas; none are expected.

## Limits

- One granule only; the other NISAR dates are not chipped yet.
- Chips are sampled at random, so water/non-water balance is not controlled.
- Granule `N023_20260618` regime ("high") is provisional pending the gauge
  analysis.
