"""RQ3 polarisation ablation by band swap, on Sentinel-1 only (issue #23).

Sen1Floods11 is C-band VV/VH and NISAR land mode is L-band HH/HV, so a drop in
IoU on NISAR could be wavelength or polarisation, and the two cannot be separated
after the fact. This experiment bounds the polarisation part without any NISAR
data: take a model trained on VV/VH, feed it Sentinel-1 test chips with the
channels permuted, and measure how much IoU is lost. Wavelength, sensor, region
and radiometry are all held fixed, so the loss is attributable to the channel
change alone.

Arms (all test-time only; no retraining):
    identity     (VV, VH)  as trained. The reference.
    swap         (VH, VV)  the ticket's channel-permuted arm.
    co_only      (VV, VV)  diagnostic: the cross-pol slot is filled with co-pol.
    cross_only   (VH, VH)  diagnostic: the co-pol slot is filled with cross-pol.

How to read the result
    The swap is a deliberately severe polarisation change: it puts cross-pol
    where the model learned to expect co-pol. Real VV -> HH is milder, since both
    are co-pol, so the swap is a stress test and not an estimate of the true
    polarisation effect.
      * A SMALL drop is strong evidence: polarisation cannot explain much of the
        transfer gap, because even a severe change costs little.
      * A LARGE drop is only an upper-bound-style signal. It shows the model is
        sensitive to polarisation identity, not that polarisation caused the gap.
    The share of the gap reported below is therefore "at most about this much".

The gap itself (Sentinel-1 test IoU minus NISAR zero-shot IoU) comes from RQ1
(zero_shot.py) and is passed in with --nisar-iou. Without it only the drop is
reported.

Run:
    nisar-flood polarisation-ablation --checkpoint runs/unet_resnet50/seed0/best.pt \
        runs/unet_resnet50/seed1/best.pt runs/unet_resnet50/seed2/best.pt \
        --nisar-iou 0.18
"""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from ..datasets.transforms import IGNORE_INDEX, permute_channels
from ..metrics.iou import HEADLINE_METRIC, IoUMeter

ARMS = {
    "identity": (0, 1),
    "swap": (1, 0),
    "co_only": (0, 0),
    "cross_only": (1, 1),
}


def chip_water_iou(pred, target, ignore_index=IGNORE_INDEX):
    """Water IoU of one chip, or NaN when neither label nor prediction has water.

    Same definition as the per-chip entries of IoUMeter, but keeps the chip's
    place in the list, which the paired comparison between arms needs.
    """
    pred, target = np.asarray(pred).ravel(), np.asarray(target).ravel()
    valid = target != ignore_index
    p, t = pred[valid] == 1, target[valid] == 1
    union = int((p | t).sum())
    return float((p & t).sum()) / union if union else float("nan")


def paired_drop(reference, perturbed, n_boot=10000, seed=0):
    """Mean per-chip IoU lost going from `reference` to `perturbed`, with a 95% CI.

    The two arrays hold one IoU per chip, in the same chip order. Chips where
    either arm is undefined are dropped from both, so the comparison is paired.
    The interval comes from resampling chips with replacement. Chips are the unit
    because the headline metric weights each chip equally.
    """
    a, b = np.asarray(reference, float), np.asarray(perturbed, float)
    keep = ~(np.isnan(a) | np.isnan(b))
    diff = (a - b)[keep]
    n = len(diff)
    if n == 0:
        return {"drop": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n_chips": 0}
    rng = np.random.default_rng(seed)
    boots = diff[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
    low, high = np.percentile(boots, [2.5, 97.5])
    return {"drop": float(diff.mean()), "ci_low": float(low), "ci_high": float(high), "n_chips": n}


def gap_share(drop, reference_iou, nisar_iou):
    """Fraction of the Sentinel-1 -> NISAR gap that the swap drop could account for.

    NaN when no NISAR figure is given or there is no gap to explain. A value above
    1 means the swap cost more than the whole gap, which shows the swap is harsher
    than the real polarisation change and is not a meaningful share.
    """
    if nisar_iou is None:
        return float("nan")
    gap = reference_iou - nisar_iou
    return drop / gap if gap > 0 else float("nan")


def evaluate_arms(model, loader, device, arms=None):
    """Score `model` on every chip of `loader` under each channel arrangement.

    Returns {arm: {"metrics": IoUMeter.compute(), "chip_iou": [per chip, NaN if
    undefined]}} plus the chip names in loader order. The loader must not shuffle,
    so that chip i is the same chip in every arm.
    """
    import torch

    arms = arms or ARMS
    model.eval()
    meters = {arm: IoUMeter() for arm in arms}
    chip_iou = {arm: [] for arm in arms}
    with torch.no_grad():
        for x, y in loader:
            x = x.to(device)
            for arm, order in arms.items():
                preds = model(permute_channels(x, order)).argmax(1).cpu()
                for pred_i, y_i in zip(preds, y):
                    meters[arm].update(pred_i, y_i)
                    chip_iou[arm].append(chip_water_iou(pred_i.numpy(), y_i.numpy()))
    return {arm: {"metrics": meters[arm].compute(), "chip_iou": chip_iou[arm]} for arm in arms}


def run(checkpoints, splits=("test", "bolivia"), root=None, nisar_iou=None,
        out_dir="reports/polarisation_ablation", n_boot=10000):
    """Run the ablation for each checkpoint and write results.json and per_chip.csv."""
    from ..datasets.sen1floods11 import make_loaders
    from ..training.evaluate import load_checkpoint
    from ..training.train import pick_device

    device = pick_device()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    runs, rows = [], []

    for path in checkpoints:
        model, ckpt = load_checkpoint(path, device)
        cfg = ckpt["config"]
        if cfg["model"].get("in_channels", 2) != 2:
            raise SystemExit(f"{path}: the band swap needs a 2-channel (VV, VH) model.")
        loaders = make_loaders(root or cfg["data"]["root"], batch_size=1,
                               workers=cfg["data"].get("workers", 2), augment=False)
        print(f"{cfg['name']} | seed {ckpt['seed']} | epoch {ckpt['epoch']} | {device}")
        result = {"checkpoint": str(path), "name": cfg["name"], "seed": ckpt["seed"], "splits": {}}

        for split in splits:
            scored = evaluate_arms(model, loaders[split], device)
            names = [r[0] for r in loaders[split].dataset.rows]
            ref = scored["identity"]["metrics"][HEADLINE_METRIC]
            entry = {"arms": {arm: s["metrics"] for arm, s in scored.items()}, "drops": {}}
            for arm in scored:
                if arm == "identity":
                    continue
                d = paired_drop(scored["identity"]["chip_iou"], scored[arm]["chip_iou"], n_boot)
                d["share_of_gap"] = gap_share(d["drop"], ref, nisar_iou) if split == "test" else float("nan")
                entry["drops"][arm] = d
            result["splits"][split] = entry
            for arm, s in scored.items():
                rows += [{"checkpoint": str(path), "seed": ckpt["seed"], "split": split,
                          "chip": n, "arm": arm, "water_iou": v}
                         for n, v in zip(names, s["chip_iou"])]
        runs.append(result)

    summary = summarise(runs, nisar_iou)
    (out / "results.json").write_text(json.dumps(_nan_to_none(
        {"headline_metric": HEADLINE_METRIC, "nisar_zero_shot_iou": nisar_iou,
         "runs": runs, "summary": summary}), indent=2))
    with (out / "per_chip.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["checkpoint", "seed", "split", "chip", "arm", "water_iou"])
        w.writeheader()
        w.writerows(rows)
    print_summary(summary, nisar_iou)
    print(f"\nwritten to {out}")
    return summary


def _nan_to_none(obj):
    """NaN is not valid JSON; write it as null so any reader can load results.json."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nan_to_none(v) for v in obj]
    return obj


def summarise(runs, nisar_iou):
    """Mean and range across checkpoints (seeds) of the IoU per arm and the swap drop."""
    summary = {}
    for split in runs[0]["splits"]:
        per_arm = {}
        for arm in ARMS:
            vals = [r["splits"][split]["arms"][arm][HEADLINE_METRIC] for r in runs]
            per_arm[arm] = {"mean": float(np.nanmean(vals)), "min": float(np.nanmin(vals)),
                            "max": float(np.nanmax(vals))}
        drops = {}
        for arm in ARMS:
            if arm == "identity":
                continue
            vals = [r["splits"][split]["drops"][arm]["drop"] for r in runs]
            drops[arm] = {"mean": float(np.nanmean(vals)), "min": float(np.nanmin(vals)),
                          "max": float(np.nanmax(vals))}
        entry = {"n_checkpoints": len(runs), "iou": per_arm, "drop": drops}
        if split == "test" and nisar_iou is not None:
            entry["share_of_gap_swap"] = gap_share(
                drops["swap"]["mean"], per_arm["identity"]["mean"], nisar_iou)
        summary[split] = entry
    return summary


def print_summary(summary, nisar_iou):
    for split, s in summary.items():
        print(f"\n{split} ({s['n_checkpoints']} checkpoint(s)), {HEADLINE_METRIC}")
        for arm, v in s["iou"].items():
            drop = s["drop"].get(arm)
            extra = f"   drop {drop['mean']:+.4f} [{drop['min']:+.4f}, {drop['max']:+.4f}]" if drop else ""
            print(f"  {arm:11s} {v['mean']:.4f}{extra}")
        share = s.get("share_of_gap_swap")
        if share is not None and not math.isnan(share):
            note = "  (above 1: the swap is harsher than the real change)" if share > 1 else ""
            print(f"  swap drop / gap to NISAR {nisar_iou:.4f}: {share:.1%}{note}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--checkpoint", nargs="+", required=True,
                   help="one or more source checkpoints, e.g. one per seed")
    p.add_argument("--splits", nargs="+", default=["test", "bolivia"])
    p.add_argument("--root", help="override the data root stored in the checkpoint")
    p.add_argument("--nisar-iou", type=float,
                   help=f"zero-shot NISAR {HEADLINE_METRIC} from RQ1, to express the drop "
                        "as a share of the gap")
    p.add_argument("--out", default="reports/polarisation_ablation")
    p.add_argument("--n-boot", type=int, default=10000)
    args = p.parse_args()
    run(args.checkpoint, tuple(args.splits), args.root, args.nisar_iou, args.out, args.n_boot)


if __name__ == "__main__":
    main()
