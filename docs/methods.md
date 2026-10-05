# Methods and fallback ladder

TODO - issue #35.

**Status:** DRAFT for issue #35. Written before any NISAR results exist.
**Freeze rule:** when this file is merged to `main`, tag that commit `protocol-v1`. After that, changes go in the Amendments log (section 7) with a date and a reason, never as silent edits.

Legend: **[PROPOSED]** = a suggestion the team still has to confirm. **[TODO]** = information someone still has to supply.

## 0. Open decisions (resolve before freezing)
1. **Primary model.** The README names SegFormer with a MiT-B4 encoder (U-Net as reference). Issues #19 and #20 name U-Net + ResNet50 and U-Net + MaxViT. One list must be chosen.
2. **Channel mapping for NISAR.** The source models see VV/VH. NISAR provides HH/HV, and only 4 of the 8 granules carry HV. How HH/HV is fed to a VV/VH model is a core choice for RQ3. [TODO]
3. **Fine-tuning draws and holdout** (section 4.5) [PROPOSED].
4. **Regime definitions** for high and low water (from the Manaus gauge series, #12). [TODO]

## 1. Research questions
- **RQ1 (zero-shot):** how much does a Sentinel-1-trained flood model lose when applied directly to NISAR, for open water and flooded forest separately?
- **RQ2 (adaptation):** how many labelled NISAR chips (0 / 10 / 25 / all) are needed to recover performance?
- **RQ3 (cause):** how much of the gap is explained by wavelength (C vs L band) and how much by polarization (VV/VH vs HH/HV)?

## 2. Data
**Source: Sen1Floods11 v1.1, hand-labelled subset.** 446 chips (512 x 512, VV and VH in dB). Splits: train 252, val 89, test 90, Bolivia 15 (Bolivia is a held-out flood event). Inputs are clipped to [-50, 1] dB and scaled to [0, 1]. The dataset's no-data label (-1) is remapped to 255 and ignored everywhere (loader, loss, metric).

**Target: NISAR L2 GCOV, path 68 / frame 90, descending.** Eight granules from 18 Jun to 22 Sep 2026 (`data/granule_manifest.csv`, PR #40; verify against the file). All are PROVISIONAL. The frame alternates polarization modes: only 18 Jun, 12 Jul, 29 Aug and 22 Sep carry HV, the others are HH only.

## 3. Models
[TODO: fill in after decision 0.1.] Whatever is chosen is trained on the Sen1Floods11 train split, the checkpoint is selected by the headline metric on the validation split, and test and Bolivia are evaluated once, after training.

## 4. Evaluation protocol (to be frozen)
1. **Headline metric:** per-chip mean of water-class IoU, with each chip weighted equally. This is how the Sen1Floods11 paper (Bonafilia et al., CVPRW 2020) reports IoU. Implemented as `iou_water_per_chip_mean` in `metrics/iou.py`.
2. **Also reported:** pooled water IoU, not-water IoU, precision, recall and F1, plus the number of chips that could be scored. Pixels labelled 255 are never counted.
3. **Chips with no water** in either label or prediction cannot be scored for water IoU; they are skipped in the per-chip mean and the count is reported.
4. **Zero-shot:** the source checkpoint is applied to NISAR chips with no weight update. Results are reported overall and per regime (open water, flooded forest). The HH/HV to VV/VH mapping is decision 0.2. [TODO]
5. **Fine-tuning [PROPOSED]:** N = 0, 10, 25, all labelled NISAR chips. For N = 10 and 25, 5 random draws with fixed seeds, reported as mean and standard deviation. Evaluation chips come from areas that do not overlap any fine-tuning chip (at least one chip of spatial separation), to avoid leakage between neighbouring chips.
6. **Seeds [PROPOSED]:** at least 3 training seeds per source model; report mean and spread.
7. **Transfer gap:** headline IoU on the Sen1Floods11 test split minus zero-shot headline IoU on NISAR, per regime. This difference includes geography as well as sensor (see section 6).
8. **RQ3 design:** [TODO: wavelength vs polarization separation, for example using the four dual-pol granules vs HH-only.]
9. **Hypotheses and thresholds:** [TODO: state expected direction before results.]

## 5. Fallback ladder (low-water baseline)
If a usable low-water frame is not available, try these in order and stop at the first that works.
1. **NISAR dry-season granule.** [TODO: current status. PR #40 lists 22 Sep as a low-water candidate; the gauge series suggests the river was still falling then, so state how "low water" is decided.]
2. **Prior-year ALOS-2 PALSAR-2 dry-season scene** (issue #36).
3. **JERS-1 low-water wetland mask.**
4. **Never-flooded uplands** within the granules already held.

[TODO: the condition for moving from one rung to the next.]
**Independence:** the headline result is scored against HAND/gauge-derived labels and the published reference, so it does not depend on the low-water frame.

## 6. Label uncertainty (limitations)
**Source labels (Sen1Floods11).**
- The hand labels were produced by analysts correcting Sentinel-2-derived water maps; areas they could not identify confidently are marked no data and ignored. Label error has not been quantified.
- Water is a minority class: 9.5% (train), 11.0% (val), 12.5% (test), 15.9% (Bolivia) of valid pixels.
- None of the 446 chips overlap the Central Amazon study area, so any NISAR gap mixes sensor effects with a change of region and land cover. Flooded-forest coverage in Sen1Floods11 has not been measured. [to verify]
- Only the train split was checked for chips with no labelled pixels (1 of 252).

**Target labels (NISAR).** [TODO: teammate to complete]
- Stage + HAND gives a modelled inundation estimate, not an observation.
- JERS-1 masks are historical and coarse. [TODO: date and resolution]
- Temporal-change labels are silver labels and carry extra noise.
- Sentinel-1 flood maps are a comparison baseline only, never ground truth.

## 7. Amendments log
| Date | Section | Change | Reason |
|---|---|---|---|
| | | | |
