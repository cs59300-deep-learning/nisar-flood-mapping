# U-Net + MaxViT-base, seed 0 (issue #20)

Transformer arm trained on the Sen1Floods11 hand-labelled split with the same
training pipeline as the CNN baseline (`reports/unet_resnet50_seed0`). Best epoch
46 of 100, selected on validation `iou_water_per_chip_mean`, 125.7 minutes on a
single T4. 122.6 million trainable parameters.

| file | contents |
|---|---|
| `curves.png` | training and validation loss, validation IoU per epoch |
| `history.csv` | per-epoch metrics, 100 rows |
| `eval.json` | test and Bolivia metrics |
| `summary.json` | best epoch, selection metric, full config |

## Results

Water IoU. The headline metric is the image-wise mean, matching the
Sen1Floods11 definition; pooled IoU is reported alongside it.

| split | per-chip mean | pooled | chips scored | ResNet50 baseline (per-chip / pooled) | published (all water) |
|---|---|---|---|---|---|
| test | **0.4434** | 0.6898 | 85 of 90 | 0.4291 / 0.6819 | 0.3125 |
| bolivia | **0.4503** | 0.7031 | 15 of 15 | 0.4633 / 0.7046 | 0.3524 |

Precision and recall for water: test 0.874 / 0.766, Bolivia 0.826 / 0.825.

Published figures are Bonafilia et al. (CVPRW 2020), the row for the model
trained on hand-labelled data. They come from an FCN decoder on a ResNet50
backbone, so a difference is a difference in method, not a reproduction error.
Chips with no water in either the label or the prediction have an undefined water
IoU and are excluded from the per-chip mean, so the two arms average over slightly
different chip sets (85 vs 87 of 90 test chips).

## How to read these numbers

- **One seed.** Differences of about 0.01 should not be read as an architecture
  effect. Against the CNN, MaxViT is 0.014 higher on test and 0.013 lower on
  Bolivia (15 chips).
- **The selection curve is noisy.** Validation per-chip IoU moves by about 0.02 from
  one epoch to the next, and the best epoch (46, 0.4519) is a spike: epochs 45 and
  47 score 0.430 and 0.425, and the last five epochs average about 0.44. Test
  (0.4434) is therefore below the validation score used to pick the checkpoint.
- **Overfitting.** Training loss falls from 1.55 to 0.30 while validation loss
  stalls near 0.65 from about epoch 10, with only 252 training chips.

## Differences from the CNN arm

The two arms share the loss, preprocessing, augmentation, learning rate, weight
decay, epochs, scheduler and seed. The deliberate differences are:

- **Encoder:** `maxvit_base` (timm `maxvit_base_tf_512`) instead of `resnet50`.
- **Pretraining:** timm `maxvit_base_tf_512.in1k`, the default tag, which is
  ImageNet-1k, the same pretraining data as the ResNet50 arm.
- **Batch size:** 4 with 2-step gradient accumulation, an effective batch of 8
  like the CNN run. Batch 8 ran out of memory on a T4.

At run time the output directory and `train.save_every` (10, to limit checkpoint
writes to Drive) were overridden through a temporary copy of
`configs/unet_maxvit.yaml`; neither affects the training. `summary.json` holds the
configuration the run actually used.

## Checkpoint

Weights are not in git (`*.pt` is gitignored; see `docs/data_sources.md`):

**https://huggingface.co/nisar-flood-mapping/unet-maxvit-sen1floods11** (private)

```bash
hf download nisar-flood-mapping/unet-maxvit-sen1floods11 seed0/best.pt --local-dir runs/unet_maxvit
PYTHONPATH=src python -m nisar_flood.cli evaluate --checkpoint runs/unet_maxvit/seed0/best.pt
```

The checkpoint stores its own config, so evaluation does not need the YAML. The
run is reproduced end to end by `notebooks/03_train_unet_maxvit.ipynb`.
