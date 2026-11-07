#!/usr/bin/env python3
"""OCR the 'voting by method' tables of the scanned canvass books (2000, 2002 general, 2006).

Same approach as ocr_registration.py: several OCR passes per page, candidate rows kept in
data/ocr_raw_method/<stem>.json; build_scanned_voting_by_method.py accepts a candidate only if its method
columns sum exactly to the printed Total, and hand corrections in corrections/method_<stem>.csv override.
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

import ocr_registration as base

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"
OUT = ROOT / "data" / "ocr_raw_method"

POLLS, MIL, ABS, NEW, TOT = "Polling Place", "Military & Overseas", "Early/Absentee", "New/Former Resident", "Total"
# stem -> (pages, columns as printed left-to-right, split page into n side-by-side blocks)
SPECS = {
    "2006_primary": ((9, 10), [POLLS, MIL, ABS, TOT], 1),
    "2006_general": ((13, 13), [POLLS, MIL, ABS, TOT], 2),
    "2002_general": ((18, 19), [POLLS, MIL, ABS, TOT], 1),
    "2000_general": ((5, 6), [POLLS, MIL, ABS, NEW, TOT], 1),
    # 2000 primary prints party and method columns in one table; the party columns are kept here only so
    # the row can be checked, and are dropped when the dataset is built.
    "2000_primary": ((7, 8), [TOT, "Republican", "Democratic", "Libertarian", "Natural Law", "Nonpartisan",
                              POLLS, MIL, ABS], 1),
}
METHODS = [POLLS, MIL, ABS, NEW]


def sum_ok(row):
    return sum(row.get(m, 0) for m in METHODS) == row[TOT]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "_png"
    work.mkdir(exist_ok=True)
    for stem in sys.argv[1:] or SPECS:
        (first, last), cols, blocks = SPECS[stem]
        cands = {}
        for p in range(first, last + 1):
            variants = []
            for dpi in (300, 120, 150, 200):
                prefix = work / f"{stem}_{p:03d}_{dpi}"
                subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(p), "-l", str(p), "-png", "-singlefile",
                                str(PDF_DIR / f"{stem}.pdf"), str(prefix)], check=True)
                img = Image.open(f"{prefix}.png")
                if blocks == 1:
                    variants.append((dpi, f"{prefix}.png"))
                else:
                    w = img.width // blocks
                    for b in range(blocks):
                        path = f"{prefix}_b{b}.png"
                        img.crop((b * w, 0, (b + 1) * w, img.height)).save(path)
                        variants.append((dpi, path))
            for dpi, path in variants:
                passes = [base.ocr_lines_page] + ([base.ocr_lines] if dpi == 300 else [])
                for method in passes:
                    for county, row in base.parse(method(path), cols).items():
                        if row not in cands.setdefault(county, []):
                            cands[county].append(row)
        (OUT / f"{stem}.json").write_text(json.dumps(cands, indent=1))
        ok = [c for c in base.COUNTIES if any(sum_ok(r) for r in cands.get(c, []))]
        print(stem, len(ok), "counties with a sum-consistent OCR row; unresolved:",
              [c for c in base.COUNTIES if c not in ok])


if __name__ == "__main__":
    main()
