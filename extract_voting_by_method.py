#!/usr/bin/env python3
"""Extract 'Total Voting by Method/Location' tables from Nebraska canvass books into a long/tidy CSV.

Output columns: election_date, election_type, jurisdiction, jurisdiction_type, method, method_as_printed, in_total, count

`method` is a standardized name (see METHOD_ORDER); `method_as_printed` is the column heading the book used.
Columns are located by header position when the page has a header. Blank cells (the books leave
"All Mail Precincts" blank for most counties) are resolved using the row's own Total: only assignments in
which the method columns sum to the printed Total are accepted.
"""
import csv
import itertools
import re
import sys
from pathlib import Path

import pdfplumber

from extract_voter_registration import ELECTIONS, SCANNED, PDF_DIR, ROOT, lines_of, parse_row

METHOD_ORDER = ["Polling Place", "Early/Absentee", "All Mail Precincts", "Provisional",
                "Military & Overseas", "New/Former Resident", "Total"]
LAST_COUNTY = "York"
# Discrepancies inside the source itself. Values are kept as printed; see data/voting_by_method.ERRATA.md.
KNOWN_SOURCE_ISSUES = {
    "2016_primary": ["Polling Place: counties sum 244745 != Statewide 244744",
                     "Early/Absentee: counties sum 58744 != Statewide 58745"],
    "2002_primary": ["Clay: methods sum 1824 != Total 1914", "Early/Absentee: counties sum 13771 != Statewide 13861"],
}
# Method columns whose counts the book's Total does NOT include (the printed Total equals the sum of the
# other columns exactly in every county, so these appear to be a subset already counted elsewhere).
NOT_IN_TOTAL = {("2018_primary", "Military & Overseas"), ("2018_general", "Military & Overseas")}
ALL_ELECTIONS = list(ELECTIONS)
# Column headings as printed in the scanned books (read from the page images).
SCANNED_PRINTED = {
    "2006_primary": {"Polling Place": "At the Polls", "Military & Overseas": "Military & Overseas",
                     "Early/Absentee": "Early Voting/ Absentees", "Total": "Total Voting"},
    "2006_general": {"Polling Place": "At the Polls", "Military & Overseas": "Military & Overseas",
                     "Early/Absentee": "Early Voting", "Total": "Total Voting"},
    "2002_general": {"Polling Place": "AtPolls", "Military & Overseas": "Military Overseas",
                     "Early/Absentee": "Absentees", "Total": "Total Voting"},
    "2000_general": {"Polling Place": "Total at Polls", "Military & Overseas": "Military & Overseas",
                     "Early/Absentee": "Absentee Voters", "New/Former Resident": "New/Former Residents (Presidential Vote)",
                     "Total": "Total Voting"},
    "2000_primary": {"Polling Place": "At the Polls", "Military & Overseas": "Military Overseas",
                     "Early/Absentee": "Absentee", "Total": "Total Voting"},
}


def header_anchors(lines, first_row_idx):
    """{method: (x, text_as_printed)} from the header lines above the first data row."""
    found = {}
    for ws in lines[:first_row_idx]:
        texts = [w["text"] for w in ws]
        if any("location" in t.lower() or t.lower() == "by" for t in texts):
            continue  # title line, e.g. 'Total Voting by Location'
        prev, prev_x1 = "", -100
        for w in ws:
            t = w["text"].lower().strip(".,*()")
            xc = (w["x0"] + w["x1"]) / 2
            m = None
            if t.startswith("poll"):
                m = "Polling Place"
            elif t == "early" and not (prev == "military" and w["x0"] - prev_x1 < 10):
                # ('Military Early Voters' in one column is not an Early Voting column)
                m = "Early/Absentee"
            elif t.startswith("absentee"):
                m = "Early/Absentee"
            elif t == "mail":
                m = "All Mail Precincts"
            elif t.startswith("provisional"):
                m = "Provisional"
            elif t.startswith("military"):
                m = "Military & Overseas"
            elif t == "resident" or "former" in t or t == "new":
                m = "New/Former Resident"
            elif t == "total":
                m = "Total"
            prev, prev_x1 = t, w["x1"]
            if m and m not in found:
                found[m] = xc
    return found


def printed_names(lines, first_row_idx, anchors):
    """Rebuild each column's printed heading from the header words nearest its anchor x."""
    words = [w for ws in lines[:first_row_idx] for w in ws
             if not any("location" in x["text"].lower() for x in ws)]
    out = {}
    order = sorted(anchors, key=lambda m: anchors[m])
    for i, m in enumerate(order):
        lo = (anchors[order[i - 1]] + anchors[m]) / 2 if i else -1
        hi = (anchors[m] + anchors[order[i + 1]]) / 2 if i + 1 < len(order) else 10 ** 6
        ws = sorted((w for w in words if lo <= (w["x0"] + w["x1"]) / 2 < hi and w["text"].lower() != "county"
                     and w["text"].lower() != "method"),
                    key=lambda w: (round(w["top"] / 4), w["x0"]))
        out[m] = " ".join(w["text"] for w in ws).strip()
    return out


def find_pages(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        started = False
        for pno, page in enumerate(pdf.pages, start=1):
            lines = lines_of(page)
            rows = [parse_row(ws) for ws in lines]
            nrows = sum(1 for r in rows if r)
            text = " ".join(w["text"] for ws in lines for w in ws)
            if not started:
                if (nrows >= 10 and ("Location" in text or "Method" in text)
                        and "Contents" not in text and "....." not in text):
                    started = True
            if started:
                yield pno, lines
                if any(r and r[0] == LAST_COUNTY for r in rows):
                    return


def candidates(nums, cols):
    """All ways to place `nums` (last is the Total) into `cols` (last is Total), as {col: value}."""
    body, total = nums[:-1], nums[-1]
    method_cols = cols[:-1]
    out = []
    for subset in itertools.combinations(range(len(method_cols)), len(body)):
        if sum(body) == total:
            out.append({cols[i]: v for i, v in zip(subset, body)} | {"Total": total})
    return out


def extract(stem):
    if stem in SCANNED:
        from build_scanned_voting_by_method import scanned_rows
        rows, cols, unresolved = scanned_rows(stem)
        if unresolved:
            raise RuntimeError(f"{stem}: unresolved counties {unresolved}")
        return rows, cols, SCANNED_PRINTED[stem]
    cols, printed = None, {}
    rows, seen = [], set()
    blank_freq = {}
    pending = []  # rows with ambiguous blank cells, resolved after blank statistics are known
    for pno, lines in find_pages(PDF_DIR / f"{stem}.pdf"):
        idx = [i for i, ws in enumerate(lines) if parse_row(ws)]
        if not idx:
            continue
        anchors = header_anchors(lines, idx[0])
        anchors_here = len(anchors) >= 3 and "Total" in anchors
        if anchors_here:
            cols = sorted(anchors, key=lambda m: anchors[m])
            printed = printed_names(lines, idx[0], anchors)
        if cols is None:
            raise RuntimeError(f"{stem} p{pno}: no header found")
        for i in idx:
            name, nums = parse_row(lines[i])
            vals = [int(w["text"].replace(",", "")) for w in nums]
            statewide = bool(re.match(r"(statewide|totals?$|grand total)", name, re.I))
            key = "Statewide" if statewide else name
            if key in seen:
                continue
            seen.add(key)
            if len(vals) == len(cols):
                row = dict(zip(cols, vals))
            else:
                cands = candidates(vals, cols)
                row = cands[0] if len(cands) == 1 else None
                if row is None and cands and anchors_here:
                    # page has its own header: choose the placement closest to the printed column positions
                    xs = [(w["x0"] + w["x1"]) / 2 for w in nums]
                    def dist(r):
                        return sum(abs(x - anchors[c]) for x, c in zip(xs, [c for c in cols if c in r]))
                    row = min(cands, key=dist)
                if row is None:
                    pending.append((key, cands, vals))
                    continue
            for c in cols:
                blank_freq[c] = blank_freq.get(c, 0) + (c not in row)
            rows.append((key, row))
    for key, cands, vals in pending:
        if not cands:
            raise RuntimeError(f"{stem}: {key} {vals} has no assignment matching its Total")
        # ambiguous: prefer the placement whose blank columns are the ones usually blank
        best = max(cands, key=lambda r: sum(blank_freq.get(c, 0) for c in cols if c not in r))
        rows.append((key, best))
    return rows, cols, printed


def to_long(stem, rows, cols, printed):
    date = ELECTIONS[stem]
    etype = stem.split("_")[1]
    methods = sorted(cols, key=METHOD_ORDER.index)
    out = []
    for name, vals in rows:
        for m in methods:
            out.append({
                "election_date": date, "election_type": etype, "jurisdiction": name,
                "jurisdiction_type": "state" if name == "Statewide" else "county",
                "method": m, "method_as_printed": printed.get(m, ""),
                "in_total": "FALSE" if (stem, m) in NOT_IN_TOTAL else "TRUE",
                "count": vals.get(m, 0),
            })
    return out


def validate(stem, rows, cols):
    by = dict(rows)
    counties = {k: v for k, v in by.items() if k != "Statewide"}
    problems, warnings = [], []
    if len(counties) != 93:
        problems.append(f"{len(counties)} counties, expected 93")
    methods = [c for c in cols if c != "Total" and (stem, c) not in NOT_IN_TOTAL]
    for k, v in by.items():
        s = sum(v.get(m, 0) for m in methods)
        if s != v["Total"]:
            problems.append(f"{k}: methods sum {s} != Total {v['Total']}")
    seen_rows = {}
    for k, v in counties.items():  # whole-page OCR can attach one county's numbers to its neighbour's name
        sig = tuple(sorted(v.items()))
        if v["Total"] > 500 and sig in seen_rows:
            problems.append(f"{k} has identical numbers to {seen_rows[sig]}")
        seen_rows[sig] = k
    if "Statewide" not in by:
        warnings.append("no statewide row printed in source")
    else:
        for c in cols:
            s = sum(v.get(c, 0) for v in counties.values())
            if s != by["Statewide"].get(c, 0):
                problems.append(f"{c}: counties sum {s} != Statewide {by['Statewide'].get(c, 0)}")
    known = [p for p in problems if p in KNOWN_SOURCE_ISSUES.get(stem, [])]
    problems = [p for p in problems if p not in known]
    warnings += [f"source inconsistency, kept as printed: {p}" for p in known]
    print(f"{stem}: {len(counties)} counties, columns={cols}", "OK" if not problems else "PROBLEMS")
    for p in problems[:10]:
        print("   ", p)
    for w in warnings:
        print("    (warning)", w)
    return not problems


def main():
    stems = sys.argv[1:] or ALL_ELECTIONS
    allrows, ok = [], True
    for stem in stems:
        rows, cols, printed = extract(stem)
        ok &= validate(stem, rows, cols)
        allrows += to_long(stem, rows, cols, printed)
    allrows.sort(key=lambda r: (r["election_date"], r["election_type"], r["jurisdiction_type"] != "state",
                                r["jurisdiction"], METHOD_ORDER.index(r["method"])))
    out = ROOT / "data" / "voting_by_method.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allrows[0]))
        w.writeheader()
        w.writerows(allrows)
    print("wrote", out, len(allrows), "rows")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
