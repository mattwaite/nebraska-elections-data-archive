#!/usr/bin/env python3
"""Assemble registration rows for the scanned canvass books (2000, 2002 general, 2006).

Source of each county row, in priority order:
  1. corrections/<stem>.csv  - transcribed by hand from the page image (always wins)
  2. data/ocr_raw/<stem>.json - an OCR candidate whose party counts sum exactly to its printed Total
Anything else is reported as unresolved. Run ocr_registration.py first.
"""
import csv
import json
from pathlib import Path

from ocr_registration import COUNTIES, SPECS

ROOT = Path(__file__).parent
DATES = {"2006_primary": "2006-05-09", "2006_general": "2006-11-07", "2002_general": "2002-11-05",
         "2000_primary": "2000-05-09", "2000_general": "2000-11-07"}


def scanned_rows(stem):
    """Return ([(jurisdiction, {column: int})], columns, unresolved) for a scanned election."""
    cols = list(SPECS[stem][2])
    cands = json.loads((ROOT / "data" / "ocr_raw" / f"{stem}.json").read_text())
    fixed = {}
    path = ROOT / "corrections" / f"{stem}.csv"
    if path.exists():
        for r in csv.DictReader(open(path)):
            county = r.pop("county")
            fixed[county] = {k: int(v) for k, v in r.items() if v != ""}
            for k in fixed.get("Statewide", {}):
                if k not in cols:
                    cols.append(k)
    rows, unresolved = [], []
    for name in ["Statewide"] + COUNTIES:
        if name in fixed:
            rows.append((name, fixed[name])); continue
        good = [c for c in cands.get(name, []) if sum(v for k, v in c.items() if k not in ("precincts", "Total")) == c["Total"]]
        if good:
            rows.append((name, good[0]))
        elif name != "Statewide":
            unresolved.append(name)
    return rows, cols, unresolved


if __name__ == "__main__":
    for stem in SPECS:
        rows, cols, unresolved = scanned_rows(stem)
        print(stem, len(rows) - 1, "counties; unresolved:", unresolved)
