"""Tests for the training loop's hardware-dependent choices (#19)."""
from unittest.mock import patch

import pytest
import torch

from nisar_flood.training.train import amp_dtype, lr_at, pick_device


class TestAmpDtype:
    """Mixed precision must be correct on whatever GPU the run lands on."""

    def test_cpu_and_mps_get_full_precision(self):
        assert amp_dtype(torch.device("cpu")) is None
        assert amp_dtype(torch.device("mps")) is None

    def test_ampere_and_newer_get_bfloat16(self):
        """A100/H100 (capability 8+): bfloat16 keeps float32's exponent range."""
        with patch.object(torch.cuda, "get_device_capability", lambda: (8, 0)):
            assert amp_dtype(torch.device("cuda")) is torch.bfloat16

    def test_older_cuda_cards_get_float16(self):
        """T4 is Turing (7.5): its tensor cores do float16, not bfloat16."""
        with patch.object(torch.cuda, "get_device_capability", lambda: (7, 5)):
            assert amp_dtype(torch.device("cuda")) is torch.float16

    def test_turing_is_not_misread_as_bfloat16_capable(self):
        """torch.cuda.is_bf16_supported() answers True on Turing via a software
        path, so the selection reads compute capability instead."""
        with patch.object(torch.cuda, "get_device_capability", lambda: (7, 5)), \
             patch.object(torch.cuda, "is_bf16_supported", lambda: True):
            assert amp_dtype(torch.device("cuda")) is torch.float16

    def test_disabled_overrides_capability(self):
        with patch.object(torch.cuda, "get_device_capability", lambda: (9, 0)):
            assert amp_dtype(torch.device("cuda"), enabled=False) is None


class TestSchedule:
    cfg = {"epochs": 10, "warmup_epochs": 2, "scheduler": "cosine"}

    def test_warmup_ramps_from_below_one(self):
        assert lr_at(0, self.cfg) == pytest.approx(0.5)
        assert lr_at(1, self.cfg) == pytest.approx(1.0)

    def test_cosine_decays_to_zero_by_the_end(self):
        assert lr_at(2, self.cfg) == pytest.approx(1.0)       # first post-warmup epoch
        assert lr_at(9, self.cfg) < 0.1                        # last epoch
        assert lr_at(9, self.cfg) >= 0.0

    def test_schedule_is_monotonic_after_warmup(self):
        after = [lr_at(e, self.cfg) for e in range(2, 10)]
        assert all(a >= b for a, b in zip(after, after[1:]))

    def test_scheduler_none_holds_the_base_rate(self):
        cfg = {**self.cfg, "scheduler": "none"}
        assert lr_at(5, cfg) == 1.0

    def test_no_warmup_is_handled(self):
        cfg = {"epochs": 4, "warmup_epochs": 0, "scheduler": "cosine"}
        assert lr_at(0, cfg) == pytest.approx(1.0)


def test_pick_device_returns_something_usable():
    assert pick_device().type in {"cuda", "mps", "cpu"}
