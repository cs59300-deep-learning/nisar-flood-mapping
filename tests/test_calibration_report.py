import json

import pytest

pd = pytest.importorskip("pandas")

from nisar_flood.groundtruth.calibration_report import (
    END,
    START,
    make_figures,
    render_results,
)


def write_run(d, at_edge=False, with_check=True):
    row = {"date": "2026-09-20", "stage_m": 20.78, "water_height_m": 8.5, "tp": 1, "fp": 1, "fn": 1, "tn": 1,
           "n_valid": 4, "iou": 0.81, "precision": 0.9, "recall": 0.88, "f1": 0.89}
    report = {
        "created_utc": "2026-10-14T20:00:00+00:00", "model": "m", "stage0_m": 12.28, "stage0_range_m": [12.1, 12.5],
        "mean_iou": 0.81, "plateau_reaches_search_edge": at_edge, "gauge_unit_to_m": 0.01,
        "fit_decimation_factor": 4, "hand": "/content/flood_tiffs/hand_aoi.tif",
        "calibration_dates": [row],
        "out_of_sample_checks": [{**row, "date": "2026-09-28", "iou": 0.7}] if with_check else [],
        "masks_written": [],
    }
    (d / "stage_calibration_report.json").write_text(json.dumps(report))
    pd.DataFrame({"stage0_m": [11.0, 12.0, 13.0], "iou_2026-09-20": [0.5, 0.81, 0.6], "mean_iou": [0.5, 0.81, 0.6]}
                 ).to_csv(d / "stage0_calibration_curve.csv", index=False)
    pd.DataFrame({
        "granule_id": ["g1", "g2"], "acquisition_date": ["2026-06-18", "2026-09-22"], "stage_m": [28.4, 20.3],
        "water_height_m": [16.1, 8.0], "wet_pixels": [5, 3], "valid_pixels": [10, 10], "wet_fraction": [0.5, 0.3],
        "status": ["ok", "ok"],
    }).to_csv(d / "hand_inundation_by_date.csv", index=False)


def test_results_are_written_between_markers_and_replaced_not_duplicated(tmp_path):
    write_run(tmp_path)
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\nbody\n")
    render_results(tmp_path, doc, "OPERA DSWx-S1 test reference")
    first = doc.read_text()
    assert first.startswith("# Title") and START in first and END in first
    assert "**12.28 m**" in first and "12.10 to 12.50 m" in first
    assert "OPERA DSWx-S1 test reference" in first and "held-out dates" in first

    render_results(tmp_path, doc, "OPERA DSWx-S1 test reference")
    assert doc.read_text() == first  # idempotent: re-running does not stack a second section
    assert doc.read_text().count(START) == 1


def test_edge_plateau_is_flagged_loudly_and_missing_check_is_stated(tmp_path):
    write_run(tmp_path, at_edge=True, with_check=False)
    doc = tmp_path / "doc.md"
    section = render_results(tmp_path, doc)
    assert "Do not use the value below" in section
    assert "No held-out date was scored" in section


def test_reference_summary_and_unmapped_codes_appear(tmp_path):
    write_run(tmp_path)
    summary = {"2026-09-20": {"n_tiles": 3, "known_fraction": 0.4, "water_fraction_of_known": 0.2,
                              "unmapped_codes": {2: 99}}}
    section = render_results(tmp_path, tmp_path / "doc.md", reference_summary=summary)
    assert "Reference coverage" in section and "40.0" in section
    assert "2026-09-20: code 2 (99 px)" in section and "never as water" in section


def test_figures_are_created(tmp_path):
    write_run(tmp_path)
    paths = make_figures(tmp_path)
    assert {p.name for p in paths} == {"stage0_calibration_curve.png", "hand_inundation_by_date.png"}
    assert all(p.stat().st_size > 1000 for p in paths)
