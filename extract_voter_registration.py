#!/usr/bin/env python3
"""Extract 'Number of Registered Voters' tables from Nebraska canvass books into a long/tidy CSV.

Table layouts differ by year (column order, column names, presence of a precincts column, blank cells
for zero). Columns are therefore located by x-position of the header words on each page and every
number is assigned to its nearest header column; blanks stay blank (== no value printed).
Each election is validated: parties sum to Total, counties sum to Statewide, 93 counties.

Output columns: election_date, election_type, jurisdiction, jurisdiction_type, precincts, party, count
"""
import csv
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"

ELECTIONS = {  # pdf stem -> election date
    "2024_primary": "2024-05-14", "2024_general": "2024-11-05",
    "2022_primary": "2022-05-10", "2022_general": "2022-11-08",
    "2020_primary": "2020-05-12", "2020_general": "2020-11-03",
    "2018_primary": "2018-05-15", "2018_general": "2018-11-06",
    "2016_primary": "2016-05-10", "2016_general": "2016-11-08",
    "2014_primary": "2014-05-13", "2014_general": "2014-11-04",
    "2012_primary": "2012-05-15", "2012_general": "2012-11-06",
    "2010_primary": "2010-05-11", "2010_general": "2010-11-02",
    "2008_primary": "2008-05-13", "2008_general": "2008-11-04",
    "2004_primary": "2004-05-11", "2004_general": "2004-11-02",
    "2002_primary": "2002-05-14",
}
# Scanned books (no text layer): OCR + hand-checked corrections; see ocr_registration.py,
# build_scanned_registration.py and corrections/. Imported lazily so the text path needs no OCR tools.
SCANNED = {
    "2006_primary": "2006-05-09", "2006_general": "2006-11-07", "2002_general": "2002-11-05",
    "2000_primary": "2000-05-09", "2000_general": "2000-11-07",
}
ELECTIONS.update(SCANNED)

# header token -> canonical column. 'Labels' / 'Nebraska' handled specially below.
HEADER_TOKENS = {
    "precincts": "precincts",
    "republican": "Republican",
    "democratic": "Democratic", "democrat": "Democratic",
    "libertarian": "Libertarian",
    "nonpartisan": "Nonpartisan",
    "marijuana": "Legal Marijuana NOW",
    "labels": "No Labels Nebraska",
    "green": "Green",
    "elect": "Americans Elect",
}
TOTAL_TOKENS = {"total", "registered", "grand"}
NUM = re.compile(r"^\d[\d,]*$")
LAST_COUNTY = "York"

# Counts that the source prints only in a footnote rather than a table column. (stem, jurisdiction) -> {party: n}
# 2002 primary: "*Douglas county has 25 voters registered to the Green Party", "**Sarpy county has 1 ...";
# these account exactly for the gap between the printed party columns and Total (26 statewide).
FOOTNOTE_COUNTS = {
    ("2002_primary", "Douglas"): {"Green": 25},
    ("2002_primary", "Sarpy"): {"Green": 1},
    ("2002_primary", "Statewide"): {"Green": 26},
}


def lines_of(page):
    """Group words into text lines by vertical centre (within 4pt of the line's first word)."""
    words = sorted(page.extract_words(), key=lambda w: (w["top"] + w["bottom"]) / 2)
    lines, current, c0 = [], [], None
    for w in words:
        c = (w["top"] + w["bottom"]) / 2
        if c0 is None or abs(c - c0) > 4:
            if current:
                lines.append(sorted(current, key=lambda x: x["x0"]))
            current, c0 = [], c
        current.append(w)
    if current:
        lines.append(sorted(current, key=lambda x: x["x0"]))
    for ln in lines:  # a letter 'O' typed for zero inside a row of numbers (e.g. 2014 primary, Kimball)
        if sum(bool(NUM.match(w["text"])) for w in ln) >= 3:
            for w in ln:
                if w["text"] in ("O", "o"):
                    w["text"] = "0"
    return lines


def merge_split_digits(nums):
    """Rejoin a number the PDF split into adjacent glyph runs (e.g. '1' '4' -> '14')."""
    out = []
    for w in nums:
        if out and w["x0"] - out[-1]["x1"] < 2.0 and NUM.match(out[-1]["text"]) and NUM.match(w["text"]):
            prev = out.pop()
            w = {**prev, "text": prev["text"] + w["text"], "x1": w["x1"]}
        out.append(w)
    return out


def parse_row(ws):
    """Return (name, [number words]) if the line is a data row, else None."""
    i = 0
    name = []
    while i < len(ws) and not NUM.match(ws[i]["text"]):
        name.append(ws[i]["text"])
        i += 1
    nums = merge_split_digits(ws[i:])
    if not name or not nums or not all(NUM.match(w["text"]) for w in nums):
        return None
    name = " ".join(name).strip("* ").strip()
    if not re.match(r"^[A-Za-z]", name) or name.startswith("Page"):
        return None
    return name, nums


def header_columns(lines, first_row_idx):
    """Locate header columns by x-center from keyword words above the first data row."""
    cols = {}
    total_x = []
    labels_x = None
    nebraska = []
    for ws in lines[:first_row_idx]:
        if {"Number", "Voters", "Statistics"} & {w["text"] for w in ws}:
            continue  # title lines ('Number of Registered Voters')
        for w in ws:
            t = w["text"].lower().strip(".,*")
            xc = (w["x0"] + w["x1"]) / 2
            if t in HEADER_TOKENS:
                cols[HEADER_TOKENS[t]] = xc
            elif t in TOTAL_TOKENS:
                total_x.append(xc)
            elif t == "nebraska":
                nebraska.append(xc)
    if "No Labels Nebraska" in cols:  # 'Nebraska' belonging to 'No Labels Nebraska'
        lx = cols["No Labels Nebraska"]
        if nebraska:
            nebraska.remove(min(nebraska, key=lambda x: abs(x - lx)))
    if nebraska:
        cols["Nebraska Party"] = nebraska[0]
    if total_x:
        cols["Total"] = sum(total_x) / len(total_x)
    return cols


def extract_pages(pdf_path):
    """Yield (page_number, lines) for pages starting at the registration table."""
    with pdfplumber.open(pdf_path) as pdf:
        started = False
        for pno, page in enumerate(pdf.pages, start=1):
            lines = lines_of(page)
            nrows = sum(1 for ws in lines if parse_row(ws))
            if not started:
                text = " ".join(w["text"] for ws in lines for w in ws)
                if (nrows >= 10 and "Registered" in text and "Voter" in text
                        and "Contents" not in text and "....." not in text):
                    started = True
            if started:
                yield pno, lines
                if any(parse_row(ws) and parse_row(ws)[0] == LAST_COUNTY for ws in lines):
                    return


def assign(nums, cols):
    """Assign numbers to columns left-to-right, skipping columns where nothing is printed (blank cells).

    Order-preserving assignment minimizing total |x-distance| (DP), so a row with all cells filled is
    mapped one-to-one regardless of header alignment, and blanks are placed by position.
    """
    names = sorted(cols, key=lambda c: cols[c])
    xs = [(w["x0"] + w["x1"]) / 2 for w in nums]
    n, m = len(xs), len(names)
    if n > m:
        raise ValueError(f"{n} numbers but {m} columns")
    INF = float("inf")
    best = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0] = [0.0] * (m + 1)
    for i in range(1, n + 1):
        for j in range(i, m + 1):
            skip = best[i][j - 1]
            take = best[i - 1][j - 1] + abs(xs[i - 1] - cols[names[j - 1]])
            best[i][j] = min(skip, take)
            back[i][j] = "skip" if skip <= take else "take"
    vals, i, j = {}, n, m
    while i > 0:
        if back[i][j] == "take":
            vals[names[j - 1]] = int(nums[i - 1]["text"].replace(",", ""))
            i -= 1
        j -= 1
    return vals


def extract(stem):
    if stem in SCANNED:
        from build_scanned_registration import scanned_rows
        rows, cols, unresolved = scanned_rows(stem)
        if unresolved:
            raise RuntimeError(f"{stem}: unresolved counties {unresolved}")
        return rows, cols
    rows, seen, cols = [], set(), None
    for pno, lines in extract_pages(PDF_DIR / f"{stem}.pdf"):
        idx = [i for i, ws in enumerate(lines) if parse_row(ws)]
        if not idx:
            continue
        page_cols = header_columns(lines, idx[0])
        if len(page_cols) > 2:
            cols = page_cols
        if cols is None:
            raise RuntimeError(f"{stem} p{pno}: no header found")
        for i in idx:
            name, nums = parse_row(lines[i])
            is_total = bool(re.search(r"total", name, re.I))
            if name in seen and not is_total or (is_total and "Statewide" in seen):
                continue
            if is_total:
                seen.add("Statewide")
                name = "Statewide"
            else:
                seen.add(name)
            vals = assign(nums, cols)
            vals.update(FOOTNOTE_COUNTS.get((stem, name), {}))
            rows.append((name, vals))
    extra = [p for (st, _), d in FOOTNOTE_COUNTS.items() if st == stem for p in d]
    return rows, list(cols) + [p for p in dict.fromkeys(extra) if p not in cols]


PARTY_ORDER = ["Republican", "Democratic", "Libertarian", "Legal Marijuana NOW", "No Labels Nebraska",
               "Green", "Nebraska Party", "Natural Law", "Reform Party", "Last Party", "Americans Elect",
               "Nonpartisan", "Total"]


def to_long(stem, rows, colnames):
    """Long format. A party column with an empty cell for a county is emitted as 0 (verified by sums)."""
    date = ELECTIONS[stem]
    etype = stem.split("_")[1]
    parties = sorted((c for c in colnames if c != "precincts"), key=PARTY_ORDER.index)
    out = []
    for name, vals in rows:
        statewide = name == "Statewide"
        for party in parties:
            out.append({
                "election_date": date, "election_type": etype,
                "jurisdiction": name, "jurisdiction_type": "state" if statewide else "county",
                "precincts": vals.get("precincts", ""), "party": party, "count": vals.get(party, 0),
            })
    return out


def validate(stem, rows, colnames):
    problems = []
    by = dict(rows)
    counties = {k: v for k, v in by.items() if k != "Statewide"}
    if len(counties) != 93:
        problems.append(f"{len(counties)} counties, expected 93")
    warnings = []
    if "Statewide" not in by:
        warnings.append("no statewide total row printed in source")
    parties = [c for c in colnames if c not in ("precincts", "Total")]
    for k, v in by.items():
        if set(v) - {"precincts"} != set(parties + ["Total"]) - (set() if k == "Statewide" else set()):
            missing = set(parties + ["Total"]) - set(v)
            if "Total" in missing or len(missing) == len(parties):
                problems.append(f"{k}: missing {sorted(missing)}")
        s = sum(v.get(p, 0) for p in parties)
        if "Total" in v and s != v["Total"]:
            problems.append(f"{k}: parties sum {s} != Total {v['Total']}")
    if "Statewide" in by:
        for c in parties + ["Total", "precincts"]:
            if c in by["Statewide"]:
                s = sum(v.get(c, 0) for v in counties.values())
                if s != by["Statewide"][c]:
                    # precinct counts that disagree are a source inconsistency, not an extraction error
                    (warnings if c == "precincts" else problems).append(
                        f"{c}: counties sum {s} != Statewide {by['Statewide'][c]}")
    print(f"{stem}: {len(counties)} counties, columns={colnames}", "OK" if not problems else "PROBLEMS")
    for p in problems[:12]:
        print("   ", p)
    for w in warnings:
        print("    (warning)", w)
    return not problems


def main():
    stems = sys.argv[1:] or list(ELECTIONS)
    allrows, ok = [], True
    for stem in stems:
        rows, colnames = extract(stem)
        ok &= validate(stem, rows, colnames)
        allrows += to_long(stem, rows, colnames)
    allrows.sort(key=lambda r: (r["election_date"], r["election_type"], r["jurisdiction_type"] != "state",
                                r["jurisdiction"], PARTY_ORDER.index(r["party"])))
    out = ROOT / "data" / "voter_registration.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allrows[0]))
        w.writeheader()
        w.writerows(allrows)
    print("wrote", out, len(allrows), "rows")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
