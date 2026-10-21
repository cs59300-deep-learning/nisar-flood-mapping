"""Score a trained checkpoint on the held-out splits (issues #19 and #20).

The Sen1Floods11 paper reports the image-wise mean water IoU on the test split;
`bolivia` is their held-out out-of-distribution split and is reported separately
because it is the closest thing in the source domain to the transfer question
E4 asks about NISAR.
"""
import argparse
import json
from pathlib import Path

import torch
from tqdm import tqdm

from ..datasets.sen1floods11 import make_loaders
from ..metrics.iou import HEADLINE_METRIC, IoUMeter
from ..models.builder import build_model
from .train import pick_device

# Reference figure from Bonafilia et al. (CVPRW 2020) for the hand-labelled test
# split. TODO(#19): read the exact value off the paper before quoting it in the
# report - this placeholder has not been checked against the source, and #19
# only commits us to "roughly 0.55-0.65". Set to None to skip the comparison.
PUBLISHED_TEST_IOU = None


def load_checkpoint(path, device):
    """Rebuild the model from the config stored in the checkpoint and load weights."""
    ckpt = torch.load(path, map_location=device, weights_only=False)
    model = build_model(ckpt["config"]["model"]).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, ckpt


@torch.no_grad()
def score(model, loader, device, desc=""):
    meter = IoUMeter()
    for x, y in tqdm(loader, desc=desc, leave=False):
        logits = model(x.to(device))
        for pred_i, y_i in zip(logits.argmax(1), y):   # image-wise, never pooled per batch
            meter.update(pred_i, y_i)
    return meter.compute()


def evaluate(checkpoint, splits=("test", "bolivia"), root=None):
    device = pick_device()
    model, ckpt = load_checkpoint(checkpoint, device)
    cfg = ckpt["config"]
    loaders = make_loaders(root or cfg["data"]["root"], batch_size=cfg["data"]["batch_size"],
                           workers=cfg["data"].get("workers", 2), augment=False)

    print(f"{cfg['name']} | checkpoint epoch {ckpt['epoch']} | seed {ckpt['seed']} | {device}\n")
    results = {}
    for split in splits:
        metrics = score(model, loaders[split], device, desc=split)
        results[split] = metrics
        print(f"{split}:")
        for key in (HEADLINE_METRIC, "iou_water", "iou_not_water", "miou",
                    "precision", "recall", "f1", "n_chips_scored"):
            value = metrics[key]
            print(f"  {key:26s} {value:.4f}" if isinstance(value, float) else
                  f"  {key:26s} {value}")
        print()

    headline = results.get("test", {}).get(HEADLINE_METRIC)
    if headline is not None and PUBLISHED_TEST_IOU is not None:
        gap = headline - PUBLISHED_TEST_IOU
        print(f"test {HEADLINE_METRIC} {headline:.4f} vs published {PUBLISHED_TEST_IOU:.4f} "
              f"({gap:+.4f})")
        print("A shortfall here is the expected reproduction gap (#19), not a bug - "
              "state it in the report rather than hiding it.")

    out = Path(checkpoint).parent / "eval.json"
    out.write_text(json.dumps({"checkpoint": str(checkpoint), "results": results,
                               "published_test_iou": PUBLISHED_TEST_IOU}, indent=2))
    print(f"\nwritten to {out}")
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--splits", nargs="+", default=["test", "bolivia"])
    p.add_argument("--root", help="override the data root stored in the checkpoint")
    args = p.parse_args()
    evaluate(args.checkpoint, tuple(args.splits), args.root)


if __name__ == "__main__":
    main()
