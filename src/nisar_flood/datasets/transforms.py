"""Preprocessing for Sen1Floods11 chips (numpy only, so it is easy to test)."""
import numpy as np

IGNORE_INDEX = 255                # label value for "no data" pixels (originally -1)
DB_MIN, DB_MAX = -50.0, 1.0       # clip range for backscatter in dB


def preprocess_sar_db(x, lo=DB_MIN, hi=DB_MAX):
    """Convert backscatter in dB to the range [0, 1]."""
    x = np.nan_to_num(x.astype("float32"), nan=0.0, posinf=hi, neginf=lo)
    return (np.clip(x, lo, hi) - lo) / (hi - lo)


def remap_labels(y):
    """Sen1Floods11 labels {-1, 0, 1} -> {255, 0, 1}."""
    y = y.astype("int64").copy()
    y[y == -1] = IGNORE_INDEX
    return y

def random_flip_rotate(x, y, rng):
    """Random dihedral transform: flips and 90-degree rotations.

    x is (C, H, W), y is (H, W). The eight symmetries of the square are the only
    augmentation applied. They are safe for SAR because they move pixels without
    altering their values; brightness or contrast jitter would change
    backscatter, which is the physical quantity the model reads.

    Orientation does carry some information in SAR, since the look direction
    fixes which slopes appear bright. On a 252-chip training split the
    overfitting risk outweighs that signal.
    """
    if rng.random() < 0.5:                      # horizontal flip
        x, y = x[:, :, ::-1], y[:, ::-1]
    if rng.random() < 0.5:                      # vertical flip
        x, y = x[:, ::-1, :], y[::-1, :]
    k = int(rng.integers(4))                    # 0, 90, 180 or 270 degrees
    if k:
        x, y = np.rot90(x, k, axes=(1, 2)), np.rot90(y, k, axes=(0, 1))
    # The slicing above produces negative strides, which torch.from_numpy rejects.
    return np.ascontiguousarray(x), np.ascontiguousarray(y)
