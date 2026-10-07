from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests


ANA_URL = (
    "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/"
    "DadosHidrometeorologicos"
)


def fetch_gauge_data(
    station_code: str,
    start_date: str,
    end_date: str,
    timeout: int = 120,
    retries: int = 3,
) -> pd.DataFrame:
    """Fetch hydrometeorological observations from the ANA API.

    Parameters
    ----------
    station_code:
        ANA station code.
    start_date:
        Start date in DD/MM/YYYY format.
    end_date:
        End date in DD/MM/YYYY format.
    timeout:
        HTTP request timeout in seconds.
    retries:
        Number of attempts if the ANA server returns an error.

    Returns
    -------
    pandas.DataFrame
        DataFrame containing datetime and river stage observations.
    """

    params = {
        "codEstacao": station_code,
        "dataInicio": start_date,
        "dataFim": end_date,
    }

    last_error = None

    for attempt in range(retries):
        try:
            response = requests.get(
                ANA_URL,
                params=params,
                timeout=timeout,
            )

            if response.status_code == 200:
                break

            last_error = f"ANA returned HTTP {response.status_code}"

        except requests.RequestException as exc:
            last_error = str(exc)

        if attempt < retries - 1:
            time.sleep(3)
    else:
        raise RuntimeError(
            f"Unable to retrieve ANA gauge data after "
            f"{retries} attempts: {last_error}"
        )

    response.raise_for_status()

    root = ET.fromstring(response.content)

    rows = [
        element
        for element in root.iter()
        if element.tag.endswith("DadosHidrometereologicos")
    ]

    records = []

    for row in rows:
        timestamp = row.findtext("DataHora")
        level = row.findtext("Nivel")

        records.append(
            {
                "datetime": timestamp.strip() if timestamp else None,
                "stage": level,
            }
        )

    df = pd.DataFrame(records)

    if df.empty:
        return pd.DataFrame(columns=["datetime", "stage"])

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        errors="coerce",
    )

    df["stage"] = pd.to_numeric(
        df["stage"],
        errors="coerce",
    )

    df = df.dropna(subset=["datetime"])

    df = df.sort_values(
        "datetime"
    ).reset_index(drop=True)

    return df


def daily_mean_stage(
    observations: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate daily mean river stage.

    Missing stage values are preserved.
    No filling or interpolation is performed.
    If all observations for a day are NaN,
    that day's mean remains NaN.
    """

    df = observations.copy()

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        errors="coerce",
    )

    df["stage"] = pd.to_numeric(
        df["stage"],
        errors="coerce",
    )

    df = df.dropna(
        subset=["datetime"]
    )

    daily = (
        df.set_index("datetime")["stage"]
        .resample("D")
        .mean()
        .rename("mean_stage")
        .reset_index()
    )

    return daily


def fetch_daily_stage(
    station_code: str = "14990000",
    start_date: str = "01/06/2026",
    end_date: str = "30/09/2026",
) -> pd.DataFrame:
    """Fetch ANA observations and return daily mean stage."""

    observations = fetch_gauge_data(
        station_code=station_code,
        start_date=start_date,
        end_date=end_date,
    )

    return daily_mean_stage(observations)