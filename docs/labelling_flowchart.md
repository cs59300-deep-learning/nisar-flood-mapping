# Labelling flowchart

A step-by-step decision flow for choosing `1`, `2`, `0` or `-1`. It adds no new
rules. The definitions are in [`labelling_protocol.md`](labelling_protocol.md),
and the one-page working list is in
[`labelling_checklist.md`](labelling_checklist.md). If this file ever
disagrees with the protocol, the protocol wins.

---

## The four values

|  Value | Meaning                                                          | Do you draw it?                              | Scored?      |
| -----: | ---------------------------------------------------------------- | -------------------------------------------- | ------------ |
|  `1` | Open water (river, lake, open flood; permanent water too)        | Yes                                          | Yes          |
|  `2` | Suspected flooded vegetation (water under canopy, unconfirmable) | Yes, flagged                                 | **No** |
| `-1` | No-data, shadow, layover, ambiguous edge, or genuinely unsure    | Yes                                          | **No** |
|  `0` | Dry land                                                         | **No.** Anything undrawn becomes `0` | Yes          |

If your QGIS layer is styled with names such as `openwater` / `flood` / `none`:
`openwater` = `1`, and `flood` = `2`. **`flood` is the excluded class, not
"flood water".** Visible open flood water is `1`.

---

## Before you start a polygon

- [ ] Normalised dB imagery. HH and HV are loaded as two layers, so you can tick HV on and off.
- [ ] Gauge for the chip date noted: **18 Jun 2026 = 28.47 m, +7.95 m above bank**, so anything less than about 8 m above the nearest drainage is floodable.
- [ ] Geojson layer selected, editing on, zoom between 1:25,000 and 1:40,000.

---

## The flow

Start at the top for every region you are unsure about.

```
START: pick a region on the dB image (HH + HV)
│
▼
Q1. Is the pixel usable?
    (inside swath, not fill, not layover/foreshortening)
│
├── NO ──────────────────────────────────────────► -1  (no-data)
│
▼ YES
Q2. Is it DARK in BOTH HH and HV?
    (smooth, uniform, roughly -18 dB or lower)
│
├── NO (bright / textured / speckled)
│     │
│     ▼
│   Q3. Is HH bright but HV stays low (HH - HV above 8),
│       on low ground, with the gauge high?
│     │
│     ├── YES (can't see water under the trees) ──────────────► 2  (excluded)
│     │
│     └── NO (bright in both, high ground, normal forest) ────► 0  (leave undrawn)
│
▼ YES (dark)
Q4. Is the ground LOW (low HAND, or floodplain pattern)?
│
├── NO (high ground: hill, ridge)
│     │
│     ▼
│   Q5. Is it radar shadow / geometry artefact?
│     ├── YES ──────────────────────────────────────────────► -1
│     └── NO (just dry smooth ground: sandbar, road, bare mud)
│                                                            ► 0  (leave undrawn)
│
▼ YES (low ground)
Q6. Is it consistent with the Manaus gauge for the chip date?
    (is the stage high enough to put water here?)
│
├── NO ──► Q7. Does JRC / JERS-1 show permanent water here?
│            ├── YES ─────────────────────────────────────────► 1
│            └── NO ──────────────────────────────────────────► -1
│
▼ YES
Q8. Is the edge clear (a clean boundary, not a mixed pixel)?
│
├── NO (thin river, ambiguous edge) ─────────────────────────► -1  (edge only)
│
└── YES ─────────────────────────────────────────────────────► 1  (water)

────────────────────────────────────────────────────────────────
SAFETY NET at ANY step: genuinely torn between two classes,
and no evidence tier settles it?  ───────────────────────────► -1
```

---

## Cheat sheet

| Label        | Fire when                                                                                                        |
| ------------ | ---------------------------------------------------------------------------------------------------------------- |
| **1**  | Dark in both HH and HV, **and** low ground, **and** the gauge agrees (or JRC shows permanent water). |
| **2**  | Low ground and gauge high, but HH is bright while HV stays low (HH - HV above 8). Canopy, not specular water.    |
| **0**  | Bright and textured on high ground, or dark but dry (high ground, not shadow). Do not draw it.                   |
| **-1** | Outside the swath, shadow or layover, ambiguous edge, or you are unsure.                                         |

---

## Reading the numbers (Identify Features)

Click **Identify Features** (the blue ⓘ), click the **HH** layer's name, then
click a pixel. Click 3 or 4 pixels in anything doubtful, because speckle moves a
single pixel by about 1.4 dB on its own.

| What you see                              | HH        | HV        | HH - HV           | What it is                             |
| ----------------------------------------- | --------- | --------- | ----------------- | -------------------------------------- |
| Very dark in both bands                   | about -18 | about -22 | ~4                | open water, **`1`**            |
| Bright, the most common thing in the chip | about -6  | about -11 | ~5                | dry forest canopy, **`0`**     |
| Brightest, and HV came up too             | about -2  | about -7  | ~5                | rough ground or slope, **`0`** |
| Brightest, but HV stayed low              | about -2  | about -12 | **above 8** | water under trees, **`2`**     |

---

## Checking HAND (ground height)

HAND is height above the nearest drainage. Under about 8 m on 18 June 2026 means
floodable. Above that means shadow, dry ground or forest, not flood.

**Is a HAND layer available?** Currently **no**. The chips contain only HH and
HV, and `data/reference/` is empty. Ask the team whether someone already has the
raster. See [`hand_methods.md`](hand_methods.md) for how it is built from MERIT
Hydro (`s05w065_hnd.tif`, `s05w060_hnd.tif`).


1. **If you have the HAND raster:**
2. Drag it into QGIS.
3. Identify Features, click the HAND layer's name, then click the pixel.
4. Read the metres. Under about 8 m is floodable. Over about 8 m is not.



Limits: resolution is about 90 m, so it is coarse for thin channels. About 75%
of this AOI has HAND of 2 m or less, so HAND alone rarely rules water out here.

**If you do not have it, use the pattern proxy** (weaker evidence, so say so in
`notes`):


| Pattern around the dark patch                            | Meaning                                                 |
| -------------------------------------------------------- | ------------------------------------------------------- |
| Branching, tree-like channels cut into the surface       | High ground. Shadow or dry, so `-1` or leave undrawn. |
| Curved, looping, scrolled shapes (meander scars, oxbows) | Floodplain, low ground. Water is plausible.             |

---

## Form fields

| Field             | What to put                                                                                                             |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `chip_id`       | The chip's name, exactly as the file, with **zero padding kept** (`N023_20260618_007600_011200`)                |
| `class`         | `1`, `2` or `-1` (an integer, not text)                                                                           |
| `labeller`      | Your GitHub handle                                                                                                      |
| `labelled_on`   | Today, `YYYY-MM-DD`                                                                                                   |
| `evidence_tier` | `1` backscatter, `2` ground height + gauge, `3` reference layer                                                   |
| `notes`         | **Required for every `2` and `-1`:** one line of reasoning, e.g. `HH -2, HV -12, low ground, gauge 28.47 m` |



Evidence tier rules of thumb:

- Class `1` on dark pixels: tier `1`.
- Class `2` is **never tier `1` alone**. It needs ground height plus gauge, so tier `2`.
- `notes` repeating the class name (`flood`, `openwater`) is not a reason.

---

## Traps

1. **Dark does not mean water.** Check ground height before writing `1`.
2. **Bright does not mean flooded.** Flooded forest is bright in HH and low in HV. Bright in both is just forest.
3. **`2` is never "kind of water".** Use it only when the ground and gauge say water should be there and you cannot see it. Optical imagery does not count.
4. **One river, one class.** If the same continuous channel changes between `1` and `2`, you need evidence for the change. Check the pixels.
5. **Do not draw `0`.** Leave it undrawn.
6. **Overshoot the chip edge.** Carry water polygons past the boundary. They get clipped.
7. **Do not trace speckle.** Place a vertex every 200-400 m, following the shape of the boundary.
8. **Snap polygons together.** Overlaps between a `1` and a `2` leave the result to drawing order.
9. **When in doubt, `-1`.** Abstaining is free. A wrong `0` or `1` corrupts IoU.

---

## Per-chip finish checklist

- [ ] Every polygon has `class` as an integer, `labeller`, `labelled_on`, `evidence_tier`.
- [ ] Every `2` and `-1` has a one-line reason in `notes`.
- [ ] `chip_id` matches the file name, with zero padding.
- [ ] No `1` polygon sits on clearly high ground.
- [ ] Same river is not split between `1` and `2` without reason.
- [ ] No overlapping slivers between polygons.
- [ ] Placeholder row with the empty `class` left untouched.
- [ ] A dry export check (see [`labelling_commands.md`](labelling_commands.md)) shows the values you expect.
