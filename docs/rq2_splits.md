# RQ2 split scheme

`data/labels/rq2_splits.json` fixes which of the 55 hand-labelled NISAR chips are
used for fine-tuning and which are held out for scoring. It is built by
`scripts/make_rq2_splits.py` and is meant to be read, not re-rolled: the RQ1
zero-shot run (#22) and every point of the RQ2 curve (#24) have to be scored on
the same chips, or the curve has no n=0 point to start from.

```
python scripts/make_rq2_splits.py --out data/labels/rq2_splits.json
```

## What it contains

| Key | Meaning |
| --- | --- |
| `test` | 20 chips, never trained on, used for every reported number |
| `pool` | the other 35 chips, the only fine-tuning data that exists |
| `subsets[seed][n]` | the n chips seed `seed` fine-tunes on, drawn from `pool` |
| `water_fraction` | water pixels over scoreable pixels, per chip |
| `stratum` | 0 (driest quarter) to 3 (wettest quarter) |

## Why it is built this way

**Stratified, not uniform.** Scoring the terrain baseline showed per-chip water
IoU correlating +0.95 with how wet the chip is (`docs/evidence/stage0_vs_gold.md`).
A uniform draw of 5 chips could therefore move the score more than fine-tuning
does. Chips are ranked by water fraction, cut into four equal strata, and drawn
from each stratum in turn. Mean water fraction then stays within 0.33-0.38 across
every subset and seed, against a per-chip range of 0.00 to 0.90.

**Nested, not independent.** Within one seed the n=5 subset is contained in n=10,
which is contained in n=20 and n=35. Each step of the curve is then the effect of
*adding* chips rather than the effect of drawing a different set of them.

**Water fraction excludes the flagged classes.** Suspected flooded vegetation
(class 2) and unusable pixels (-1) are left out of the denominator, because
neither is scored. 44 of the 55 chips carry some class 2, so including it would
distort the ranking the strata are built from.

## Deviation from the ticket

Issue #24 asks for n = 0, 5, 10, 20, 40. Forty chips cannot be drawn from a pool
of 35 once a test set is held out, so the top point is **n = 35** and the sizes
are 0, 5, 10, 20, 35. The alternative - a 15-chip test set - buys the round
number by making every reported IoU noisier, which is the wrong trade on the
project's headline metric.

At n = 35 the pool is exhausted, so all three seeds train on the same chips and
the spread at that point reflects training randomness alone, not the draw. The
error bar there is not comparable to the ones at n = 5 and n = 10.

## For the zero-shot run (#22)

Zero-shot trains on nothing, so no chip is off limits to it. Scoring on all 55
is legitimate and gives a tighter estimate than 20 does. Report both figures.

- **All 55 chips** is the headline for #22. More chips make the number more
  precise, and the open-water against flooded-vegetation breakdown needs every
  example it can get.
- **The 20 `test` chips** is the same model scored on that subset, reported
  alongside. This is the figure the RQ2 curve starts from, because every later
  point of the curve is scored on those 20 chips and nowhere else.

This costs an extra line, not an extra run: IoU is computed chip by chip, so
both figures come out of one pass. Quoting only the 55-chip number leaves the
curve starting from a score its other points cannot be compared with; quoting
only the 20-chip number throws away two thirds of the evidence for the question
#22 actually asks.

All 20 test chips contain both water and dry pixels once the flagged classes are
removed, so all 20 can be scored.
