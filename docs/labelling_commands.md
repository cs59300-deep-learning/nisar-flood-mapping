# Labelling commands

Copy-paste commands for cutting your assigned chips and exporting your labels.
Who labels what is in [`../data/labelling_assignments.csv`](../data/labelling_assignments.csv).
What to do between steps 2 and 3 is in [`labelling_checklist.md`](labelling_checklist.md).

If `nisar-flood` is not found, activate the environment first:

```bash
source .venv/bin/activate
```

Only one machine currently holds the 1.8 GB granule, so in practice one person
runs step 1 for everybody and sends each member their `data/` folder.

---

## 1. Cut your chips

```bash
GRANULE=data/raw/NISAR_L2_PR_GCOV_023_068_D_090_2005_DHDH_A_20260618T222452_20260618T222527_P05023_N_F_J_001.h5
```

**varunteja99** — 21 chips

```bash
nisar-flood make-chips --granule $GRANULE \
  --granule-id N023_20260618 --date 2026-06-18 --out data/chips \
  --only 8000,13600 7600,11200 12000,4400 6400,12400 4400,10400 \
         8800,13200 8000,13200 4400,13200 13200,4800 6800,11600 \
         5200,9600 11600,1200 12000,6800 1200,3600 7600,12000 \
         10000,10400 3600,9200 2000,8000 7600,11600 10000,11200 10800,3200
```

**Yashada7** — 19 chips

```bash
nisar-flood make-chips --granule $GRANULE \
  --granule-id N023_20260618 --date 2026-06-18 --out data/chips \
  --only 8000,13600 7600,11200 12000,4400 6400,12400 4400,10400 \
         7200,4400 11600,2400 13200,4800 6800,11200 12400,2000 \
         8000,6000 1600,4000 10400,6400 12400,5200 9600,4800 \
         13200,6000 9600,9600 10000,11600
```

**pushanverma** — 23 chips

```bash
nisar-flood make-chips --granule $GRANULE \
  --granule-id N023_20260618 --date 2026-06-18 --out data/chips \
  --only 8000,13600 7600,11200 12000,4400 6400,12400 4400,10400 \
         12000,1200 8000,13200 6000,10000 5600,14000 6800,11200 \
         12400,8000 9200,12800 12000,6800 12000,1600 5600,10800 \
         7600,5600 6400,11200 2000,8000 8400,12400 9200,10000 \
         9600,9600 4000,8800 10000,11600
```

**NidhiMusale** — 19 chips

```bash
nisar-flood make-chips --granule $GRANULE \
  --granule-id N023_20260618 --date 2026-06-18 --out data/chips \
  --only 8000,13600 7600,11200 12000,4400 6400,12400 4400,10400 \
         11200,6000 14000,12800 3200,13200 2000,7600 9200,12800 \
         11200,2400 9600,12800 5600,10800 10000,10400 9200,10400 \
         14800,12400 7600,11600 9200,2800 10800,7200
```

Every list starts with the same five chips. Those are the calibration set (#29)
that all four members label independently.

A chip reporting less than 100% valid sits on the edge of the radar swath, so
part of the square falls outside what the satellite imaged. Those pixels are
no-data and are excluded from scoring; do not draw over them.

---

## 2. Create your annotation files

```bash
nisar-flood label-init --chips data/chips \
  --out data/labels/annotations --labeller YOUR_GITHUB_HANDLE
```

One `.geojson` per chip, named to match it. The command refuses to overwrite a
file that already exists, so re-running it cannot destroy finished work.

---

## 3. Label in QGIS

See [`labelling_checklist.md`](labelling_checklist.md).

---

## 4. Export your labels to masks

```bash
nisar-flood label-export --chips data/chips \
  --annotations data/labels/annotations --out data/labels/masks
```

Prints a water / excluded / no-data pixel count per chip and writes
`labels_manifest.csv`. If a count looks nothing like what you drew, check it
before moving on.

---

## Regenerating these lists

The commands above are derived from the assignment CSV. If the assignments
change, rebuild them rather than editing this file by hand:

```bash
python - <<'EOF'
import csv
from collections import OrderedDict
rows = list(csv.DictReader(open("data/labelling_assignments.csv")))
for who in ["varunteja99", "Yashada7", "pushanverma", "NidhiMusale"]:
    pos = list(OrderedDict.fromkeys(
        f"{r['row']},{r['col']}" for r in rows if r["labeller"] == who))
    print(f"\n{who}  ({len(pos)} chips)\n  --only " + " ".join(pos))
EOF
```
