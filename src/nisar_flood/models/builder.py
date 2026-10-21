"""Build the segmentation models for E3 from a config dict.

Both arms share this builder and the training loop, so the CNN baseline (#19)
and the transformer arm (#20) differ only by the `encoder` name in their config.
That is what makes their numbers comparable.
"""
import segmentation_models_pytorch as smp

# Encoders we have configs for. MaxViT comes from timm, hence the "tu-" prefix
# that segmentation_models_pytorch uses for timm-universal encoders.
ENCODERS = {
    "resnet50": "resnet50",                       # CNN baseline (#19)
    "maxvit_base": "tu-maxvit_base_tf_512",       # transformer arm (#20)
}


def build_model(cfg):
    """Return an untrained model described by the `model` block of a config.

    ImageNet weights are trained on 3-channel RGB. We feed 2 channels (VV, VH),
    so segmentation_models_pytorch adapts the first convolution by summing the
    pretrained kernels across the missing channel. Pretrained weights still help
    markedly here: the hand-labelled split is only 252 training chips.
    """
    arch = cfg.get("arch", "unet").lower()
    if arch != "unet":
        raise ValueError(f"only the unet decoder is wired up, got {arch!r}")

    encoder = cfg["encoder"]
    return smp.Unet(
        encoder_name=ENCODERS.get(encoder, encoder),
        encoder_weights=cfg.get("encoder_weights", "imagenet"),
        in_channels=cfg.get("in_channels", 2),
        classes=cfg.get("classes", 2),
    )


def count_parameters(model):
    """Trainable parameter count, reported at the start of a run."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
