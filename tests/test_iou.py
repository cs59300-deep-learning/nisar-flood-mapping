"""Unit tests for the IoU metric, using tiny synthetic masks where the right answer is known by hand."""
import math

import numpy as np
import pytest

from nisar_flood.datasets.transforms import IGNORE_INDEX
from nisar_flood.metrics.iou import IoUMeter


def score(pred, target):
    m = IoUMeter()
    m.update(np.array(pred), np.array(target))
    return m.compute()


def test_known_example_with_ignored_pixel():
    # last pixel is ignored -> TP=1, FP=1, TN=1, FN=0
    r = score([1, 1, 0, 0], [1, 0, 0, IGNORE_INDEX])
    assert r["iou_water"] == pytest.approx(1 / 2)
    assert r["iou_not_water"] == pytest.approx(1 / 2)
    assert r["precision"] == pytest.approx(1 / 2)
    assert r["recall"] == pytest.approx(1.0)
    assert r["f1"] == pytest.approx(2 / 3)


def test_perfect_prediction_scores_one():
    r = score([1, 1, 0, 0], [1, 1, 0, 0])
    assert r["iou_water"] == 1.0 and r["iou_not_water"] == 1.0 and r["f1"] == 1.0


def test_completely_wrong_prediction_scores_zero():
    r = score([0, 0, 1, 1], [1, 1, 0, 0])
    assert r["iou_water"] == 0.0 and r["iou_not_water"] == 0.0
    assert r["precision"] == 0.0 and r["recall"] == 0.0 and r["f1"] == 0.0


def test_precision_recall_f1_values():
    # TP=2, FP=1, FN=1, TN=2
    r = score([1, 1, 1, 0, 0, 0], [1, 1, 0, 1, 0, 0])
    assert r["precision"] == pytest.approx(2 / 3)
    assert r["recall"] == pytest.approx(2 / 3)
    assert r["f1"] == pytest.approx(2 / 3)
    assert r["iou_water"] == pytest.approx(2 / 4)
    assert r["iou_not_water"] == pytest.approx(2 / 4)


def test_ignored_pixels_never_change_the_score():
    base = score([1, 1, 0, 0], [1, 0, 0, 1])
    # add pixels labelled "no data": whatever the model predicts there must not matter
    with_ignored = score([1, 1, 0, 0, 1, 0, 1], [1, 0, 0, 1, IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX])
    assert with_ignored == base


def test_pooled_and_per_chip_definitions_differ():
    m = IoUMeter()
    m.update(np.array([1] * 90 + [0] * 10), np.array([1] * 100))   # big chip: IoU 0.9
    m.update(np.array([1, 0]), np.array([1, 1]))                   # tiny chip: IoU 0.5
    r = m.compute()
    assert r["iou_water_per_chip_mean"] == pytest.approx((0.9 + 0.5) / 2)   # each chip counts equally
    assert r["iou_water"] == pytest.approx(91 / 102)                        # big chip dominates
    assert r["n_chips_scored"] == 2


def test_chip_with_no_valid_pixels_is_harmless():
    # like the training chip Ghana_26376: every pixel is "no data"
    m = IoUMeter()
    m.update(np.array([1, 0, 1, 0]), np.array([IGNORE_INDEX] * 4))
    r = m.compute()
    assert r["n_chips_scored"] == 0
    assert math.isnan(r["iou_water"]) and math.isnan(r["precision"])


def test_no_water_anywhere_gives_nan_not_zero():
    # nothing to find and nothing predicted: water IoU is undefined, land IoU is perfect
    r = score([0, 0, 0], [0, 0, 0])
    assert math.isnan(r["iou_water"])
    assert r["iou_not_water"] == 1.0
    assert r["n_chips_scored"] == 0