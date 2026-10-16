# Labelling protocol

**Agree these rules before anyone labels.** Four people labelling ~50 gold
chips (#30) by different mental rules wastes ~40 person-hours and produces a
noisy evaluation set that quietly corrupts every IoU number downstream. This
document fixes the rules once (issue #27). It is read-and-agreed by all four
members before the calibration round (#29).

---

## The honest limitation up front

We label from SAR backscatter with hydrological side-evidence. We do **not**
have reliable optical confirmation of flooding **under the Amazon canopy** -
optical sensors see treetops, not the water beneath them. So we refuse to
guess at flooded forest from optical cues.

The consequence, stated as a limitation rather than hidden:

> **Open water is the headline, labelled class. Suspected flooded vegetation
> is a separate, *excluded* class - flagged, never labelled as flood - and the
> only admissible evidence for the vegetated case is HAND + river gauge, not
> optical imagery.**

This bounds the claim our project can make: we measure Sentinel-1 -> NISAR
transfer **for open-water flood extent**, and we report flooded-forest
separately and qualitatively. Pretending otherwise would inflate IoU with
labels we cannot defend.

---

## Class scheme

Label values match **Sen1Floods11** exactly, so a Sentinel-1-trained model's
output maps straight onto our NISAR evaluation with no relabelling. Sen1Floods11
hand labels use water = 1, non-water = 0, no-data = -1; we keep that and add a
dedicated **excluded** value for the flooded-vegetation case.

| Value | Class | In loss / IoU? | Meaning |
|---:|---|---|---|
| `1` | **Water** | **yes** | Open surface water: rivers, lakes, open flood. The positive class. |
| `0` | **Non-water** | **yes** | Dry land, exposed bank, non-flooded ground. The negative class. |
| `2` | **Excluded - suspected flooded vegetation** | **no** | Canopy likely over water, cannot confirm as open water. Masked out. |
| `-1` | **No-data** | **no** | Outside swath, sensor fill, layover/shadow, unusable pixels. |

**Only `0` and `1` enter the loss and the IoU.** Values `2` and `-1` are
masked from both - exactly as Sen1Floods11's `-1` must be (see
`docs/data_sources.md`). Scoring a pixel we deliberately could not label would
be scoring our own guess.

> Implementation note for #18 (IoU) and the training loss: mask
> `label < 0 OR label == 2`. Do not remap class `2` to `0` - that would teach
> the model that flooded forest is dry land, the opposite of the truth.

---

## Evidence hierarchy

Decide each pixel using the strongest available evidence, in this order. Record
which tier decided a chip in the chip's note field.

1. **SAR backscatter (primary).** On the normalised dB imagery (see
   `docs/radiometry.md`): open water is **specular** - very dark, smooth, low
   backscatter (typically well below the land mode, around -18 dB and lower in
   our granule). HH and HV together; water is dark in both.
2. **HAND + river gauge (hydrological gate).** A pixel can only *be* flood if
   it is hydrologically floodable: low HAND (canopy-corrected MERIT Hydro, #13)
   **and** consistent with the Manaus gauge stage for the acquisition date
   (#12). High-HAND dark pixels are not flood (see edge cases).
3. **Published reference layers (corroboration).** JERS-1 dual-season wetland
   masks and JRC Global Surface Water (#15) to separate permanent water from
   event flooding and to sanity-check extent. Corroborating, not overriding.

Optical imagery is **not** on this list for the vegetated case. It may be used
only to confirm *open* water where canopy is absent.

---

## Decision rules

- **Dark + low HAND + gauge-consistent -> `1` (water).** The textbook open-water
  flood pixel.
- **Dark + high HAND (e.g. hill/terrain shadow) -> `0` or `-1`, never `1`.**
  Radar shadow and dry smooth surfaces are also dark; HAND is what separates
  "dark because water" from "dark because shadow/dry-smooth". If it is radar
  shadow/layover, label `-1`; if it is simply dry smooth ground, label `0`.
- **Bright, textured, high HAND -> `0` (non-water).** Normal land/forest.
- **Suspected flooded forest (floodable HAND, gauge says high water, but
  backscatter is vegetation-like not open-water-dark) -> `2` (excluded).** This
  is the canopy case we refuse to call. Flag it; do not label it water.
- **Permanent water body (present in JRC/JERS-1 baseline) -> `1`.** We label
  water extent, not flood-vs-permanent; the permanent/flood split is an
  analysis step, not a labelling decision, to keep the task unambiguous.
- **Unsure between two labelled classes -> `-1`.** A no-data pixel costs us
  nothing; a wrong 0/1 pixel corrupts IoU. When genuinely uncertain and no
  evidence tier resolves it, abstain with `-1`.

---

## Edge cases

| Situation | Label | Why |
|---|---|---|
| River with bright wind-roughened surface | `1` | Still open water; roughening dims the contrast but context + gauge confirm. |
| Thin river visible as a dark line, sub-pixel width | `1` where clearly water, `-1` at ambiguous edges | Keep confident core, abstain on mixed-pixel edges. |
| Radar shadow behind terrain (dark, high HAND) | `-1` | Dark but not water; not reliably interpretable. |
| Layover / foreshortening artefact | `-1` | Geometry artefact, not a surface class. |
| Sandbar / exposed bank at low water | `0` | Dry ground even if normally submerged. |
| Flooded forest, gauge high, canopy backscatter | `2` | The excluded case - cannot confirm open water under canopy. |
| Aquaculture / pond with vegetation emergent | `2` | Treat as suspected vegetated water, exclude. |
| Cloud/optical artefact in a corroborating layer | ignore that layer | SAR is unaffected by cloud; do not import optical errors. |
| Granule fill / outside AOI footprint | `-1` | No-data. |

---

## Worked examples

One concrete example per class, so "what would you label this?" has a
reference answer. Each cites the evidence tier that decided it.

### Water (`1`)
A broad, very dark, smooth patch along the Solimões main stem. Dark in both HH
and HV on the dB imagery (tier 1). HAND is near zero and the Manaus gauge reads
high stage for 18 Jun 2026 (tier 2). JRC marks it as frequent water (tier 3).
All tiers agree open water -> **`1`**.

### Non-water (`0`)
A bright, speckled, texture-rich block of terra firme forest on a terrace. High
backscatter in both polarisations (tier 1), high HAND well above gauge stage
(tier 2). Not floodable, not dark -> **`0`**.

### Excluded - suspected flooded vegetation (`2`)
A várzea stand where HAND is low and the gauge says the floodplain is inundated
(tier 2 suggests water *should* be present), but backscatter looks like
vegetation canopy, not specular open water (tier 1 cannot confirm open water).
We cannot see the water surface under the canopy and refuse to guess ->
**`2`**, flagged and masked from scoring.

### No-data (`-1`)
A dark wedge in the scene corner outside the imaged swath, plus a terrain-shadow
strip behind a ridge (dark but high HAND, tier 2 rules out water). Neither is an
interpretable surface class -> **`-1`**.

---

## Workflow

1. Label on the **normalised dB** HH/HV imagery (`docs/radiometry.md`), with
   HAND, gauge stage, and reference layers available as side panels.
2. Record per chip: labeller, date, which evidence tier decided ambiguous
   regions, and any `2`/`-1` rationale.
3. The **calibration round (#29)** has all four label the *same* 5 chips; we
   compare agreement before mass labelling and revise this doc if agreement is
   poor.
4. The **gold set (#30, ~50 chips)** is labelled only after calibration passes.

Tooling and the exact mask format are issue #28; this document defines *what*
the labels mean, not the tool.

---

## Sign-off (acceptance criterion 3)

This protocol is binding once all four members mark agreement here (or approve
the PR that adds this file). Record disagreements as review comments so the
resolution is in the history.

- [ ] Varun Teja Chundru
- [ ] Nidhi Musale
- [ ] Yashada Ajit Tembe
- [ ] Pushan Verma
