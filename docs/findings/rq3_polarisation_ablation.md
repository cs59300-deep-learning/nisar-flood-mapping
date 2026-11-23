# Finding: how much of the transfer gap can polarisation explain? (RQ3, #23)

**Status: method implemented, results PENDING.** No numbers below have been
measured yet. Fill the table from `reports/polarisation_ablation/results.json`
after running the command in "Reproduce".

## Question

Sen1Floods11 is C-band VV/VH. NISAR land mode is L-band HH/HV. A drop in IoU on
NISAR could be wavelength or polarisation, and the two cannot be separated after
the fact. Can we bound the polarisation part using Sentinel-1 alone?

## Method

Train the source model on VV/VH as usual (no change to training). At test time,
feed Sentinel-1 test and Bolivia chips with the two channels permuted and measure
how much water IoU is lost. Sensor, wavelength, region and radiometry are all
fixed, so any loss comes from the channel change.

| arm | channels fed to the model | purpose |
|---|---|---|
| identity | (VV, VH) | reference, as trained |
| swap | (VH, VV) | the ablation in the ticket |
| co_only | (VV, VV) | diagnostic: how much the model needs VH |
| cross_only | (VH, VH) | diagnostic: how much the model needs VV |

Metric: per-chip mean water IoU (`iou_water_per_chip_mean`), the same headline
metric as the rest of the project. The drop is computed per chip and paired
across arms, with a 95% bootstrap interval over chips. With several seeds, the
mean and range of the drop across seeds are reported.

Code: `src/nisar_flood/experiments/polarisation_ablation.py`
Tests: `tests/test_polarisation_ablation.py`

## How to read it

The swap puts cross-pol where the model learned to expect co-pol. The real
change from VV to HH is milder, because both are co-pol. So the swap is a stress
test, not an estimate of the true polarisation effect.

- **Small drop:** strong evidence. Even a severe polarisation change costs
  little, so polarisation cannot explain much of the gap.
- **Large drop:** only an upper-bound-style signal. The model is sensitive to
  polarisation identity, but that does not show polarisation caused the gap.
  Report the share of the gap as "at most about this much".
- **Share above 100%:** the swap cost more than the whole gap, so it is harsher
  than the real change and the share is not meaningful.

## What this does not separate

The ablation isolates polarisation. The rest of the gap is a mixture of
wavelength, region and land cover (no Sen1Floods11 chip overlaps the Central
Amazon), and the sigma-nought vs gamma-nought difference (`docs/radiometry.md`).
Without this experiment, the remainder cannot be attributed to wavelength alone.

Open decision 0.2 in `docs/methods.md` (how HH/HV is mapped onto the VV/VH
input) changes what the swap stands for. If HH goes to the VV slot and HV to the
VH slot, the NISAR input is *not* a swap, and this result bounds polarisation
sensitivity but is not a replica of the zero-shot condition.

## Results

Sentinel-1 test split, `iou_water_per_chip_mean`. Seeds: PENDING.

| arm | IoU | drop vs identity (95% CI) |
|---|---|---|
| identity | PENDING | |
| swap | PENDING | PENDING |
| co_only | PENDING | PENDING |
| cross_only | PENDING | PENDING |

Gap to NISAR zero-shot (from RQ1): PENDING.
Swap drop as a share of that gap: PENDING.

Bolivia (15 chips, out-of-distribution): PENDING. Too few chips for a tight
interval; report it, but do not lean on it.

## Reproduce

```bash
nisar-flood polarisation-ablation \
    --checkpoint runs/unet_resnet50/seed0/best.pt \
                 runs/unet_resnet50/seed1/best.pt \
                 runs/unet_resnet50/seed2/best.pt \
    --nisar-iou <zero-shot NISAR per-chip mean water IoU from RQ1>
```

Writes `reports/polarisation_ablation/results.json` and `per_chip.csv`.
