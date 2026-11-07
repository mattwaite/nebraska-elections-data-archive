#!/usr/bin/env python3
"""OCR the registration tables of the scanned canvass books (2000, 2002 general, 2006).

Writes data/ocr_raw/<stem>.json: {county: {column: int}} for every row OCR read cleanly (right number of
numeric fields). Rows OCR could not read, and every sum-check failure, are reported by
build_scanned_registration.py, which applies hand corrections from corrections/ (read from page images).
"""
import difflib
import numpy as np
from PIL import Image, ImageFilter
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"
OUT = ROOT / "data" / "ocr_raw"

# stem -> (first page, last page, column order as printed)
SPECS = {
    "2006_general": (11, 13, ["precincts", "Republican", "Democratic", "Nonpartisan", "Green", "Nebraska Party", "Total"]),
    "2006_primary": (5, 7, ["precincts", "Total", "Republican", "Democratic", "Nonpartisan", "Green", "Nebraska Party"]),
    "2002_general": (16, 18, ["precincts", "Total", "Republican", "Democratic", "Libertarian", "Nonpartisan", "Nebraska Party"]),
    "2000_general": (3, 5, ["Total", "Republican", "Democratic", "Libertarian", "Natural Law", "Green", "Nonpartisan"]),
    "2000_primary": (5, 7, ["precincts", "Total", "Republican", "Democratic", "Libertarian", "Natural Law", "Nonpartisan"]),
}
COUNTIES = """Adams Antelope Arthur Banner Blaine Boone Box_Butte Boyd Brown Buffalo Burt Butler Cass Cedar Chase Cherry
Cheyenne Clay Colfax Cuming Custer Dakota Dawes Dawson Deuel Dixon Dodge Douglas Dundy Fillmore Franklin Frontier
Furnas Gage Garden Garfield Gosper Grant Greeley Hall Hamilton Harlan Hayes Hitchcock Holt Hooker Howard Jefferson
Johnson Kearney Keith Keya_Paha Kimball Knox Lancaster Lincoln Logan Loup Madison McPherson Merrick Morrill Nance
Nemaha Nuckolls Otoe Pawnee Perkins Phelps Pierce Platte Polk Red_Willow Richardson Rock Saline Sarpy Saunders
Scotts_Bluff Seward Sheridan Sherman Sioux Stanton Thayer Thomas Thurston Valley Washington Wayne Webster Wheeler York"""
COUNTIES = [c.replace("_", " ") for c in COUNTIES.split()]
assert len(COUNTIES) == 93

TRANS = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8"})


def clean_num(t):
    t = t.translate(TRANS).replace(",", "").replace(".", "")
    return int(t) if re.fullmatch(r"\d+", t) else None


def clean_image(png):
    """Flatten shading (2002 scan), binarize, and erase ruling lines that make tesseract skip rows."""
    img = Image.open(png).convert("L")
    bg = img.filter(ImageFilter.BoxBlur(40))
    a = np.asarray(img).astype(int) - np.asarray(bg).astype(int)
    ink = a < -35  # darker than local background
    h, w = ink.shape
    # horizontal rules: long dark runs; vertical rules likewise
    for axis, n in ((1, w), (0, h)):
        frac = ink.sum(axis=axis) / n
        for i in np.where(frac > 0.35)[0]:
            if axis == 1:
                ink[max(i - 2, 0):i + 3, :] = False
            else:
                ink[:, max(i - 2, 0):i + 3] = False
    out = Image.fromarray(np.where(ink, 0, 255).astype("uint8"))
    cleaned = Path(str(png).replace(".png", "_clean.png"))
    out.save(cleaned)
    return cleaned


def ocr_lines_page(png):
    """Whole-page OCR of the unprocessed scan (word boxes grouped into lines)."""
    tsv = subprocess.run(["tesseract", str(png), "-", "--psm", "6", "tsv"], capture_output=True, text=True).stdout
    words = []
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) == 12 and f[11].strip() and float(f[10]) >= 0:
            words.append((int(f[7]), int(f[6]), f[11].strip()))
    words.sort()
    lines, cur, top0 = [], [], None
    for top, left, text in words:
        if top0 is None or top - top0 > 18:
            if cur:
                lines.append(sorted(cur))
            cur, top0 = [], top
        cur.append((left, text))
    if cur:
        lines.append(sorted(cur))
    return [[t for _, t in ln] for ln in lines]


def ocr_lines(png):
    """OCR each text row separately: find row bands by horizontal ink projection, then OCR each band (psm 7)."""
    cleaned = clean_image(png)
    img = Image.open(cleaned)
    ink = np.asarray(img) < 128
    prof = ink[:, 150:-150].sum(axis=1)
    rows, start = [], None
    for y, v in enumerate(prof):
        if v > 2 and start is None:
            start = y
        elif v <= 2 and start is not None:
            if y - start >= 18:
                rows.append((start, y))
            start = None
    lines = []
    for top, bot in rows:
        crop = img.crop((0, max(top - 8, 0), img.width, bot + 8))
        big = Image.new("L", (crop.width + 40, crop.height + 40), 255)
        big.paste(crop, (20, 20))
        tmp = str(cleaned).replace("_clean.png", "_row.png")
        big.save(tmp)
        txt = subprocess.run(["tesseract", tmp, "-", "--psm", "7"], capture_output=True, text=True).stdout
        toks = txt.split()
        if toks:
            lines.append(toks)
    return lines


def match_county(name):
    name = re.sub(r"[^A-Za-z. ]", "", name).strip()
    if name.upper().startswith("TOTAL") or name.upper() in ("TOTAL", "TOTAI", "TOTAR"):
        return "Statewide"
    m = difflib.get_close_matches(name, COUNTIES, n=1, cutoff=0.8)
    return m[0] if m else None


def parse(lines, cols):
    rows = {}
    for toks in lines:
        i = 0
        while i < len(toks) and not re.search(r"\d", toks[i]):
            i += 1
        name = " ".join(toks[:i])
        county = match_county(name)
        if not county:
            continue
        nums = [clean_num(t) for t in toks[i:] if re.search(r"[0-9]", t) or t in ("O", "o")]
        if len(nums) == len(cols) and None not in nums:
            rows[county] = dict(zip(cols, nums))
    return rows


def sum_ok(row):
    parties = sum(v for k, v in row.items() if k not in ("precincts", "Total"))
    return parties == row["Total"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    work = ROOT / "data" / "ocr_raw" / "_png"
    work.mkdir(exist_ok=True)
    for stem in sys.argv[1:] or SPECS:
        first, last, cols = SPECS[stem]
        cands = {}  # county -> list of candidate rows from different OCR passes
        for p in range(first, last + 1):
            prefix = work / f"{stem}_{p:03d}"
            subprocess.run(["pdftoppm", "-r", "300", "-f", str(p), "-l", str(p), "-png", "-singlefile",
                            str(PDF_DIR / f"{stem}.pdf"), str(prefix)], check=True)
            passes = [(ocr_lines_page, f"{prefix}.png"), (ocr_lines, f"{prefix}.png")]
            for dpi in (120, 150, 200):  # other resolutions read different rows correctly
                low = work / f"{stem}_{p:03d}_{dpi}"
                subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(p), "-l", str(p), "-png", "-singlefile",
                                str(PDF_DIR / f"{stem}.pdf"), str(low)], check=True)
                passes.append((ocr_lines_page, f"{low}.png"))
            for method, img in passes:
                scale = 18 if "_1" not in str(img) and "_2" not in str(img) else 18
                for county, row in parse(method(img), cols).items():
                    if row not in cands.setdefault(county, []):
                        cands[county].append(row)
        (OUT / f"{stem}.json").write_text(json.dumps(cands, indent=1))
        ok = [c for c in COUNTIES if any(sum_ok(r) for r in cands.get(c, []))]
        print(stem, len(ok), "counties with a sum-consistent OCR row; unresolved:", [c for c in COUNTIES if c not in ok])


if __name__ == "__main__":
    main()
