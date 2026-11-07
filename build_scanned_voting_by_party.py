#!/usr/bin/env python3
"""Assemble voting-by-party rows for the scanned primary books (2000, 2006).

Per county, in priority order:
  1. corrections/party_<stem>.csv - transcribed by hand from the page image (always wins)
  2. the single OCR candidate whose party columns sum exactly to its Total
Anything else is unresolved. Run ocr_voting_by_party.py (and ocr_voting_by_method.py for 2000) first.
"""
import csv
import json
from pathlib import Path

from ocr_registration import COUNTIES
from ocr_voting_by_party import PARTIES

ROOT = Path(__file__).parent
SOURCES = {"2006_primary": "ocr_raw_party", "2000_primary": "ocr_raw_method"}
PRINTED = {
    "2006_primary": {"Republican": "Republican", "Democratic": "Democrat", "Green": "Green",
                     "Nebraska Party": "Nebraska", "Nonpartisan": "Nonpartisan", "Total": "Total Voting"},
    "2000_primary": {"Republican": "Republican", "Democratic": "Democrat", "Libertarian": "Libertarian",
                     "Natural Law": "Natural Law", "Nonpartisan": "Non-partisan", "Total": "Total Voting"},
}


def scanned_rows(stem):
    parties = PARTIES[stem]
    cols = parties + ["Total"]
    cands = json.loads((ROOT / "data" / SOURCES[stem] / f"{stem}.json").read_text())
    fixed = {}
    path = ROOT / "corrections" / f"party_{stem}.csv"
    if path.exists():
        for r in csv.DictReader(open(path)):
            county = r.pop("county")
            fixed[county] = {k: int(v) for k, v in r.items() if v != ""}
            for k in fixed[county]:
                if k not in cols:
                    cols.append(k)
    rows, unresolved = [], []
    for name in ["Statewide"] + COUNTIES:
        if name in fixed:
            rows.append((name, fixed[name])); continue
        good = [{k: v for k, v in c.items() if k in parties or k == "Total"} for c in cands.get(name, [])
                if all(p in c for p in parties) and sum(c[p] for p in parties) == c["Total"]]
        distinct = {json.dumps(c, sort_keys=True) for c in good}
        if len(distinct) == 1:
            rows.append((name, good[0]))
        elif name != "Statewide":
            unresolved.append(name)
    return rows, cols, PRINTED[stem], unresolved


if __name__ == "__main__":
    for stem in PARTIES:
        rows, cols, printed, unresolved = scanned_rows(stem)
        print(stem, len(rows) - 1, "counties; unresolved:", unresolved)
