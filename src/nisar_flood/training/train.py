"""Train a source model on Sen1Floods11 (issues #19 and #20).

Both arms use this loop. A run is fully described by its config plus the seed,
so `python -m nisar_flood.training.train --config configs/unet_resnet50.yaml`
reproduces it.

Writes into the config's output directory:
    history.csv      per-epoch loss and validation metrics
    curves.png       loss and IoU curves
    best.pt          checkpoint with the best validation headline metric
    last.pt          full training state (model, optimizer, history), rewritten every
                     `save_every` epochs, for resuming with --resume
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


def amp_dtype(device, enabled=True):
    """Which mixed-precision dtype to use, or None for full precision.

    Older cards (T4, and anything pre-Ampere) only accelerate float16, which has
    a narrow exponent range - gradients underflow to zero, which is why a
    GradScaler is needed to keep them representable.

    Ampere and newer (A100, H100, 40-series) support bfloat16, which keeps
    float32's exponent range at reduced precision. Nothing underflows, so no
    scaler is needed and there is one less way for a run to diverge silently.

    Picking by capability means the same config trains correctly on a T4 and on
    an H100 with no edit.

    The check reads compute capability directly. torch.cuda.is_bf16_supported()
    defaults to including_emulation=True, so it answers True on Turing, where
    bfloat16 runs in software and misses the float16 tensor cores entirely.
    """
    if not enabled or device.type != "cuda":
        return None
    return torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16


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

    Gradient accumulation: with cfg["accum_steps"] = k, gradients from k
    consecutive batches are summed before one optimizer step, so a batch size that
    fits in memory can stand in for a larger one (batch 4 x 2 behaves like 8).
    Each batch's loss is divided by the size of its group, so the summed gradient
    is the mean over the group. A short final group is divided by its own size.
    The default, k = 1, is a step after every batch.
    """
    training = optimizer is not None
    model.train(training)
    meter, total, n = IoUMeter(), 0.0, 0
    dtype = amp_dtype(device, bool(cfg.get("amp", False)))
    accum = max(int(cfg.get("accum_steps", 1)), 1)
    n_batches = len(loader)

    for i, (x, y) in enumerate(tqdm(loader, desc=desc, leave=False)):
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        with torch.set_grad_enabled(training):
            with torch.autocast("cuda", dtype=dtype or torch.float16,
                                enabled=dtype is not None):
                logits = model(x)
                loss = masked_ce_dice_loss(logits, y, dice_weight=cfg.get("dice_weight", 1.0))
        if training:
            if i % accum == 0:                               # first batch of a group
                optimizer.zero_grad(set_to_none=True)
            group_size = min(accum, n_batches - (i // accum) * accum)
            step_now = (i + 1) % accum == 0 or i == n_batches - 1
            scaled_loss = loss / group_size
            if scaler is not None and scaler.is_enabled():   # float16 only
                scaler.scale(scaled_loss).backward()
                if step_now:
                    if cfg.get("grad_clip"):
                        scaler.unscale_(optimizer)
                        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])
                    scaler.step(optimizer)
                    scaler.update()
            else:
                scaled_loss.backward()
                if step_now:
                    if cfg.get("grad_clip"):
                        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])
                    optimizer.step()
        else:
            # Scored chip by chip. The headline metric is an image-wise mean,
            # so pooling a batch into one update would compute something else.
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


def save_checkpoint(path, model, optimizer, scaler, cfg, seed, epoch, history,
                    best, best_epoch, started):
    """Full training state. Written to a temporary file first, then renamed, so a
    disconnect in the middle of a write cannot leave a corrupt last.pt behind."""
    state = {"model": model.state_dict(), "optimizer": optimizer.state_dict(),
             "scaler": scaler.state_dict() if scaler.is_enabled() else None,
             "config": cfg, "seed": seed, "epoch": epoch, "history": history,
             "best": best, "best_epoch": best_epoch, "elapsed": time.time() - started}
    tmp = path.with_suffix(".tmp")
    torch.save(state, tmp)
    tmp.replace(path)


def train(config_path, overrides=None, resume=False):
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
    dtype = amp_dtype(device, bool(tcfg.get("amp")))
    # bfloat16 cannot underflow the way float16 does, so it needs no scaler.
    scaler = torch.amp.GradScaler("cuda", enabled=dtype is torch.float16)

    precision = str(dtype).replace("torch.", "") if dtype else "float32"
    accum = max(int(tcfg.get("accum_steps", 1)), 1)
    print(f"{cfg['name']} | {device} | {precision} | "
          f"{count_parameters(model):,} trainable params | seed {seed}")
    print(f"batch {dcfg['batch_size']} x accumulation {accum} = effective batch "
          f"{dcfg['batch_size'] * accum}")
    print(f"train {len(loaders['train'].dataset)} chips, val {len(loaders['val'].dataset)} chips")

    select_on = cfg["eval"]["select_on"]
    val_split = cfg["eval"].get("split", "val")
    history, best, best_epoch, start_epoch, elapsed = [], -float("inf"), -1, 0, 0.0

    if resume and (out / "last.pt").exists():
        ckpt = torch.load(out / "last.pt", map_location=device, weights_only=False)
        if "optimizer" not in ckpt:
            raise SystemExit("last.pt has no optimizer state (written by an older train.py); "
                             "it cannot be resumed.")
        if ckpt["config"] != cfg:
            raise SystemExit("The config differs from the one stored in last.pt. Resuming "
                             "with different settings would make the run unreproducible.")
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        if scaler.is_enabled() and ckpt.get("scaler"):
            scaler.load_state_dict(ckpt["scaler"])
        history, best, best_epoch = ckpt["history"], ckpt["best"], ckpt["best_epoch"]
        start_epoch, elapsed = ckpt["epoch"], ckpt.get("elapsed", 0.0)
        print(f"resuming after epoch {start_epoch} (best so far {best:.4f} at epoch {best_epoch})")
    started = time.time() - elapsed
    save_every = max(int(tcfg.get("save_every", 1)), 1)

    for epoch in range(start_epoch, tcfg["epochs"]):
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

        if (epoch + 1) % save_every == 0 and epoch + 1 < tcfg["epochs"]:
            save_checkpoint(out / "last.pt", model, optimizer, scaler, cfg, seed,
                            epoch + 1, history, best, best_epoch, started)

    save_checkpoint(out / "last.pt", model, optimizer, scaler, cfg, seed,
                    tcfg["epochs"], history, best, best_epoch, started)
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
    p.add_argument("--resume", action="store_true",
                   help="continue from last.pt in the output directory, if it exists")
    args = p.parse_args()
    overrides = {f"train.{k}": v for k, v in [("seed", args.seed), ("epochs", args.epochs)]
                 if v is not None}
    train(args.config, overrides, resume=args.resume)


if __name__ == "__main__":
    main()
