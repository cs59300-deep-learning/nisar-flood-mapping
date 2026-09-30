import pandas as pd

from nisar_flood.groundtruth.gauge import daily_mean_stage


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