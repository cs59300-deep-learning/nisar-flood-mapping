"""Tests for the polarisation band-swap ablation (#23), on tiny synthetic inputs."""
import math

import numpy as np
import pytest

from nisar_flood.datasets.transforms import IGNORE_INDEX, permute_channels
from nisar_flood.experiments.polarisation_ablation import (
    ARMS,
    chip_water_iou,
    evaluate_arms,
    gap_share,
    paired_drop,
)


def test_permute_channels_swaps_and_repeats():
    x = np.stack([np.zeros((2, 2)), np.ones((2, 2))])          # (C=2, H, W): VV=0, VH=1
    assert permute_channels(x, (0, 1)).tolist() == x.tolist()
    swapped = permute_channels(x, (1, 0))
    assert swapped[0].min() == 1 and swapped[1].max() == 0
    assert permute_channels(x, (0, 0))[1].max() == 0            # VV fed into both slots


def test_permute_channels_works_on_a_batch():
    x = np.stack([np.zeros((3, 2, 2)), np.ones((3, 2, 2))], axis=1)   # (B=3, C=2, H, W)
    out = permute_channels(x, (1, 0))
    assert out.shape == x.shape and out[:, 0].min() == 1 and out[:, 1].max() == 0


def test_permute_channels_does_not_modify_input():
    x = np.stack([np.zeros((2, 2)), np.ones((2, 2))])
    permute_channels(x, (1, 0))
    assert x[0].max() == 0 and x[1].min() == 1


def test_chip_water_iou_known_value_and_ignored_pixel():
    # last pixel ignored -> TP=1, FP=1, FN=0 -> IoU 1/2
    assert chip_water_iou([1, 1, 0, 0], [1, 0, 0, IGNORE_INDEX]) == pytest.approx(0.5)


def test_chip_water_iou_is_nan_when_no_water_anywhere():
    assert math.isnan(chip_water_iou([0, 0, 0], [0, 0, IGNORE_INDEX]))


def test_chip_water_iou_agrees_with_the_meter():
    from nisar_flood.metrics.iou import IoUMeter
    pred, target = np.array([1, 1, 1, 0, 0, 0]), np.array([1, 1, 0, 1, 0, IGNORE_INDEX])
    m = IoUMeter()
    m.update(pred, target)
    assert chip_water_iou(pred, target) == pytest.approx(m.chip_ious[0])


def test_paired_drop_constant_offset_has_zero_width_interval():
    ref = np.array([0.8, 0.6, 0.7, 0.9])
    r = paired_drop(ref, ref - 0.1, n_boot=500)
    assert r["drop"] == pytest.approx(0.1)
    assert r["ci_low"] == pytest.approx(0.1) and r["ci_high"] == pytest.approx(0.1)
    assert r["n_chips"] == 4


def test_paired_drop_identical_arms_is_zero():
    ref = np.array([0.8, 0.6, 0.7])
    assert paired_drop(ref, ref, n_boot=200)["drop"] == 0.0


def test_paired_drop_skips_chips_undefined_in_either_arm():
    r = paired_drop([0.8, float("nan"), 0.6], [0.5, 0.4, float("nan")], n_boot=200)
    assert r["n_chips"] == 1 and r["drop"] == pytest.approx(0.3)


def test_paired_drop_interval_contains_the_mean_and_is_reproducible():
    rng = np.random.default_rng(1)
    ref = rng.uniform(0.3, 0.9, 60)
    pert = ref - rng.uniform(0.0, 0.2, 60)
    a, b = paired_drop(ref, pert, n_boot=2000, seed=3), paired_drop(ref, pert, n_boot=2000, seed=3)
    assert a == b
    assert a["ci_low"] <= a["drop"] <= a["ci_high"]


def test_gap_share():
    assert gap_share(0.05, 0.45, 0.25) == pytest.approx(0.25)        # 0.05 of a 0.20 gap
    assert gap_share(0.30, 0.45, 0.25) == pytest.approx(1.5)         # harsher than the gap
    assert math.isnan(gap_share(0.05, 0.45, None))                   # no NISAR figure yet
    assert math.isnan(gap_share(0.05, 0.45, 0.50))                   # no gap to explain


def test_nan_to_none_makes_results_valid_json():
    import json

    from nisar_flood.experiments.polarisation_ablation import _nan_to_none
    cleaned = _nan_to_none({"a": float("nan"), "b": [1.0, float("nan")], "c": {"d": 0.5}})
    assert cleaned == {"a": None, "b": [1.0, None], "c": {"d": 0.5}}
    json.loads(json.dumps(cleaned, allow_nan=False))      # raises if any NaN remains


def test_arms_are_two_channel_orders():
    assert ARMS["identity"] == (0, 1) and ARMS["swap"] == (1, 0)
    assert all(len(order) == 2 and set(order) <= {0, 1} for order in ARMS.values())


def test_evaluate_arms_detects_a_model_that_relies_on_channel_order():
    torch = pytest.importorskip("torch")

    class ReadsVV(torch.nn.Module):
        """Predicts water where channel 0 (VV) is positive, and ignores channel 1."""
        def forward(self, x):
            return torch.cat([-x[:, :1], x[:, :1]], dim=1)

    water = torch.zeros(1, 4, 4, dtype=torch.long)
    water[:, :2] = 1
    vv = torch.where(water.bool(), 1.0, -1.0)[:, None]               # VV marks the water
    vh = -vv                                                         # VH marks the opposite
    loader = [(torch.cat([vv, vh], dim=1), water)] * 3

    out = evaluate_arms(ReadsVV(), loader, torch.device("cpu"))
    assert out["identity"]["chip_iou"] == [1.0, 1.0, 1.0]
    assert out["swap"]["chip_iou"] == [0.0, 0.0, 0.0]               # reads VH, which is inverted
    assert out["co_only"]["chip_iou"] == [1.0, 1.0, 1.0]            # VV still in slot 0
    assert out["cross_only"]["chip_iou"] == [0.0, 0.0, 0.0]
    drop = paired_drop(out["identity"]["chip_iou"], out["swap"]["chip_iou"], n_boot=100)
    assert drop["drop"] == 1.0


def test_evaluate_arms_ignores_a_model_that_does_not_depend_on_polarisation():
    torch = pytest.importorskip("torch")

    class ReadsMean(torch.nn.Module):
        def forward(self, x):
            m = x.mean(dim=1, keepdim=True)
            return torch.cat([-m, m], dim=1)

    water = torch.zeros(1, 4, 4, dtype=torch.long)
    water[:, :2] = 1
    vv = torch.where(water.bool(), 1.0, -1.0)[:, None]
    loader = [(torch.cat([vv, vv], dim=1), water)] * 2
    out = evaluate_arms(ReadsMean(), loader, torch.device("cpu"))
    assert out["identity"]["chip_iou"] == out["swap"]["chip_iou"] == [1.0, 1.0]
