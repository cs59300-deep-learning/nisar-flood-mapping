from __future__ import annotations

import pandas as pd
import matplotlib.pyplot as plt


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
