#!/usr/bin/env python3
"""Extract 'Total Voting by Party' tables (primary elections only) into a long/tidy CSV.

Output columns: election_date, election_type, jurisdiction, jurisdiction_type, party, party_as_printed, count

General-election canvass books have no by-party table (general ballots are not party ballots), so this
dataset has primary elections only. See data/voting_by_party.ERRATA.md.
"""
import csv
import re
import sys
from pathlib import Path

import pdfplumber

from extract_voter_registration import ELECTIONS, SCANNED, PDF_DIR, ROOT, lines_of, parse_row, assign

PRIMARIES = [e for e in ELECTIONS if e.endswith("_primary")]
LAST_COUNTY = "York"
PARTY_ORDER = ["Republican", "Democratic", "Libertarian", "Legal Marijuana NOW", "Green", "Nebraska Party",
               "Natural Law", "Reform Party", "Americans Elect", "Nonpartisan",
               "Nonpartisan (Republican ballot)", "Nonpartisan (Democratic ballot)",
               "Nonpartisan (Libertarian ballot)", "Nonpartisan (Legal Marijuana NOW ballot)", "Total"]

# 2024's header is wrapped across many lines; its columns (in print order) are fixed here.
COLS_2024 = ["Republican", "Democratic", "Libertarian", "Legal Marijuana NOW", "Nonpartisan",
             "Nonpartisan (Republican ballot)", "Nonpartisan (Democratic ballot)",
             "Nonpartisan (Libertarian ballot)", "Nonpartisan (Legal Marijuana NOW ballot)", "Total"]
PRINTED_2024 = {"Republican": "Republican", "Democratic": "Democratic", "Libertarian": "Libertarian",
                "Legal Marijuana NOW": "Legal Marijuana NOW", "Total": "Total",
                "Nonpartisan": "Nonpartisan (no party ballot)",
                "Nonpartisan (Republican ballot)": "Nonpartisan Republican*",
                "Nonpartisan (Democratic ballot)": "Nonpartisan Democratic*",
                "Nonpartisan (Libertarian ballot)": "Nonpartisan Libertarian*",
                "Nonpartisan (Legal Marijuana NOW ballot)": "Nonpartisan Legal Marijuana NOW*"}

TOKENS = {"republican": "Republican", "democratic": "Democratic", "democrat": "Democratic",
          "libertarian": "Libertarian", "marijuana": "Legal Marijuana NOW", "green": "Green",
          "nebraska": "Nebraska Party", "elect": "Americans Elect", "nonpartisan": "Nonpartisan",
          "law": "Natural Law"}


# Counts the book prints only in a footnote. 2002 primary: "*Douglas county had 4 voters from the Green party."
FOOTNOTE_COUNTS = {("2002_primary", "Douglas"): {"Green": 4}, ("2002_primary", "Statewide"): {"Green": 4}}


def header_columns(lines, first_row_idx):
    cols, printed = {}, {}
    for ws in lines[:first_row_idx]:
        texts = {w["text"].lower() for w in ws}
        if "by" in texts and "party" in texts or "number" in texts:
            continue  # title line
        for i, w in enumerate(ws):
            t = w["text"].lower().strip(".,*")
            xc = (w["x0"] + w["x1"]) / 2
            if t in TOKENS and TOKENS[t] not in cols:
                cols[TOKENS[t]] = xc
                printed[TOKENS[t]] = {"Natural Law": "Natural Law", "Americans Elect": "Americans Elect",
                                      "Legal Marijuana NOW": "Legal Marijuana NOW"}.get(TOKENS[t], w["text"])
            elif t == "total" and "Total" not in cols:
                cols["Total"] = xc
                printed["Total"] = "Total Voting" if any(x["text"].lower() == "voting" for x in ws) else "Total"
    return cols, printed


def find_pages(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        started = False
        for pno, page in enumerate(pdf.pages, start=1):
            lines = lines_of(page)
            rows = [parse_row(ws) for ws in lines]
            nrows = sum(1 for r in rows if r)
            text = " ".join(w["text"] for ws in lines for w in ws).lower()
            if not started:
                if (nrows >= 10 and ("voting by party" in text or "number of people voting" in text)
                        and "contents" not in text and "....." not in text):
                    started = True
            if started:
                yield pno, lines
                if any(r and r[0] == LAST_COUNTY for r in rows):
                    return


def extract(stem):
    if stem in SCANNED:
        from build_scanned_voting_by_party import scanned_rows
        rows, cols, printed, unresolved = scanned_rows(stem)
        if unresolved:
            raise RuntimeError(f"{stem}: unresolved counties {unresolved}")
        return rows, cols, printed
    fixed = COLS_2024 if stem == "2024_primary" else None
    cols, printed, rows, seen = None, {}, [], set()
    anchors = None
    for pno, lines in find_pages(PDF_DIR / f"{stem}.pdf"):
        idx = [i for i, ws in enumerate(lines) if parse_row(ws)]
        if not idx:
            continue
        if not fixed:
            found, pr = header_columns(lines, idx[0])
            if "Total" in found and len(found) >= 3:
                anchors, printed = found, pr
                cols = sorted(found, key=lambda c: found[c])
        elif cols is None:
            cols = fixed
            printed = PRINTED_2024
        if cols is None:
            raise RuntimeError(f"{stem} p{pno}: no header found")
        for i in idx:
            name, nums = parse_row(lines[i])
            statewide = bool(re.match(r"(statewide|totals?$|grand total)", name, re.I))
            key = "Statewide" if statewide else name
            if key in seen:
                continue
            seen.add(key)
            if fixed:
                if len(nums) != len(fixed):
                    raise RuntimeError(f"{stem}: {key} has {len(nums)} numbers, expected {len(fixed)}")
                row = {c: int(w["text"].replace(",", "")) for c, w in zip(fixed, nums)}
            else:
                row = assign(nums, anchors)
            row.update(FOOTNOTE_COUNTS.get((stem, key), {}))
            rows.append((key, row))
    extra = [p for (st, _), d in FOOTNOTE_COUNTS.items() if st == stem for p in d]
    cols = list(cols) + [p for p in dict.fromkeys(extra) if p not in cols]
    return rows, cols, printed


def to_long(stem, rows, cols, printed):
    date = ELECTIONS[stem]
    parties = sorted(cols, key=PARTY_ORDER.index)
    out = []
    for name, vals in rows:
        for p in parties:
            out.append({"election_date": date, "election_type": "primary", "jurisdiction": name,
                        "jurisdiction_type": "state" if name == "Statewide" else "county",
                        "party": p, "party_as_printed": printed.get(p, "(footnote only)"), "count": vals.get(p, 0)})
    return out


def validate(stem, rows, cols):
    by = dict(rows)
    counties = {k: v for k, v in by.items() if k != "Statewide"}
    problems, warnings = [], []
    if len(counties) != 93:
        problems.append(f"{len(counties)} counties, expected 93")
    parties = [c for c in cols if c != "Total"]
    for k, v in by.items():
        if "Total" not in v:
            problems.append(f"{k}: no Total")
            continue
        s = sum(v.get(p, 0) for p in parties)
        if s != v["Total"]:
            problems.append(f"{k}: parties sum {s} != Total {v['Total']}")
    seen_rows = {}
    for k, v in counties.items():
        sig = tuple(sorted(v.items()))
        if v.get("Total", 0) > 500 and sig in seen_rows:
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


# Discrepancies inside the source itself; values are kept as printed (see the ERRATA).
KNOWN_SOURCE_ISSUES = {
    "2014_primary": ["Statewide: parties sum 324225 != Total 324227", "Republican: counties sum 225214 != Statewide 225212"],
}


def main():
    stems = sys.argv[1:] or PRIMARIES
    allrows, ok = [], True
    for stem in stems:
        rows, cols, printed = extract(stem)
        ok &= validate(stem, rows, cols)
        allrows += to_long(stem, rows, cols, printed)
    allrows.sort(key=lambda r: (r["election_date"], r["jurisdiction_type"] != "state", r["jurisdiction"],
                                PARTY_ORDER.index(r["party"])))
    out = ROOT / "data" / "voting_by_party.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allrows[0]))
        w.writeheader()
        w.writerows(allrows)
    print("wrote", out, len(allrows), "rows")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
