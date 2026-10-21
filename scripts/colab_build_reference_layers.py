# %% [markdown]
# # Ticket #15: build the published reference layers (Colab / local)
# Run the cells in order. Needs: this repo on the path, `pip install rasterio`,
# the NISAR-grid HAND raster from #13 (`merit_hand_aligned.tif`) as the grid reference,
# and the JERS-1 wetland GeoTIFF downloaded by hand from ORNL DAAC (Earthdata login).

# %% Paths: EDIT THESE
from pathlib import Path

WORK = Path("/content/ticket15")                      # scratch dir for downloads/outputs
REFERENCE = Path("/content/drive/MyDrive/nisar_ticket13_hand/merit_hand_aligned.tif")
JERS1 = Path("/content/drive/MyDrive/jers1_wetland.tif")  # lon/lat GeoTIFF from ORNL DAAC
WETLAND_VALUES = None  # set after step 3, e.g. [3, 4], from the ORNL dataset guide
WORK.mkdir(parents=True, exist_ok=True)

# %% 1. Download the two JRC GSW v1.4 seasonality tiles that cover the AOI (public, no login)
import urllib.request

BASE = "https://storage.googleapis.com/global-surface-water/downloads2021/seasonality/"
JRC = []
for tile in ("70W_0N", "60W_0N"):
    name = f"seasonality_{tile}v1_4_2021.tif"
    dest = WORK / name
    if not dest.exists():
        urllib.request.urlretrieve(BASE + name, dest)
    JRC.append(dest)
print([p.name for p in JRC])

# %% 2. Sanity-check JRC values: expect 0-12 plus 255 (no data)
from nisar_flood.groundtruth.published_reference import unique_values

print("JRC", unique_values(JRC[0]))

# %% 3. Inspect JERS-1 class codes and compare with the ORNL DAAC dataset guide
print("JERS-1", unique_values(JERS1))
assert WETLAND_VALUES, "Set WETLAND_VALUES from the dataset guide, then re-run from here."

# %% 4. Build everything
from nisar_flood.groundtruth.published_reference import build_reference_layers

out = build_reference_layers(JRC, JERS1, REFERENCE, WORK / "out", WETLAND_VALUES)
for k, v in out.items():
    print(k, v)

# %% 5. Verify against the acceptance criteria and print numbers for the PR
import numpy as np
import rasterio

with rasterio.open(out["separation"]) as s, rasterio.open(REFERENCE) as r:
    assert s.crs == r.crs and s.transform == r.transform and s.shape == r.shape, "grid mismatch"
    cls = s.read(1)
vals, counts = np.unique(cls, return_counts=True)
total = cls.size
names = {0: "land", 1: "permanent water", 2: "flood water", 255: "no data"}
for v, c in zip(vals, counts):
    print(f"{names.get(int(v), v):16s} {c:>12,d}  {100 * c / total:6.2f}%")
print("grid matches NISAR reference:", s.shape, s.crs)
# Then look at it: permanent water should trace the Amazon / Rio Negro channels,
# flood water should sit on the floodplain around them.
