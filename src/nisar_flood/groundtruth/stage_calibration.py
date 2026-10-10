from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ANA "Nivel" is reported in centimetres; HAND is in metres.
GAUGE_CM_TO_M = 0.01


def match_nisar_dates_to_stage(
    gauge: pd.DataFrame,
    nisar: pd.DataFrame,
) -> pd.DataFrame:
    """Match NISAR acquisition dates with daily Manaus river stage.

    Parameters
    ----------
    gauge:
        Daily gauge dataframe containing:
        - datetime
        - mean_stage

    nisar:
        NISAR granule manifest containing:
        - granule_id
        - acquisition_date

    Returns
    -------
    pd.DataFrame
        NISAR manifest rows with the matching daily mean river stage
        added as ``mean_stage``.
    """

    gauge = gauge.copy()
    nisar = nisar.copy()

    # Validate required columns
    required_gauge = {"datetime", "mean_stage"}
    required_nisar = {"granule_id", "acquisition_date"}

    missing_gauge = required_gauge - set(gauge.columns)
    missing_nisar = required_nisar - set(nisar.columns)

    if missing_gauge:
        raise ValueError(
            f"Gauge data is missing required columns: {sorted(missing_gauge)}"
        )

    if missing_nisar:
        raise ValueError(
            f"NISAR manifest is missing required columns: {sorted(missing_nisar)}"
        )

    # Convert dates to pandas datetime
    gauge["datetime"] = pd.to_datetime(
        gauge["datetime"],
        errors="coerce",
    )

    nisar["acquisition_date"] = pd.to_datetime(
        nisar["acquisition_date"],
        errors="coerce",
    )

    # Normalize both to calendar dates
    gauge["date"] = gauge["datetime"].dt.normalize()
    nisar["acquisition_date"] = nisar["acquisition_date"].dt.normalize()

    # Match each NISAR acquisition date to the gauge daily mean
    matched = nisar.merge(
        gauge[["date", "mean_stage"]],
        left_on="acquisition_date",
        right_on="date",
        how="left",
    )

    matched = matched.drop(columns=["date"])

    return matched


def plot_stage_vs_nisar_dates(
    gauge: pd.DataFrame,
    nisar: pd.DataFrame,
    output_path: str,
) -> None:
    """Plot Manaus daily river stage and NISAR acquisition dates."""

    gauge = gauge.copy()
    gauge["datetime"] = pd.to_datetime(
        gauge["datetime"],
        errors="coerce",
    )

    matched = match_nisar_dates_to_stage(
        gauge,
        nisar,
    )

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(
        gauge["datetime"],
        gauge["mean_stage"],
        label="Manaus daily mean river stage",
    )

    for _, row in matched.iterrows():
        acquisition_date = row["acquisition_date"]

        ax.axvline(
            acquisition_date,
            linestyle="--",
            alpha=0.7,
        )

        ax.text(
            acquisition_date,
            ax.get_ylim()[1],
            acquisition_date.strftime("%Y-%m-%d"),
            rotation=90,
            verticalalignment="top",
            horizontalalignment="right",
            fontsize=8,
        )

    ax.set_title(
        "Manaus River Stage and NISAR Acquisition Dates"
    )
    ax.set_xlabel("Date")
    ax.set_ylabel("River stage (ANA Nivel)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


# ---------------------------------------------------------------------------
# HAND stage calibration (#14)
#
# Model:  h(date) = stage(date) - stage0,   wet(date) = {HAND <= h(date)}
#
# ``stage0`` is the gauge reading (metres) at which the floodplain waterline sits at HAND = 0.
# It is fixed once, by matching the HAND extent to an independent reference on one or two dates,
# then reused for every granule date. Flat-water-surface limitation: see docs/stage_calibration.md.
# ---------------------------------------------------------------------------


def inundation_mask(hand: np.ndarray, water_height_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Flood extent for a water surface ``water_height_m`` above the HAND = 0 level.

    Returns ``(wet, valid)``. ``wet`` is True where ``HAND <= water_height_m``. Pixels with no HAND
    value (NaN) are False in both masks, so callers must exclude them via ``valid`` rather than
    treat them as dry. A negative height (water below the HAND = 0 level) floods nothing.
    """
    hand = np.asarray(hand)
    valid = np.isfinite(hand)
    wet = np.zeros(hand.shape, dtype=bool)
    if water_height_m >= 0:
        wet[valid] = hand[valid] <= water_height_m
    return wet, valid


def stage_to_metres(stage, unit_to_m: float = GAUGE_CM_TO_M):
    """Convert gauge readings (ANA ``Nivel``, centimetres) to metres."""
    return np.asarray(stage, dtype=float) * unit_to_m


def water_height(stage_m, stage0_m: float):
    """Water-surface height above the HAND = 0 level: ``h = stage - stage0`` (metres)."""
    return np.asarray(stage_m, dtype=float) - stage0_m


def _div(num: float, den: float) -> float:
    return float(num) / float(den) if den else float("nan")


def agreement_metrics(pred, ref, valid=None) -> dict:
    """Pixel agreement between a predicted and a reference water mask (water = True).

    Pixels outside ``valid`` are ignored. Ratios that cannot be computed are NaN, never 0.
    """
    pred = np.asarray(pred, dtype=bool)
    ref = np.asarray(ref, dtype=bool)
    if pred.shape != ref.shape:
        raise ValueError(f"pred {pred.shape} and ref {ref.shape} must have the same shape")
    if valid is None:
        valid = np.ones(pred.shape, dtype=bool)
    p, r = pred[valid], ref[valid]
    tp = int(np.sum(p & r))
    fp = int(np.sum(p & ~r))
    fn = int(np.sum(~p & r))
    tn = int(np.sum(~p & ~r))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "n_valid": tp + fp + fn + tn,
        "iou": _div(tp, tp + fp + fn),
        "precision": _div(tp, tp + fp),
        "recall": _div(tp, tp + fn),
        "f1": _div(2 * tp, 2 * tp + fp + fn),
    }


@dataclass
class ReferenceScene:
    """An independent flood-extent reference on one date, used to calibrate ``stage0``."""

    date: str
    stage_m: float  # gauge reading on ``date``, in metres
    reference: np.ndarray  # bool, True = water, on the same grid as HAND
    valid: np.ndarray | None = None  # bool, False where the reference has no information


@dataclass
class CalibrationResult:
    stage0_m: float
    mean_iou: float
    stage0_range_m: tuple[float, float]  # contiguous span within ``plateau_tol`` of the best IoU
    # True if the near-optimal span reaches the edge of the search range: either the range is too
    # narrow (widen it) or the reference cannot bound stage0 (e.g. it is wet everywhere).
    at_edge: bool
    per_date: pd.DataFrame  # metrics for each calibration scene at ``stage0_m``
    curve: pd.DataFrame = field(repr=False)  # IoU for every candidate ``stage0``


def _iou_vs_height(hand, reference, valid, heights) -> np.ndarray:
    """IoU of ``{HAND <= t}`` against ``reference`` for every ``t`` in ``heights``.

    Exact and vectorised: sort the HAND values once, then count how many fall at or below each
    threshold, instead of building one mask per candidate. Negative heights flood nothing, which
    matches ``hand.inundation_mask``.
    """
    ok = np.isfinite(hand) & valid
    values = hand[ok]
    ref = reference[ok]
    all_sorted = np.sort(values)
    ref_sorted = np.sort(values[ref])
    n_ref = ref_sorted.size

    predicted = np.searchsorted(all_sorted, heights, side="right")
    hit = np.searchsorted(ref_sorted, heights, side="right")
    below = heights < 0
    predicted = np.where(below, 0, predicted)
    hit = np.where(below, 0, hit)

    union = predicted + n_ref - hit
    return np.where(union > 0, hit / np.maximum(union, 1), np.nan)


def calibrate_stage0(
    hand: np.ndarray,
    scenes: Sequence[ReferenceScene],
    candidates_m: np.ndarray | None = None,
    step_m: float = 0.05,
    plateau_tol: float = 0.005,
) -> CalibrationResult:
    """Find the ``stage0`` that makes the HAND extent best match the reference scene(s).

    Maximises the mean IoU (unweighted across scenes) of ``{HAND <= stage - stage0}`` against each
    reference. With a single scene this is the one-date calibration; with two it is a compromise
    and the per-date table shows how well each is honoured.

    Parameters
    ----------
    hand:
        2-D HAND array in metres, NaN = no data.
    scenes:
        One or two (or more) ``ReferenceScene`` on the same grid as ``hand``.
    candidates_m:
        ``stage0`` values to try, in metres. Default: a grid of ``step_m`` spanning every value that
        could matter, from ``min(stage) - max(HAND)`` to ``max(stage)``.
    plateau_tol:
        IoU slack used to report ``stage0_range_m``, the span of near-optimal values. A wide range
        means the reference barely constrains ``stage0``; quote it as the calibration uncertainty.
    """
    scenes = list(scenes)
    if not scenes:
        raise ValueError("calibrate_stage0 needs at least one ReferenceScene")
    hand = np.asarray(hand, dtype=float)
    if not np.isfinite(hand).any():
        raise ValueError("HAND has no valid pixels")

    prepared = []
    for scene in scenes:
        ref = np.asarray(scene.reference, dtype=bool)
        if ref.shape != hand.shape:
            raise ValueError(
                f"reference for {scene.date} is {ref.shape}, HAND is {hand.shape}: "
                "resample both onto one grid first"
            )
        valid = np.ones(hand.shape, dtype=bool) if scene.valid is None else np.asarray(scene.valid, bool)
        if valid.shape != hand.shape:
            raise ValueError(f"valid mask for {scene.date} does not match HAND")
        if not (ref & valid & np.isfinite(hand)).any():
            raise ValueError(f"reference for {scene.date} has no water over valid HAND pixels")
        prepared.append((scene, ref, valid))

    stages = np.array([s.stage_m for s in scenes], dtype=float)
    if candidates_m is None:
        # One metre of margin each side so saturation (everything wet / nothing wet) shows up as a
        # plateau that reaches the edge, instead of being cut off exactly at the last useful value.
        lo = float(stages.min() - np.nanmax(hand) - 1.0)
        hi = float(stages.max() + 1.0)
        candidates_m = np.round(np.arange(lo, hi + step_m, step_m), 6)
    candidates_m = np.asarray(candidates_m, dtype=float)

    curve = pd.DataFrame({"stage0_m": candidates_m})
    for scene, ref, valid in prepared:
        curve[f"iou_{scene.date}"] = _iou_vs_height(hand, ref, valid, scene.stage_m - candidates_m)
    iou_cols = [f"iou_{s.date}" for s in scenes]
    curve["mean_iou"] = curve[iou_cols].mean(axis=1, skipna=False)

    mean = curve["mean_iou"].to_numpy()
    if np.isnan(mean).all():
        raise ValueError("IoU is undefined for every candidate: the references contain no water")
    best_value = np.nanmax(mean)
    ties = np.flatnonzero(np.isclose(mean, best_value, rtol=0.0, atol=1e-12))
    best = int(ties[len(ties) // 2])  # centre of an exact plateau, not its lowest edge

    lo_i = hi_i = best
    floor = best_value - plateau_tol
    while lo_i > 0 and mean[lo_i - 1] >= floor:
        lo_i -= 1
    while hi_i < len(mean) - 1 and mean[hi_i + 1] >= floor:
        hi_i += 1

    stage0 = float(candidates_m[best])
    rows = []
    for scene, ref, valid in prepared:
        wet, hand_valid = inundation_mask(hand, scene.stage_m - stage0)
        metrics = agreement_metrics(wet, ref, valid & hand_valid)
        rows.append({"date": scene.date, "stage_m": scene.stage_m, "water_height_m": scene.stage_m - stage0, **metrics})

    return CalibrationResult(
        stage0_m=stage0,
        mean_iou=float(best_value),
        stage0_range_m=(float(candidates_m[lo_i]), float(candidates_m[hi_i])),
        at_edge=lo_i == 0 or hi_i == len(mean) - 1,
        per_date=pd.DataFrame(rows),
        curve=curve,
    )


def predict_inundation_by_date(
    hand: np.ndarray,
    matched: pd.DataFrame,
    stage0_m: float,
    stage_col: str = "mean_stage",
    unit_to_m: float = GAUGE_CM_TO_M,
) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    """Per-date inundation masks from the calibrated ``stage0``.

    ``matched`` is the output of ``match_nisar_dates_to_stage`` (manifest rows plus ``mean_stage``,
    in gauge units). Returns ``(masks, summary)``: ``masks`` maps ``granule_id`` to a boolean wet
    mask; ``summary`` has one row per granule. A granule with no gauge value gets no mask and
    ``status == "no_gauge"`` rather than a guessed one.
    """
    masks: dict[str, np.ndarray] = {}
    rows = []
    for _, row in matched.iterrows():
        stage_m = float(stage_to_metres(row[stage_col], unit_to_m)) if pd.notna(row[stage_col]) else np.nan
        entry = {
            "granule_id": row["granule_id"],
            "acquisition_date": pd.Timestamp(row["acquisition_date"]).date().isoformat(),
            "stage_m": stage_m,
            "water_height_m": np.nan,
            "wet_pixels": np.nan,
            "valid_pixels": np.nan,
            "wet_fraction": np.nan,
            "status": "no_gauge",
        }
        if np.isfinite(stage_m):
            h = stage_m - stage0_m
            wet, valid = inundation_mask(hand, h)
            masks[row["granule_id"]] = wet
            n_wet, n_valid = int(wet.sum()), int(valid.sum())
            entry.update(
                water_height_m=h,
                wet_pixels=n_wet,
                valid_pixels=n_valid,
                wet_fraction=_div(n_wet, n_valid),
                status="below_hand0" if h < 0 else "ok",
            )
        rows.append(entry)
    return masks, pd.DataFrame(rows)


def write_inundation_masks(
    masks: dict[str, np.ndarray],
    summary: pd.DataFrame,
    hand: np.ndarray,
    grid: dict,
    out_dir,
) -> list:
    """Write one GeoTIFF per date: 1 = wet, 0 = dry, 255 = no HAND value. Returns the paths."""
    from pathlib import Path

    import rasterio

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    nodata_pixels = ~np.isfinite(hand)
    written = []
    for _, row in summary.iterrows():
        if row["granule_id"] not in masks:
            continue
        data = masks[row["granule_id"]].astype("uint8")
        data[nodata_pixels] = 255
        path = out_dir / f"hand_inundation_{row['acquisition_date']}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype="uint8",
            crs=grid["crs"],
            transform=grid["transform"],
            nodata=255,
            compress="deflate",
        ) as dst:
            dst.write(data, 1)
        written.append(path)
    return written
