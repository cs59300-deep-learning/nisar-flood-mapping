# Radiometry

**Why this document exists.** Sen1Floods11 and NISAR GCOV arrive in different
radiometric conventions. If we feed them to the same model without
reconciling those conventions, the mismatch is a *hidden domain shift*: the
model learns to tell the two sensors apart by their radiometric offset rather
than by the physics we care about, and that silently contaminates the
polarisation ablation (#23). This document records what each dataset actually
contains and the single convention we normalise both onto.

Implemented in `src/nisar_flood/pipeline/radiometry.py`; tested in
`tests/test_radiometry.py`.

---

## The two conventions

| | NISAR L2 GCOV | Sen1Floods11 (Sentinel-1) |
|---|---|---|
| Quantity | **gamma-nought (γ⁰)** | **sigma-nought (σ⁰)** |
| Scale | **linear power** | **decibels (dB)** |
| Terrain treatment | radiometrically **terrain-flattened** (β⁰→γ⁰ RTC) | ellipsoid/range-Doppler terrain-corrected GRD |
| Polarisations used | HH, HV (frequency A diagonal terms `HHHH`, `HVHV`) | VV, VH |
| Produced by | ASF NISAR SDS, area-based RTC + geocoding | Google Earth Engine `COPERNICUS/S1_GRD` |
| Typical range | ~0 to a few (unitless power ratio) | ~ -30 to 0 dB |

### NISAR GCOV — γ⁰, linear

The GCOV product stores the elements of the polarimetric covariance matrix.
The diagonal terms `HHHH` and `HVHV` are calibrated backscatter **power**,
corrected for radiometric *and* terrain distortions, and expressed as
**gamma-nought power values in linear units** (ASF NISAR GCOV documentation).
Processing normalises the backscatter coefficient from β⁰ to γ⁰ with an
area-based radiometric terrain correction, then geocodes with area-based
adaptive multilooking. These values are non-negative power ratios — **not**
dB. Our reader (`nisar_flood.pipeline.gcov.read_gcov`) returns them as-is in
`GCOVData.hh` / `GCOVData.hv`.

### Sen1Floods11 — σ⁰, dB

The Sen1Floods11 Sentinel-1 chips are Google Earth Engine `COPERNICUS/S1_GRD`
exports. Earth Engine applies orbit files, border/thermal noise removal,
radiometric calibration, and terrain correction, and delivers the backscatter
coefficient **σ⁰ in decibels** (GEE Sentinel-1 documentation). So these chips
are *already* in dB — no log conversion is needed, only a shared floor.

---

## The common convention

> **gamma-nought-style backscatter in decibels (dB), clamped so nothing sits
> below a physical floor of -40 dB.**

dB is the natural shared target because:

- Sen1Floods11 is already dB, so we avoid round-tripping it unnecessarily.
- SAR backscatter spans orders of magnitude in linear power; dB compresses
  that into a near-Gaussian range that convolutional/transformer encoders
  handle far better than raw linear power.
- The source-domain model is pretrained on dB inputs, so the target domain
  must be dB for zero-shot transfer to mean anything.

Conversion is `10 · log10(power)`:

| Input | Function | Action |
|---|---|---|
| GCOV γ⁰ (linear) | `normalise_gcov_gamma0` | `10·log10`, then clamp to floor |
| Sen1Floods11 σ⁰ (dB) | `normalise_sen1floods11` | clamp to floor only (no log) |

Both share `linear_to_db` / `db_to_linear` primitives and the same
`DB_FLOOR = -40.0`.

### The -40 dB physical floor

Nothing below **-40 dB** is real backscatter for these sensors — below that
you are looking at the noise floor, calibration residue, radar shadow, or
exact-zero masked pixels. We clamp such values **up to -40 dB** rather than
leaving them as `-inf` (which `10·log10(0)` would produce) or `nan`. This:

- keeps the input finite and bounded for the network,
- prevents a handful of near-zero pixels from dominating normalisation
  statistics,
- gives both domains the *same* lower bound, so a dark pixel in NISAR and a
  dark pixel in Sentinel-1 land at the same value.

Genuine no-data (`nan`) is **preserved as `nan`**, not pushed to the floor, so
downstream validity masking (#7) still works. Zeros and negatives, by
contrast, go to the floor.

---

## Known residual: σ⁰ vs γ⁰

Normalising to a shared dB scale removes the gross convention mismatch
(linear-vs-dB, and the terrain-flattening difference is largely absorbed by
both being terrain-corrected). It does **not** erase the definitional
difference between **sigma-nought** (normalised to the ground area) and
**gamma-nought** (normalised to the area perpendicular to the look
direction). The two differ by a factor of roughly `cos(θ_inc)` — a few dB that
varies with incidence angle.

We accept this residual rather than attempting a full σ⁰↔γ⁰ reprojection
because:

- it is small and smoothly varying relative to the flood signal,
- a proper conversion needs per-pixel local incidence angle we do not reliably
  have for both products,
- it is a known, bounded quantity we can reason about in error analysis (#26),
  not a silent linear-vs-dB blunder.

This is called out so the polarisation ablation interprets any remaining
cross-sensor offset correctly instead of mistaking it for a polarisation
effect.

---

## Before / after

See `reports/figures/radiometry_before_after.png`, generated by
`scripts/radiometry_histograms.py`. It shows, for one granule:

- **before** — GCOV γ⁰ in raw linear power (heavily right-skewed, long tail), and
- **after** — the same data in dB after `normalise_gcov_gamma0` (near-Gaussian,
  bounded below at the -40 dB floor).

The script runs on a real GCOV granule when one is present (path from
`data/granule_manifest.csv`); when no granule is available locally it falls
back to a synthetic γ⁰ field with NISAR-like statistics so the figure is
always reproducible without committing the ~2 GB raw product (see
`docs/data_sources.md` on why raw granules are not committed). The committed
figure is labelled with which source produced it.

---

## References

- ASF, *Geocoded Polarimetric Covariance (GCOV)* — γ⁰ power values.
- NASA Earthdata, *NISAR Geocoded Polarimetric Covariance Product* — β⁰→γ⁰ RTC.
- Google Earth Engine, *Sentinel-1 Algorithms* — σ⁰ in dB from GRD.
- Small & Schubert, *Flattening Gamma: Radiometric Terrain Correction for SAR*.
