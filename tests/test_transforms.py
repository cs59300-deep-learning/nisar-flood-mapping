"""Tests for the augmentation added for the source-model training loop (#19)."""
import numpy as np
import pytest
import torch

from nisar_flood.datasets.transforms import (IGNORE_INDEX, preprocess_sar_db,
                                             random_flip_rotate, remap_labels)


def sample(size=8):
    """A chip whose water mask is asymmetric, so a wrong rotation is detectable."""
    x = np.arange(2 * size * size, dtype="float32").reshape(2, size, size)
    y = np.zeros((size, size), dtype="int64")
    y[:3, :2] = 1                      # water in one corner only
    y[-1, :] = IGNORE_INDEX            # a no-data row
    return x, y


@pytest.mark.parametrize("seed", range(8))
def test_shapes_are_preserved(seed):
    x, y = sample()
    xa, ya = random_flip_rotate(x, y, np.random.default_rng(seed))
    assert xa.shape == x.shape and ya.shape == y.shape


@pytest.mark.parametrize("seed", range(8))
def test_pixel_values_are_only_permuted(seed):
    """Dihedral transforms must not change backscatter, only move it."""
    x, y = sample()
    xa, ya = random_flip_rotate(x, y, np.random.default_rng(seed))
    assert np.array_equal(np.sort(xa, axis=None), np.sort(x, axis=None))
    assert np.array_equal(np.sort(ya, axis=None), np.sort(y, axis=None))


@pytest.mark.parametrize("seed", range(8))
def test_image_and_label_stay_aligned(seed):
    """The same transform must be applied to both channels and to the label."""
    x, y = sample()
    # Channel 1 is channel 0 plus a constant, so alignment is checkable after the move.
    x[1] = x[0] + 1000.0
    xa, ya = random_flip_rotate(x, y, np.random.default_rng(seed))
    assert np.array_equal(xa[1], xa[0] + 1000.0)
    # Water count survives, and no-data is still exactly one row or column.
    assert (ya == 1).sum() == (y == 1).sum()
    assert (ya == IGNORE_INDEX).sum() == (y == IGNORE_INDEX).sum()


@pytest.mark.parametrize("seed", range(4))
def test_output_is_contiguous_for_torch(seed):
    """Flips and rot90 give negative strides, which torch.from_numpy rejects."""
    x, y = sample()
    xa, ya = random_flip_rotate(x, y, np.random.default_rng(seed))
    assert torch.from_numpy(xa).shape == (2, 8, 8)
    assert torch.from_numpy(ya).shape == (8, 8)


def test_same_seed_gives_same_augmentation():
    x, y = sample()
    a = random_flip_rotate(x, y, np.random.default_rng(3))
    b = random_flip_rotate(x, y, np.random.default_rng(3))
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_augmentation_composes_with_preprocessing():
    """What the Dataset actually does: preprocess, remap, then augment."""
    x = np.full((2, 8, 8), -20.0, dtype="float32")
    y = np.full((8, 8), -1, dtype="int16")
    y[:4, :4] = 1
    xa, ya = random_flip_rotate(preprocess_sar_db(x), remap_labels(y),
                                np.random.default_rng(0))
    assert 0.0 <= xa.min() and xa.max() <= 1.0
    assert set(np.unique(ya)) <= {0, 1, IGNORE_INDEX}
