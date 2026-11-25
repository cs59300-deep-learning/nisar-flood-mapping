# RQ2 fine-tuning curve, U-Net + ResNet50 (issue #24)

How much of the Sentinel-1 to NISAR transfer loss is recovered by fine-tuning on a
small number of hand-labelled NISAR chips. The CNN source model
(`reports/unet_resnet50_seed0`) is adapted to n chips drawn from the 35-chip pool
in `data/labels/rq2_splits.json` and scored on the 20 held-out test chips.

Thirteen runs, 16.1 GPU-minutes in total on a T4.

| file | contents |
|---|---|
| `curve.json` | per-n mean and standard deviation over seeds, and the full config |
| `curve.png` | the curve with error bars |
| `run_n{n}_seed{s}.json` | one run: metrics, the chips it trained on, per-chip IoU |

## Results

Water IoU, per-chip mean over the 20 test chips. Each point is 300 optimiser steps
at learning rate 5e-5, batch 8, averaged over seeds 0, 1 and 2.

| chips | per-chip mean | std over seeds | gain over n=0 | share of the gain at n=35 |
|---|---|---|---|---|
| 0 | 0.6326 | — | — | — |
| 5 | 0.6918 | 0.0079 | +0.0591 | 61% |
| 10 | 0.7027 | 0.0179 | +0.0700 | 72% |
| 20 | 0.7108 | 0.0139 | +0.0781 | 80% |
| 35 | 0.7300 | 0.0087 | +0.0973 | 100% |

**Five chips recover 61% of what thirty-five recover.** The curve rises steeply to
n=5, then flattens: each later step buys less than the one before it, and the
remaining 39% costs seven times the labelling effort. For a labelling budget, the
first handful of chips is worth far more per chip than the rest.

The trend is monotonic and the seed spread is small relative to it (0.008 to 0.018
against a total gain of 0.097), so the shape is not an artefact of which chips each
seed happened to draw.

## How to read these numbers

- **n=0 is the curve's anchor, not the RQ1 result.** It is the un-adapted source
  model scored on the 20 test chips. The reportable zero-shot figure, broken down by
  open water and flooded vegetation and compared against a dB threshold, comes from
  #22.
- **At n=35 the pool is exhausted**, so all three seeds train on the same 35 chips.
  The spread there reflects training randomness alone, not the draw, and its error
  bar is not comparable to the ones at n=5 and n=10.
- **No checkpoint selection.** The pool and the test set are the only labelled NISAR
  data available, so there is no third split on which to choose an epoch. Selecting
  the best epoch by test score would report a number tuned on the chips it claims to
  generalise to. Every run is scored as it stands after the full step budget.
- **A fixed step budget, not epochs.** Every point trains for the same 300 steps, so
  moving along the curve changes how many distinct chips the model has seen and
  nothing else.
- **"N chips recover X% of the gap"** is not stated here. The gap is the source
  model's Sentinel-1 score minus its zero-shot NISAR score, and the second term is
  #22's to report.

## Reproducing

```bash
PYTHONPATH=src python -m nisar_flood.experiments.finetune_curve \
    --config configs/finetune.yaml --batch-size 8 --workers 2 \
    --out runs/rq2_finetune_resnet50
```

`notebooks/05_rq2_finetune_curve.ipynb` runs the same sweep on Colab, including the
data and checkpoint downloads. The split is read from `data/labels/rq2_splits.json`
and is not re-drawn; `docs/rq2_splits.md` explains how it was built.
