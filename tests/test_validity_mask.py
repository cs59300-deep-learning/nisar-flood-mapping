import numpy as np
import pytest

from nisar_flood.pipeline.validity_mask import (
    apply_validity_mask,
    compare_zero_heuristic,
    granule_validity_report,
    valid_pixel_fraction,
    valid_pixels,
)


def test_only_mask_code_one_is_valid():
    mask = np.array([[1, 0, 2], [255, 1, 7]])

    np.testing.assert_array_equal(
        valid_pixels(mask),
        np.array([[True, False, False], [False, True, False]]),
    )


def test_apply_mask_preserves_valid_values_and_masks_invalid_before_statistics():
    samples = np.array([[2.0, 100.0], [4.0, 200.0]])
    mask = np.array([[1, 0], [1, 255]])

    result = apply_validity_mask(samples, mask)

    np.testing.assert_array_equal(np.ma.getmaskarray(result), [[False, True], [False, True]])
    assert np.ma.mean(result) == pytest.approx(3.0)
    filled = result.filled()
    assert filled[0, 0] == 2.0
    assert np.isnan(filled[0, 1])
    assert filled[1, 0] == 4.0
    assert np.isnan(filled[1, 1])


def test_apply_mask_broadcasts_pixel_validity_across_channels():
    samples = np.arange(8).reshape(2, 2, 2)
    mask = np.array([[1, 0], [2, 1]])

    result = apply_validity_mask(samples, mask)

    assert result.mask.shape == samples.shape
    np.testing.assert_array_equal(result.mask[0, 1], [True, True])
    np.testing.assert_array_equal(result.mask[1, 0], [True, True])


def test_apply_mask_rejects_mismatched_spatial_shapes():
    with pytest.raises(ValueError, match="must match sample spatial shape"):
        apply_validity_mask(np.zeros((2, 3)), np.ones((3, 2)))


def test_valid_fraction_and_granule_report():
    mask = np.array([[1, 1, 0], [255, 3, 1]])

    assert valid_pixel_fraction(mask) == pytest.approx(0.5)
    report = granule_validity_report("granule-A", mask)
    assert report == {
        "granule_id": "granule-A",
        "pixel_count": 6,
        "valid_pixel_count": 3,
        "valid_pixel_fraction": 0.5,
    }


def test_report_documents_agreement_with_zero_based_heuristic():
    mask = np.array([[1, 0], [2, 255]])
    legacy_valid = np.array([[True, False], [True, False]])

    comparison = compare_zero_heuristic(mask, legacy_valid)
    assert comparison == {
        "pixel_count": 4,
        "product_valid_count": 1,
        "heuristic_valid_count": 2,
        "agreement_count": 3,
        "agreement_fraction": 0.75,
    }
    report = granule_validity_report(
        "granule-A", mask, zero_heuristic_valid=legacy_valid
    )
    assert report["agreement_fraction"] == pytest.approx(0.75)


def test_empty_mask_and_mismatched_heuristic_are_rejected():
    with pytest.raises(ValueError, match="at least one pixel"):
        valid_pixel_fraction(np.empty((0, 2)))
    with pytest.raises(ValueError, match="must match mask shape"):
        compare_zero_heuristic(np.ones((2, 2)), np.ones((4,), dtype=bool))
