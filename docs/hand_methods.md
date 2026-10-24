# HAND ground truth: source, processing and canopy correction (Ticket #13)

## Source
- Product: **MERIT Hydro**, layer `hnd` (Height Above Nearest Drainage), 3 arc-second (~90 m), EPSG:4326.
- Tiles used: `s05w065_hnd.tif` (65-60 W) and `s05w060_hnd.tif` (60-55 W), both 5 S-0.
  They come from the 30-degree packages `hnd_s30w090.tar` and `hnd_s30w060.tar`
  (a package name is the lower-left corner of its block, so `s30w060` spans 30 S-0, 60 W-30 W).

## DEM choice and canopy correction
- MERIT Hydro HAND is computed from MERIT Hydro's flow directions, which are built on the **MERIT DEM**
  (Yamazaki et al. 2017). MERIT DEM is SRTM/AW3D based and has had error components removed,
  including **tree-height (vegetation) bias**, which is the issue for HAND under Amazon forest.
- The canopy correction is therefore **inherited from MERIT DEM; it was not computed in this project.**
  It is a statistical correction and can leave residual bias under dense canopy.
- Fallback (FABDEM-based HAND computation) was **not needed**.

## Processing (reproducible via `src/nisar_flood/groundtruth/hand.py`)
1. Mosaic the two tiles (nodata -9999).
2. `clip_hand_to_aoi`: clip to the NISAR GCOV footprint transformed to lon/lat **plus a 0.02 deg margin**
   ((-62.7057, -4.5855, -59.6485, -1.5855)), so bilinear resampling has valid neighbours at the edges.
3. `prepare_hand_for_chip`: reproject + bilinear resample onto the exact NISAR Frequency-A grid
   (EPSG:32720, 20 m, 16740 x 16344, origin 534960, 9822240).
   CRS, transform and shape are copied from the reference raster, not computed by hand.

## Verification
- CRS equal, transform pixel-exact, shape equal to the NISAR grid.
- Valid pixels: 273,598,560 / 273,598,560 (100.000%); HAND range 0.0-151.0 m.
- River check vs HydroRIVERS (v10, South America): see `docs/evidence/hand_hydrorivers_overlay.png`,
  `docs/evidence/hand_manaus_zoom.png`, `docs/evidence/hand_river_check.json`.
  Distance-to-river check (HAND on a 200 m block-averaged grid vs distance to HydroRIVERS reaches): along major rivers (upstream area >= 1000 km2, 1525 reaches) median HAND is 1.4 m within 0.2 km and 4.5 m at 1.6-3 km (p90 7.5 -> 15.0 m); 94% of points on these reaches have local-minimum HAND <= 2 m (tolerance +-400 m), but 75% of the whole AOI is also <= 2 m, so that figure alone is weak evidence. For the full reach network (>= 10 km2) the contrast is small (median 2.7 m within 0.2 km vs 2.7 m at 3-6 km) and HAND does not rise monotonically with distance (Spearman rho 0.01). Interpretation: HAND is clearly lowest along the major rivers; small streams are not resolved by this check (HydroRIVERS positional uncertainty is comparable to the grid cell, and the AOI is low-relief). This is a sanity check, not an accuracy assessment.

## Limitations
- Effective resolution is ~90 m; the 20 m grid is for pixel alignment with NISAR, not added detail.
- HydroRIVERS is derived from HydroSHEDS terrain, so the river check is a sanity check, not an independent accuracy assessment.
- Gold labels (gauge height + HAND thresholds) are **not** generated here; that is a later ticket.

## References
- Yamazaki et al. (2019), MERIT Hydro, Water Resources Research 55, doi:10.1029/2019WR024873
- Yamazaki et al. (2017), MERIT DEM, Geophysical Research Letters 44, doi:10.1002/2017GL072874
- Nobre et al. (2011), HAND, Journal of Hydrology 404, doi:10.1016/j.jhydrol.2011.03.051
- Lehner & Grill (2013), HydroRIVERS, Hydrological Processes 27, doi:10.1002/hyp.9740
