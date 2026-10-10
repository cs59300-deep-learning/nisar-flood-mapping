# Ticket #13 evidence index

| Acceptance criterion | Evidence |
|---|---|
| HAND clipped to the AOI and reprojected to match the NISAR chips | `hand_alignment_report.json` / `.txt` (CRS, transform, shape match the NISAR grid; 100% valid), `hand_nisar_comparison.png`, `hand_provenance.json` |
| DEM choice and canopy correction documented | `../hand_methods.md`, `../data_sources.md` |
| Visual check against known river channels | `hand_hydrorivers_overlay.png`, `hand_manaus_zoom.png`, `hand_river_check.json`, `hand_validation_notes.md` |

**The aligned raster itself is not in git** (945 MB). It is `hand_aoi.tif` in the Drive folder `nisar_ticket13_hand`.
Verify you have the same file with the SHA-256 in `hand_provenance.json`
(`dffb657e980e138e...`).
