"""Unit tests for the NISAR chip Dataset, on tiny synthetic rasters."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from nisar_flood.datasets.nisar_chips import NisarChips, make_loaders, remap_nisar_labels, scoreable
from nisar_flood.datasets.transforms import IGNORE_INDEX


def write_chip(chip_dir, mask_dir, chip_id, label, backscatter=(-8.0, -14.0)):
    """Write one two-band chip and its label mask, both 4x4."""
    chip_dir.mkdir(parents=True, exist_ok=True)
    mask_dir.mkdir(parents=True, exist_ok=True)
    profile = {"driver": "GTiff", "width": 4, "height": 4, "crs": "EPSG:32720",
               "transform": from_origin(0, 0, 20, 20)}
    with rasterio.open(chip_dir / f"{chip_id}.tif", "w", count=2, dtype="float32", **profile) as f:
        for band, value in enumerate(backscatter, start=1):
            f.write(np.full((4, 4), value, dtype="float32"), band)
    with rasterio.open(mask_dir / f"{chip_id}_label.tif", "w", count=1, dtype="int16", **profile) as f:
        f.write(np.asarray(label, dtype="int16"), 1)


@pytest.fixture
def chips(tmp_path):
    chip_dir, mask_dir = tmp_path / "chips", tmp_path / "masks"
    mixed = np.zeros((4, 4), dtype="int16")
    mixed[0] = 1          # one row of water
    mixed[1] = 2          # one row of flagged vegetation
    mixed[2] = -1         # one row of unusable
    write_chip(chip_dir, mask_dir, "mixed", mixed)
    write_chip(chip_dir, mask_dir, "dry", np.zeros((4, 4), dtype="int16"))
    return chip_dir, mask_dir


def test_flagged_vegetation_and_unusable_both_become_ignore():
    y = remap_nisar_labels(np.array([[-1, 0, 1, 2]], dtype="int16"))
    assert y.tolist() == [[IGNORE_INDEX, 0, 1, IGNORE_INDEX]]


def test_flagged_vegetation_is_not_counted_as_water():
    # Class 2 is a flag, so it must not reach the model as either class.
    y = remap_nisar_labels(np.full((2, 2), 2, dtype="int16"))
    assert not (y == 1).any() and not (y == 0).any()


def test_item_shapes_and_value_range(chips):
    chip_dir, mask_dir = chips
    x, y = NisarChips(chip_dir, mask_dir, ["mixed"])[0]
    assert tuple(x.shape) == (2, 4, 4) and tuple(y.shape) == (4, 4)
    assert 0.0 <= float(x.min()) and float(x.max()) <= 1.0
    # HH is the brighter channel here and must stay in the first slot.
    assert float(x[0].mean()) > float(x[1].mean())


def test_chip_ids_fix_membership_and_order(chips):
    chip_dir, mask_dir = chips
    assert NisarChips(chip_dir, mask_dir, ["dry", "mixed"]).chip_ids == ["dry", "mixed"]
    assert len(NisarChips(chip_dir, mask_dir, ["mixed"])) == 1


def test_missing_chip_is_reported(chips):
    chip_dir, mask_dir = chips
    with pytest.raises(FileNotFoundError):
        NisarChips(chip_dir, mask_dir, ["absent"])


def test_scoreable_drops_chips_without_both_classes(chips):
    _, mask_dir = chips
    assert scoreable(mask_dir, ["mixed", "dry"]) == ["mixed"]


def test_test_loader_keeps_chips_whole(chips):
    chip_dir, mask_dir = chips
    loaders = make_loaders(chip_dir, mask_dir, ["mixed"], ["mixed", "dry"], workers=0)
    assert all(batch[0].shape[0] == 1 for batch in loaders["test"])
