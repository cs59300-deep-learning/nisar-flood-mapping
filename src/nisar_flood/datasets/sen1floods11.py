"""Sen1Floods11 v1.1 hand-labeled chips: download, Dataset and DataLoaders."""
import csv
from pathlib import Path

import rasterio
import torch
from torch.utils.data import DataLoader, Dataset

from .transforms import IGNORE_INDEX, preprocess_sar_db, remap_labels

BASE = "https://storage.googleapis.com/sen1floods11/v1.1"
SPLITS = {
    "train": "flood_train_data.csv",
    "val": "flood_valid_data.csv",
    "test": "flood_test_data.csv",
    "bolivia": "flood_bolivia_data.csv",
}


def read_split(root, split):
    """Return a list of (radar_filename, label_filename) pairs for one split."""
    with open(Path(root) / "splits" / SPLITS[split], newline="") as f:
        return [row[:2] for row in csv.reader(f) if row]


def download(root):
    """Download the split lists, then every chip and label they mention."""
    import requests
    from tqdm import tqdm

    root = Path(root)

    def fetch(url, dest):
        if dest.exists() and dest.stat().st_size > 0:
            return  # already downloaded, so re-running is safe
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)

    for name in SPLITS.values():
        fetch(f"{BASE}/splits/flood_handlabeled/{name}", root / "splits" / name)

    hand = f"{BASE}/data/flood_events/HandLabeled"
    for split in SPLITS:
        for s1_name, label_name in tqdm(read_split(root, split), desc=split):
            fetch(f"{hand}/S1Hand/{s1_name}", root / "data" / "S1Hand" / s1_name)
            fetch(f"{hand}/LabelHand/{label_name}", root / "data" / "LabelHand" / label_name)


class Sen1Floods11(Dataset):
    def __init__(self, root, split):
        self.root = Path(root)
        self.rows = read_split(root, split)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        s1_name, label_name = self.rows[i]
        with rasterio.open(self.root / "data" / "S1Hand" / s1_name) as f:
            x = f.read().astype("float32")   # shape (2, H, W): VV and VH in dB
        with rasterio.open(self.root / "data" / "LabelHand" / label_name) as f:
            y = f.read(1)                    # shape (H, W): -1 / 0 / 1
        x = preprocess_sar_db(x)
        y = remap_labels(y)
        return torch.from_numpy(x), torch.from_numpy(y)


def make_loaders(root, batch_size=8, workers=2):
    """One DataLoader per split. Only training is shuffled and batched."""
    loaders = {}
    for split in SPLITS:
        training = split == "train"
        loaders[split] = DataLoader(
            Sen1Floods11(root, split),
            batch_size=batch_size if training else 1,
            shuffle=training,
            num_workers=workers,
            drop_last=training,
        )
    return loaders

EXPECTED = {"train": 252, "val": 89, "test": 90, "bolivia": 15}  # 446 chips in total


def check(root):
    """Verify split sizes, that all files exist, value ranges and water share."""
    root = Path(root)
    for split in SPLITS:
        rows = read_split(root, split)
        missing = [
            r for r in rows
            if not (root / "data" / "S1Hand" / r[0]).exists()
            or not (root / "data" / "LabelHand" / r[1]).exists()
        ]
        ds = Sen1Floods11(root, split)
        water = valid = 0
        for i in range(len(ds)):
            x, y = ds[i]
            assert x.shape[0] == 2, "expected 2 channels (VV, VH)"
            assert 0 <= float(x.min()) and float(x.max()) <= 1, "input outside [0, 1]"
            water += int((y == 1).sum())
            valid += int((y != IGNORE_INDEX).sum())
        status = "OK   " if len(rows) == EXPECTED[split] and not missing else "CHECK"
        print(f"{status} {split:8s} n={len(rows):3d} (expected {EXPECTED[split]}) "
              f"missing={len(missing)} water={100 * water / max(valid, 1):.1f}%")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["download", "check"])
    p.add_argument("--root", default="data/sen1floods11")
    args = p.parse_args()
    {"download": download, "check": check}[args.command](args.root)