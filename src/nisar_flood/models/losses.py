"""Loss for water segmentation that ignores "no data" pixels (label 255)."""
import torch
import torch.nn.functional as F

from ..datasets.transforms import IGNORE_INDEX


def masked_ce_dice_loss(logits, target, ignore_index=IGNORE_INDEX, dice_weight=1.0):
    """Cross-entropy + soft Dice on the water class, counting only pixels whose label is not ignore_index.

    logits: (N, 2, H, W) raw model outputs.  target: (N, H, W) with values 0, 1 or ignore_index.
    """
    valid = target != ignore_index
    if not valid.any():
        # Every pixel is "no data" (like the train chip Ghana_26376). Plain cross_entropy would
        # divide 0 by 0 and return NaN, so return a zero loss that still works with backward().
        return logits.sum() * 0.0

    ce = F.cross_entropy(logits.float(), target, ignore_index=ignore_index)

    water_prob = logits.float().softmax(dim=1)[:, 1] * valid      # probability of water, zeroed where no data
    water_true = (target == 1).float() * valid                    # 1 where the label says water
    dice = 1 - (2 * (water_prob * water_true).sum() + 1) / (water_prob.sum() + water_true.sum() + 1)
    return ce + dice_weight * dice