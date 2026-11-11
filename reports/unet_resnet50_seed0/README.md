# U-Net + ResNet50, seed 0 (issue #19)

CNN baseline trained on the Sen1Floods11 hand-labelled split. Best epoch
43 of 100, selected on validation
`iou_water_per_chip_mean`, 22.5 minutes on a single T4.

| file | contents |
|---|---|
| `curves.png` | training and validation loss, validation IoU per epoch |
| `history.csv` | per-epoch metrics, 100 rows |
| `eval.json` | test and Bolivia metrics |
| `summary.json` | best epoch, selection metric, full config |

## Results

Water IoU. The headline metric is the image-wise mean, matching the
Sen1Floods11 definition; pooled IoU has no published counterpart.

| split | per-chip mean | pooled | chips scored | published (Table 1/2, all water) |
|---|---|---|---|---|
| test | **0.4291** | 0.6819 | 87 of 90 | 0.3125 |
| bolivia | **0.4633** | 0.7046 | 15 of 15 | 0.3524 |

Published figures are Bonafilia et al. (CVPRW 2020), the row for the model
trained on hand-labelled data. Chips containing no water in either the label or
the prediction have an undefined water IoU and are excluded from the mean.

`eval.json` here records `published_test_iou: null` because it was generated
before that constant was set in `training/evaluate.py`; later runs will carry
the value.

## Checkpoint

Weights are not in git (`*.pt` is gitignored; see `docs/data_sources.md`):

**https://huggingface.co/varunchundru/unet-resnet50-sen1floods11** (private)

```bash
hf download varunchundru/unet-resnet50-sen1floods11 seed0/best.pt --local-dir runs/unet_resnet50
PYTHONPATH=src python -m nisar_flood.cli evaluate --checkpoint runs/unet_resnet50/seed0/best.pt
```

The checkpoint stores its own config, so evaluation does not need the YAML.
