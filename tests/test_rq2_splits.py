"""Unit tests for the RQ2 split builder."""
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from make_rq2_splits import build

from tests.test_nisar_chips import write_chip


@pytest.fixture
def masks(tmp_path):
    """Forty chips whose water fraction climbs from 0 to nearly all of the chip."""
    chip_dir, mask_dir = tmp_path / "chips", tmp_path / "masks"
    for i in range(40):
        label = np.zeros((4, 4), dtype="int16")
        label.flat[:i // 3] = 1
        write_chip(chip_dir, mask_dir, f"chip{i:02d}", label)
    return mask_dir


def test_subsets_are_nested_within_a_seed(masks):
    split = build(masks, test_size=12, seeds=(0, 1), sizes=(4, 8, 16, 28), seed=0)
    for subsets in split["subsets"].values():
        sizes = sorted(subsets, key=int)
        for smaller, larger in pairwise(sizes):
            assert set(subsets[smaller]) <= set(subsets[larger])


def test_test_set_and_pool_do_not_overlap(masks):
    split = build(masks, test_size=12, seeds=(0,), sizes=(4,), seed=0)
    assert not set(split["test"]) & set(split["pool"])
    assert len(split["test"]) + len(split["pool"]) == split["n_chips"]
    for subset in split["subsets"]["0"].values():
        assert not set(subset) & set(split["test"])


def test_same_seed_gives_the_same_split(masks):
    a = build(masks, test_size=12, seeds=(0,), sizes=(4, 8), seed=0)
    b = build(masks, test_size=12, seeds=(0,), sizes=(4, 8), seed=0)
    assert a["test"] == b["test"] and a["subsets"] == b["subsets"]


def test_every_stratum_is_represented_in_the_smallest_subset(masks):
    split = build(masks, test_size=12, seeds=(0, 1, 2), sizes=(4,), seed=0)
    stratum = split["stratum"]
    for subsets in split["subsets"].values():
        assert len({stratum[c] for c in subsets["4"]}) == split["n_strata"]


def test_sizes_larger_than_the_pool_are_dropped(masks):
    split = build(masks, test_size=12, seeds=(0,), sizes=(4, 28, 40), seed=0)
    assert split["sizes"] == [4, 28]


def test_strata_are_equal_sized_and_ordered_by_wetness(masks):
    split = build(masks, test_size=12, seeds=(0,), sizes=(4,), seed=0)
    water, stratum = split["water_fraction"], split["stratum"]
    counts = np.bincount(list(stratum.values()), minlength=split["n_strata"])
    assert counts.max() - counts.min() <= 1
    means = [np.mean([water[c] for c in stratum if stratum[c] == s]) for s in range(split["n_strata"])]
    assert means == sorted(means)
