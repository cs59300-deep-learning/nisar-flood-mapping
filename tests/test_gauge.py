import pandas as pd

from nisar_flood.groundtruth.gauge import daily_mean_stage
from nisar_flood.groundtruth.stage_calibration import (
    match_nisar_dates_to_stage,
)


def test_daily_mean_stage():
    observations = pd.DataFrame(
        {
            "datetime": [
                "2026-06-01 00:00:00",
                "2026-06-01 01:00:00",
                "2026-06-01 02:00:00",
                "2026-06-02 00:00:00",
            ],
            "stage": [
                100.0,
                200.0,
                300.0,
                400.0,
            ],
        }
    )

    result = daily_mean_stage(observations)

    assert len(result) == 2
    assert result.iloc[0]["mean_stage"] == 200.0
    assert result.iloc[1]["mean_stage"] == 400.0


def test_nan_values_are_not_filled():
    observations = pd.DataFrame(
        {
            "datetime": [
                "2026-06-01 00:00:00",
                "2026-06-01 01:00:00",
            ],
            "stage": [
                float("nan"),
                float("nan"),
            ],
        }
    )

    result = daily_mean_stage(observations)

    assert pd.isna(result.iloc[0]["mean_stage"])


def test_nisar_manifest_dates_match_daily_stage():
    """Test matching using the actual NISAR manifest column structure."""

    gauge = pd.DataFrame(
        {
            "datetime": [
                "2026-06-18",
                "2026-06-30",
                "2026-07-12",
                "2026-07-24",
                "2026-08-17",
                "2026-08-29",
                "2026-09-10",
                "2026-09-22",
            ],
            "mean_stage": [
                2800.0,
                2750.0,
                2700.0,
                2650.0,
                2500.0,
                2400.0,
                2200.0,
                2000.0,
            ],
        }
    )

    nisar = pd.DataFrame(
        {
            "granule_id": [
                "NISAR_20260618",
                "NISAR_20260630",
                "NISAR_20260712",
                "NISAR_20260724",
                "NISAR_20260817",
                "NISAR_20260829",
                "NISAR_20260910",
                "NISAR_20260922",
            ],
            "acquisition_date": [
                "2026-06-18",
                "2026-06-30",
                "2026-07-12",
                "2026-07-24",
                "2026-08-17",
                "2026-08-29",
                "2026-09-10",
                "2026-09-22",
            ],
            "frame": ["path68_frame90"] * 8,
            "orbit_pass": ["Descending"] * 8,
            "product_version": ["PROVISIONAL (CRID P05023)"] * 8,
            "polarisations": [
                "HH+HV",
                "HH",
                "HH+HV",
                "HH",
                "HH",
                "HH+HV",
                "HH",
                "HH+HV",
            ],
            "water_regime": [
                "high",
                "high",
                "high",
                "falling",
                "falling",
                "falling",
                "low",
                "low",
            ],
        }
    )

    result = match_nisar_dates_to_stage(
        gauge,
        nisar,
    )

    assert len(result) == 8

    assert "granule_id" in result.columns
    assert "acquisition_date" in result.columns
    assert "water_regime" in result.columns
    assert "mean_stage" in result.columns

    assert result["mean_stage"].notna().all()

    assert result.iloc[0]["mean_stage"] == 2800.0
    assert result.iloc[7]["mean_stage"] == 2000.0


def test_unmatched_nisar_date_remains_nan():
    """An acquisition date without gauge data should remain NaN."""

    gauge = pd.DataFrame(
        {
            "datetime": ["2026-06-18"],
            "mean_stage": [2800.0],
        }
    )

    nisar = pd.DataFrame(
        {
            "granule_id": ["NISAR_TEST"],
            "acquisition_date": ["2026-07-01"],
        }
    )

    result = match_nisar_dates_to_stage(
        gauge,
        nisar,
    )

    assert len(result) == 1
    assert pd.isna(result.iloc[0]["mean_stage"])
