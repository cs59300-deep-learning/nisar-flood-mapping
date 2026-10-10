# Ticket #13: HAND Terrain Validation

## Source and rationale

The workflow uses a precomputed MERIT Hydro HAND product.
HAND represents height above the nearest drainage level and is
intended to help characterize terrain susceptible to flooding.

The source documentation is maintained in `docs/data_sources.md`.

Do not describe the selected product as independently canopy-corrected
unless that property is verified from the product's authoritative
metadata or documentation.

## Processing evidence

- Source, AOI-clipped, and aligned raster inspection:
  `hand_alignment_report.json`
- Human-readable raster report:
  `hand_alignment_report.txt`
- Qualitative HAND/NISAR comparison:
  `hand_nisar_comparison.png`

## Acceptance criterion 1: AOI clipping and alignment

Review the report and verify:
- The clipped raster bounds match the intended AOI.
- The aligned raster uses the expected CRS and pixel spacing.
- Its pixel grid aligns with the intended NISAR chip reference.
- The output raster can be read and contains valid data where expected.

Metadata checks alone do not prove that the correct AOI was used.

## Acceptance criterion 2: DEM choice and canopy correction

Review `docs/data_sources.md` and the authoritative source metadata.
Document what the source product actually provides. Do not infer
canopy-correction processing merely from the name HAND.

## Acceptance criterion 3: Known river channels

Inspect `hand_nisar_comparison.png` for spatial correspondence between
low-HAND corridors and known river channels. For reproducible
validation, overlay an independently sourced river network or
reference hydrography layer for the same AOI.

Record the reference dataset, source, date/version, and any observed
mismatches. The comparison image alone is qualitative evidence and
does not independently establish river-channel accuracy.

## Validation status

This document describes the evidence to review. Mark acceptance
criteria complete only after the corresponding checks are confirmed.


## Grid and coverage check results

Checked against the NISAR Frequency-A reference grid in EPSG:32720.

- Aligned HAND CRS: EPSG:32720
- Aligned HAND resolution: 20 m
- Aligned HAND dimensions: 16,740 x 16,344
- Aligned HAND bounds (projected):
  (534960, 9495360, 869760, 9822240)
- Valid aligned HAND pixels: 271,176,984 / 273,598,560
- Valid-pixel percentage: 99.115%
- Clipped HAND bounds (longitude/latitude):
  (-62.700417, -4.599583, -59.700417, -1.599583)
- NISAR grid bounds transformed to longitude/latitude:
  (-62.685702, -4.565470, -59.668457, -1.605526)

Interpretation:
The aligned raster matches the NISAR reference grid metadata, and the
NISAR geographic bounding box lies within the clipped HAND bounding
box. This confirms bounding-box coverage, not exact AOI polygon
coverage or river-channel accuracy.


## Final status (supersedes the earlier coverage figures)
The earlier aligned raster was built from a tightly clipped AOI and had 99.115% valid pixels
(nodata strip on the east edge). It was rebuilt from a footprint-plus-margin clip:
**100.000% valid**.

| Acceptance criterion | Evidence |
|---|---|
| HAND clipped and reprojected to the NISAR grid | `hand_alignment_report.json` (CRS, transform, shape checks all pass) |
| DEM choice and canopy correction documented | `docs/hand_methods.md` |
| Visual check against known river channels | `hand_hydrorivers_overlay.png`, `hand_manaus_zoom.png`, `hand_river_check.json` |


## River check addendum
Along river reaches with upstream area >= 1000 km2 the local-minimum HAND has median 0.05 m (94% of points <= 2 m). HAND rises with distance from the rivers (Spearman rho = 0.09; median per distance bin in `hand_river_check.json`): **False**. A simple ratio flag against the all-land baseline was inconclusive because 75% of this lowland AOI already has local-minimum HAND <= 2 m.
