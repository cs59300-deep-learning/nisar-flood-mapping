# FloodTransfer: Cross-Satellite Flood Mapping with NISAR

## Overview

**FloodTransfer** investigates whether deep-learning flood segmentation
models trained on **Sentinel-1 SAR imagery** can transfer effectively to
the new **NISAR L-band SAR imagery**.

The project measures the performance gap between the two satellite
domains, examines differences between **open water and flooded forest**,
and studies how much labeled NISAR data is required to adapt the model
and recover performance.

## Problem

Floods often occur during storms and at night, when optical satellite
imagery can be limited by clouds and lack of illumination. SAR provides
day-and-night, cloud-penetrating observations.

However, existing flood models are largely developed using Sentinel-1
C-band data. NISAR uses L-band radar, which interacts differently with
vegetation and can reveal flooded forests that shorter-wavelength radar
may miss.

The key question is:

> **Can a flood model trained on Sentinel-1 transfer to NISAR, and how
> much adaptation is needed?**

## Research Questions

1.  **Zero-shot transfer:** How much does a Sentinel-1-trained model's
    performance drop when applied directly to NISAR?
2.  **Adaptation:** How many labeled NISAR samples are needed to recover
    performance?
3.  **Cause of the gap:** How much of the performance difference can be
    explained by wavelength and polarization differences?

## Approach

The project follows three main phases:

### 1. Pretraining

Train a **U-Net** flood segmentation model using the **Sen1Floods11**
Sentinel-1 dataset.

### 2. Zero-Shot Evaluation

Apply the trained model directly to real NISAR imagery without
fine-tuning and measure its IoU performance.

### 3. Fine-Tuning

Fine-tune the model using different amounts of labeled NISAR data:

-   0 chips
-   10 chips
-   25 chips
-   All available labeled chips

This produces a recovery curve showing how much labeled data is required
to close the transfer gap.

## Study Focus

Performance is evaluated separately for:

-   **Open water**
-   **Flooded forest**

The project also examines polarization differences between Sentinel-1
and NISAR as part of the analysis.

## Data

-   **Sentinel-1:** Sen1Floods11 benchmark dataset
-   **NISAR:** Real NISAR L-band imagery from the Central Amazon
    floodplain
-   **Study region:** Solimões--Negro confluence / Central Amazon
    floodplain

The project has already established a working NISAR data pipeline,
including data download, HDF5 reading, dual-polarization processing, and
initial water/land separability analysis.

## Ground Truth

Because optical imagery cannot reliably observe flooding beneath forest
canopies, the project uses independent sources for validation:

1.  **Hydrology:** River-stage data combined with canopy-corrected
    terrain (HAND)
2.  **Expert wetland maps:** JERS-1 Amazon inundation masks
3.  **Temporal change:** Used as a supplementary/silver-label source

Sentinel-1 flood maps are used as a comparison baseline rather than as
final ground truth.

## Evaluation

The primary metric is **Intersection over Union (IoU)**, measured
separately by flood regime.

The main outputs are:

-   Baseline Sentinel-1 model performance
-   Zero-shot performance on NISAR
-   Cross-satellite performance gap
-   Fine-tuning recovery curve
-   Analysis of wavelength/polarization effects

## Expected Deliverables

-   A benchmark of Sentinel-1 → NISAR flood-model transfer
-   A labeled NISAR flood dataset for future research
-   Complete training and evaluation code
-   An interactive flood-mapping demo
-   Research report and presentation

## Group Members

1.  **Varun Teja Chundru**
2.  **Nidhi Musale**
3.  **Yashada Ajit Tembe**
4.  **Pushan Verma**

## Course

**CS 59300 --- Application of Deep Learning**\
Research-Based Course Project\
**Instructor:** Dr. Zesheng Chen\
**September 2026**

## Project Goal

> **Measure how well existing flood AI transfers to NISAR, identify
> where it fails, and determine how much NISAR data is needed to make it
> work.**
