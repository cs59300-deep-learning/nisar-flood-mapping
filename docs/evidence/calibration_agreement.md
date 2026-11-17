# Inter-annotator agreement — calibration round (#29)

**Mean pairwise water IoU: 0.808** across 15 pairs.
Three of four labellers; Yashada7 has not pushed labels, so this is provisional.

Machine-readable results: [`calibration_agreement_report.json`](calibration_agreement_report.json)
Script: [`../../scripts/calibration_agreement.py`](../../scripts/calibration_agreement.py)

## Result

| Chip | Band | Mean | Nidhi/Pushan | Nidhi/Varun | Pushan/Varun |
|---|---|---|---|---|---|
| `N023_20260618_008000_013600` | high | 0.966 | 0.970 | 0.970 | 0.957 |
| `N023_20260618_004400_010400` | mid | 0.867 | 0.839 | 0.915 | 0.846 |
| `N023_20260618_007600_011200` | low | 0.826 | 0.772 | 0.881 | 0.827 |
| `N023_20260618_012000_004400` | low | 0.714 | 0.721 | 0.665 | 0.755 |
| `N023_20260618_006400_012400` | low | 0.665 | 0.631 | 0.726 | 0.638 |

Per labeller pair, averaged over the five chips:

| Pair | Mean water IoU |
|---|---|
| NidhiMusale / varunteja99 | 0.873 |
| pushanverma / varunteja99 | 0.805 |
| NidhiMusale / pushanverma | 0.803 |

Agreement falls as open water gets scarcer — 0.97 on the high-water chip against
0.67 on the driest. Thin channels and mixed-pixel edges are where labellers
diverge, which is the expected shape for this task. No labeller is an outlier:
the three pair means span 0.070.

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

## Reproducing

```
python scripts/calibration_agreement.py --out docs/evidence/calibration_agreement_report.json
```

Reads directly from git refs, so no branch needs checking out. Sources are
listed in `SOURCES` at the top of the script, and the commit each was read from
is recorded in the report's `sources` block.

## Known issues

**Yashada7 has pushed no labels.** `Yashada7/hand-labelled-chips` contains one
commit ahead of main, a merge, and no annotation files. Until she pushes, this
figure covers three labellers and #29 is not complete.

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

## Updating

When Yashada pushes, re-run the script. It picks her branch up automatically
from `SOURCES`; nothing needs editing unless her ref name changes. Then update
the headline figure and the table here, and remove her from Known issues.

Expect the number to move: she has not seen anyone else's labels, so her five
are genuinely independent, whereas a labeller who pulled `main` after the
annotations landed there would not be.
