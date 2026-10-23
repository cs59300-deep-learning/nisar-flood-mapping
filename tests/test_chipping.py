import csv

import numpy as np
import rasterio
from rasterio.transform import from_origin

from nisar_flood.pipeline.chipping import ChipConfig, chip_raster
from nisar_flood.pipeline.reproject import reproject_raster


def test_chip_size_stride_validity_transform_and_manifest(tmp_path):
    source = tmp_path / "source.tif"
    data = np.ones((1, 912, 912), dtype="uint8")
    mask = np.full((912, 912), 255, dtype="uint8")
    mask[:200, :200] = 0
    with rasterio.open(source, "w", driver="GTiff", width=912, height=912,
                       count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(10, 20, 0.01, 0.01)) as dst:
        dst.write(data)
        dst.write_mask(mask)

    output = tmp_path / "chips"
    rows = chip_raster(source, output, granule_id="G1", acquisition_date="2024-01-02",
                       config=ChipConfig(size=512, stride=400, min_valid_fraction=0.70))
    assert len(rows) == 4
    assert all(float(row["valid_fraction"]) >= 0.70 for row in rows)
    with rasterio.open(output / f"{rows[0]['chip_id']}.tif") as chip:
        assert (chip.width, chip.height) == (512, 512)
        assert chip.transform == from_origin(10, 20, 0.01, 0.01)
        assert chip.crs.to_string() == "EPSG:4326"
    with (output / "manifest.csv").open(newline="", encoding="utf-8") as stream:
        manifest = list(csv.DictReader(stream))
    assert len(manifest) == 4
    assert {"chip_id", "source_granule", "date", "bbox", "valid_fraction"} <= set(manifest[0])


def test_rejects_low_valid_fraction(tmp_path):
    source = tmp_path / "mostly_invalid.tif"
    with rasterio.open(source, "w", driver="GTiff", width=512, height=512,
                       count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(1, 10, 1, 1)) as dst:
        dst.write(np.ones((1, 512, 512), dtype="uint8"))
        dst.write_mask(np.zeros((512, 512), dtype="uint8"))
    rows = chip_raster(source, tmp_path / "out", granule_id="G2",
                       acquisition_date="2024-01-02")
    assert rows == []


def test_reproject_preserves_data_and_validity_mask(tmp_path):
    source = tmp_path / "source.tif"
    with rasterio.open(source, "w", driver="GTiff", width=8, height=8,
                       count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(-1, 1, 0.25, 0.25)) as dst:
        dst.write(np.full((1, 8, 8), 7, dtype="uint8"))
        mask = np.full((8, 8), 255, dtype="uint8")
        mask[0, 0] = 0
        dst.write_mask(mask)

    output = reproject_raster(source, tmp_path / "projected.tif", dst_crs="EPSG:3857")
    with rasterio.open(output) as projected:
        assert projected.crs.to_string() == "EPSG:3857"
        assert projected.count == 1
        assert projected.read(1).max() == 7
        assert (projected.dataset_mask() == 0).any()
