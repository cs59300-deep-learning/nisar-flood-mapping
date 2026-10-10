import numpy as np
import pandas as pd
import pytest

from nisar_flood.groundtruth.stage_calibration import (
    ReferenceScene,
    _iou_vs_height,
    agreement_metrics,
    calibrate_stage0,
    inundation_mask,
    predict_inundation_by_date,
    stage_to_metres,
    water_height,
)


def ramp_hand(rows=20, cols=100, slope_m_per_col=0.5):
    """Terrain that rises 0.5 m per column: HAND = 0 at column 0, 49.5 m at column 99."""
    return np.tile(np.arange(cols, dtype="float32") * slope_m_per_col, (rows, 1))


TRUE_STAGE0 = 12.0


def scene_for(hand, date, stage_m, stage0=TRUE_STAGE0, offset_m=0.0):
    """A perfect reference for ``stage0``; ``offset_m`` shifts the water surface to mimic drift."""
    wet, _ = inundation_mask(hand, stage_m - stage0 + offset_m)
    return ReferenceScene(date=date, stage_m=stage_m, reference=wet)


# --- units and basic maths -------------------------------------------------


def test_gauge_centimetres_become_metres():
    assert stage_to_metres(2850.0) == pytest.approx(28.5)
    assert water_height(28.5, 12.0) == pytest.approx(16.5)


def test_inundation_boundary_is_inclusive_and_negative_height_floods_nothing():
    hand = np.array([[0.0, 1.0, 2.0, np.nan]])
    wet, valid = inundation_mask(hand, 1.0)
    assert wet.tolist() == [[True, True, False, False]]
    assert valid.tolist() == [[True, True, True, False]]

    wet, _ = inundation_mask(hand, 0.0)
    assert wet.tolist() == [[True, False, False, False]]  # HAND == 0 is wet at h = 0

    wet, _ = inundation_mask(hand, -0.1)
    assert not wet.any()


def test_agreement_metrics_known_case():
    pred = np.array([[1, 1, 0, 0]], dtype=bool)
    ref = np.array([[1, 0, 1, 0]], dtype=bool)
    m = agreement_metrics(pred, ref)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["iou"] == pytest.approx(1 / 3)
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["f1"] == pytest.approx(0.5)


def test_agreement_metrics_ignores_invalid_and_returns_nan_not_zero():
    pred = np.array([[1, 0]], dtype=bool)
    ref = np.array([[0, 0]], dtype=bool)
    valid = np.array([[False, True]])
    m = agreement_metrics(pred, ref, valid)
    assert m["n_valid"] == 1
    assert np.isnan(m["iou"])  # no water in either mask over valid pixels


# --- the fast IoU curve must equal the obvious per-mask computation --------


def test_vectorised_iou_matches_brute_force():
    rng = np.random.default_rng(0)
    hand = rng.uniform(0, 30, size=(40, 40)).astype("float32")
    hand[:5, :5] = np.nan
    hand[10, 10] = 5.0  # exact threshold value, to exercise the <= boundary
    reference = rng.random((40, 40)) < 0.3
    valid = rng.random((40, 40)) < 0.9

    heights = np.array([-5.0, -0.01, 0.0, 5.0, 12.34, 29.9, 100.0])
    fast = _iou_vs_height(hand, reference, valid, heights)

    for t, got in zip(heights, fast):
        wet, hand_valid = inundation_mask(hand, t)
        want = agreement_metrics(wet, reference, valid & hand_valid)["iou"]
        if np.isnan(want):
            assert np.isnan(got)
        else:
            assert got == pytest.approx(want)


# --- calibration -----------------------------------------------------------


def test_single_date_recovers_known_stage0():
    hand = ramp_hand()
    result = calibrate_stage0(hand, [scene_for(hand, "2026-09-22", 20.35)])
    assert result.mean_iou == pytest.approx(1.0)
    lo, hi = result.stage0_range_m
    # Terrain steps 0.5 m per column, so stage0 is only identifiable to that spacing: every value in
    # (11.85, 12.35] gives the same extent. The truth must sit inside the reported plateau.
    assert lo <= TRUE_STAGE0 <= hi
    assert hi - lo < 0.6
    assert abs(result.stage0_m - TRUE_STAGE0) <= 0.5
    assert not result.at_edge


def test_two_consistent_dates_agree_on_stage0():
    hand = ramp_hand()
    scenes = [scene_for(hand, "2026-06-18", 28.0), scene_for(hand, "2026-09-22", 20.0)]
    result = calibrate_stage0(hand, scenes)
    assert result.mean_iou == pytest.approx(1.0)
    assert abs(result.stage0_m - TRUE_STAGE0) <= 0.5
    assert set(result.per_date["date"]) == {"2026-06-18", "2026-09-22"}
    assert result.per_date["iou"].tolist() == pytest.approx([1.0, 1.0])


def test_drifting_reference_gives_a_compromise_and_lower_iou():
    """If the real water surface drifts off the flat model on one date, no single stage0 fits both."""
    hand = ramp_hand()
    a = scene_for(hand, "A", 28.0)
    b = scene_for(hand, "B", 20.0, offset_m=3.0)  # reference water stands 3 m higher than modelled
    both = calibrate_stage0(hand, [a, b])
    only_a = calibrate_stage0(hand, [a])
    only_b = calibrate_stage0(hand, [b])

    assert both.mean_iou < 1.0
    assert min(only_a.stage0_m, only_b.stage0_m) <= both.stage0_m <= max(only_a.stage0_m, only_b.stage0_m)
    assert both.per_date["iou"].min() < 1.0


def test_unconstraining_reference_is_flagged_not_silently_accepted():
    """A reference that is wet everywhere cannot pin stage0 down: every stage0 that floods the
    whole area scores IoU 1. The result must say so rather than return a confident-looking value."""
    hand = ramp_hand()
    wet_everywhere = ReferenceScene("X", 30.0, np.ones(hand.shape, dtype=bool))
    result = calibrate_stage0(hand, [wet_everywhere])
    assert result.mean_iou == pytest.approx(1.0)
    assert result.at_edge  # the plateau runs off the end of the search range
    lo, _ = result.stage0_range_m
    assert lo == pytest.approx(30.0 - 49.5 - 1.0)  # starts at the lower bound of the search grid


def test_edge_optimum_is_flagged():
    hand = ramp_hand()
    scene = scene_for(hand, "2026-09-22", 20.0)
    result = calibrate_stage0(hand, [scene], candidates_m=np.arange(13.0, 16.0, 0.1))
    assert result.at_edge  # the true stage0 (12.0) is outside the search range


def test_hand_nodata_never_counts_for_or_against():
    hand = ramp_hand()
    clean = calibrate_stage0(hand, [scene_for(hand, "d", 20.0)])

    holed = hand.copy()
    holed[:, 0:5] = np.nan  # no terrain value over the wettest columns
    scene = scene_for(hand, "d", 20.0)  # reference still says those columns are wet
    result = calibrate_stage0(holed, [scene])
    assert result.mean_iou == pytest.approx(1.0)
    assert abs(result.stage0_m - clean.stage0_m) <= 0.5


def test_bad_inputs_raise():
    hand = ramp_hand()
    with pytest.raises(ValueError, match="at least one"):
        calibrate_stage0(hand, [])
    with pytest.raises(ValueError, match="same grid|resample"):
        calibrate_stage0(hand, [ReferenceScene("d", 20.0, np.ones((3, 3), dtype=bool))])
    with pytest.raises(ValueError, match="no water"):
        calibrate_stage0(hand, [ReferenceScene("d", 20.0, np.zeros(hand.shape, dtype=bool))])


# --- per-date prediction ---------------------------------------------------


def _matched(stages_cm):
    return pd.DataFrame(
        {
            "granule_id": [f"g{i}" for i in range(len(stages_cm))],
            "acquisition_date": pd.date_range("2026-06-18", periods=len(stages_cm), freq="12D"),
            "mean_stage": stages_cm,
        }
    )


def test_per_date_masks_grow_with_stage_and_use_metres():
    hand = ramp_hand()
    masks, summary = predict_inundation_by_date(hand, _matched([2000.0, 2400.0, 2850.0]), stage0_m=12.0)

    assert summary["water_height_m"].tolist() == pytest.approx([8.0, 12.0, 16.5])
    assert (summary["status"] == "ok").all()
    # higher river -> strictly more water, and every lower extent sits inside the higher one
    assert masks["g0"].sum() < masks["g1"].sum() < masks["g2"].sum()
    assert not (masks["g0"] & ~masks["g1"]).any()
    assert not (masks["g1"] & ~masks["g2"]).any()


def test_missing_gauge_gets_no_mask_and_below_hand0_is_flagged():
    hand = ramp_hand()
    matched = _matched([1000.0, np.nan])  # 10 m is below stage0 = 12 m
    masks, summary = predict_inundation_by_date(hand, matched, stage0_m=12.0)

    assert summary.loc[0, "status"] == "below_hand0"
    assert masks["g0"].sum() == 0
    assert summary.loc[1, "status"] == "no_gauge"
    assert "g1" not in masks


# --- raster I/O ------------------------------------------------------------


def _write_tif(path, array, nodata=None, res=90.0):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
        dtype=str(array.dtype), crs="EPSG:32720", transform=from_origin(500000, 9700000, res, res),
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)


def test_write_inundation_masks_roundtrip(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    from nisar_flood.groundtruth.stage_calibration import write_inundation_masks

    hand = ramp_hand(rows=4, cols=30)  # HAND = 0.5 * column
    hand[0, 0] = np.nan
    masks, summary = predict_inundation_by_date(hand, _matched([2000.0]), stage0_m=12.0)
    grid = {"crs": "EPSG:32720", "transform": from_origin(500000, 9700000, 90.0, 90.0)}

    paths = write_inundation_masks(masks, summary, hand, grid, tmp_path)
    assert [p.name for p in paths] == ["hand_inundation_2026-06-18.tif"]
    with rasterio.open(paths[0]) as src:
        data = src.read(1)
    assert data[0, 0] == 255  # no HAND value -> nodata, never "dry"
    # stage 20 m, stage0 12 m -> h = 8 m: column 0 (HAND 0 m) wet, column 29 (HAND 14.5 m) dry
    assert data[1, 0] == 1 and data[1, 16] == 1 and data[1, 17] == 0 and data[1, 29] == 0
