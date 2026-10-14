"""Radiometric normalisation to a common backscatter convention.

NISAR GCOV and Sen1Floods11 arrive in *different radiometric conventions*,
and if they are not reconciled the difference silently contaminates the
polarisation ablation (issue #8). This module converts both onto one shared
convention: **gamma-nought-style backscatter in decibels (dB) with a physical
floor at -40 dB**.

Conventions in play
-------------------
* **NISAR L2 GCOV** - the diagonal covariance terms (``HHHH``, ``HVHV``) are
  calibrated, radiometrically terrain-flattened **gamma-nought (gamma0) power
  in linear units**. They are non-negative power ratios, not dB.
* **Sen1Floods11** - the Sentinel-1 chips are Google Earth Engine
  ``COPERNICUS/S1_GRD`` exports, i.e. **sigma-nought (sigma0) already in dB**.

See ``docs/radiometry.md`` for the full write-up and the sigma0/gamma0 caveat.

Common convention (this module's output)
-----------------------------------------
``10 * log10(power)`` clamped so nothing sits below ``DB_FLOOR`` (-40 dB).
Values below the floor are not physically meaningful backscatter - they are
noise, calibration artefacts, or exact zeros from masked / shadowed pixels -
so they are clamped up to the floor rather than left as ``-inf``.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "DB_FLOOR",
    "db_to_linear",
    "linear_to_db",
    "normalise_gcov_gamma0",
    "normalise_sen1floods11",
]

#: Physical lower bound on real backscatter, in dB. Nothing below -40 dB is
#: physically meaningful for these sensors; such values are clamped up to it.
DB_FLOOR: float = -40.0


def linear_to_db(
    power: ArrayLike,
    *,
    floor_db: float = DB_FLOOR,
) -> NDArray[np.float64]:
    """Convert linear backscatter power to decibels with a physical floor.

    Applies ``10 * log10(power)`` and clamps the result so nothing falls below
    ``floor_db``. Zeros and negatives - which can appear as masked pixels,
    radar shadow, or small numerical artefacts - map to the floor instead of
    producing ``-inf`` or ``nan`` from the logarithm. Genuine ``nan`` inputs
    (no-data) are preserved as ``nan`` so downstream masking still works.

    Parameters
    ----------
    power:
        Linear backscatter power (e.g. GCOV gamma0 diagonal terms). Any array
        shape is accepted.
    floor_db:
        Lower clamp applied after the dB conversion. Defaults to
        :data:`DB_FLOOR` (-40 dB).

    Returns
    -------
    numpy.ndarray
        ``float64`` array of the same shape, in dB, with no value below
        ``floor_db`` (except ``nan``, which is preserved).
    """
    values = np.asarray(power, dtype=np.float64)
    nan_mask = np.isnan(values)

    # log10 is only defined for strictly positive input. Everything that is
    # zero, negative, or (after the log) below the floor collapses to the floor,
    # so we can safely evaluate the log only where it is well defined.
    positive = values > 0.0
    db = np.full(values.shape, floor_db, dtype=np.float64)
    np.log10(values, out=db, where=positive)
    db[positive] *= 10.0

    np.maximum(db, floor_db, out=db)
    db[nan_mask] = np.nan
    return db


def db_to_linear(db: ArrayLike) -> NDArray[np.float64]:
    """Convert decibels back to linear power via ``10 ** (db / 10)``.

    This is the exact inverse of :func:`linear_to_db` for any input that was
    not clamped by the floor. ``nan`` is preserved.

    Parameters
    ----------
    db:
        Backscatter in decibels.

    Returns
    -------
    numpy.ndarray
        ``float64`` linear power of the same shape.
    """
    values = np.asarray(db, dtype=np.float64)
    return np.power(10.0, values / 10.0)


def normalise_gcov_gamma0(
    gamma0_linear: ArrayLike,
    *,
    floor_db: float = DB_FLOOR,
) -> NDArray[np.float64]:
    """Normalise NISAR GCOV gamma0 (linear power) to the common dB convention.

    GCOV diagonal terms are already gamma-nought, so this is purely the
    linear-to-dB conversion with the physical floor. It exists as a named
    entry point so callers express intent ("this is GCOV gamma0") rather than
    reaching for :func:`linear_to_db` directly.

    Parameters
    ----------
    gamma0_linear:
        Linear gamma0 power, e.g. ``GCOVData.hh`` or ``GCOVData.hv`` from
        :func:`nisar_flood.pipeline.gcov.read_gcov`.
    floor_db:
        Physical dB floor. Defaults to :data:`DB_FLOOR`.

    Returns
    -------
    numpy.ndarray
        Gamma0 in dB with the floor applied.
    """
    return linear_to_db(gamma0_linear, floor_db=floor_db)


def normalise_sen1floods11(
    sigma0_db: ArrayLike,
    *,
    floor_db: float = DB_FLOOR,
) -> NDArray[np.float64]:
    """Normalise Sen1Floods11 Sentinel-1 chips to the common dB convention.

    Sen1Floods11 chips are already sigma-nought in dB, so no log conversion is
    applied; only the physical floor is enforced so both domains share the
    same lower bound and the same no-data (``nan``) handling. Values at or
    above the floor pass through unchanged.

    .. note::
       These chips are **sigma0**, whereas GCOV is **gamma0**. The two differ
       by ``cos(theta_local)`` / ``cos(theta_inc)`` geometry. Enforcing a
       shared dB scale and floor removes the gross convention mismatch (linear
       vs dB) but does not equalise the sigma0-vs-gamma0 definition itself;
       that residual is tracked and discussed in ``docs/radiometry.md``.

    Parameters
    ----------
    sigma0_db:
        Sentinel-1 backscatter already expressed in dB.
    floor_db:
        Physical dB floor. Defaults to :data:`DB_FLOOR`.

    Returns
    -------
    numpy.ndarray
        ``float64`` dB array with the floor applied; ``nan`` preserved.
    """
    values = np.asarray(sigma0_db, dtype=np.float64)
    nan_mask = np.isnan(values)
    clamped = np.maximum(values, floor_db)
    clamped[nan_mask] = np.nan
    return clamped
