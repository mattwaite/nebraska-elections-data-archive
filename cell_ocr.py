#!/usr/bin/env python3
"""Re-read individual number cells of a scanned page at high resolution.

Used for the cells of a candidate column that fail the sum check: each is cropped from a 500 dpi render, the ruling
lines touching it are erased, and tesseract reads it as a single line of digits.
"""
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"
CACHE = ROOT / "data" / "ocr_races" / "_png"
DPI = 500


@lru_cache(maxsize=8)
def page_image(stem, pno):
    CACHE.mkdir(parents=True, exist_ok=True)
    prefix = CACHE / f"{stem}_{pno:03d}_cell"
    png = Path(f"{prefix}.png")
    if not png.exists():
        subprocess.run(["pdftoppm", "-r", str(DPI), "-f", str(pno), "-l", str(pno), "-gray", "-png", "-singlefile",
                        str(PDF_DIR / f"{stem}.pdf"), str(prefix)], check=True)
    img = Image.open(png).convert("L")
    png.unlink(missing_ok=True)
    return img


def read_cell(stem, pno, box, pad=5.0):
    """Distinct readings of one cell (a list, possibly empty)."""
    img = page_image(stem, pno)
    s = DPI / 72.0
    x0, top, x1, bottom = box
    x0 = min(x0, x1 - 26)  # numbers are right-aligned: take a window ending at the right edge, wide enough for 6 digits
    crop = img.crop((int((x0 - 1) * s), int((top - pad * 0.5) * s), int((x1 + 4) * s), int((bottom + pad * 0.5) * s)))
    a = np.asarray(crop).astype(int)
    ink = a < 150
    # erase ruling lines: rows or columns that are dark for most of the crop
    for axis in (1, 0):
        frac = ink.mean(axis=axis)
        for i in np.where(frac > 0.8)[0]:
            if axis == 1:
                ink[i, :] = False
            else:
                ink[:, i] = False
    base = Image.fromarray(np.where(ink, 0, 255).astype("uint8"))
    from PIL import ImageFilter
    reads = []
    tmp = CACHE / f"cell_{pno}_{int(x0)}_{int(top)}.png"
    for sigma in (0, 1.6, 2.4, 3.2):  # smoothing levels: jagged strokes need some, thin ones need none
        out = base if sigma == 0 else base.filter(ImageFilter.GaussianBlur(sigma)).point(lambda p: 0 if p < 170 else 255)
        out = out.resize((out.width * 2, out.height * 2))
        border = Image.new("L", (out.width + 40, out.height + 40), 255)
        border.paste(out, (20, 20))
        border.save(tmp)
        for psm in (7, 8):
            res = subprocess.run(["tesseract", str(tmp), "stdout", "--psm", str(psm), "-c",
                                  "tessedit_char_whitelist=0123456789"], capture_output=True, text=True)
            txt = "".join(ch for ch in res.stdout if ch.isdigit())
            if txt:
                reads.append(int(txt))
    tmp.unlink(missing_ok=True)
    return sorted(set(reads))  # every distinct reading; callers keep the one that makes the column add up
