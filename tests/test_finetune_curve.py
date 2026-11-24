"""Unit tests for the RQ2 fine-tuning sweep: schedule, aggregation and scoring."""
import numpy as np
import pytest
import torch

from nisar_flood.datasets.nisar_chips import NisarChips
from nisar_flood.experiments.finetune_curve import evaluate, fingerprint, lr_at, summarise
from tests.test_nisar_chips import write_chip

CFG = {"steps": 100, "warmup_steps": 10, "scheduler": "cosine"}


def test_warmup_climbs_to_the_full_rate():
    assert lr_at(0, CFG) == pytest.approx(0.1)
    assert lr_at(9, CFG) == pytest.approx(1.0)


def test_cosine_decays_to_zero_by_the_last_step():
    assert lr_at(10, CFG) == pytest.approx(1.0)
    assert lr_at(99, CFG) < 0.01
    assert all(lr_at(s, CFG) >= lr_at(s + 1, CFG) for s in range(10, 99))


def test_schedule_can_be_switched_off():
    assert lr_at(50, {"steps": 100, "warmup_steps": 0, "scheduler": "none"}) == 1.0


def test_summarise_reports_spread_across_seeds():
    results = [{"n": 5, "metrics": {"m": 0.4}}, {"n": 5, "metrics": {"m": 0.6}},
               {"n": 10, "metrics": {"m": 0.5}}]
    s = summarise(results, "m")
    assert s["5"]["mean"] == pytest.approx(0.5)
    assert s["5"]["std"] == pytest.approx(np.std([0.4, 0.6], ddof=1))
    assert s["5"]["n_seeds"] == 2


def test_a_single_seed_has_no_spread():
    # std over one value is undefined; reporting 0 keeps the error bar drawable.
    assert summarise([{"n": 0, "metrics": {"m": 0.5}}], "m")["0"]["std"] == 0.0


class AllWater(torch.nn.Module):
    """Predicts class 1 everywhere, so the expected IoU is known by hand."""

    def forward(self, x):
        logits = torch.zeros(x.shape[0], 2, *x.shape[2:])
        logits[:, 1] = 1.0
        return logits


def test_evaluate_scores_chip_by_chip_and_names_them(tmp_path):
    chip_dir, mask_dir = tmp_path / "chips", tmp_path / "masks"
    half = np.zeros((4, 4), dtype="int16")
    half[:2] = 1                                   # half water, half dry
    write_chip(chip_dir, mask_dir, "half", half)
    write_chip(chip_dir, mask_dir, "wet", np.ones((4, 4), dtype="int16"))

    loader = torch.utils.data.DataLoader(
        NisarChips(chip_dir, mask_dir, ["half", "wet"]), batch_size=1)
    metrics, per_chip = evaluate(AllWater(), loader, torch.device("cpu"))

    assert [c["chip"] for c in per_chip] == ["half", "wet"]
    assert per_chip[0]["iou_water"] == pytest.approx(0.5)   # all 8 dry pixels are false positives
    assert per_chip[1]["iou_water"] == pytest.approx(1.0)
    assert metrics["iou_water_per_chip_mean"] == pytest.approx(0.75)


def sweep_cfg(**over):
    cfg = {
        "source": {"config": "configs/unet_resnet50.yaml", "checkpoint": "runs/a/best.pt"},
        "train": {"steps": 300, "lr": 5e-5, "weight_decay": 1e-4, "dice_weight": 1.0,
                  "scheduler": "cosine", "warmup_steps": 20},
        "data": {"batch_size": 4, "augment": True, "splits": "data/labels/rq2_splits.json"},
    }
    for section, fields in over.items():
        cfg[section] = {**cfg[section], **fields}
    return cfg


def test_fingerprint_is_stable_for_the_same_settings():
    assert fingerprint(sweep_cfg()) == fingerprint(sweep_cfg())


@pytest.mark.parametrize("over", [
    {"train": {"steps": 200}},
    {"train": {"lr": 1e-4}},
    {"train": {"dice_weight": 0.5}},
    {"data": {"batch_size": 8}},
    {"data": {"augment": False}},
    {"source": {"checkpoint": "runs/b/best.pt"}},
])
def test_fingerprint_changes_when_a_run_would_differ(over):
    assert fingerprint(sweep_cfg(**over)) != fingerprint(sweep_cfg())


def test_fingerprint_ignores_settings_that_only_change_speed():
    # Reusing a finished run after raising --workers is correct; the result is the same.
    cfg = sweep_cfg()
    cfg["data"]["workers"] = 8
    assert fingerprint(cfg) == fingerprint(sweep_cfg())
