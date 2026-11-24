# Stage0 terrain rule scored against the gold set (#14, #30)

The stage0 rule predicts water from topography and the river gauge alone, with no
radar input:

    h(date) = stage(date) - stage0        wet = {HAND <= h(date)}

This is the baseline the learned models have to beat. It had never been scored
against the hand labels — the 20.51 m bank level was fitted against an
independent reference mask in October (`stage_calibration_report.json`, mean IoU
0.511), which is a different measurement on different ground. The numbers below
are on the same 55 chips, against the same labels, with the same headline metric
the models use.

## Result

| | |
|---|---|
| **iou_water_per_chip_mean** | **0.4318** |
| chips | 55 |
| water height used | 7.95 m (the calibrated stage0) |
| precision | 0.438 |
| recall | 0.934 |
| labelled water | 36.9% of scored pixels |
| predicted wet | 77.3% of scored pixels |

Recall 0.93 against precision 0.44 says what the rule is doing: it finds nearly
all the water by flooding roughly twice as much ground as is actually wet, a
median of **2.06x** over-prediction per chip.

## The threshold is not the problem

Sweeping the water height from 0 to 16 m, the best any threshold achieves is
**0.5516 at 0.75 m** — and even that is optimistic, since it is picked by looking
at the labels it is scored on.

```
0.00 m  0.4940
0.75 m  0.5516   <- best
2.00 m  0.5298
4.00 m  0.4857
7.95 m  0.4318   <- calibrated
12.00 m 0.4030
```

The curve has no real peak. It rises over the first metre and then decays
slowly, which means almost all of the rule's skill is in knowing where the
drainage network is, not in how high the water stands. `HAND <= 0` — the channels
themselves, no flooding at all — already scores 0.494, better than the
calibrated threshold.

This is a property of the terrain, not a calibration error. The central Amazon
floodplain is flat enough that 7.95 m above the nearest drainage covers most of
the scene.

## Where it fails

Per-chip IoU: min 0.000, median 0.471, max 0.988. Nineteen of 55 chips score
below 0.3; sixteen score above 0.6.

Per-chip IoU correlates with how wet the chip is at **+0.95**, and the best-scoring
chips are predicted 99-100% wet. The rule is not discriminating well on those
chips — it floods nearly everything, and scores well where the label happens to
agree. On the five chips with essentially no labelled water it scores 0.000
while predicting up to 97.7% wet.

So 0.4318 is not a floor the models need only to edge past. A model that
distinguishes wet from dry at all should beat it comfortably; the interesting
comparison is against the 0.5516 best-case threshold, and against the per-chip
spread rather than the mean.

## How it was computed

```
python scripts/fetch_hand_from_gee.py --project <gee-project>
python scripts/score_stage0_gold.py --hand data/reference/hand_chips \
    --out docs/evidence/stage0_vs_gold.json
```

Class `2` (suspected flooded vegetation) and `-1` (unusable) are dropped from
both sides, per `docs/labelling_protocol.md`, as are pixels where HAND has no
value. That leaves 81.4% of the labelled area scored.

## Caveat on the HAND source

The original `hand_aoi.tif` (945 MB, #13) is in a Drive folder nobody could
reach, so HAND was pulled fresh from Earth Engine's copy of the same product,
MERIT Hydro v1.0.1 band `hnd`, resampled bilinear onto each chip grid. Same
dataset and version, but reprojected by Earth Engine rather than GDAL, so it is
not byte-identical and cannot be checked against the sha256 in
`hand_provenance.json`.

The cross-check that it is close: at the calibrated 7.95 m this HAND predicts
77.3% of the chip area wet, against the 70.6% of the whole AOI recorded in
`hand_inundation_by_date.csv` for the same date. The chips are deliberately
water-biased, so the gap is the expected direction and size.
