#!/usr/bin/env python3
"""Extract statewide, federal and legislative race results (county level) into a long/tidy CSV.

Output: data/race_results.csv, one row per election x race x jurisdiction x candidate.
See data/race_results.ERRATA.md.

Scope: President, U.S. Senate, U.S. House, Governor, Lt. Governor, Secretary of State, Auditor, Treasurer,
Attorney General, Public Service Commission, Legislature, State Board of Education, University Regents.
Judicial retention, ballot measures and local contests are out of scope for now.

How it works (see docs/METHODOLOGY.md): race_blocks.py finds each table on a page from its grid lines;
this module groups tables into races (a headerless table continues the previous one; so does a table with the
same candidates and no new district label), names the office/district/term from the titles above, and
validates that county rows add up to the race Total.
"""
import csv
import re
import sys
from collections import defaultdict

import pdfplumber

from extract_voter_registration import ELECTIONS, SCANNED, PDF_DIR, ROOT
from race_blocks import page_tables, TOTAL_RE
from ocr_registration import COUNTIES

# (regex on a title line, canonical office, level). First match wins.
OFFICES = [
    (r"president and vice president|president of the united states|presidential electors|^president\b", "President", "federal"),
    (r"united states senat|u\.?s\.? senat|\bsenator,? united|^for united states senator", "U.S. Senate", "federal"),
    (r"representatives? in congress|u\.?s\.? house|house of representatives", "U.S. House", "federal"),
    (r"governor and l(ieutenan)?t\.? governor|^for governor|^governor", "Governor", "state"),
    (r"lieutenant governor", "Lieutenant Governor", "state"),
    (r"secretary of state", "Secretary of State", "state"),
    (r"auditor of public accounts|state auditor", "Auditor of Public Accounts", "state"),
    (r"state treasurer", "State Treasurer", "state"),
    (r"attorney general", "Attorney General", "state"),
    (r"public service commission", "Public Service Commissioner", "state"),
    (r"member of the legislature|state senator|legislative district|^legislature", "Legislature", "legislative"),
    (r"state board of education", "State Board of Education", "state"),
    (r"board of regents|university regents", "University Regents", "state"),
]
LEVEL = {name: level for _, name, level in OFFICES}
OUT_OF_SCOPE = re.compile(
    r"judicial|judge|community college|natural resources|educational service|learning community|public power|"
    r"reclamation|metropolitan utilities|airport|hospital|sanitary|fire district|cemetery|library|village|"
    r"city of|school district|county (clerk|treasurer|sheriff|attorney|assessor)|"
    r"proposed amendments|amendment|initiative|referendum|ballot (question|measure)|"
    r"voting statistics|registered voters|total voting|reported problems|table of contents", re.I)
DISTRICT_RE = re.compile(r"((?:Legislative |Congressional )?District\s+(?:\d+|[A-Za-z]+))", re.I)
TERM_RE = re.compile(r"(unexpired[^–\-]*|(?:two|four|six|2|4|6)[ -]year term|\d+ year term)", re.I)
PARTY_RE = re.compile(r"\(([^()]*)\)\s*$")
BALLOT_RE = re.compile(r"(republican|democratic|democrat|libertarian|green|nonpartisan|nebraska)\s+(party\s+)?"
                       r"(nomination|primary|ballot|candidates)", re.I)
VG_RE = re.compile(r"(nonpartisan\s+)?(republican|democratic|democrat)(?:\s+party)?\s+voters", re.I)
PARTY_NORM = {"republican": "Republican", "democratic": "Democratic", "democrat": "Democratic",
              "libertarian": "Libertarian", "legal marijuana now": "Legal Marijuana NOW",
              "nonpartisan": "Nonpartisan", "by petition": "By Petition", "green": "Green",
              "independent": "Independent", "americans elect": "Americans Elect", "constitution": "Constitution",
              "reform": "Reform", "natural law": "Natural Law", "nebraska": "Nebraska Party",
              "american independent": "American Independent", "rep": "Republican", "dem": "Democratic",
              "np": "Nonpartisan", "lib": "Libertarian"}
PARTY_WORDS = re.compile(r"^(republican|democratic|democrat|libertarian|nonpartisan|independent|green|by petition|"
                         r"legal marijuana now|american independent|reform|constitution|nebraska|natural law|"
                         r"americans elect|petition|no party affiliation|non-partisan|socialist|taxpayers?)$", re.I)
# header cells that are summary columns, not candidates
NOISE_HEADER = re.compile(r"^(rep|dem|np|lib|total|total all votes|republican votes|democrat votes|"
                          r"democratic votes|nonpartisan votes|votes|\d+)$", re.I)


def office_of(line):
    t = line.lower()
    if OUT_OF_SCOPE.search(t):
        return "OUT"
    for rx, name, level in OFFICES:
        if re.search(rx, t):
            return name
    return None


def parse_candidate(cell_lines):
    cell_lines = list(cell_lines)
    party_line = ""
    if len(cell_lines) > 1 and PARTY_WORDS.match(cell_lines[-1].strip("() ")):
        party_line = cell_lines.pop().strip("() ")
    text = " ".join(cell_lines)
    winner = "✔" in text
    text = re.sub(r"\s+", " ", text.replace("✔", "")).strip()
    party = ""
    m = PARTY_RE.search(text)
    if party_line:
        party = PARTY_NORM.get(party_line.lower(), party_line)
    elif m:
        raw = m.group(1).strip()
        party = PARTY_NORM.get(raw.lower(), raw)
        text = text[:m.start()].strip()
    return {"as_printed": " ".join(cell_lines).replace("✔", "").strip(), "name": text, "party": party,
            "winner": winner, "write_in": bool(re.match(r"write[- ]?in|scattering", text, re.I)),
            "noise": bool(NOISE_HEADER.match(text.strip()))}


def district_and_term(sources):
    district, term = "", ""
    for source in sources:
        for ln in reversed(source):
            m = DISTRICT_RE.search(ln)
            if m and not district:
                district = re.sub(r"\s+", " ", m.group(1)).strip()
            t = TERM_RE.search(ln)
            if t and not term:
                term = re.sub(r"\s+", " ", t.group(1)).strip().title()
        if district and term:
            break
    return district, term


def norm_district(d):
    d = d.title().replace("Legislative ", "").replace("Congressional ", "")
    units = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
             "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = {"Twenty": 20, "Thirty": 30, "Forty": 40}
    words = {w: str(i + 1) for i, w in enumerate(units)}
    parts_ = d.replace("-", " ").split()
    out_ = []
    i_ = 0
    while i_ < len(parts_):
        p_ = parts_[i_]
        if p_ in tens:
            n_ = tens[p_]
            if i_ + 1 < len(parts_) and parts_[i_ + 1] in units[:9]:
                n_ += units.index(parts_[i_ + 1]) + 1
                i_ += 1
            out_.append(str(n_))
        else:
            out_.append(p_)
        i_ += 1
    d = " ".join(out_)
    parts = [words.get(p, p) for p in d.split()]
    parts = [str(int(p)) if p.isdigit() else p for p in parts]  # "District 06" -> "District 6"
    return " ".join(parts).strip()


def norm_term(t):
    t = t.title().replace("-", " ")
    for digit, word in (("2", "Two"), ("4", "Four"), ("6", "Six")):
        t = re.sub(rf"^{digit}\b", word, t)
    return t


def collect(stem):
    """All tables of a book in reading order, annotated with office/district/term titles."""
    tables = []
    with pdfplumber.open(PDF_DIR / f"{stem}.pdf") as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            tabs, lines = page_tables(page)
            tabs = [t for t in tabs if any(r[0] in COUNTIES for r in t["rows"])]  # drops summary tables
            ordered, band_top = [], None
            for t in sorted(tabs, key=lambda t: t["bbox"][1]):
                if band_top is None or t["bbox"][1] - band_top > 20:
                    band_top = t["bbox"][1]
                ordered.append((band_top, t["bbox"][0], t))
            for _, _, t in sorted(ordered, key=lambda z: (z[0], z[1])):
                x0, top, x1, bottom = t["bbox"]
                wide = (x1 - x0) > 0.62 * page.width or (x0 < page.width / 2 - 30 and x1 > page.width / 2 + 30)
                above = sorted([(y, s) for y, s in lines if y < top - 1], reverse=True)
                half_off = None
                if not wide:  # narrow tables: titles in their own half first
                    for s in reversed(t["labels"]):
                        if office_of(s):
                            half_off = (office_of(s), s)
                            break
                cur, ctx = half_off, []
                found_full = False
                for y, s in above:
                    o = office_of(s)
                    if o:
                        if cur is None:
                            cur = (o, s)
                        found_full = True
                        break
                    ctx.insert(0, s)
                t.update(page=pno, office=cur[0] if cur else None, printed=cur[1] if cur else None,
                         ctx=ctx, wide=wide)
                tables.append(t)
    return tables


def same_header(a, b):
    return bool(a["header"]) and [tuple(a["header"].get(c, [])) for c in range(1, len(a["edges"]))] == \
        [tuple(b["header"].get(c, [])) for c in range(1, len(b["edges"]))]


def build_races(stem, tables):
    races, cur, pending = [], None, []
    for t in tables:
        is_cont_hdr = bool(t["header"]) and any(re.search(r"\bcont(inued|\.)?\b", " ".join(v), re.I)
                                                for v in t["header"].values())
        if is_cont_hdr:  # "Smith cont.": continues the race with those candidates, wherever it sits on the page
            pending.append(t)
            continue
        has_header = bool(t["header"])
        if not has_header:
            if cur is not None:
                cur["tables"].append(t)
            continue
        district, term = district_and_term([t["labels"], t["ctx"], [t["printed"] or ""]])
        ballot_src = " ".join(t["labels"] + t["ctx"] + [t["printed"] or ""])
        mb = BALLOT_RE.search(ballot_src)
        ballot = PARTY_NORM.get(mb.group(1).lower(), mb.group(1).title()) if mb else ""
        mv = VG_RE.search(ballot_src)
        vgroup = ""
        if mv:  # the 2012 primary prints each partisan race once per kind of voter
            ballot = PARTY_NORM[mv.group(2).lower()]
            vgroup = ("Nonpartisan voters (%s ballot)" % ballot) if mv.group(1) else ("%s voters" % ballot)
        if not mv and not mb and cur is not None and cur["vgroup"] and t["page"] - cur["tables"][-1]["page"] <= 1 \
                and district and district != cur["district"]:
            ballot, vgroup = cur["ballot"], cur["vgroup"]  # "District Two" under a "Nonpartisan ... Voters" heading
        recount = bool(re.search(r"recount", ballot_src, re.I))
        prev = cur["tables"][-1] if cur else None
        own_labels = [s for s in t["labels"] if not re.match(r"^page\b", s, re.I)]
        if (cur is not None and prev["page"] == t["page"] and not own_labels and not t.get("text_only")
                and t["office"] in (None, cur["office"]) and not same_header(prev, t)
                and sorted(r[0] for r in t["rows"]) == sorted(set(r[0] for tb in cur["tables"] if not tb.get("extension")
                                                               for r in tb["rows"]))):
            t["extension"] = True  # more candidate columns of the same race (same county rows)
            cur["tables"].append(t)
            continue
        total_in = lambda tb: any(TOTAL_RE.match(r[0]) for r in tb["rows"])
        if (cur is not None and same_header(prev, t) and not (district and district != cur["district"])
                and (not cur["has_total"] or not total_in(t)) and t["page"] - prev["page"] <= 1
                and (t["office"] in (None, cur["office"])) and recount == cur["recount"] and (vgroup == cur["vgroup"] or not mv)):
            cur["tables"].append(t)
            cur["has_total"] = cur["has_total"] or total_in(t)
            continue
        cur = {"office": t["office"] or (cur["office"] if cur else None), "printed": t["printed"],
               "district": district, "term": term, "ballot": ballot, "recount": recount, "vgroup": vgroup, "tables": [t], "has_total": total_in(t),
               "page": t["page"]}
        races.append(cur)
    for t in pending:
        words = {w.lower().strip(".,") for v in t["header"].values() for ln in v for w in ln.split()} - {"cont", "continued"}
        for r in reversed(races):
            first = r["tables"][0]
            names = " ".join(" ".join(v) for v in first["header"].values()).lower()
            if r["office"] and words and all(w in names for w in words) and abs(r["page"] - t["page"]) <= 1:
                r["tables"].append(t)
                break
    keyset = {(r["office"], r["district"], r["term"], r["ballot"]) for r in races if r["vgroup"].startswith("Nonpartisan")}
    for r in races:
        if not r["vgroup"] and (r["office"], r["district"], r["term"], r["ballot"]) in keyset:
            r["vgroup"] = "%s voters" % r["ballot"]
    return races


SUBLABEL = re.compile(r"^(dem|rep|np|lib|total|dem\.|rep\.|republican|democrat|democratic|nonpartisan|all|votes|voters)$", re.I)


def candidate_columns(t0):
    """{vote column: candidate dict}. Handles the 2014-style layout where each candidate has Dem/NP/Total
    sub-columns (the Total sub-column is the candidate's vote)."""
    header = t0["header"]
    ncol = len(t0["edges"]) - 1
    subs = {c for c in range(1, ncol + 1)
            if any(SUBLABEL.match(w) for ln in header.get(c, []) for w in ln.split()[-1:])}
    if sum(1 for c in range(1, ncol + 1) if any(re.match(r"total\b", ln.strip(), re.I) for ln in header.get(c, []))) >= 1 \
            and len(subs) >= ncol - 1 and ncol >= 3:
        cands, group = {}, []
        for c in range(1, ncol + 1):
            group.append(c)
            lines = header.get(c, [])
            if any(re.match(r"total\b", ln.strip(), re.I) for ln in lines):
                words = []
                for g in group:
                    for ln in header.get(g, []):
                        ws_ = [w for w in ln.split() if not SUBLABEL.match(w)]
                        words += ws_
                cands[c] = parse_candidate([" ".join(words)])
                group = []
        return cands
    return {c: parse_candidate(header.get(c, [])) for c in range(1, ncol + 1)}


def race_rows(stem, race):
    date, etype = ELECTIONS[stem], stem.split("_")[1]
    office = race["office"]
    t0 = race["tables"][0]
    cands = candidate_columns(t0)
    out, issues = [], []
    for t in race["tables"]:
        if t is not t0 and t["header"] and not any(re.search(r"\bcont(inued|\.)?\b", " ".join(v), re.I)
                                                    for v in t["header"].values()):
            cands = candidate_columns(t)
        ncol = len(t["edges"]) - 1
        if ncol != len(t0["edges"]) - 1:
            issues.append(f"{stem} p{t['page']}: {ncol} columns, race has {len(t0['edges']) - 1}")
            continue
        for name, prec, vals in t["rows"]:
            total = bool(TOTAL_RE.match(name))
            for ci, cand in cands.items():
                v = vals.get(ci)
                if v is None or cand["noise"]:
                    continue
                if len(v) == 3 and v[2] == v[0] + v[1]:  # Dem / NP / Total sub-columns in one cell
                    v = [v[2]]
                if len(v) != 1:
                    issues.append(f"{stem} p{t['page']}: {name} cell {ci} has {v}")
                    continue
                out.append({
                    "election_date": date, "election_type": etype, "office": office,
                    "office_level": LEVEL[office], "office_as_printed": race["printed"],
                    "district": norm_district(race["district"]), "term": norm_term(race["term"]),
                    "primary_ballot": race["ballot"], "voter_group": race["vgroup"], "is_recount": race["recount"], "jurisdiction": "Total" if total else name,
                    "jurisdiction_type": "race_total" if total else "county",
                    "partial_county_precincts": prec if prec is not None else "",
                    "candidate": cand["name"],
                    "party": cand["party"] or (race["ballot"] if etype == "primary" and not cand["write_in"] else ""),
                    "candidate_as_printed": cand["as_printed"], "is_write_in": cand["write_in"],
                    "winner": cand["winner"], "votes": v[0], "total_derived": False, "_page": t["page"]})
    # Races contained in a single county print no Total row; the county row is the race total.
    by = defaultdict(list)
    for r in out:
        by[r["candidate_as_printed"]].append(r)
    for rs in by.values():
        if not any(r["jurisdiction_type"] == "race_total" for r in rs):
            counties = [r for r in rs if r["jurisdiction_type"] == "county"]
            if len(counties) == 1:
                out.append({**counties[0], "jurisdiction": "Total", "jurisdiction_type": "race_total",
                            "partial_county_precincts": "", "total_derived": True})
    return out, issues


def validate(stem, races, rows):
    problems = []
    by = defaultdict(list)
    for r in rows:
        by[(r["office"], r["district"], r["term"], r["primary_ballot"], r["voter_group"], r["is_recount"], r["candidate_as_printed"])].append(r)
    for k, rs in by.items():
        tot = [r["votes"] for r in rs if r["jurisdiction_type"] == "race_total"]
        cty = [r for r in rs if r["jurisdiction_type"] == "county"]
        names = [r["jurisdiction"] for r in cty]
        if len(tot) != 1:
            problems.append((k, f"{len(tot)} Total rows"))
            continue
        if len(set(names)) != len(names):
            problems.append((k, f"duplicate county rows ({len(names) - len(set(names))})"))
        s = sum(r["votes"] for r in cty)
        if s != tot[0]:
            problems.append((k, f"counties sum {s} != Total {tot[0]} (ratio {s / tot[0] if tot[0] else 0:.2f})"))
    return problems


def process_book(stem):
    tables = collect(stem)
    races = build_races(stem, tables)
    rows, issues, skipped = [], [], []
    keep = []
    for race in races:
        if race["office"] in (None, "OUT"):
            if race["office"] is None:
                skipped.append(race["page"])
            continue
        r, i = race_rows(stem, race)
        rows += r
        issues += i
        keep.append(race)
    return rows, issues, keep, skipped


# Discrepancies inside the source itself; values are kept as printed (see data/race_results.ERRATA.md).
# (election, office, district, candidate): why
KNOWN_SOURCE_ISSUES = {
    ("2016_general", "President", "District 1", "Jill Stein & Ajamu Baraka"):
        "county rows sum to 3,375 but the printed district Total is 3,374",
    ("2016_primary", "President", "", "John McAfee"):
        "county rows sum to 124 but the printed Total is 123",
    ("2014_primary", "Auditor of Public Accounts", "", "Charlie Janssen"):
        "county rows sum to 93,262 but the printed Total is 93,212",
    ("2016_primary", "University Regents", "District 7", "Bob Phares"):
        "county rows sum to 35,549 but the printed Total is 33,549",
}
# Elections included in the published CSV (all checks pass apart from KNOWN_SOURCE_ISSUES).
PUBLISH = ["2024_general", "2024_primary", "2022_general", "2022_primary", "2020_general", "2020_primary",
           "2018_general", "2018_primary", "2016_general", "2016_primary", "2014_general", "2014_primary", "2012_general", "2012_primary",
           "2010_primary"]
COLUMNS = ["election_date", "election_type", "race_id", "office", "office_level", "office_as_printed", "district",
           "term", "primary_ballot", "voter_group", "is_recount", "jurisdiction", "jurisdiction_type", "partial_county_precincts",
           "candidate", "party", "candidate_as_printed", "is_write_in", "winner", "votes", "total_derived"]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    write = "--write" in sys.argv
    stems = args or (PUBLISH if write else [s for s in ELECTIONS if s not in SCANNED])
    verbose = "-v" in sys.argv
    allrows, ok = [], True
    for stem in stems:
        rows, issues, races, skipped = process_book(stem)
        problems = validate(stem, races, rows)
        known, real = [], []
        for k, msg in problems:
            why = KNOWN_SOURCE_ISSUES.get((stem, k[0], k[1], k[6]))
            (known if why else real).append((k, msg))
        print(f"{stem}: {len(races)} races, {len(rows)} rows, {len(real)} problems, {len(known)} known source "
              f"issues, {len(issues)} issues, unknown-title tables on pages {sorted(set(skipped))[:8]}")
        for k, msg in real[: (40 if verbose else 6)]:
            print("   PROBLEM", k[:6], k[6][:40], msg)
        for i in issues[:4]:
            print("   ISSUE", i)
        ok &= not real and not issues
        if not any(r["winner"] for r in rows):  # the book marks no winners; unknown, not "lost"
            for r in rows:
                r["winner"] = ""
        for r in rows:
            r["race_id"] = "-".join(filter(None, [r["election_date"], slug(r["office"]), slug(r["district"]),
                                                  slug(r["term"]), slug(r["primary_ballot"]), slug(r["voter_group"]),
                                                  "recount" if r["is_recount"] else ""]))
        allrows += rows
    if write:
        if not ok:
            sys.exit("not writing: unresolved problems")
        order = {"race_total": 0, "county": 1}
        allrows.sort(key=lambda r: (r["election_date"], r["race_id"], order[r["jurisdiction_type"]],
                                    r["jurisdiction"], r["candidate_as_printed"]))
        out = ROOT / "data" / "race_results.csv"
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(allrows)
        print("wrote", out, len(allrows), "rows")


if __name__ == "__main__":
    main()
