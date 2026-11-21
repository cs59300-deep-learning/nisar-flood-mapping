# Hand labels

Drawn in QGIS against the normalised dB chips, following
[`docs/labelling_protocol.md`](../../docs/labelling_protocol.md). The protocol
defines what the classes mean; this file only describes the layout.

## Layout

| Path | Contents |
|---|---|
| `annotations/` | The gold set: **one file per chip, one labeller per file.** 55 chips — the 50 `task=gold` chips plus the 5 calibration chips, each represented by one labeller's version. |
| `annotations_secondary/<labeller>/` | Everything drawn in addition to the gold label: the 5 calibration chips drawn independently by all four labellers, and second-pass copies of chips that were assigned twice. |
| `masks/*_label.tif` | Rasterised from `annotations/`. Not tracked — `*.tif` is gitignored. |
| `masks/labels_manifest.csv` | Per-chip polygon and pixel counts for those masks. Tracked, and the record of what the masks contained. |

## Classes

`1` open water · `2` suspected flooded vegetation, flagged and never scored ·
`-1` unusable or unsure · `0` dry, which is every pixel no polygon covers.

Overlaps resolve as water over excluded over no-data, matching `label-export`.

## How the calibration chips enter the gold set

The calibration round (#29) has all four people label the same 5 chips
independently, to measure agreement before mass labelling, so each of those
chips has four versions and no single agreed one. Rather than waste five
labelled chips, one version of each is promoted into the gold set: four chips
dealt one per labeller so no one's style dominates, and the fifth drawn at
random from the four. Both draws come from a seeded RNG, recorded with the
resulting assignment in `calibration_gold_selection.json`, so the choice is
reproducible and was fixed before anyone compared the versions.

The four labellers agree closely on how much of these chips is water — within
0.6 percentage points of the median on four of the five chips, and 2.7 points
on the fifth — so which version is promoted makes little difference to the
evaluation set.

All four versions stay under `annotations_secondary/`, including the promoted
one. That preserves the evidence behind the 0.827 agreement figure in
[`docs/evidence/calibration_agreement.md`](../../docs/evidence/calibration_agreement.md),
which otherwise lives only on four personal branches.

## Rebuilding the masks

```
nisar-flood label-export --chips data/chips --annotations data/labels/annotations \
                         --out data/labels/masks
```

Chips come from `make-chips`; `data/chips/manifest.csv` records the grid each
one was cut on. Both are regenerated, never hand-edited — opening either CSV in
a spreadsheet splits the quoted `bbox` field across columns and corrupts it.

## File format

One feature per line, so a changed polygon is a single changed line in review.
QGIS rewrites these files on save and does not preserve that; reformatting is
cosmetic and changes no geometry.
