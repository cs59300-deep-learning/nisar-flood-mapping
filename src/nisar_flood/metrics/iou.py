"""IoU, precision, recall and F1 for water segmentation (numpy only, so it is easy to test).

Class 1 = water, class 0 = not water. Pixels equal to IGNORE_INDEX (no data) are never counted.
Two IoU definitions are reported, because papers differ:
  - pooled:   count TP/FP/FN over every valid pixel in the split, then compute one IoU
  - per-chip: compute water IoU for each chip, then average (the Sen1Floods11 authors' image-wise mean)
Values that cannot be computed (division by zero) are NaN, never silently 0.
"""
import math

import numpy as np


from ..datasets.transforms import IGNORE_INDEX   # 255: what the dataloader turns the -1 "no data" label into

# The number to report as "the" IoU. Sen1Floods11 (Bonafilia et al., CVPRW 2020) reports the mean of
# per-chip water IoU, with every chip weighted equally. The pooled `iou_water` is a secondary figure.
HEADLINE_METRIC = "iou_water_per_chip_mean"


def _div(a, b):
    return float(a) / float(b) if b else float("nan")

def _mean_ignoring_nan(values):
    values = [v for v in values if not math.isnan(v)]
    return sum(values) / len(values) if values else float("nan")


def _to_numpy(a):
    return a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a)


class IoUMeter:
    def __init__(self, ignore_index=IGNORE_INDEX):
        self.ignore_index = ignore_index
        self.cm = np.zeros((2, 2), dtype=np.int64)   # rows = true class, columns = predicted class
        self.chip_ious = []                          # water IoU of each chip that can be scored

    def update(self, pred, target):
        """pred and target hold class ids (0/1); target may contain the ignore value."""
        p = _to_numpy(pred).ravel().astype(np.int64)
        t = _to_numpy(target).ravel().astype(np.int64)
        valid = t != self.ignore_index
        # 2*true + predicted gives 0=TN, 1=FP, 2=FN, 3=TP
        cm = np.bincount(2 * t[valid] + p[valid], minlength=4).reshape(2, 2)
        self.cm += cm
        (_, fp), (fn, tp) = cm
        if tp + fp + fn > 0:                         # chips with no water at all (true or predicted) can't be scored
            self.chip_ious.append(tp / (tp + fp + fn))

    def compute(self):
        (tn, fp), (fn, tp) = self.cm
        iou_water = _div(tp, tp + fp + fn)
        iou_not_water = _div(tn, tn + fp + fn)
        return {
            "iou_water": iou_water,                          # pooled
            "iou_not_water": iou_not_water,
            "miou": _mean_ignoring_nan([iou_water, iou_not_water]),
            "iou_water_per_chip_mean": float(np.mean(self.chip_ious)) if self.chip_ious else float("nan"),
            "n_chips_scored": len(self.chip_ious),
            "precision": _div(tp, tp + fp),
            "recall": _div(tp, tp + fn),
            "f1": _div(2 * tp, 2 * tp + fp + fn),
        }