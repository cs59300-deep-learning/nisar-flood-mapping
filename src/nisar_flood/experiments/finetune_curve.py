"""RQ2: how many labelled NISAR chips does it take to recover the transfer gap (issue #24).

Sweeps (n, seed) pairs. For each, a Sen1Floods11 source checkpoint is fine-tuned
on n NISAR chips drawn from the pool in `data/labels/rq2_splits.json`, then
scored on the 20 held-out test chips. n=0 is the source model evaluated with no
adaptation at all, which anchors the curve.

Two choices keep the curve readable:

A fixed step budget. Every point trains for the same number of optimiser steps,
so moving along the curve changes how many distinct chips the model has seen and
nothing else. Counting epochs instead would give n=35 seven times the updates of
n=5 and confound the two effects.

No checkpoint selection. The pool and the test set are the only labelled NISAR
data there is, so there is no third split to select an epoch on. Selecting on the
test set would report a score tuned on the chips it claims to generalise to.
Each run is scored as it stands when the budget runs out.

Writes `curve.json` and one `run_n{n}_seed{s}.json` per run into the output
directory, and a `curve.png` with error bars over seeds. Finished runs are
reused on a second invocation, so an interrupted sweep continues where it
stopped; `--force` redoes them.
"""
import argparse
import hashlib
import json
import math
import time
from itertools import cycle
from pathlib import Path

import numpy as np
import torch
import yaml

from ..datasets.nisar_chips import NisarChips, make_loaders
from ..metrics.iou import IoUMeter
from ..models.builder import build_model
from ..models.losses import masked_ce_dice_loss
from ..training.train import amp_dtype, pick_device, set_seed


def load_source(source_cfg, device):
    """Build the architecture from its training config and load the checkpoint weights."""
    arch = yaml.safe_load(Path(source_cfg["config"]).read_text())["model"]
    model = build_model(arch).to(device)
    ckpt = torch.load(source_cfg["checkpoint"], map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model"])
    return model


def lr_at(step, cfg):
    """Cosine decay over the step budget, after a short linear warmup."""
    warmup, steps = cfg.get("warmup_steps", 0), cfg["steps"]
    if step < warmup:
        return (step + 1) / max(warmup, 1)
    if cfg.get("scheduler", "cosine") != "cosine":
        return 1.0
    return 0.5 * (1 + math.cos(math.pi * (step - warmup) / max(steps - warmup, 1)))


@torch.no_grad()
def evaluate(model, loader, device):
    """Score the model chip by chip, as the headline metric is an image-wise mean."""
    model.eval()
    meter = IoUMeter()
    per_chip = []
    for (x, y), chip_id in zip(loader, loader.dataset.chip_ids):
        pred = model(x.to(device)).argmax(1)[0]
        before = len(meter.chip_ious)
        meter.update(pred, y[0].to(device))
        # A chip with no water, true or predicted, cannot be scored and is skipped.
        per_chip.append({"chip": chip_id,
                         "iou_water": meter.chip_ious[-1] if len(meter.chip_ious) > before else None})
    return meter.compute(), per_chip


def finetune(model, loader, device, tcfg):
    """Run the fixed step budget over `loader`, cycling it as often as needed."""
    optimizer = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"],
                                  weight_decay=tcfg.get("weight_decay", 0.0))
    dtype = amp_dtype(device, bool(tcfg.get("amp")))
    scaler = torch.amp.GradScaler("cuda", enabled=dtype is torch.float16)
    model.train()

    losses = []
    batches = cycle(loader)
    for step in range(tcfg["steps"]):
        for group in optimizer.param_groups:
            group["lr"] = tcfg["lr"] * lr_at(step, tcfg)
        x, y = next(batches)
        x, y = x.to(device), y.to(device)
        with torch.autocast("cuda", dtype=dtype or torch.float16, enabled=dtype is not None):
            loss = masked_ce_dice_loss(model(x), y, dice_weight=tcfg.get("dice_weight", 1.0))
        optimizer.zero_grad(set_to_none=True)
        if scaler.is_enabled():
            scaler.scale(loss).backward()
            if tcfg.get("grad_clip"):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), tcfg["grad_clip"])
            scaler.step(optimizer)
            scaler.update()
        else:
            loss.backward()
            if tcfg.get("grad_clip"):
                torch.nn.utils.clip_grad_norm_(model.parameters(), tcfg["grad_clip"])
            optimizer.step()
        losses.append(float(loss.detach()))
    return losses


def fingerprint(cfg):
    """Short hash of the settings that change a run's result.

    A finished run is only reusable if these still match. Output paths, sweep
    membership and worker counts are left out: they move results around or change
    how fast they arrive, not what they are.
    """
    dcfg, tcfg, scfg = cfg["data"], cfg["train"], cfg["source"]
    relevant = {
        "source": [scfg["config"], scfg["checkpoint"]],
        "train": [tcfg[k] for k in ("steps", "lr", "weight_decay", "dice_weight",
                                    "scheduler", "warmup_steps")],
        "data": [dcfg["batch_size"], dcfg.get("augment", True), dcfg["splits"]],
    }
    return hashlib.sha1(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:12]


def run_one(cfg, split, n, seed, device, out_dir, force=False):
    """One (n, seed) point of the curve.

    A run whose JSON is already on disk is reused, so a sweep interrupted
    part-way can be restarted without repeating the points it finished. The
    fingerprint guards that: if the settings changed, the stale result is
    recomputed rather than quietly reported.
    """
    path = out_dir / f"run_n{n}_seed{seed}.json"
    stamp = fingerprint(cfg)
    if path.exists() and not force:
        cached = json.loads(path.read_text())
        if cached.get("fingerprint") == stamp:
            cached["cached"] = True
            return cached
        print(f"  n={n} seed={seed}: settings changed since that run, redoing it")

    set_seed(seed)
    dcfg, tcfg = cfg["data"], cfg["train"]
    train_ids = split["subsets"][str(seed)][str(n)] if n else []
    test_ids = split["test"]

    model = load_source(cfg["source"], device)
    started = time.time()
    losses = []
    if train_ids:
        loaders = make_loaders(dcfg["chips"], dcfg["masks"], train_ids, test_ids,
                               batch_size=dcfg["batch_size"], workers=dcfg.get("workers", 0),
                               augment=dcfg.get("augment", True), seed=seed)
        losses = finetune(model, loaders["train"], device, tcfg)
        test_loader = loaders["test"]
    else:
        test_loader = torch.utils.data.DataLoader(
            NisarChips(dcfg["chips"], dcfg["masks"], test_ids), batch_size=1)

    metrics, per_chip = evaluate(model, test_loader, device)
    result = {"n": n, "seed": seed, "train_chips": train_ids,
              "fingerprint": stamp,
              "steps": tcfg["steps"] if train_ids else 0,
              "final_loss": losses[-1] if losses else None,
              "minutes": round((time.time() - started) / 60, 2),
              "metrics": metrics, "per_chip": per_chip}
    path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def summarise(results, metric):
    """Mean and standard deviation over seeds, for each n."""
    by_n = {}
    for r in results:
        by_n.setdefault(r["n"], []).append(r["metrics"][metric])
    return {str(n): {"mean": float(np.mean(v)), "std": float(np.std(v, ddof=1)) if len(v) > 1 else 0.0,
                     "n_seeds": len(v), "values": v}
            for n, v in sorted(by_n.items())}


def plot_curve(summary, metric, path, arm):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ns = sorted(int(n) for n in summary)
    means = [summary[str(n)]["mean"] for n in ns]
    stds = [summary[str(n)]["std"] for n in ns]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.errorbar(ns, means, yerr=stds, marker="o", capsize=4)
    ax.axhline(means[0], linestyle="--", linewidth=1, color="grey")
    ax.annotate("no adaptation", (ns[-1], means[0]), textcoords="offset points",
                xytext=(-4, 4), ha="right", fontsize=8, color="grey")
    ax.set(xlabel="labelled NISAR chips used for fine-tuning",
           ylabel=metric.replace("_", " "), title=f"RQ2 fine-tuning curve ({arm})")
    ax.set_xticks(ns)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="configs/finetune.yaml")
    p.add_argument("--sizes", type=int, nargs="+", help="override sweep.sizes")
    p.add_argument("--seeds", type=int, nargs="+", help="override sweep.seeds")
    p.add_argument("--steps", type=int, help="override train.steps")
    p.add_argument("--batch-size", type=int, help="override data.batch_size")
    p.add_argument("--workers", type=int, help="override data.workers")
    p.add_argument("--source-config", help="override source.config (the other arm)")
    p.add_argument("--source-checkpoint", help="override source.checkpoint")
    p.add_argument("--name", help="override name, used in curve.json and the plot title")
    p.add_argument("--out", type=Path, help="override output.dir")
    p.add_argument("--force", action="store_true",
                   help="redo every point, instead of reusing finished runs")
    args = p.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    sizes = args.sizes or cfg["sweep"]["sizes"]
    seeds = args.seeds or cfg["sweep"]["seeds"]
    if args.steps:
        cfg["train"]["steps"] = args.steps
    if args.batch_size:
        cfg["data"]["batch_size"] = args.batch_size
    if args.workers is not None:
        cfg["data"]["workers"] = args.workers
    if args.source_config:
        cfg["source"]["config"] = args.source_config
    if args.source_checkpoint:
        cfg["source"]["checkpoint"] = args.source_checkpoint
    if args.name:
        cfg["name"] = args.name
    out_dir = args.out or Path(cfg["output"]["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    split = json.loads(Path(cfg["data"]["splits"]).read_text())
    device = pick_device()
    metric = cfg["eval"]["metric"]
    print(f"{cfg['name']} | {device} | {cfg['train']['steps']} steps | "
          f"test {len(split['test'])} chips")

    results = []
    for n in sizes:
        # n=0 is the same model every time, so one evaluation stands for all seeds.
        for seed in (seeds[:1] if n == 0 else seeds):
            r = run_one(cfg, split, n, seed, device, out_dir, force=args.force)
            results.append(r)
            note = "reused" if r.get("cached") else f"{r['minutes']} min"
            print(f"  n={n:<3} seed={seed}  {metric} {r['metrics'][metric]:.4f}  "
                  f"pooled {r['metrics']['iou_water']:.4f}  ({note})")

    summary = summarise(results, metric)
    curve = {"name": cfg["name"], "metric": metric, "device": str(device),
             "steps": cfg["train"]["steps"], "test_chips": split["test"],
             "summary": summary, "config": cfg}
    (out_dir / "curve.json").write_text(json.dumps(curve, indent=2) + "\n")
    plot_curve(summary, metric, out_dir / "curve.png", cfg["name"])
    print(f"\nwrote {out_dir / 'curve.json'} and curve.png")


if __name__ == "__main__":
    main()
