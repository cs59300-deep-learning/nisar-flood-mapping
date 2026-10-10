# Stage calibration: gauge height to HAND inundation (Ticket #14)

## Method

For each acquisition date the flood extent is the set of pixels whose height above the nearest
drainage (HAND) is at or below the water height on that date:

    h(date)   = stage(date) - stage0
    wet(date) = { pixel : HAND <= h(date) }

- `stage(date)` is the daily mean Porto de Manaus level from `data/gauge/manaus_daily_stage_2026.csv`.
  ANA `Nivel` is in **centimetres**; the code converts to metres (`GAUGE_CM_TO_M`) because HAND is in
  metres. Override with `--gauge-unit-to-m` if the export turns out to use other units.
- `stage0` is the gauge reading at which the floodplain waterline sits at HAND = 0. It absorbs the
  offset between the gauge zero and the HAND datum, so it is specific to this gauge and this HAND product.
- `stage0` is fixed **once**, by matching the HAND extent to an independent reference on one or two
  dates, then reused for every granule date. It is chosen to maximise the mean IoU between
  `{HAND <= stage - stage0}` and the reference (`calibrate_stage0`). The IoU is computed exactly for
  every candidate from the sorted HAND values, not by building one mask per candidate.
- Negative `h` (river below the HAND = 0 level) floods nothing and is reported as `below_hand0`.
  Pixels with no HAND value are excluded from every metric; they are never counted as dry.

Code: `src/nisar_flood/groundtruth/stage_calibration.py`. Runner: `scripts/calibrate_stage0.py`.
Tests: `tests/test_stage_calibration.py` (synthetic terrain with a known `stage0`).

## Running it

    python scripts/calibrate_stage0.py --hand <HAND on the NISAR grid, from #13> \
        --reference 2026-09-22=<independent water mask> \
        --check 2026-06-18=<second independent mask, optional>

- `--reference` (one or two dates) is used for fitting. `--check` dates are scored with the fitted
  `stage0` but never used to fit it, so they give the out-of-sample agreement figure.
- The reference must be independent of NISAR and of HAND: a binary mask, 1 = water, 0 = not water,
  nodata = unknown. Pick dates whose gauge level brackets the range being mapped (one near the
  low-water 22 Sep granule and, if available, one near the June high-water granules).
- The fit runs on a decimated grid (`--max-pixels`, default 20 M) because the full 20 m AOI is about
  274 M pixels; the per-date masks are written at full resolution to `data/reference/hand_inundation/`.
- Outputs in `docs/evidence/`: `stage_calibration_report.json` (stage0, range, per-date agreement),
  `stage0_calibration_curve.csv`, `hand_inundation_by_date.csv`.

## Reporting the result

Quote `stage0` together with its `stage0_range_m`, not as a bare number. The range is the span of values
within 0.005 IoU of the best, so it states how tightly the reference pins `stage0` down; it can never be
tighter than the vertical resolution of HAND. If `plateau_reaches_search_edge` is true, the reference
does not bound `stage0` (or the search range is too narrow) and the value should not be used.

## Limitation (for the methods section)

HAND assumes a flat water surface that rises uniformly everywhere. Over a wide area this does not
hold: the Amazon's water-surface slope and backwater effects (the study area sits at the confluence of
the Negro and Solimoes, and the gauge is one point near it) make the true water surface drift away from
`stage(date) - stage0` with distance from the gauge. Because `stage0` is fitted to one or two dates,
its error is lowest for dates and places near those conditions and grows away from them. Labelled tiles
are therefore kept clustered near the confluence, where a single `stage0` is most defensible; where
they are not, the flat-surface approximation is stated explicitly rather than assumed away.

Further caveats that bear on how far the gold labels can be trusted:

- **Resolution.** HAND is about 90 m. The 20 m grid aligns it to NISAR; it adds no terrain detail
  (see `hand_methods.md`).
- **Canopy bias.** The canopy correction is inherited from MERIT DEM and can leave residual bias
  under dense forest, which shifts the effective `stage0` for flooded forest relative to open water.
- **Choice of reference.** An optical or C-band open-water reference does not see water under canopy.
  Calibrating on it sets `stage0` from open-water margins and can mis-place the waterline in flooded
  forest, which is the class this project cares about. State which reference was used and for which class.
- **Timing.** The gauge value is a daily mean; the NISAR overpass is around 22:25 UTC. In September the
  river fell about 0.19 m/day, so a daily mean can differ from the overpass level by roughly a
  decimetre, small next to the HAND uncertainty but not zero.
- **One gauge.** A single point gauge cannot represent the along-river slope; that is the drift above.