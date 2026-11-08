#!/usr/bin/env python3
"""Present OCR'd pages (data/ocr_races/<stem>/NNN.json) to the race parser as if they were text-layer pages.

OCR is cleaned in two ways before parsing: digit look-alikes inside numbers are repaired (O->0, l->1, ...), and
near-miss county names are snapped to the real county. Everything else (candidate names, labels) is left as read;
hand corrections for those live in corrections/races_<stem>.json (see apply_corrections).
"""
import difflib
import json
import re
from pathlib import Path

from ocr_registration import COUNTIES

ROOT = Path(__file__).parent
OCR_DIR = ROOT / "data" / "ocr_races"
CORR_DIR = ROOT / "corrections"

COUNTY_TOKENS = sorted({t for c in COUNTIES for t in c.split()})
LOOK = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "!": "1", "i": "1", "S": "5",
                      "s": "5", "B": "8", "Z": "2", "z": "2", "g": "9", "q": "9", "T": "7"})


def fix_number(t):
    """'1,2O4' -> '1204'; leave words alone. Returns the token unchanged if it is not number-like."""
    core = t.strip(".,;:'`\"")
    if not core:
        return t
    digits = sum(ch.isdigit() for ch in core)
    if digits == 0 and not re.fullmatch(r"[OolI|!SBZzDq]{1,2}", core):
        return t
    if digits >= 1 or re.fullmatch(r"[OolI|!]{1,2}", core):
        cand = core.translate(LOOK).replace(",", "").replace(".", "").replace("'", "")
        if re.fullmatch(r"\d+", cand) and len(core) - digits <= max(1, len(core) // 3):
            return cand
    return t


def snap_county(t):
    if t != "County" and t.isalpha() and 3 <= len(t) <= 7 and t not in COUNTY_TOKENS and \
            difflib.SequenceMatcher(None, t.lower(), "county").ratio() >= 0.7:
        return "County"  # "Coun", "Counly", "Cou nty": the table header word
    if t in COUNTY_TOKENS or not t.isalpha() or len(t) < 3 or t.lower() in ("the", "for", "and", "page"):
        return t
    m = difflib.get_close_matches(t, COUNTY_TOKENS, n=1, cutoff=0.82)
    return m[0] if m else t


class OcrPage:
    is_ocr = True
    width = 612.0
    height = 792.0
    rects = []
    lines = []
    curves = []

    def __init__(self, stem, pno):
        self.stem, self.page_number = stem, pno  # stem may be a variant directory such as "2006_general@300p6"
        self._words = json.loads((OCR_DIR / stem / f"{pno:03d}.json").read_text())

    def extract_words(self):
        out = []
        for w in self._words:
            parts = w["text"].split()
            n = sum(len(p) for p in parts) + max(len(parts) - 1, 0)
            pos = w["x0"]
            for p in parts:
                width = (w["x1"] - w["x0"]) * len(p) / max(n, 1)
                if re.fullmatch(r"[|_.\-:;~=\[\]{}()'\"`,!]+", p):  # rule lines and specks
                    pos += width + (w["x1"] - w["x0"]) / max(n, 1)
                    continue
                t = fix_number(p)
                if t == p:
                    t = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9.&]+$", "", t) or t
                    t = snap_county(t)
                out.append({**w, "text": t, "x0": pos, "x1": pos + width})
                pos += width + (w["x1"] - w["x0"]) / max(n, 1)
        return self._mark_unreadable(out)

    @staticmethod
    def _mark_unreadable(words):
        """Within a county/TOTAL row, anything after the name that is not a number is a cell OCR could not read ("?").
        Rows are found by the x position of the name column(s), so two tables side by side stay separate."""
        from race_blocks import cluster_lines
        second = {"Box": "Butte", "Red": "Willow", "Scotts": "Bluff", "Keya": "Paha"}
        for w in words:
            if w["text"].upper() in ("TOTAL", "TOTAI", "T0TAL", "TOTA1", "TOTALS"):
                w["text"] = "TOTAL"
        xs = sorted(w["x0"] for w in words if w["text"] in COUNTY_TOKENS or w["text"] == "TOTAL")
        cols = []
        for x in xs:
            if cols and x - cols[-1][-1] <= 10:
                cols[-1].append(x)
            else:
                cols.append([x])
        name_x = [sum(c) / len(c) for c in cols if len(c) >= 4]

        def is_name_start(w):
            return any(abs(w["x0"] - nx) <= 12 for nx in name_x)

        for ln in cluster_lines(words):
            starts = [i for i, w in enumerate(ln) if is_name_start(w)]
            for si, i in enumerate(starts):
                j = starts[si + 1] if si + 1 < len(starts) else len(ln)
                first = ln[i]["text"]
                if first == "County":
                    continue
                if first not in COUNTY_TOKENS and first != "TOTAL" and re.fullmatch(r"[\d,]+", first):
                    continue  # a number sitting in the name column: not a row start
                if first not in COUNTY_TOKENS and first != "TOTAL":
                    # a name OCR garbled only counts as a row if it is followed by real numbers; otherwise it is a
                    # title or header line and must keep its words
                    if sum(1 for w in ln[i + 1:j] if re.fullmatch(r"[\d,]+", w["text"])) < 1:
                        continue
                k = i + 1
                if first in second and k < j and ln[k]["text"] == second[first]:
                    k += 1
                for w in ln[k:j]:
                    if not re.fullmatch(r"[\d,]+", w["text"]):
                        w["text"] = "?"
        return words

    def extract_text(self):
        from race_blocks import cluster_lines
        return "\n".join(" ".join(w["text"] for w in ln) for ln in cluster_lines(self.extract_words()))


def ocr_pages(stem):
    """Pages of a book (or of a variant reading, stem like "2006_general@300p6")."""
    files = sorted((OCR_DIR / stem).glob("*.json"))
    return [OcrPage(stem, int(f.stem)) for f in files]
