#!/usr/bin/env python
"""Draw the calibration figures and write the Results section of docs/stage_calibration.md (#14).

Run after scripts/calibrate_stage0.py. Reads docs/evidence/{stage_calibration_report.json,
stage0_calibration_curve.csv, hand_inundation_by_date.csv}; writes two PNGs next to them and replaces the
generated block in the doc (safe to re-run).

    python scripts/write_calibration_results.py \
        --reference-notes "OPERA DSWx-S1 v1.0 water layer, 2026-09-20 (fit), 2026-09-28 and 2026-09-16 (held out)" \
        --reference-summary docs/evidence/reference_summary.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nisar_flood.groundtruth.calibration_report import make_figures, render_results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--report-dir", type=Path, default=Path("docs/evidence"))
    p.add_argument("--doc", type=Path, default=Path("docs/stage_calibration.md"))
    p.add_argument("--reference-notes", default="")
    p.add_argument("--reference-summary", type=Path, default=None, help="JSON {date: mosaic summary}")
    args = p.parse_args()

    summary = json.loads(args.reference_summary.read_text()) if args.reference_summary else None
    for path in make_figures(args.report_dir):
        print("wrote", path)
    render_results(args.report_dir, args.doc, args.reference_notes, summary)
    print("updated", args.doc)


if __name__ == "__main__":
    main()
