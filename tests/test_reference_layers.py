import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin

from nisar_flood.groundtruth.reference_layers import (
    NOT_WATER,
    UNKNOWN,
    WATER,
    mosaic_tiles_to_grid,
    recode,
)


def write_tif(path, array, crs, transform, nodata=None):
    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
        dtype=str(array.dtype), crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(array, 1)


# --- recode -------------------------------------------------------------------


def test_recode_maps_listed_codes_and_flags_the_rest_as_unknown():
    codes = np.array([[0, 1, 2, 252, 253, 255]], dtype="uint8")
    out, unmapped = recode(codes, water_codes=(1,), not_water_codes=(0,), unknown_codes=(253, 255))
    assert out.tolist() == [[NOT_WATER, WATER, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN]]
    # 2 and 252 were not listed: reported, and never read as water
    assert unmapped == {2: 1, 252: 1}


def test_recode_never_reads_an_unlisted_code_as_water():
    out, unmapped = recode(np.full((3, 3), 2, dtype="uint8"))
    assert (out == UNKNOWN).all() and unmapped == {2: 9}


def test_recode_rejects_a_code_with_two_meanings():
    with pytest.raises(ValueError, match="more than one meaning"):
        recode(np.zeros((2, 2), dtype="uint8"), water_codes=(1,), not_water_codes=(1,))


# --- mosaic -------------------------------------------------------------------


@pytest.fixture
def grid(tmp_path):
    """HAND-like grid: EPSG:32720, 20 m, 100 x 100 px."""
    path = tmp_path / "hand.tif"
    write_tif(path, np.zeros((100, 100), dtype="float32"), "EPSG:32720",
              from_origin(600000, 9700000, 20, 20), nodata=float("nan"))
    return path


def test_mosaic_two_overlapping_tiles_keeps_known_pixels(tmp_path, grid):
    # Tile A (all water) covers grid columns 0-74 (50 px x 30 m = 1500 m = 75 columns of 20 m).
    # Tile B (all dry) starts at column 60, but its first 10 pixels (columns 60-74) are unknown (255),
    # so inside A the overlap must stay water, and B's own known pixels begin at column 75.
    a = np.full((50, 50), 1, dtype="uint8")
    b = np.full((50, 50), 0, dtype="uint8")
    b[:, :10] = 255
    write_tif(tmp_path / "a.tif", a, "EPSG:32720", from_origin(600000, 9700000, 30, 30), nodata=255)
    write_tif(tmp_path / "b.tif", b, "EPSG:32720", from_origin(600000 + 1200, 9700000, 30, 30), nodata=255)

    s = mosaic_tiles_to_grid([tmp_path / "a.tif", tmp_path / "b.tif"], grid, tmp_path / "out.tif")
    with rasterio.open(tmp_path / "out.tif") as src:
        out = src.read(1)
        assert src.nodata == 255 and src.dtypes[0] == "uint8"
        assert src.crs == rasterio.open(grid).crs and src.transform == rasterio.open(grid).transform
    assert out[10, 5] == WATER  # inside A only
    assert out[10, 62] == WATER and out[10, 70] == WATER  # A/B overlap where B is unknown -> A is kept
    assert out[10, 85] == NOT_WATER  # inside B only (B's known part)
    assert out[90, 90] == UNKNOWN  # outside every tile
    assert s["n_tiles"] == 2 and 0 < s["known_fraction"] < 1


def test_mosaic_reprojects_a_tile_from_another_utm_zone(tmp_path, grid):
    import pyproj

    # Build a small all-water tile in zone 21 (EPSG:32721) that covers the middle of the zone-20 grid.
    to21 = pyproj.Transformer.from_crs("EPSG:32720", "EPSG:32721", always_xy=True)
    x0, y0 = to21.transform(600000 + 500, 9700000 - 500)
    tile = np.full((40, 40), 1, dtype="uint8")
    write_tif(tmp_path / "z21.tif", tile, "EPSG:32721", from_origin(x0 - 300, y0 + 300, 30, 30), nodata=255)

    s = mosaic_tiles_to_grid([tmp_path / "z21.tif"], grid, tmp_path / "out.tif")
    with rasterio.open(tmp_path / "out.tif") as src:
        out = src.read(1)
    assert out[50, 50] == WATER
    assert out[2, 2] == UNKNOWN
    assert 0 < s["known_fraction"] < 0.5 and s["water_fraction_of_known"] == pytest.approx(1.0)


def test_mosaic_reports_unmapped_codes_and_does_not_count_them_as_water(tmp_path, grid):
    tile = np.zeros((70, 70), dtype="uint8")
    tile[:, :35] = 1
    tile[:, 35:] = 2  # an unlisted class, e.g. "partial water"
    write_tif(tmp_path / "t.tif", tile, "EPSG:32720", from_origin(600000, 9700000, 30, 30), nodata=255)
    s = mosaic_tiles_to_grid([tmp_path / "t.tif"], grid, tmp_path / "out.tif")
    with rasterio.open(tmp_path / "out.tif") as src:
        out = src.read(1)
    assert s["unmapped_codes"] == {2: 70 * 35}
    assert out[10, 5] == WATER and out[10, 80] == UNKNOWN


def test_mosaic_needs_at_least_one_tile(tmp_path, grid):
    with pytest.raises(ValueError, match="no tiles"):
        mosaic_tiles_to_grid([], grid, tmp_path / "out.tif")


# --- CMR search helpers (the network call itself is not tested) -----------------

from nisar_flood.groundtruth.reference_layers import (
    download_with_session,
    list_layer_suffixes,
    select_layer_links,
)

BASE = "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/OPERA_L3_DSWX-S1_V1/"
REL = "http://esipfed.org/ns/fedsearch/1.1/data#"


def fake_entry(title, start, layers=("B01_WTR", "B02_BWTR", "B05_WTR-1", "B03_CONF")):
    return {
        "title": title,
        "time_start": start,
        "links": [{"rel": REL, "href": f"{BASE}{title}_{x}.tif"} for x in layers]
        + [{"rel": "http://esipfed.org/ns/fedsearch/1.1/browse#", "href": f"{BASE}{title}.png"}],
    }


def test_select_layer_links_picks_the_exact_layer_on_the_exact_date():
    entries = [
        fake_entry("OPERA_L3_DSWx-S1_T20MRB_20260920T221342Z_x", "2026-09-20T22:13:42.000Z"),
        fake_entry("OPERA_L3_DSWx-S1_T20MRB_20260928T093832Z_x", "2026-09-28T09:38:50.000Z"),
        fake_entry("OPERA_L3_DSWx-S1_T20MRB_20260920T221342Z_x", "2026-09-20T22:13:42.000Z"),  # duplicate
    ]
    got = select_layer_links(entries, "2026-09-20", "B01_WTR")
    assert [u.rsplit("/", 1)[-1] for _, u in got] == ["OPERA_L3_DSWx-S1_T20MRB_20260920T221342Z_x_B01_WTR.tif"]
    # B01_WTR must not also match B05_WTR-1, and a different date is excluded
    assert select_layer_links(entries, "2026-09-21", "B01_WTR") == []


def test_select_layer_links_ignores_non_https_and_browse_links():
    entry = fake_entry("T", "2026-09-20T00:00:00Z")
    entry["links"].append({"rel": REL, "href": "s3://bucket/T_B01_WTR.tif"})
    assert len(select_layer_links([entry], "2026-09-20", "B01_WTR")) == 1


def test_list_layer_suffixes_shows_real_names_when_a_name_is_wrong():
    assert list_layer_suffixes([fake_entry("T_a_b", "2026-09-20T00:00:00Z")]) == [
        "B01_WTR", "B02_BWTR", "B03_CONF", "B05_WTR-1",
    ]
    assert list_layer_suffixes([]) == []


class FakeResponse:
    def __init__(self, status=200, payload=b"abc" * 1000):
        self.status_code, self._p = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        for i in range(0, len(self._p), n):
            yield self._p[i : i + n]


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, 0

    def get(self, url, **kw):
        self.calls += 1
        return self.response


def test_download_streams_to_disk_and_skips_a_finished_file(tmp_path):
    session = FakeSession(FakeResponse())
    path = download_with_session(session, BASE + "x_B01_WTR.tif", tmp_path)
    assert path.read_bytes() == b"abc" * 1000 and not list(tmp_path.glob("*.part"))
    download_with_session(session, BASE + "x_B01_WTR.tif", tmp_path)
    assert session.calls == 1  # second call reused the finished file


def test_download_explains_a_403(tmp_path):
    with pytest.raises(PermissionError, match="accept the PO.DAAC/ASF data terms"):
        download_with_session(FakeSession(FakeResponse(403)), BASE + "x_B01_WTR.tif", tmp_path)
    assert not list(tmp_path.iterdir())  # nothing half-written is left behind
