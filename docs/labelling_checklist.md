# Labelling checklist

One page, to keep open while you label. The full reasoning is in
[`labelling_protocol.md`](labelling_protocol.md); the tooling is in
[`labelling_tooling.md`](labelling_tooling.md). This is the short version.

---

## Once per chip, before drawing

Load the **same `.tif` twice**, so you can flip between HH and HV without
editing symbology every time.

1. Drag the chip in. Properties → Symbology → **Singleband gray**, **Band 1**,
   Min `-25`, Max `5`. Double-click the layer name and rename it **HH**.
2. Drag the **same file** in again. Symbology → **Singleband gray**, **Band 2**,
   Min `-30`, Max `-5`. Rename it **HV**.
   (HV sits about 5 dB darker than HH, so it needs its own range or it looks
   black everywhere.)
3. Drag the matching `.geojson` in. It goes on top.

Your layer list now reads:

```
geojson      <- draw here
HV           <- tick / untick to compare
HH
```

Ticking and unticking **HV** is how you check both bands. No menus.

- [ ] Three layers loaded in that order
- [ ] Geojson layer **selected** by name (grey text means nothing will work)
- [ ] Zoom between **1:25,000 and 1:40,000** — if you can see single pixels, zoom out
- [ ] Editing **on** (pencil icon lit)
- [ ] Read the gauge figure for this chip's date in the table below

---

## How high is the river on this date

Every chip in the current assignment is from **18 June 2026**, so for now the
answer is always the first row.

| Chip date | Gauge | Above bank level | Where that sits in the year | What to expect |
|---|---|---|---|---|
| **2026-06-18** | **28.47 m** | **+7.95 m** | 88th percentile | floodplain is inundated — expect plenty of class `2` |
| 2026-07-12 | 28.26 m | +7.74 m | 73rd | still high |
| 2026-08-29 | 24.44 m | +3.93 m | 26th | falling |
| 2026-09-22 | 20.35 m | −0.16 m | 6th | low — river within its banks, little or no class `2` |

"Above bank level" is the gauge reading minus **20.51 m**, the level at which
the river sits exactly at its banks. Ground lying less than that height above
the nearest channel can be under water; ground above it cannot.

So on 18 June, anything less than about 8 m above the nearest drainage is
floodable. That is what makes a dark patch plausible as water, and a
vegetation-textured patch a candidate for class `2`.

Sources: [`../data/gauge/manaus_daily_stage_2026.csv`](../data/gauge/manaus_daily_stage_2026.csv)
for the daily readings, and `stage0_m` in
[`evidence/stage_calibration_report.json`](evidence/stage_calibration_report.json)
for the 20.51 m bank level.

---

## When your eyes are not enough: read the numbers

Click **Identify Features** (the blue ⓘ), click the **HH** layer's name, then
click any pixel on the map. It prints both bands:

```
Band 1 (HH gamma0 dB)   -18.4
Band 2 (HV gamma0 dB)   -22.9
```

Compare against the values measured on this granule:

| | HH | HV | HH − HV |
|---|---|---|---|
| Water | below −14 | below −18 | small |
| Dry land or forest | about −6 | about −11 | about 5 |
| Flooded vegetation | above −6 | still about −12 | **above 8** |

Click three or four pixels inside anything doubtful, not just one — speckle
moves a single pixel by about 1.4 dB on its own.

---

## For every polygon, before you fill the form

Work down the list. Stop at the first line that matches.

| # | Check | If yes |
|---|---|---|
| 1 | Dark in **both HH and HV** (untick HV to check), and on low ground? | **`1` water** |
| 2 | Dark, but on **high ground**? | **`-1`** — radar shadow, not water |
| 3 | Dark, but a **dry smooth surface** (sandbar, road, bare mud)? | leave undrawn → `0` |
| 4 | **Bright in HH but HV stays dark** (HH − HV above 8), and on low ground? | **`2`** flooded vegetation |
| 5 | Bright in both, on high ground? | leave undrawn → `0` |
| 6 | Still unsure after all of the above? | **`-1`** |

---

## The four values

| Value | Meaning | Do you draw it? |
|---|---|---|
| `1` | Open water | Yes |
| `2` | Suspected flooded vegetation | Yes — flagged, never scored |
| `-1` | Unusable or genuinely unsure | Yes |
| `0` | Dry land | **No.** Anything undrawn becomes this |

---

## Rules that are easy to get wrong

- **Never draw `0`.** It is most of the chip and it happens automatically.
- **Bright does not mean flooded.** Flooded forest is bright in HH *and* stays
  dark in HV. Bright in both is just forest or rough ground.
- **Dark does not mean water.** Shadow and dry smooth ground are dark too.
  Ground height is what separates them.
- **Overshoot the chip edge.** Where water runs off the side, carry the polygon
  past the boundary. It gets clipped. Stopping short leaves a dry strip.
- **One polygon per water body.** River, lake and each channel separately.
- **Abstaining is free; guessing is not.** A `-1` pixel is dropped from scoring.
  A wrong `1` or `0` corrupts the result.
- **Do not trace speckle.** Place a vertex every 200–400 m, following the shape
  of the boundary, not its texture. Being off by 40 m costs about 0.03 IoU;
  chasing pixels costs hours.

---

## Filling the form

| Field | What to put |
|---|---|
| `chip_id` | the chip's name, same as the file |
| `class` | `1`, `2` or `-1` |
| `labeller` | your GitHub handle |
| `labelled_on` | today, `YYYY-MM-DD` |
| `evidence_tier` | `1` backscatter · `2` ground height + gauge · `3` reference layer |
| `notes` | required for every `2` and `-1`: one line on why |

Switch on **Reuse Last Entered Attribute Values** on the digitizing toolbar and
only `class` needs typing after the first polygon.

---

## Finishing a chip

- [ ] Right-click closed every polygon, and clicked **OK** on each form
      (Cancel throws the polygon away)
- [ ] **Layer → Save Layer Edits** — not ⌘S, which saves the project instead
- [ ] Attribute table (F6) shows the expected number of rows
- [ ] Placeholder row with the empty `class` left untouched
- [ ] Editing toggled off

Then export and look at the result:

```
nisar-flood label-export --chips data/chips \
    --annotations data/labels/annotations --out data/labels/masks
```

If the water percentage is wildly different from what you drew, something went
wrong — check it before moving on.

---

## During the calibration round (#29)

The five calibration chips are labelled by all four people **independently**.
Do not look at anyone else's annotations, and do not discuss the chips until
everyone has finished. Comparing notes first makes the agreement figure
measure the conversation instead of the labels.
