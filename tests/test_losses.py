"""Unit tests for the masked loss. Skipped automatically where torch is not installed."""
import pytest

torch = pytest.importorskip("torch")

from nisar_flood.datasets.transforms import IGNORE_INDEX
from nisar_flood.models.losses import masked_ce_dice_loss

# one 2x2 chip: water, land / land, no-data
TARGET = torch.tensor([[[1, 0], [0, IGNORE_INDEX]]])


def make_logits(seed=0):
    torch.manual_seed(seed)
    return torch.randn(1, 2, 2, 2)


def test_loss_is_finite_and_positive():
    loss = masked_ce_dice_loss(make_logits(), TARGET)
    assert torch.isfinite(loss) and loss.item() > 0


def test_logits_at_ignored_pixels_do_not_change_the_loss():
    a = make_logits()
    b = a.clone()
    b[:, :, 1, 1] = 100.0          # wild values exactly where the label is "no data"
    assert torch.isclose(masked_ce_dice_loss(a, TARGET), masked_ce_dice_loss(b, TARGET))


def test_no_gradient_flows_to_ignored_pixels():
    logits = make_logits().requires_grad_(True)
    masked_ce_dice_loss(logits, TARGET).backward()
    assert logits.grad[:, :, 1, 1].abs().sum().item() == 0.0     # the ignored pixel gets no learning signal
    assert logits.grad[:, :, 0, 0].abs().sum().item() > 0.0      # a labelled pixel does


def test_all_ignored_chip_gives_zero_loss_not_nan():
    logits = make_logits().requires_grad_(True)
    target = torch.full((1, 2, 2), IGNORE_INDEX)
    loss = masked_ce_dice_loss(logits, target)
    loss.backward()
    assert loss.item() == 0.0
    assert torch.isfinite(logits.grad).all()


def test_confident_correct_prediction_has_near_zero_loss():
    logits = torch.zeros(1, 2, 2, 2)
    logits[0, 1, 0, 0], logits[0, 0, 0, 0] = 10.0, -10.0         # water pixel
    for (r, c) in [(0, 1), (1, 0)]:                              # land pixels
        logits[0, 0, r, c], logits[0, 1, r, c] = 10.0, -10.0
    assert masked_ce_dice_loss(logits, TARGET).item() < 1e-3