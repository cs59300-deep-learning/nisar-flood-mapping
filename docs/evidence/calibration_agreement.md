# Inter-annotator agreement — calibration round (#29)

**Mean pairwise water IoU: 0.827** across 30 pairs — all four labellers, five chips.

Machine-readable results: [`calibration_agreement_report.json`](calibration_agreement_report.json)
Script: [`../../scripts/calibration_agreement.py`](../../scripts/calibration_agreement.py)

## Result

Water IoU per chip, for each of the six labeller pairs:

| Chip | Band | Mean | Nidhi/Yash | Nidhi/Push | Nidhi/Varun | Yash/Push | Yash/Varun | Push/Varun |
|---|---|---|---|---|---|---|---|---|
| `N023_20260618_008000_013600` | high | **0.970** | 0.979 | 0.970 | 0.970 | 0.971 | 0.971 | 0.957 |
| `N023_20260618_004400_010400` | mid | **0.882** | 0.914 | 0.839 | 0.915 | 0.865 | 0.914 | 0.846 |
| `N023_20260618_007600_011200` | low | **0.849** | 0.855 | 0.772 | 0.881 | 0.865 | 0.896 | 0.827 |
| `N023_20260618_012000_004400` | low | **0.738** | 0.819 | 0.721 | 0.665 | 0.746 | 0.722 | 0.755 |
| `N023_20260618_006400_012400` | low | **0.695** | 0.759 | 0.631 | 0.726 | 0.662 | 0.754 | 0.638 |

Averaged over the five chips:

| Pair | Mean water IoU |
|---|---|
| NidhiMusale / Yashada7 | 0.865 |
| Yashada7 / varunteja99 | 0.851 |
| NidhiMusale / varunteja99 | 0.831 |
| Yashada7 / pushanverma | 0.822 |
| pushanverma / varunteja99 | 0.805 |
| NidhiMusale / pushanverma | 0.787 |

Agreement falls as open water gets scarcer — 0.97 on the high-water chip against
0.70 on the driest. Thin channels and mixed-pixel edges are where labellers
diverge, which is the expected shape for this task. No labeller is an outlier:
the six pair means span 0.078.

**This figure is the ceiling for any model scored on these labels.** A model
cannot meaningfully exceed the rate at which the people who made the labels
agree with each other.

## How it was computed

Each labeller draws the same five chips independently. For every pair of
labellers on every chip:

1. Polygons are read from that labeller's branch and reprojected from EPSG:4326
   to the chip's CRS.
2. They are rasterised onto the chip's own 512 x 512 pixel grid, burning
   `2` then `-1` then `1`, so water drawn over an excluded area wins. This is
   the same precedence `label-export` applies.
3. Pixels either labeller marked `-1` are dropped. `-1` means "I cannot tell";
   scoring it as disagreement would penalise abstention, and scoring it as
   agreement would reward two people for both giving up.
4. Water IoU is computed over the surviving pixels:
   `|A=1 AND B=1| / |A=1 OR B=1|`.

The headline figure is the unweighted mean over all pairs and chips, so each
chip contributes equally regardless of how much water it holds. Pixel agreement
is also recorded per pair, but it runs 89-98% everywhere because most of every
chip is dry land, which is why IoU is the figure quoted.

This measures the water class only. Class `2` (suspected flooded vegetation) is
flagged and never scored, so agreement on it is not part of this number.

## Sources

| Labeller | Ref | Commit |
|---|---|---|
| varunteja99 | working tree | `840753e` |
| pushanverma | `origin/feature/labelling-pushanverma` | `a721662` |
| NidhiMusale | `origin/Nidhi-handlabelled-chips` | `8966f36` |
| Yashada7 | `origin/Yashada7/hand-labelled-chips` | `bb1c3bb` |

## Reproducing

```
python scripts/calibration_agreement.py --out docs/evidence/calibration_agreement_report.json
```

Reads directly from git refs, so no branch needs checking out.

## Caveats

**Independence is not guaranteed for every labeller.** varunteja99's annotations
were merged to `main` before the other three finished drawing. Anyone who pulled
`main` after that point could have seen them, which would inflate their pair
scores. Yashada7 drew hers last and scores highest against everyone (0.865 and
0.851 on her top two pairs), so this is worth confirming with each labeller
before the figure is published, and stating in the write-up either way.

**Nidhi's polygons for `N023_20260618_012000_004400` are not on her branch
head.** Commit `8966f36` deleted `N023_20260618_012000_004400_new.geojson` and
left an empty `N023_20260618_012000_004400.geojson` plus an orphaned `.qmd`
beside it. The 23 polygons survive in `2b3e248`, and the script reads them from
there via `REF_OVERRIDES`. To restore and drop the override:

```
git checkout 2b3e248 -- data/labels/annotations/N023_20260618_012000_004400_new.geojson
git mv data/labels/annotations/N023_20260618_012000_004400_new.geojson \
       data/labels/annotations/N023_20260618_012000_004400.geojson
git rm data/labels/annotations/N023_20260618_012000_004400_new.qmd
```

**Nidhi's `labeller` field reads `nidhimusale`**, lower case, against the
`NidhiMusale` GitHub handle used everywhere else. Worth normalising before the
dataset is released.

**Five chips is a small sample.** Each pair mean rests on five numbers, so the
0.078 spread between pairs should not be read as a real difference in labeller
skill.
