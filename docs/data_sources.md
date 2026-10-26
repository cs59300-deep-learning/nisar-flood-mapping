# Data sources

## MERIT Hydro HAND

This project uses the precomputed MERIT Hydro Height Above Nearest
Drainage (HAND) product as a terrain-derived ground-truth input.

MERIT Hydro provides hydrography and terrain-derived products at
approximately 3 arc-second (~90 m) resolution. HAND represents the
height of a location above its nearest drainage.

### Why this source?

Standard digital elevation models can contain vegetation or canopy
elevation rather than bare-earth elevation. This is particularly
important in the Amazon floodplain, where dense vegetation can introduce
substantial elevation errors.

The project therefore uses the precomputed MERIT Hydro HAND product
rather than deriving HAND directly from an uncorrected surface-elevation
DEM. See `docs/hand_methods.md`: the canopy (tree-height bias) correction is inherited from MERIT DEM and was not computed in this project.

### Source

MERIT Hydro project:
https://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/

The data are an external dependency and are not stored in this repository.

## NISAR reference grid

HAND outputs are aligned to the corresponding NISAR reference raster or
chip. The inspected GCOV Frequency-A grid uses:

- CRS: EPSG:32720 (WGS 84 / UTM zone 20S)
- Pixel spacing: 20 m
- HH and HV backscatter grids
- Dimensions: 16,740 columns x 16,344 rows

The selected NISAR reference raster determines the output CRS, transform,
spatial extent, width, height, and resolution.

## Processing workflow

1. Obtain the MERIT Hydro HAND raster.
2. Clip the HAND raster to the required area of interest.
3. Reproject and resample HAND to the NISAR reference grid.
4. Write the output as a Float32 GeoTIFF.
5. Visually compare the result with NISAR imagery and known river channels.

The current comparison is a qualitative visual check, not an independent
validation against a separate river-network dataset.

Large source rasters remain outside Git. The repository stores the
processing code, tests, configuration, and selected evidence.

## Published reference layers (Ticket #15)

These are an independent cross-check of the HAND + gauge labels. They are
not used to train.

### JERS-1 dual-season Amazon wetland masks

Hess et al., *LBA-ECO LC-07 Wetland Extent, Vegetation, and Inundation:
Lowland Amazon Basin* (ORNL DAAC, version 2, 2015, DOI
10.3334/ORNLDAAC/1284). Built from JERS-1 SAR mosaics: low water Oct-Nov
1995, high water May-June 1996 (the guide also says May-July). This is the
canonical flooded-forest extent product for the basin. Download needs a
free NASA Earthdata login, so it is fetched by hand and kept outside Git.

File used: `LBA_Amazon_wetland_dual-season_veg_flood_3arcsec.tif` (whole
basin, EPSG:4326, 3 arc-second ~90 m, uint8, no nodata value set). The
Albers `..._AA100m.tif` in the same dataset is not used (the code needs
lon/lat input). Dataset 1079 is the older version 1 and is not used.

Each code has two digits: first = low-water state, second = high-water
state (guide Table 1). Codes present in the file: 0 outside basin, 1
non-wetland, 11 open water both seasons, 13/23/33 flooded herbaceous at high
water, 21/41/51 open water at high water, 44/66/88 not flooded, 45/55
flooded shrub at high water, 67/77 flooded woodland at high water, 89/99
flooded forest at high water, 200 elevation >= 500 m, 255 ocean.

**Flood-water definition used:** every class that is flooded or open water at
the high-water stage, except 11 (open water in both seasons):
`13, 21, 23, 33, 41, 45, 51, 55, 67, 77, 89, 99`. A stricter flooded
forest/woodland-only set is `67, 77, 89, 99`. The codes used for a run are
recorded in `evidence/reference_layers_report.json`.

### JRC Global Surface Water (seasonality)

Pekel et al. (2016), JRC GSW v1.4, 30 m. Layer `seasonality` = months per
year with water (0-12, 255 = no data). AOI (-62.71 to -59.65 E,
-4.59 to -1.59 N) falls in two 10 degree tiles: `70W_0N` and `60W_0N`.
Source: https://global-surface-water.appspot.com/download

### Permanent vs flood water

Following DeepSARFlood, a pixel is **permanent water if seasonality is
greater than 5 months** (strictly: 6 or more). Then, on the NISAR grid:

| Class | Value | Rule |
|---|---|---|
| Land | 0 | neither of the below |
| Permanent water | 1 | JRC seasonality > 5 |
| Flood water | 2 | JERS-1 flooded-wetland class and not permanent |
| No data | 255 | JRC no data, or JERS-1 no data where not permanent |

Permanent water wins over the JERS-1 class, so the river channel is never
counted as flood. Processing (`groundtruth/published_reference.py`):
`clip_raster_to_aoi` (mosaics the JRC tiles; values and dtype preserved) ->
`align_categorical_to_reference` (nearest neighbour onto the NISAR grid,
EPSG:32720, 20 m, as for HAND) -> `separate_permanent_and_flood_water`.

Limitations: JERS-1 is ~90 m and from 1995-96 acquisitions, JRC
seasonality is a multi-year climatology (1984-2021) and neither matches the
2026 NISAR dates, so they describe typical extent, not the flood on a given
day. Nearest-neighbour resampling onto 20 m adds no detail.

### Result on the NISAR grid (EPSG:32720, 20 m, 16740 x 16344)

Run with the flood-water codes above; full report in
`docs/evidence/reference_layers_report.json`, map in
`docs/evidence/reference_layers_overview.png`.

| Class | Pixels | Share |
|---|---|---|
| Land | 204,088,226 | 74.59% |
| Permanent water | 17,607,911 | 6.44% |
| Flood water | 51,902,423 | 18.97% |
| No data | 0 | 0% |

The output grid matches the NISAR reference exactly (CRS, transform and
shape). The permanent-water share agrees with the raw JRC clip (6.46% of
pixels with seasonality > 5 months). Seasonal water with 1-5 months of JRC
water counts as flood water only where JERS-1 also marks it flooded;
otherwise it is land. Visual check: permanent water follows the main river
channels and flood water sits on the floodplain around them. This is a
consistency check against published products, not an accuracy assessment.
