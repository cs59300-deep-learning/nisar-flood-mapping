# Methods and fallback ladder

**Status:** DRAFT for issue #35. Written before any NISAR results exist.
**Freeze rule:** when this file is merged to `main`, tag that commit `protocol-v1`. After that, changes go in the Amendments log (section 7) with a date and a reason, never as silent edits.

Legend: **[PROPOSED]** = a suggestion the team still has to confirm. **[TODO]** = information someone still has to supply.

## 0. Open decisions (resolve before freezing)
1. **Primary model.** The README names SegFormer with a MiT-B4 encoder (U-Net as reference). Issues #19 and #20 name U-Net + ResNet50 and U-Net + MaxViT. One list must be chosen.
2. **Channel mapping for NISAR.** The source models see VV/VH. NISAR provides HH/HV, and only 4 of the 8 granules carry HV. How HH/HV is fed to a VV/VH model is a core choice for RQ3. [TODO]
3. **Fine-tuning draws and holdout** (section 4.5) [PROPOSED].
4. **Regime definitions** for high and low water (from the Manaus gauge series, #12). [TODO]
5. **Shared dB window.** The Sen1Floods11 loader clips to [-50, 1] dB; the NISAR convention (`docs/radiometry.md`) clamps at -40 dB. One window and one scaling function must be used for both domains before any training (#19). [TODO]

## 1. Research questions
- **RQ1 (zero-shot):** how much does a Sentinel-1-trained flood model lose when applied directly to NISAR, for open water and flooded forest separately?
- **RQ2 (adaptation):** how many labelled NISAR chips (0 / 10 / 25 / all) are needed to recover performance?
- **RQ3 (cause):** how much of the gap is explained by wavelength (C vs L band) and how much by polarization (VV/VH vs HH/HV)?

## 2. Data
**Source: Sen1Floods11 v1.1, hand-labelled subset** (`docs/data_sources.md`). 446 chips (512 x 512; VV and VH; sigma-nought in dB). Splits: train 252, val 89, test 90, Bolivia 15 (a held-out flood event). The label -1 (no data) is remapped to 255 and ignored in the loader, the loss and the metric.

**Target: NISAR L2 GCOV, collection `NISAR_L2_GCOV_PROVISIONAL_V1`, path 68 / frame 90, descending** (ASF DAAC). Eight granules, 18 Jun to 22 Sep 2026, listed in `data/granule_manifest.csv`. All are PROVISIONAL products. The frame alternates polarisation modes: only 18 Jun, 12 Jul, 29 Aug and 22 Sep carry HV; the other four are HH only. GCOV is gamma-nought in linear power.

**Common preprocessing** (`docs/radiometry.md`). NISAR is converted from linear gamma-nought to dB, values below -40 dB are clamped up to -40 dB, and both domains then go through the same dB-to-[0, 1] scaling. [TODO: confirm the window, see decision 0.5.]

**NISAR validity** (`docs/validity_mask.md`). A NISAR pixel is valid only where the GCOV `mask` layer equals 1 (0 = partially focused or invalid, 255 = outside the acquisition extent, other values = subswaths). Invalid pixels are excluded from every statistic and from scoring.

## 3. Models
[TODO: fill in after decision 0.1.] Whatever is chosen is trained on the Sen1Floods11 train split, the checkpoint is selected by the headline metric on the validation split, and test and Bolivia are evaluated once, after training.

## 4. Evaluation protocol (to be frozen)
1. **Headline metric:** per-chip mean of water-class IoU, with each chip weighted equally. This is how the Sen1Floods11 paper (Bonafilia et al., CVPRW 2020) reports IoU. Implemented as `iou_water_per_chip_mean` in `metrics/iou.py`.
2. **Also reported:** pooled water IoU, not-water IoU, precision, recall and F1, plus the number of chips that could be scored. Pixels labelled 255 are never counted.
3. **Chips with no water** in either label or prediction cannot be scored for water IoU; they are skipped in the per-chip mean and the count is reported.
4. **Zero-shot:** the source checkpoint is applied to NISAR chips with no weight update. Results are reported overall and per regime (open water, flooded forest). The HH/HV to VV/VH mapping is decision 0.2. [TODO]
5. **Fine-tuning [PROPOSED]:** N = 0, 10, 25, all labelled NISAR chips. For N = 10 and 25, 5 random draws with fixed seeds, reported as mean and standard deviation. See item 12 for the splitting rule.
6. **Seeds [PROPOSED]:** at least 3 training seeds per source model; report mean and spread.
7. **Transfer gap:** headline IoU on the Sen1Floods11 test split minus zero-shot headline IoU on NISAR, per regime. This difference includes geography as well as sensor (see section 6).
8. **RQ3 design:** [TODO: wavelength vs polarization separation, for example using the four dual-pol granules vs HH-only.]
9. **Hypotheses and thresholds:** [TODO: state expected direction before results.]
10. **Same preprocessing in both domains.** One shared function turns dB values into model input. There are no domain-specific scalings or normalisation statistics. [TODO: link the function]
11. **NISAR scoring mask.** NISAR pixels whose validity mask is not 1 are set to the ignore value (255) in the labels, so they are excluded from IoU, precision, recall and F1, as no-data pixels are in Sen1Floods11. The 255 in the NISAR `mask` layer ("outside the acquisition extent") and the 255 in our labels ("ignore") are different arrays.
12. **Chip overlap and splitting.** NISAR chips are 512 x 512 at stride 400 (#9; confirm in the merged code), so adjacent chips share 112 pixels. Fine-tuning and evaluation chips are assigned by spatial block, never at random, and no two chips on opposite sides may overlap. [PROPOSED: block size, and a minimum gap of one full chip]

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

**Sensor and processing differences.**
- Sen1Floods11 is sigma-nought; NISAR GCOV is gamma-nought. The two differ by roughly cos(incidence angle), a few dB that varies with angle (`docs/radiometry.md`). This is accepted, not corrected, and adds to the transfer gap alongside wavelength and polarisation, so RQ3 cannot attribute the whole gap to those two.
- NISAR granules are PROVISIONAL products. Values may change on reprocessing, so granule IDs and the processing version are recorded.

## 7. Amendments log
| Date | Section | Change | Reason |
|---|---|---|---|
| | | | |
