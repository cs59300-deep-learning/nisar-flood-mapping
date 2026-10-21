"""Train a source model on Sen1Floods11 (issues #19 and #20).

Both arms use this loop. A run is fully described by its config plus the seed,
so `python -m nisar_flood.training.train --config configs/unet_resnet50.yaml`
reproduces it.

Writes into the config's output directory:
    history.csv      per-epoch loss and validation metrics
    curves.png       loss and IoU curves (an acceptance criterion on #19)
    best.pt          checkpoint with the best validation headline metric
    last.pt          final-epoch checkpoint, for resuming
    summary.json     best epoch, metrics and the config used
"""
import argparse
import csv
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
import yaml
from tqdm import tqdm

from ..datasets.sen1floods11 import make_loaders
from ..metrics.iou import HEADLINE_METRIC, IoUMeter
from ..models.builder import build_model, count_parameters
from ..models.losses import masked_ce_dice_loss


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device():
    """CUDA on Kaggle/Colab, MPS on an Apple laptop, CPU otherwise."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def lr_at(epoch, cfg):
    """Cosine schedule with a short linear warmup, as a multiplier on the base lr."""
    warmup, epochs = cfg.get("warmup_epochs", 0), cfg["epochs"]
    if epoch < warmup:
        return (epoch + 1) / max(warmup, 1)
    if cfg.get("scheduler", "cosine") != "cosine":
        return 1.0
    progress = (epoch - warmup) / max(epochs - warmup, 1)
    return 0.5 * (1 + math.cos(math.pi * progress))


def run_epoch(model, loader, device, optimizer=None, scaler=None, cfg=None, desc=""):
    """One pass over `loader`. Trains when `optimizer` is given, else evaluates.

    Returns (mean loss, metrics dict). Metrics are only meaningful for evaluation
    passes, where predictions are not moving under the optimiser.
    """
    training = optimizer is not None
    model.train(training)
    meter, total, n = IoUMeter(), 0.0, 0
    amp = bool(cfg.get("amp", False)) and device.type == "cuda"

    for x, y in tqdm(loader, desc=desc, leave=False):
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        with torch.set_grad_enabled(training):
            with torch.autocast("cuda", enabled=amp):
                logits = model(x)
                loss = masked_ce_dice_loss(logits, y, dice_weight=cfg.get("dice_weight", 1.0))
        if training:
            optimizer.zero_grad(set_to_none=True)
            if amp:
                scaler.scale(loss).backward()
                if cfg.get("grad_clip"):
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])
                scaler.step(optimizer)
                scaler.update()
            else:
                loss.backward()
                if cfg.get("grad_clip"):
                    torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])
                optimizer.step()
        else:
            # Score chip by chip: the headline metric is an image-wise mean, so
            # a whole batch must not be pooled into one "chip".
            for pred_i, y_i in zip(logits.argmax(1), y):
                meter.update(pred_i, y_i)
        total += loss.detach().item() * x.size(0)
        n += x.size(0)

    return total / max(n, 1), meter.compute()


def plot_curves(history, path):
    """Loss and validation IoU against epoch."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    epochs = [h["epoch"] for h in history]
    fig, (ax_loss, ax_iou) = plt.subplots(1, 2, figsize=(11, 4))
    ax_loss.plot(epochs, [h["train_loss"] for h in history], label="train")
    ax_loss.plot(epochs, [h["val_loss"] for h in history], label="val")
    ax_loss.set(xlabel="epoch", ylabel="loss", title="Loss")
    ax_loss.legend()
    ax_iou.plot(epochs, [h[HEADLINE_METRIC] for h in history], label="per-chip mean")
    ax_iou.plot(epochs, [h["iou_water"] for h in history], label="pooled", linestyle="--")
    ax_iou.set(xlabel="epoch", ylabel="water IoU", title="Validation IoU")
    ax_iou.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def train(config_path, overrides=None):
    cfg = yaml.safe_load(Path(config_path).read_text())
    for key, value in (overrides or {}).items():      # e.g. --seed, --epochs
        section, _, field = key.partition(".")
        cfg[section][field] = value

    tcfg, dcfg = cfg["train"], cfg["data"]
    seed = tcfg["seed"]
    set_seed(seed)
    device = pick_device()
    out = Path(cfg["output"]["dir"]) / f"seed{seed}"
    out.mkdir(parents=True, exist_ok=True)

    loaders = make_loaders(dcfg["root"], batch_size=dcfg["batch_size"],
                           workers=dcfg.get("workers", 2),
                           augment=dcfg.get("augment", False), seed=seed)
    model = build_model(cfg["model"]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"],
                                  weight_decay=tcfg.get("weight_decay", 0.0))
    scaler = torch.amp.GradScaler("cuda", enabled=bool(tcfg.get("amp")) and device.type == "cuda")

    print(f"{cfg['name']} | {device} | {count_parameters(model):,} trainable params | seed {seed}")
    print(f"train {len(loaders['train'].dataset)} chips, val {len(loaders['val'].dataset)} chips")

    select_on = cfg["eval"]["select_on"]
    val_split = cfg["eval"].get("split", "val")
    history, best, best_epoch, started = [], -float("inf"), -1, time.time()

    for epoch in range(tcfg["epochs"]):
        for group in optimizer.param_groups:
            group["lr"] = tcfg["lr"] * lr_at(epoch, tcfg)

        train_loss, _ = run_epoch(model, loaders["train"], device, optimizer, scaler,
                                  tcfg, desc=f"epoch {epoch + 1}/{tcfg['epochs']}")
        val_loss, metrics = run_epoch(model, loaders[val_split], device, cfg=tcfg, desc="val")

        row = {"epoch": epoch + 1, "lr": optimizer.param_groups[0]["lr"],
               "train_loss": train_loss, "val_loss": val_loss, **metrics}
        history.append(row)
        print(f"  epoch {epoch + 1:3d}  train {train_loss:.4f}  val {val_loss:.4f}  "
              f"{select_on} {metrics[select_on]:.4f}  pooled {metrics['iou_water']:.4f}")

        score = metrics[select_on]
        if not math.isnan(score) and score > best:
            best, best_epoch = score, epoch + 1
            torch.save({"model": model.state_dict(), "config": cfg, "seed": seed,
                        "epoch": epoch + 1, "metrics": metrics}, out / "best.pt")

        with (out / "history.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(history[0]))
            writer.writeheader()
            writer.writerows(history)
        plot_curves(history, out / "curves.png")

    torch.save({"model": model.state_dict(), "config": cfg, "seed": seed,
                "epoch": tcfg["epochs"]}, out / "last.pt")
    summary = {"name": cfg["name"], "seed": seed, "best_epoch": best_epoch,
               f"best_{select_on}": best, "minutes": round((time.time() - started) / 60, 1),
               "device": str(device), "config": cfg}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nbest {select_on} {best:.4f} at epoch {best_epoch} -> {out}")
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--seed", type=int, help="override train.seed")
    p.add_argument("--epochs", type=int, help="override train.epochs")
    args = p.parse_args()
    overrides = {f"train.{k}": v for k, v in [("seed", args.seed), ("epochs", args.epochs)]
                 if v is not None}
    train(args.config, overrides)


if __name__ == "__main__":
    main()
