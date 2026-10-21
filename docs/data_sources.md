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

Hess et al., dual-season JERS-1 SAR mapping of wetland inundation and
vegetation for the central Amazon basin, distributed by ORNL DAAC. This is
the canonical flooded-forest extent product for the basin. Download needs a
free NASA Earthdata login, so it is fetched by hand and kept outside Git.
**Class codes are taken from the ORNL DAAC dataset guide, not assumed.**
Run `python scripts/build_reference_layers.py --inspect <file>` to list the
codes in the raster and pass the flooded-wetland ones as `--wetland-values`.

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

Limitations: JERS-1 is ~100 m and from 1990s acquisitions (1995-96), JRC
seasonality is a multi-year climatology (1984-2021) and neither matches the
2026 NISAR dates, so they describe typical extent, not the flood on a given
day. Nearest-neighbour resampling onto 20 m adds no detail.
