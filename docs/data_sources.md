# Data sources and storage

Two things live here: **where each external dataset comes from**, and **where
our own derived data lives** so all four of us can reach it.

---

## Part 1 — External data sources

### NISAR L2 GCOV (primary)

| | |
|---|---|
| Source | ASF DAAC, NASA Earthdata |
| Access | `asf_search` (`dataset="NISAR"`, `processingLevel="GCOV"`) |
| Collection | `NISAR_L2_GCOV_PROVISIONAL_V1` |
| Auth | Earthdata Login, credentials in `~/.netrc` — never in this repo |
| Selected | path 68 / frame 90, descending — see `data/granule_manifest.csv` |
| Issue | #5, #6 |

Only **PROVISIONAL** products (CRID P05023). Never mix with BETA: different
processing software, and the difference would contaminate the radiometry (#8)
and the polarisation ablation (#23).

PROVISIONAL covers acquisitions from **17 June 2026** onward, so nothing
earlier is available at this maturity.

**The frame alternates polarisation modes every 12 days.** Only `DHDH`
granules carry HV; `SHSH` granules are HH-only and the HV was never recorded.
Usable dual-pol dates: 18 Jun, 12 Jul, 29 Aug, 22 Sep 2026.

Read `frequencyA` (20 MHz), not `frequencyB` (5 MHz, coarser).

### Sen1Floods11 (source-domain training data)

| | |
|---|---|
| Source | Public Google Cloud Storage bucket (~14 GB); a Kaggle mirror also exists |
| Scope | **Hand-labelled split only** — 446 chips |
| Issue | #17 |

Reproducing all four of their label-source models is 3-4x the work for no
extra credit. **Labels use `-1` for no-data and it must be masked out of both
the loss and the IoU** — this silently corrupts results otherwise.

### MERIT Hydro HAND (terrain reference)

| | |
|---|---|
| Source | MERIT Hydro, precomputed HAND band (~90 m) |
| Issue | #13 |

Use the precomputed, canopy-corrected band. Do **not** use SRTM or Copernicus
GLO-30: those are *surface* models measuring treetops, which biases HAND
upward by tens of metres under Amazon canopy — wrong exactly where we care.

### Manaus river gauge

| | |
|---|---|
| Source | ANA HidroWeb, station Porto de Manaus |
| Access | ANA SOAP endpoint (`zeep`); manual CSV export is an acceptable fallback |
| Lands in | `data/gauge/` |
| Issue | #12 |

Verify the station code on the portal rather than trusting a remembered value.

### Wetland and surface-water reference layers

| | |
|---|---|
| JERS-1 Amazon dual-season wetland masks | ORNL DAAC |
| JRC Global Surface Water | permanent vs. flood water separation |
| Lands in | `data/reference/` |
| Issue | #15 |

### ALOS-2 PALSAR-2 (contingency)

JAXA/ASF, prior-year dry-season scene over the same footprint (#36). Now a
cross-check rather than a primary fallback, since a real low-water NISAR
granule exists (22 Sep 2026).

---

## Part 2 — Where our data lives

### The principle

**The manifest replaces sharing raw data.** `data/granule_manifest.csv` holds
exact granule IDs, so anyone can re-download the identical granules from NASA.
Copying ~2 GB files between four people adds nothing the manifest does not
already guarantee, and creates copies that can drift.

### The tiers

| What | Size | Where | Why |
|---|---|---|---|
| Raw GCOV granules | ~1.9 GB each | **Not shared** | Reproducible from the manifest; NASA is authoritative |
| Chips, reference layers | <500 MB | **Hugging Face**, private dataset repo | Works from Kaggle, Colab and local alike |
| Labels, manifests | KB | **git**, this repo | Small, and they need revision history |
| Public dataset release | — | **Same HF repo**, flipped public | Sprint 5 deliverable (#30) |

### Why Hugging Face rather than Kaggle

- **One home.** Working data and the public release are the same repo — at
  release we flip visibility and add a dataset card, with no migration.
- **Not tied to one platform.** A Kaggle dataset only mounts inside Kaggle.
  If the 30 GPU-h/week budget (#19) runs out and we move to Colab, nothing
  about the data setup breaks.
- **Real versioning.** HF repos are git, so a run can pin an exact revision:
  "trained on revision `abc123`". This matters for #24's multi-seed curve.
- **Capacity.** Free tier gives 100 GB private storage; we need under 1 GB.

Trade-off accepted: Kaggle attaches datasets with zero transfer, whereas HF
downloads at session start — about a minute for 500 MB, once per session.

### Setup

1. An HF organisation with all four members.
2. One **private** dataset repo for chips and reference layers.
3. An HF access token stored in **Kaggle Secrets** so notebooks can reach the
   private repo.
4. Pull with `huggingface_hub.snapshot_download`.

### Do not

- **Do not use Git LFS on GitHub.** The free quota is 1 GB — a single granule
  exhausts it and the team hits a paywall mid-sprint.
- **Do not commit credentials.** Earthdata goes in `~/.netrc`, HF tokens in
  Kaggle Secrets or the local HF cache. Never in this repo.
- **Do not commit raw granules or chips.** `data/.gitignore` already blocks
  HDF5 and GeoTIFF; manifests and CSVs stay tracked.

### Fallback

If HF setup stalls, a shared Google Drive folder is acceptable — worse for
training and with no versioning, but far better than four people each
improvising. The failure mode to avoid is not picking the imperfect option;
it is not picking one.
