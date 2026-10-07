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