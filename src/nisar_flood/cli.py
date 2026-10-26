"""Single entry point for the project's commands.

    nisar-flood download --root data/sen1floods11
    nisar-flood check    --root data/sen1floods11
    nisar-flood train    --config configs/unet_resnet50.yaml
    nisar-flood evaluate --checkpoint runs/unet_resnet50/seed0/best.pt
    nisar-flood label-init   --chips data/nisar/chips --out data/labels/annotations
    nisar-flood label-export --chips data/nisar/chips --annotations data/labels/annotations
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

    li = sub.add_parser("label-init", help="seed a QGIS annotation file per chip (#28)")
    li.add_argument("--chips", required=True)
    li.add_argument("--out", required=True)
    li.add_argument("--labeller", default="")
    li.add_argument("--overwrite", action="store_true",
                    help="replace annotation files that already exist")

    le = sub.add_parser("label-export", help="burn annotations into label rasters (#28)")
    le.add_argument("--chips", required=True)
    le.add_argument("--annotations", required=True)
    le.add_argument("--out", default="data/labels/masks")

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
    elif args.command == "label-init":
        from .labelling.chip_export import start_annotations_directory
        created = start_annotations_directory(args.chips, args.out, labeller=args.labeller,
                                              overwrite=args.overwrite)
        print(f"{len(created)} annotation files written to {args.out}")
    elif args.command == "label-export":
        from .labelling.chip_export import rasterise_directory
        rows = rasterise_directory(args.chips, args.annotations, args.out)
        for row in rows:
            print(f"{row['chip_id']:30s} water {row['water_px']:7d} px  "
                  f"excluded {row['excluded_px']:7d}  no-data {row['no_data_px']:7d}")
        print(f"\n{len(rows)} chips written to {args.out}")


if __name__ == "__main__":
    main()
