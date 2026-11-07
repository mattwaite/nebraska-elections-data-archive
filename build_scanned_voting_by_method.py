#!/usr/bin/env python3
"""Assemble voting-by-method rows for the scanned canvass books (2000, 2002 general, 2006).

Per county, in priority order:
  1. corrections/method_<stem>.csv - transcribed by hand from the page image (always wins)
  2. data/ocr_raw_method/<stem>.json - an OCR candidate whose method columns sum exactly to its Total
Run ocr_voting_by_method.py first.
"""
import csv
import json
from pathlib import Path

from ocr_registration import COUNTIES
from ocr_voting_by_method import SPECS, METHODS, TOT

ROOT = Path(__file__).parent


def scanned_rows(stem):
    """([(jurisdiction, {method: int})], method columns, unresolved counties)."""
    cols = [c for c in SPECS[stem][1] if c in METHODS or c == TOT]  # drop party columns (2000 primary)
    cands = json.loads((ROOT / "data" / "ocr_raw_method" / f"{stem}.json").read_text())
    fixed = {}
    path = ROOT / "corrections" / f"method_{stem}.csv"
    if path.exists():
        for r in csv.DictReader(open(path)):
            county = r.pop("county")
            fixed[county] = {k: int(v) for k, v in r.items() if v != ""}
    rows, unresolved = [], []
    for name in ["Statewide"] + COUNTIES:
        if name in fixed:
            rows.append((name, fixed[name])); continue
        good = [c for c in cands.get(name, []) if sum(c.get(m, 0) for m in METHODS) == c[TOT]]
        # Whole-page OCR sometimes pairs a county name with a neighbouring row's (internally consistent)
        # numbers, so more than one distinct consistent candidate means the county needs a hand correction.
        distinct = {json.dumps(c, sort_keys=True) for c in good}
        if len(distinct) == 1:
            rows.append((name, {k: v for k, v in good[0].items() if k in cols}))
        elif distinct:
            unresolved.append(name)
        elif name != "Statewide":
            unresolved.append(name)
    return rows, cols, unresolved


if __name__ == "__main__":
    for stem in SPECS:
        rows, cols, unresolved = scanned_rows(stem)
        print(stem, len(rows) - 1, "counties; unresolved:", unresolved)
