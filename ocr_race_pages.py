#!/usr/bin/env python3
"""OCR every page of a scanned canvass book into word boxes (data/ocr_races/<stem>/<page>.json).

Usage: python3 ocr_race_pages.py <stem> <first> <last> [dpi]

Each word is {text, x0, x1, top, bottom, conf} in PDF points (72 per inch), the same shape pdfplumber gives for a
text-layer page, so the race table parser can read an OCR'd page exactly as it reads a text page.
"""
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"
OUT = ROOT / "data" / "ocr_races"


def ocr_page(stem, pno, dpi=200, psm=6, clean=False):
    work = OUT / "_png"
    work.mkdir(parents=True, exist_ok=True)
    prefix = work / f"{stem}_{pno:03d}_{dpi}_{psm}"
    subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(pno), "-l", str(pno), "-gray", "-png", "-singlefile",
                    str(PDF_DIR / f"{stem}.pdf"), str(prefix)], check=True)
    png = f"{prefix}.png"
    if clean:  # flatten shading, binarize and erase ruling lines (same helper as the registration OCR)
        from ocr_registration import clean_image
        cleaned = clean_image(png)
        Path(png).unlink(missing_ok=True)
        png = str(cleaned)
    res = subprocess.run(["tesseract", png, "stdout", "--psm", str(psm), "-c", "preserve_interword_spaces=1", "tsv"],
                         capture_output=True, text=True)
    scale = 72.0 / dpi
    words = []
    for row in csv.DictReader(io.StringIO(res.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        t = (row.get("text") or "").strip()
        if row.get("level") != "5" or not t:
            continue
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        words.append({"text": t, "x0": x * scale, "x1": (x + w) * scale, "top": y * scale, "bottom": (y + h) * scale,
                      "conf": float(row["conf"])})
    Path(png).unlink(missing_ok=True)
    return words


def main():
    stem, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    dpi = int(sys.argv[4]) if len(sys.argv) > 4 else 200
    psm = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    # the main reading is dpi 200 / psm 6 in data/ocr_races/<stem>; other readings are variants used to repair cells
    clean = len(sys.argv) > 6 and sys.argv[6] == "c"
    name = stem if (dpi, psm, clean) == (200, 6, False) else f"{stem}@{dpi}p{psm}{'c' if clean else ''}"
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    for p in range(first, last + 1):
        f = d / f"{p:03d}.json"
        if f.exists():
            continue
        f.write_text(json.dumps(ocr_page(stem, p, dpi, psm, clean), separators=(",", ":")))


if __name__ == "__main__":
    main()
