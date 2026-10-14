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
