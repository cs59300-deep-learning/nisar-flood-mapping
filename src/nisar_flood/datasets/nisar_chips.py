"""Hand-labelled NISAR chips as a Dataset, for zero-shot scoring and fine-tuning.

The chips are 512x512 two-band GeoTIFFs holding HH and HV gamma0 in dB; the
labels are int16 masks written by `labelling/chip_export.py`.

Two things differ from Sen1Floods11 and are handled here:

Channels. The source models were trained on Sentinel-1 VV and VH. NISAR land
mode gives HH and HV, so HH is fed to the VV input and HV to the VH input: the
co-polarised channel to the co-polarised slot, cross-polarised to
cross-polarised. The mismatch that remains is the point RQ1 measures, not
something to correct away here.

Labels. The export uses 1 water, 0 dry, 2 suspected flooded vegetation and -1
unusable. Only water and dry are scored. Flooded vegetation is a flag, not a
decision - it cannot be confirmed from the radar alone - so it is mapped to the
ignore value along with the unusable pixels rather than being folded into
either class.
"""
from pathlib import Path

import numpy as np
import rasterio
import torch
from torch.utils.data import DataLoader, Dataset

from .transforms import IGNORE_INDEX, preprocess_sar_db, random_flip_rotate, remap_labels

WATER, DRY, FLOODED_VEG, UNUSABLE = 1, 0, 2, -1
LABEL_SUFFIX = "_label.tif"


def remap_nisar_labels(y):
    """NISAR labels {-1, 0, 1, 2} -> {255, 0, 1, 255}."""
    y = remap_labels(y)                  # handles -1 -> IGNORE_INDEX
    y[y == FLOODED_VEG] = IGNORE_INDEX
    return y


class NisarChips(Dataset):
    """Chips named by id, paired with their label masks.

    `chip_ids` fixes both membership and order, so a split file is the only
    thing that decides which chips a run sees.
    """

    def __init__(self, chip_dir, mask_dir, chip_ids, augment=False, seed=0):
        self.chip_dir = Path(chip_dir)
        self.mask_dir = Path(mask_dir)
        self.chip_ids = list(chip_ids)
        self.augment = augment
        self.rng = np.random.default_rng(seed)
        missing = [c for c in self.chip_ids if not self._paths(c)[0].exists()]
        if missing:
            raise FileNotFoundError(f"{len(missing)} chips not under {self.chip_dir}: {missing[:3]}")

    def _paths(self, chip_id):
        return self.chip_dir / f"{chip_id}.tif", self.mask_dir / f"{chip_id}{LABEL_SUFFIX}"

    def __len__(self):
        return len(self.chip_ids)

    def __getitem__(self, i):
        chip_path, mask_path = self._paths(self.chip_ids[i])
        with rasterio.open(chip_path) as f:
            x = f.read().astype("float32")        # (2, H, W): HH then HV, in dB
        with rasterio.open(mask_path) as f:
            y = f.read(1)
        x = preprocess_sar_db(x)
        y = remap_nisar_labels(y)
        if self.augment:
            x, y = random_flip_rotate(x, y, self.rng)
        return torch.from_numpy(x), torch.from_numpy(y)


def scoreable(mask_dir, chip_ids):
    """Chip ids that still have both water and dry pixels once the ignore classes are removed.

    A chip whose water is entirely flagged as vegetation carries no water signal
    to learn from or score against.
    """
    keep = []
    for chip_id in chip_ids:
        with rasterio.open(Path(mask_dir) / f"{chip_id}{LABEL_SUFFIX}") as f:
            y = remap_nisar_labels(f.read(1))
        if (y == WATER).any() and (y == DRY).any():
            keep.append(chip_id)
    return keep


def make_loaders(chip_dir, mask_dir, train_ids, test_ids, batch_size=4, workers=2,
                 augment=True, seed=0):
    """A shuffled, augmented training loader and an unshuffled test loader.

    The test loader uses batch size 1 so that per-chip IoU is computed on whole
    chips, matching how Sen1Floods11 is scored.
    """
    return {
        "train": DataLoader(
            NisarChips(chip_dir, mask_dir, train_ids, augment=augment, seed=seed),
            batch_size=min(batch_size, max(len(train_ids), 1)),
            shuffle=True,
            num_workers=workers,
            drop_last=False,
        ),
        "test": DataLoader(
            NisarChips(chip_dir, mask_dir, test_ids, augment=False, seed=seed),
            batch_size=1,
            shuffle=False,
            num_workers=workers,
        ),
    }
