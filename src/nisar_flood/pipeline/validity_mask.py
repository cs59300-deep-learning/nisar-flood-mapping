"""Utilities for applying the validity layer in NISAR GCOV products.

For the granules used by this project, a sample is valid only when the
product's ``mask`` value is 1. In particular, ``mask != 0`` is not a valid
test: 255 marks pixels outside the radar acquisition and other nonzero
values can identify different subswaths.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def valid_pixels(mask: npt.ArrayLike) -> npt.NDArray[np.bool_]:
    """Return the project-valid pixels from a NISAR mask layer.

    A pixel is valid exactly when its mask code equals 1. The comparison
    preserves the mask's spatial shape and naturally marks NaNs invalid.
    """
    return np.asarray(mask) == 1


def apply_validity_mask(
    samples: npt.ArrayLike,
    mask: npt.ArrayLike,
    *,
    fill_value: float = np.nan,
) -> np.ma.MaskedArray:
    """Mask invalid samples before computing statistics or downstream features.

    ``mask`` must match the first two dimensions of ``samples``. Any trailing
    dimensions (for example polarization or feature channels) are broadcast
    from the same pixel-validity layer. The returned masked array is a view
    where possible; use it directly for masked-aware reductions such as
    ``numpy.ma.mean``. ``fill_value`` is used only when explicitly filled.
    """
    values = np.asarray(samples)
    valid = valid_pixels(mask)
    if values.ndim < 2:
        raise ValueError("samples must have at least two spatial dimensions")
    if valid.shape != values.shape[:2]:
        raise ValueError(
            f"mask shape {valid.shape} must match sample spatial shape {values.shape[:2]}"
        )

    # Integer arrays cannot represent the default NaN fill value. Promote
    # them so callers can materialize a filled result without losing samples.
    if values.dtype.kind in "biu" and np.isnan(fill_value):
        values = values.astype(np.float64)

    invalid = ~valid
    if values.ndim > 2:
        invalid = invalid[(...,) + (None,) * (values.ndim - 2)]
    masked = np.ma.array(values, mask=np.broadcast_to(invalid, values.shape), copy=False)
    masked.set_fill_value(fill_value)
    return masked


def valid_pixel_fraction(mask: npt.ArrayLike) -> float:
    """Return the share of pixels whose NISAR mask code is exactly 1."""
    valid = valid_pixels(mask)
    if valid.size == 0:
        raise ValueError("mask must contain at least one pixel")
    return float(np.count_nonzero(valid) / valid.size)


def compare_zero_heuristic(
    mask: npt.ArrayLike,
    zero_heuristic_valid: npt.ArrayLike,
) -> dict[str, int | float]:
    """Quantify agreement with a precomputed zero/floor heuristic.

    ``zero_heuristic_valid`` is a boolean validity map produced by the legacy
    zero/floor rule for the same granule. Returning counts as well as the
    agreement fraction makes the comparison interpretable in the methods
    section. This helper does not recreate that heuristic because its exact
    floor threshold depends on the measurement product and preprocessing.
    """
    product_valid = valid_pixels(mask)
    heuristic = np.asarray(zero_heuristic_valid, dtype=bool)
    if product_valid.shape != heuristic.shape:
        raise ValueError(
            f"heuristic shape {heuristic.shape} must match mask shape {product_valid.shape}"
        )
    if product_valid.size == 0:
        raise ValueError("mask must contain at least one pixel")
    agree = product_valid == heuristic
    return {
        "pixel_count": int(product_valid.size),
        "product_valid_count": int(np.count_nonzero(product_valid)),
        "heuristic_valid_count": int(np.count_nonzero(heuristic)),
        "agreement_count": int(np.count_nonzero(agree)),
        "agreement_fraction": float(np.count_nonzero(agree) / agree.size),
    }


def granule_validity_report(
    granule_id: str,
    mask: npt.ArrayLike,
    *,
    zero_heuristic_valid: npt.ArrayLike | None = None,
) -> dict[str, str | int | float]:
    """Build the per-granule QA record for validity coverage and comparison."""
    valid = valid_pixels(mask)
    if valid.size == 0:
        raise ValueError("mask must contain at least one pixel")
    report: dict[str, str | int | float] = {
        "granule_id": granule_id,
        "pixel_count": int(valid.size),
        "valid_pixel_count": int(np.count_nonzero(valid)),
        "valid_pixel_fraction": valid_pixel_fraction(mask),
    }
    if zero_heuristic_valid is not None:
        report.update(compare_zero_heuristic(mask, zero_heuristic_valid))
    return report
