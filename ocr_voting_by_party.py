#!/usr/bin/env python3
"""OCR the 'voting by party' tables of the two scanned primary books (2000, 2006).

2000 primary: the party columns share one table with the method columns, so its OCR candidates are reused
from ocr_voting_by_method.py (data/ocr_raw_method/2000_primary.json).
2006 primary: OCR'd here (data/ocr_raw_party/2006_primary.json).
build_scanned_voting_by_party.py accepts a candidate only if its party columns sum exactly to its Total
and the county has a single consistent candidate; corrections/party_<stem>.csv (read from page images) wins.
"""
import json
import subprocess
import sys
from pathlib import Path

import ocr_registration as base

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"
OUT = ROOT / "data" / "ocr_raw_party"

TOT = "Total"
SPECS = {
    "2006_primary": ((7, 8), [TOT, "Republican", "Democratic", "Green", "Nebraska Party", "Nonpartisan"]),
}
PARTIES = {"2006_primary": ["Republican", "Democratic", "Green", "Nebraska Party", "Nonpartisan"],
           "2000_primary": ["Republican", "Democratic", "Libertarian", "Natural Law", "Nonpartisan"]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "_png"
    work.mkdir(exist_ok=True)
    for stem in sys.argv[1:] or SPECS:
        (first, last), cols = SPECS[stem]
        cands = {}
        for p in range(first, last + 1):
            for dpi in (300, 120, 150, 200):
                prefix = work / f"{stem}_{p:03d}_{dpi}"
                subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(p), "-l", str(p), "-png", "-singlefile",
                                str(PDF_DIR / f"{stem}.pdf"), str(prefix)], check=True)
                passes = [base.ocr_lines_page] + ([base.ocr_lines] if dpi == 300 else [])
                for method in passes:
                    for county, row in base.parse(method(f"{prefix}.png"), cols).items():
                        if row not in cands.setdefault(county, []):
                            cands[county].append(row)
        (OUT / f"{stem}.json").write_text(json.dumps(cands, indent=1))
        ok = [c for c in base.COUNTIES if any(sum(r[q] for q in PARTIES[stem]) == r[TOT] for r in cands.get(c, []))]
        print(stem, len(ok), "counties with a sum-consistent OCR row; unresolved:",
              [c for c in base.COUNTIES if c not in ok])


if __name__ == "__main__":
    main()
