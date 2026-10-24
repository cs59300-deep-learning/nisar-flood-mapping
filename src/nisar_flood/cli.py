"""Single entry point for the project's commands.

    nisar-flood download --root data/sen1floods11
    nisar-flood check    --root data/sen1floods11
    nisar-flood train    --config configs/unet_resnet50.yaml
    nisar-flood evaluate --checkpoint runs/unet_resnet50/seed0/best.pt
"""
import argparse


def main():
    p = argparse.ArgumentParser(prog="nisar-flood", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="fetch the Sen1Floods11 hand-labelled split")
    dl.add_argument("--root", default="data/sen1floods11")

    ck = sub.add_parser("check", help="verify split sizes, files and value ranges")
    ck.add_argument("--root", default="data/sen1floods11")

    tr = sub.add_parser("train", help="train a source model")
    tr.add_argument("--config", required=True)
    tr.add_argument("--seed", type=int)
    tr.add_argument("--epochs", type=int)

    ev = sub.add_parser("evaluate", help="score a checkpoint on the held-out splits")
    ev.add_argument("--checkpoint", required=True)
    ev.add_argument("--splits", nargs="+", default=["test", "bolivia"])
    ev.add_argument("--root")

    args = p.parse_args()

    if args.command in ("download", "check"):
        from .datasets import sen1floods11
        getattr(sen1floods11, args.command)(args.root)
    elif args.command == "train":
        from .training.train import train
        overrides = {f"train.{k}": v for k, v in
                     [("seed", args.seed), ("epochs", args.epochs)] if v is not None}
        train(args.config, overrides)
    elif args.command == "evaluate":
        from .training.evaluate import evaluate
        evaluate(args.checkpoint, tuple(args.splits), args.root)


if __name__ == "__main__":
    main()
