"""Tests for :mod:`nisar_flood.pipeline.radiometry`."""

import numpy as np
import pytest

from nisar_flood.pipeline.radiometry import (
    DB_FLOOR,
    db_to_linear,
    linear_to_db,
    normalise_gcov_gamma0,
    normalise_sen1floods11,
)


# --------------------------------------------------------------------------- #
# linear_to_db: core conversion
# --------------------------------------------------------------------------- #
def test_linear_to_db_known_values():
    # 10*log10(1)=0, 10*log10(10)=10, 10*log10(0.1)=-10, 10*log10(100)=20.
    power = np.array([1.0, 10.0, 0.1, 100.0])
    db = linear_to_db(power)
    np.testing.assert_allclose(db, [0.0, 10.0, -10.0, 20.0])


def test_linear_to_db_returns_float64():
    db = linear_to_db(np.array([1.0, 2.0], dtype=np.float32))
    assert db.dtype == np.float64


def test_linear_to_db_preserves_shape():
    power = np.ones((4, 5))
    assert linear_to_db(power).shape == (4, 5)


def test_linear_to_db_accepts_scalar_and_list():
    np.testing.assert_allclose(linear_to_db(1.0), 0.0)
    np.testing.assert_allclose(linear_to_db([1.0, 10.0]), [0.0, 10.0])


# --------------------------------------------------------------------------- #
# linear_to_db: the physical floor (-40 dB)
# --------------------------------------------------------------------------- #
def test_default_floor_is_minus_40():
    assert DB_FLOOR == -40.0


def test_values_below_floor_are_clamped():
    # 1e-5 linear -> -50 dB, which is below the -40 dB floor.
    db = linear_to_db(np.array([1e-5]))
    assert db[0] == DB_FLOOR


def test_value_exactly_at_floor_passes_through():
    # 1e-4 linear -> exactly -40 dB.
    db = linear_to_db(np.array([1e-4]))
    np.testing.assert_allclose(db, [-40.0])


def test_custom_floor_is_respected():
    db = linear_to_db(np.array([1e-5]), floor_db=-30.0)
    assert db[0] == -30.0


def test_nothing_below_floor_on_mixed_input():
    rng = np.random.default_rng(0)
    power = rng.exponential(scale=0.05, size=10_000)
    db = linear_to_db(power)
    assert np.all(db >= DB_FLOOR)


# --------------------------------------------------------------------------- #
# linear_to_db: zero / negative / nan handling
# --------------------------------------------------------------------------- #
def test_zero_maps_to_floor_not_minus_inf():
    db = linear_to_db(np.array([0.0]))
    assert db[0] == DB_FLOOR
    assert np.isfinite(db[0])


def test_negative_maps_to_floor():
    # Negative "power" is unphysical (noise / artefacts) -> floor, not nan.
    db = linear_to_db(np.array([-1.0, -0.001]))
    assert np.all(db == DB_FLOOR)


def test_nan_is_preserved():
    db = linear_to_db(np.array([np.nan, 1.0, 0.0]))
    assert np.isnan(db[0])
    assert db[1] == 0.0
    assert db[2] == DB_FLOOR


def test_no_runtime_warning_on_zero_or_negative():
    # The implementation must not emit log10 divide/invalid warnings.
    with np.errstate(all="raise"):
        linear_to_db(np.array([0.0, -1.0, 1.0, np.nan]))


# --------------------------------------------------------------------------- #
# db_to_linear and roundtrip
# --------------------------------------------------------------------------- #
def test_db_to_linear_known_values():
    linear = db_to_linear(np.array([0.0, 10.0, -10.0, 20.0]))
    np.testing.assert_allclose(linear, [1.0, 10.0, 0.1, 100.0])


def test_roundtrip_linear_db_linear_above_floor():
    # Values whose dB stays above the floor must survive a roundtrip.
    power = np.array([1.0, 0.5, 2.0, 0.01, 100.0])  # min dB = -20, above -40
    recovered = db_to_linear(linear_to_db(power))
    np.testing.assert_allclose(recovered, power, rtol=1e-12)


def test_roundtrip_db_linear_db():
    db = np.array([-40.0, -20.0, -3.0, 0.0, 5.5, 18.0])
    recovered = linear_to_db(db_to_linear(db))
    np.testing.assert_allclose(recovered, db, rtol=1e-12)


def test_roundtrip_breaks_below_floor_as_expected():
    # A value below the floor is clamped, so the roundtrip is lossy by design.
    power = np.array([1e-6])  # -60 dB, clamped to -40 dB
    recovered = db_to_linear(linear_to_db(power))
    assert recovered[0] > power[0]
    np.testing.assert_allclose(recovered, db_to_linear(np.array([DB_FLOOR])))


def test_db_to_linear_preserves_nan():
    assert np.isnan(db_to_linear(np.array([np.nan]))[0])


# --------------------------------------------------------------------------- #
# normalise_gcov_gamma0: GCOV linear power -> dB
# --------------------------------------------------------------------------- #
def test_normalise_gcov_matches_linear_to_db():
    rng = np.random.default_rng(1)
    gamma0 = rng.exponential(scale=0.1, size=1000)
    np.testing.assert_array_equal(
        normalise_gcov_gamma0(gamma0), linear_to_db(gamma0)
    )


def test_normalise_gcov_clamps_and_preserves_nan():
    out = normalise_gcov_gamma0(np.array([0.0, 1e-9, 1.0, np.nan]))
    assert out[0] == DB_FLOOR
    assert out[1] == DB_FLOOR
    assert out[2] == 0.0
    assert np.isnan(out[3])


# --------------------------------------------------------------------------- #
# normalise_sen1floods11: already dB, just floored
# --------------------------------------------------------------------------- #
def test_normalise_sen1floods11_passes_through_above_floor():
    sigma0 = np.array([-25.0, -12.3, 0.0, 3.0])
    np.testing.assert_array_equal(normalise_sen1floods11(sigma0), sigma0)


def test_normalise_sen1floods11_clamps_below_floor():
    out = normalise_sen1floods11(np.array([-55.0, -40.0, -41.0]))
    np.testing.assert_array_equal(out, [-40.0, -40.0, -40.0])


def test_normalise_sen1floods11_does_not_log_convert():
    # If it (wrongly) applied 10*log10, an input of 1.0 would become 0.0.
    # Correct behaviour: 1.0 dB stays 1.0 dB.
    out = normalise_sen1floods11(np.array([1.0, 10.0]))
    np.testing.assert_array_equal(out, [1.0, 10.0])


def test_normalise_sen1floods11_preserves_nan():
    out = normalise_sen1floods11(np.array([np.nan, -10.0]))
    assert np.isnan(out[0])
    assert out[1] == -10.0


def test_normalise_sen1floods11_custom_floor():
    out = normalise_sen1floods11(np.array([-35.0]), floor_db=-30.0)
    assert out[0] == -30.0


# --------------------------------------------------------------------------- #
# cross-domain: both normalisers produce the same floor / scale
# --------------------------------------------------------------------------- #
def test_both_domains_share_floor():
    gcov = normalise_gcov_gamma0(np.array([0.0]))  # linear zero
    s1 = normalise_sen1floods11(np.array([-100.0]))  # far-below-floor dB
    assert gcov[0] == s1[0] == DB_FLOOR


@pytest.mark.parametrize("floor", [-40.0, -35.0, -30.0, -25.0])
def test_floor_is_the_minimum_for_both(floor):
    gcov = normalise_gcov_gamma0(
        np.array([0.0, 1e-9, 1.0, 10.0]), floor_db=floor
    )
    s1 = normalise_sen1floods11(
        np.array([-100.0, -50.0, 0.0, 5.0]), floor_db=floor
    )
    assert gcov.min() >= floor
    assert s1.min() >= floor
