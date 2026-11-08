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
from race_blocks import page_tables, TOTAL_RE, label_phrases, cluster_lines, center_y
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
DISTRICT_RE = re.compile(r"((?:Legislative |Congressional )?District\s+(?:\d+|[A-Za-z]+(?:-[A-Za-z]+)?))", re.I)
TERM_RE = re.compile(r"(unexpired[^–\-]*|(?:two|four|six|2|4|6)[ -]year term|\d+ year term)", re.I)
PARTY_RE = re.compile(r"\(([^()]*)\)\s*$")
BALLOT_RE = re.compile(r"(republican|democratic|democrat|libertarian|green|nonpartisan|nebraska)\s+(party\s+)?"
                       r"(nomination|primary|ballot|candidates)", re.I)
VG_RE = re.compile(r"(nonpartisan\s+)?(republican|democratic|democrat|libertarian|green|nebraska)(?:\s+party)?\s+voters", re.I)
VG2_RE = re.compile(r"^(nonpartisan\s+)?(republican|democratic|democrat|libertarian)\s+party$", re.I)  # 2002 primary
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
    if t.startswith("*"):  # footnote ("*Please see Reported Problems.")
        return None
    if OUT_OF_SCOPE.search(t):
        return "OUT"
    for rx, name, level in OFFICES:
        if re.search(rx, t):
            return name
    return None


def parse_candidate(cell_lines):
    cell_lines = list(cell_lines)
    party_line = ""
    if len(cell_lines) > 1 and cell_lines[-1].strip().lower().rstrip(")") == "petition" and re.search(r"(^|\s)By$", cell_lines[-2].strip()):
        cell_lines = cell_lines[:-2] + [re.sub(r"(^|\s)By$", "", cell_lines[-2].strip()).strip()]  # "... By" / "Petition"
        cell_lines = [c for c in cell_lines if c]
        party_line = "By Petition"
    elif len(cell_lines) > 1 and PARTY_WORDS.match(cell_lines[-1].strip("() ")):
        party_line = cell_lines.pop().strip("() ")
    text = " ".join(cell_lines)
    if not party_line and re.search(r"\bBy Petition$", text):
        text, party_line = re.sub(r"\s*\bBy Petition$", "", text), "By Petition"
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


NOT_A_LABEL = re.compile(r"did not|nomination\b.*\(", re.I)  # footnotes that mention a district in passing


def phrase_district(t):
    """The "District N" phrase nearest above the table whose horizontal extent covers the table's. Tables side by
    side share one line ("District Fifteen      District Seventeen"), so each phrase is matched by position."""
    x0, top, x1, _ = t["bbox"]
    best = None
    for px, py, text, a, b in t.get("page_phrases", []):
        if py >= top - 1 or NOT_A_LABEL.search(text):
            continue
        if b < x0 - 10 or a > x1 + 10:  # the phrase must sit over this table
            continue
        m = DISTRICT_RE.search(text)
        if m:
            key = (top - py, abs(px - (x0 + x1) / 2))
            if best is None or key < best[0]:
                best = (key, m.group(1))
    return re.sub(r"\s+", " ", best[1]).strip() if best else ""


def phrase_ballot(t):
    """The "<Party> Party Nomination" heading printed over this table (neighbours may share the line)."""
    x0, top, x1, _ = t["bbox"]
    best = None
    for px, py, text, a, b in t.get("page_phrases", []):
        if py >= top - 1 or b < x0 - 10 or a > x1 + 10:
            continue
        m = BALLOT_RE.search(text)
        if m:
            key = (top - py, abs(px - (x0 + x1) / 2))
            if best is None or key < best[0]:
                best = (key, m)
    return best[1] if best else None


def district_and_term(sources):
    district, term = "", ""
    for source in sources:
        for ln in reversed(source):
            if NOT_A_LABEL.search(ln):
                continue
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


def page_phrase_rows(page):
    words = page.extract_words()
    out = []
    for ln in cluster_lines(words):
        y = sum(center_y(w) for w in ln) / len(ln)
        out.append((y, label_phrases(ln)))
    return out


def collect(stem):
    """All tables of a book in reading order, annotated with office/district/term titles."""
    tables = []
    if stem.split("@")[0] in SCANNED:
        from ocr_pages import ocr_pages
        pages = [(p.page_number, p) for p in ocr_pages(stem)]
        pdf = None
    else:
        pdf = pdfplumber.open(PDF_DIR / f"{stem}.pdf")
        pages = list(enumerate(pdf.pages, start=1))
    if True:
        manual = manual_tables(stem)
        for pno, page in pages:
            if pno in manual:
                for k, blk in enumerate(manual[pno]):
                    tables.append(synthetic_table(pno, k, blk))
                continue
            tabs, lines = page_tables(page)
            tabs = [t for t in tabs if any(r[0] in COUNTIES for r in t["rows"])]  # drops summary tables
            pphr = [(px, py, tx, a, b) for py, ph in page_phrase_rows(page) for px, tx, a, b in ph]
            for t in tabs:
                t["page_phrases"] = pphr
            ordered, band_top = [], None
            for t in sorted(tabs, key=lambda t: t["bbox"][1]):
                if band_top is None or t["bbox"][1] - band_top > 20:
                    band_top = t["bbox"][1]
                ordered.append((band_top, t["bbox"][0], t))
            seen_slot = {}
            for t in sorted(tabs, key=lambda t: (((t["bbox"][0] + t["bbox"][2]) / 2 > page.width / 2), t["bbox"][1])):
                slot = int((t["bbox"][0] + t["bbox"][2]) / 2 > page.width / 2)
                t["tkey"] = (pno, slot, seen_slot.get(slot, 0))
                seen_slot[slot] = seen_slot.get(slot, 0) + 1
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
    """Same candidate columns (party lines may be missing on a continuation page's repeated header)."""
    if not a["header"] or not b["header"]:
        return False
    ca, cb = candidate_columns(a), candidate_columns(b)
    if len(ca) != len(cb):
        return False
    import difflib
    for x, y in zip(ca.values(), cb.values()):
        if x["name"] == y["name"]:
            continue
        a, b = x["name"].lower(), y["name"].lower()
        if not (a and b and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.72)):
            return False  # (OCR'd repeats of a header differ by a few characters)
    return True


def build_races(stem, tables):
    races, cur, pending = [], None, []
    for t in tables:
        is_cont_hdr = bool(t["header"]) and any(re.search(r"\bcont(inued|\.)?\b", " ".join(v), re.I)
                                                for v in t["header"].values())
        if is_cont_hdr:  # "Smith cont.": continues the race with those candidates, wherever it sits on the page
            pending.append(t)
            continue
        has_header = bool(t["header"])
        if t.get("hand_entered") and has_header:
            f = t["force"]
            ident = (t["office"], f.get("district", ""), f.get("term", ""), f.get("ballot", ""), f.get("vgroup", ""))
            if cur is not None and cur.get("ident") == ident and same_header(cur["tables"][-1], t):
                cur["tables"].append(t)  # the same race continued on the next page
                continue
            cur = {"office": t["office"], "printed": f.get("office"), "district": f.get("district", ""),
                   "term": f.get("term", ""), "ballot": f.get("ballot", ""), "recount": False,
                   "vgroup": f.get("vgroup", ""), "tables": [t], "ident": ident,
                   "has_total": any(TOTAL_RE.match(r[0]) for r in t["rows"]), "page": t["page"]}
            races.append(cur)
            continue
        if not has_header:
            if cur is not None:
                cur["tables"].append(t)
            continue
        district, term = district_and_term([t["labels"], t["ctx"], [t["printed"] or ""]])
        inline_d = ""
        for s_ in t.get("inline", []):
            m_ = DISTRICT_RE.search(s_)
            if m_:
                inline_d = re.sub(r"\s+", " ", m_.group(1)).strip()
        district = inline_d or phrase_district(t) or district
        if t.get("force", {}).get("district") is not None:
            district = t["force"]["district"]
        if t.get("force", {}).get("term") is not None:
            term = t["force"]["term"]
        ballot_src = " ".join(t["labels"] + t["ctx"] + [t["printed"] or ""])
        mb = phrase_ballot(t) or BALLOT_RE.search(ballot_src)
        if t.get("force", {}).get("office"):
            t["office"] = t["force"]["office"]
        ballot = PARTY_NORM.get(mb.group(1).lower(), mb.group(1).title()) if mb else ""
        mv = VG_RE.search(" ".join(t["labels"]))  # this table's own half of the page first
        bare_np = any(re.fullmatch(r"nonpartisan voters", s.strip(), re.I) for s in t["labels"])
        if not mv and not bare_np:
            mv = VG_RE.search(ballot_src)
        if not mv and not bare_np and not mb:  # 2002-style bare "Republican Party" headings
            for cl in (t["labels"], t["ctx"]):
                for i in range(len(cl) - 1, -1, -1):
                    ln = cl[i].strip()
                    if any(x.strip().lower() == "nonpartisan" for x in cl[max(0, i - 2):i]):  # heading wrapped over lines
                        ln = "Nonpartisan " + ln
                    mv = VG2_RE.match(ln)
                    if mv:
                        break
                if mv:
                    break
        vgroup = ""
        if not mv and ballot and (bare_np or any(re.fullmatch(r"nonpartisan voters", s.strip(), re.I) for s in t["ctx"][-3:])):
            vgroup = "Nonpartisan voters (%s ballot)" % ballot  # "Nonpartisan Voters" under a party nomination heading
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
    infer_districts(races)
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


def infer_districts(races):
    """U.S. House races printed without a district label: assign the one congressional district whose counties
    (taken from labelled House races in the same book) contain all of the race's counties."""
    ref = {}
    for r in races:
        if r["office"] == "U.S. House" and r["district"]:
            ref.setdefault(norm_district(r["district"]), set()).update(
                row[0] for tb in r["tables"] for row in tb["rows"] if row[0] in COUNTIES)
    for r in races:
        r["inferred"] = False
        if r["office"] == "U.S. House" and not r["district"] and ref:
            cs = {row[0] for tb in r["tables"] for row in tb["rows"] if row[0] in COUNTIES}
            fits = [d for d, s in ref.items() if cs and cs <= s]
            if len(fits) == 1:
                r["district"], r["inferred"] = fits[0], True


def race_rows(stem, race):
    base = stem.split("@")[0]
    date, etype = ELECTIONS[base], base.split("_")[1]
    office = race["office"]
    t0 = race["tables"][0]
    cands = candidate_columns(t0)
    renames = load_renames(stem)
    for cd in cands.values():
        for old, new_ in renames.items():
            if cd["name"] == old or cd["as_printed"] == old:
                cd["name"] = new_
    named = [c["name"].strip() for c in cands.values() if c["name"].strip()]
    if named and all(re.fullmatch(r"for|against|yes|no|retain|repeal", n, re.I) for n in named):
        return [], []  # a ballot measure or retention question, out of scope
    out, issues = [], []
    for t in race["tables"]:
        if t is not t0 and t.get("extension") and t["header"] and not any(re.search(r"\bcont(inued|\.)?\b", " ".join(v), re.I)
                                                    for v in t["header"].values()):
            cands = candidate_columns(t)
        ncol = len(t["edges"]) - 1
        if ncol != len(t0["edges"]) - 1:
            issues.append(f"{stem} p{t['page']}: {ncol} columns, race has {len(t0['edges']) - 1}")
            continue
        for ri, (name, prec, vals) in enumerate(t["rows"]):
            total = bool(TOTAL_RE.match(name))
            for ci, cand in cands.items():
                v = vals.get(ci)
                if v is None or cand["noise"]:
                    continue
                if len(v) == 3 and None not in v and v[2] == v[0] + v[1]:  # Dem / NP / Total sub-columns in one cell
                    v = [v[2]]
                if len(v) != 1:
                    issues.append(f"{stem} p{t['page']}: {name} cell {ci} has {v}")
                    continue
                out.append({
                    "election_date": date, "election_type": etype, "office": office,
                    "office_level": LEVEL[office], "office_as_printed": race["printed"],
                    "district": norm_district(race["district"]), "district_inferred": race.get("inferred", False), "term": norm_term(race["term"]),
                    "primary_ballot": race["ballot"], "voter_group": race["vgroup"], "is_recount": race["recount"], "jurisdiction": "Total" if total else name,
                    "jurisdiction_type": "race_total" if total else "county",
                    "partial_county_precincts": prec if prec is not None else "",
                    "candidate": cand["name"],
                    "party": cand["party"] or (race["ballot"] if etype == "primary" and not cand["write_in"] else ""),
                    "candidate_as_printed": cand["as_printed"], "is_write_in": cand["write_in"],
                    "winner": cand["winner"], "votes": v[0], "total_derived": False, "ocr_derived": False, "_page": t["page"],
                    "_tkey": None if t.get("hand_entered") else t.get("tkey"), "_ci": ci, "_ri": ri,
                    "_box": (t.get("boxes") or [{}] * (ri + 1))[ri].get(ci), "_stem": stem.split("@")[0]})
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


def resolve_unknowns(rows):
    """A cell OCR could not read is recovered when it is the only unknown in its candidate's column: it equals the
    race Total minus the other counties (or the Total equals the sum of the counties)."""
    by = defaultdict(list)
    for r in rows:
        by[(r["office"], r["district"], r["term"], r["primary_ballot"], r["voter_group"], r["is_recount"],
            r["candidate_as_printed"])].append(r)
    for rs in by.values():
        unknown = [r for r in rs if r["votes"] is None]
        if len(unknown) != 1:
            continue
        u = unknown[0]
        tot = [r for r in rs if r["jurisdiction_type"] == "race_total" and r["votes"] is not None]
        cty = [r for r in rs if r["jurisdiction_type"] == "county" and r["votes"] is not None]
        if u["jurisdiction_type"] == "race_total":
            u["votes"] = sum(r["votes"] for r in cty)
        elif tot:
            u["votes"] = tot[0]["votes"] - sum(r["votes"] for r in cty)
        else:
            continue
        if u["votes"] >= 0:
            u["ocr_derived"] = True
        else:
            u["votes"] = None
    return rows


def candidate_key(r):
    return (r["office"], r["district"], r["term"], r["primary_ballot"], r["voter_group"], r["is_recount"],
            r["candidate_as_printed"])


def repair_from_variants(rows, variant_rows, cell_reader=None):
    """For each candidate column whose county rows do not add up to the Total, try replacing one or two cells with
    the value another OCR reading gave for the same cell; accept only an unambiguous exact fix."""
    from itertools import combinations
    alt = defaultdict(set)
    votes = defaultdict(list)
    for vr in variant_rows:
        for r in vr:
            if r.get("_tkey") and r["votes"] is not None:
                alt[(r["_tkey"], r["jurisdiction"], r["_ci"])].add(r["votes"])
                votes[(r["_tkey"], r["jurisdiction"], r["_ci"])].append(r["votes"])
    # a county row the main reading lost altogether (typically the last row, sitting on a heavy underline) comes back
    # when at least two other readings of the same table have it
    from collections import Counter, defaultdict as _dd
    have = _dd(set)
    template = {}
    for r in rows:
        if r.get("_tkey"):
            have[r["_tkey"]].add(r["jurisdiction"])
            template.setdefault((r["_tkey"], r["_ci"]), r)
    seen = _dd(list)
    for vr in variant_rows:
        for r in vr:
            if r.get("_tkey") and r["jurisdiction_type"] == "county" and r["jurisdiction"] not in have[r["_tkey"]] \
                    and r["votes"] is not None and r["jurisdiction"] in COUNTIES:
                seen[(r["_tkey"], r["jurisdiction"], r["_ci"])].append(r["votes"])
    # accept a recovered row only if adding it makes every candidate column of that table add up to its Total
    cand_rows = _dd(lambda: _dd(list))  # tkey -> jurisdiction -> [row dicts, one per ci]
    for (tk, jur, ci), vals in seen.items():
        tmpl = template.get((tk, ci))
        if tmpl is not None and len(vals) >= 2:
            cand_rows[tk][jur].append({**tmpl, "jurisdiction": jur, "jurisdiction_type": "county",
                                       "votes": Counter(vals).most_common(1)[0][0], "ocr_derived": True, "_box": None})
    from itertools import combinations as _comb
    added = []
    for tk, byj in cand_rows.items():
        cols = sorted({r["_ci"] for r in rows if r.get("_tkey") == tk})
        tab = [r for r in rows if r.get("_tkey") == tk]

        def gaps(extra):
            out = []
            for ci in cols:
                col = [r for r in tab if r["_ci"] == ci] + [x for x in extra if x["_ci"] == ci]
                t = [r["votes"] for r in col if r["jurisdiction_type"] == "race_total"]
                if len(t) != 1 or t[0] is None or any(r["votes"] is None for r in col):
                    return None
                out.append(t[0] - sum(r["votes"] for r in col if r["jurisdiction_type"] == "county"))
            return out
        g0 = gaps([])
        if g0 is None or not any(g0):
            continue
        for n in (1, 2):
            hit = []
            for combo in _comb(sorted(byj), n):
                extra = [x for j in combo for x in byj[j]]
                if set(x["_ci"] for x in extra) >= set(cols) and gaps(extra) == [0] * len(cols):
                    hit.append(extra)
            if len(hit) == 1:
                added.extend(hit[0])
                break
    rows.extend(added)
    # consensus: a cell the main reading could not read, or that most other readings disagree with, takes the
    # value at least three other readings agree on
    from collections import Counter
    for r in rows:
        key = (r.get("_tkey"), r["jurisdiction"], r.get("_ci"))
        if not key[0] or key not in votes:
            continue
        top = Counter(votes[key]).most_common(2)
        v, n = top[0]
        second = top[1][1] if len(top) > 1 else 0
        if v != r["votes"] and n >= 3 and n > second and (r["votes"] is None or n >= 4):
            r["votes"], r["ocr_derived"] = v, True
    by = defaultdict(list)
    for r in rows:
        by[candidate_key(r)].append(r)
    fixed = 0
    crop_read = {}
    for rs in by.values():
        cells = [r for r in rs if r["jurisdiction_type"] in ("county", "race_total")]
        tot = [r for r in cells if r["jurisdiction_type"] == "race_total"]
        if len(tot) != 1:
            continue

        def gap():
            t = tot[0]["votes"]
            s = sum(r["votes"] or 0 for r in cells if r["jurisdiction_type"] == "county")
            return None if t is None else t - s
        if gap() == 0 and all(r["votes"] is not None for r in cells):
            continue
        if cell_reader:  # add a high-resolution re-reading of every cell in the failing column
            for r in cells:
                if r.get("_box"):
                    vs_ = cell_reader(r["_stem"], r["_page"], r["_box"])
                    for v in vs_:
                        alt[(r["_tkey"], r["jurisdiction"], r["_ci"])].add(v)
                    if len(vs_) == 1:
                        crop_read[id(r)] = vs_[0]
        options = []
        for r in cells:
            vals = {v for v in alt.get((r["_tkey"], r["jurisdiction"], r["_ci"]), ()) if v != r["votes"]}
            if vals:
                options.append((r, sorted(vals)))
        solutions = []
        mandatory = [o for o in options if o[0]["votes"] is None]
        optional = [o for o in options if o[0]["votes"] is not None]
        unread = [r for r in cells if r["votes"] is None]
        if len(mandatory) == len(unread):  # every unreadable cell has at least one alternative reading
            from itertools import product
            for n in (0, 1, 2):
                for combo in combinations(optional, n):
                    group = mandatory + list(combo)
                    for pick in product(*[o[1] for o in group]):
                        old = [c[0]["votes"] for c in group]
                        for c, v in zip(group, pick):
                            c[0]["votes"] = v
                        ok = gap() == 0 and all(r["votes"] is not None for r in cells)
                        for c, v in zip(group, old):
                            c[0]["votes"] = v
                        if ok:
                            solutions.append([(c[0], v) for c, v in zip(group, pick)])
                if len(solutions) == 1:
                    break
                if solutions:
                    solutions = []  # ambiguous at this size: leave for hand correction
                    break
        if len(solutions) == 1:
            for r, v in solutions[0]:
                r["votes"], r["ocr_derived"] = v, True
            fixed += 1
        elif cell_reader:
            # several cells wrong: take the high-resolution reading wherever it differs, if that makes the column add up
            diff = [r for r in cells if id(r) in crop_read and crop_read[id(r)] != r["votes"]]
            if 0 < len(diff) <= 10:
                old_v = [r["votes"] for r in diff]
                for r in diff:
                    r["votes"] = crop_read[id(r)]
                if gap() == 0 and all(r["votes"] is not None for r in cells):
                    for r in diff:
                        r["ocr_derived"] = True
                    fixed += 1
                else:
                    for r, v in zip(diff, old_v):
                        r["votes"] = v
    return fixed


def validate(stem, races, rows):
    problems = []
    by = defaultdict(list)
    for r in rows:
        by[(r["office"], r["district"], r["term"], r["primary_ballot"], r["voter_group"], r["is_recount"], r["candidate_as_printed"])].append(r)
    for k, rs in by.items():
        if any(r["votes"] is None for r in rs):
            problems.append((k, "%d unreadable cells" % sum(r["votes"] is None for r in rs)))
            continue
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


def manual_tables(stem):
    """Hand transcriptions of whole scanned pages: corrections/races_<stem>.txt.

        @page 17
        @race Legislature | District 2 | | | |
        @cols Dave Pankonin | Jerry O. Bond
        TOTAL 7932 3538
        Cass 5577 2390

    @race fields: office | district | term | primary ballot | voter group (blank = none). Candidate names may end
    in "(Party)". A race that continues on the next page repeats @race and @cols. Every OCR table on a transcribed
    page is discarded, so a page is either fully OCR or fully by hand."""
    f = ROOT / "corrections" / f"races_{stem.split('@')[0]}.txt"
    pages = {}
    if not f.exists() or "@" in stem:
        return pages
    page, cur = None, None
    for raw in f.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@page"):
            page = int(line.split()[1])
            pages.setdefault(page, [])
            cur = None
        elif line.startswith("@race"):
            parts = [p.strip() for p in line[5:].split("|")] + [""] * 5
            cur = {"office": parts[0], "district": parts[1], "term": parts[2], "ballot": parts[3], "vgroup": parts[4],
                   "cols": [], "rows": [], "page": page}
            pages[page].append(cur)
        elif line.startswith("@cols"):
            cur["cols"] = [c.strip() for c in line[5:].split("|")]
        else:
            m = re.match(r"^(.*?)\s+((?:[\d,]+\s*)+)$", line)
            if not m:
                raise ValueError(f"{f.name}: cannot read row {line!r}")
            cur["rows"].append((m.group(1).strip(), [int(x.replace(",", "")) for x in m.group(2).split()]))
    return pages


def synthetic_table(page_no, k, blk):
    cols = []
    for c in blk["cols"]:
        m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", c)
        cols.append((m.group(1), m.group(2)) if m else (c, ""))
    header = {i + 1: ([n, "(%s)" % p] if p else [n]) for i, (n, p) in enumerate(cols)}
    for name, vals in blk["rows"]:
        if len(vals) != len(cols):
            raise ValueError(f"page {page_no} {blk['office']} {blk['district']}: row {name} has {len(vals)} numbers, "
                             f"{len(cols)} candidates")
    rows = [(name, None, {i + 1: [v] for i, v in enumerate(vals)}) for name, vals in blk["rows"]]
    office = office_of(blk["office"])
    top = 50 + 10 * k
    return {"bbox": (0, top, 612, top + 5 + 10 * len(rows)), "edges": [0] + [80 * (i + 1) for i in range(len(cols))] +
            [80 * len(cols) + 80], "header": header, "rows": rows, "boxes": [{} for _ in rows], "labels": [],
            "phrases": [], "inline": [], "header_lines": [], "page": page_no, "tkey": (page_no, 0, k), "office": office,
            "printed": blk["office"], "ctx": [], "wide": True, "page_phrases": [],
            "force": {"district": blk["district"], "term": blk["term"], "ballot": blk["ballot"],
                      "vgroup": blk["vgroup"], "office": blk["office"]}, "hand_entered": True}


def load_renames(stem):
    import json
    f = ROOT / "corrections" / f"races_{stem.split('@')[0]}.json"
    if "@" in stem or not f.exists():
        return {}
    return json.loads(f.read_text()).get("renames", {})


def apply_corrections(stem, tables):
    """Hand corrections for a scanned book (corrections/races_<stem>.json), read from the page images. Keys are
    [page, slot, ordinal-in-slot] table ids as printed by review_races.py; they override whatever OCR read."""
    import json
    f = ROOT / "corrections" / f"races_{stem.split('@')[0]}.json"
    if not f.exists() or "@" in stem:
        return tables
    c = json.loads(f.read_text())
    idx = {tuple(t["tkey"]): t for t in tables if t.get("tkey")}
    for p, s, o, meta in c.get("tables", []):
        t = idx.get((p, s, o))
        if t is not None:
            t.setdefault("force", {}).update(meta)
    for p, s, o, ci, name in c.get("headers", []):
        t = idx.get((p, s, o))
        if t is not None:
            t["header"][ci] = [name]
    for p, s, o, ri, name in c.get("row_names", []):
        t = idx.get((p, s, o))
        if t is not None:
            n, prec, vals = t["rows"][ri]
            t["rows"][ri] = (name, prec, vals)
    for p, s, o, ri, ci, v in c.get("cells", []):
        t = idx.get((p, s, o))
        if t is not None:
            t["rows"][ri][2][ci] = [v]
            t.setdefault("fixed_cells", set()).add((ri, ci))
    for spec in c.get("replace_tables", []):
        # a table too damaged to repair: keep its title/position, replace candidates and rows with a hand transcription
        p, s, o = spec["table"]
        t = idx.get((p, s, o))
        if t is None:
            continue
        t["header"] = {i + 1: [n] for i, n in enumerate(spec["candidates"])}
        t["edges"] = [t["edges"][0] + 80 * i for i in range(len(spec["candidates"]) + 2)]
        t["rows"] = [(name, None, {i + 1: [v] for i, v in enumerate(vals)}) for name, vals in spec["rows"]]
        t["boxes"] = [{} for _ in t["rows"]]
        t["hand_entered"] = True
        if spec.get("force"):
            t.setdefault("force", {}).update(spec["force"])
        for dp, ds, do in spec.get("drop", []):
            d = idx.pop((dp, ds, do), None)
            if d is not None:
                tables = [x for x in tables if x is not d]
    for p, s, o in c.get("drop_tables", []):
        t = idx.pop((p, s, o), None)
        if t is not None:
            tables = [x for x in tables if x is not t]
    return tables


def process_scanned(stem, use_cells=True):
    """Scanned book: main OCR reading + hand corrections, repaired cell by cell from the other readings
    (data/ocr_races/<stem>@...) and from per-cell high-resolution re-reads, wherever the sums don't work."""
    rows, issues, races, skipped = process_book(stem)
    variants = sorted(p.name for p in (ROOT / "data" / "ocr_races").glob(f"{stem}@*"))
    vrows = [process_book(v)[0] for v in variants]
    reader = None
    if use_cells:
        from cell_ocr import read_cell
        reader = read_cell
    repair_from_variants(rows, vrows, reader)
    return rows, issues, races, skipped


def process_book(stem):
    tables = apply_corrections(stem, collect(stem))
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
    return resolve_unknowns(rows), issues, keep, skipped


# Discrepancies inside the source itself; values are kept as printed (see data/race_results.ERRATA.md).
# (election, office, district, candidate): why
KNOWN_SOURCE_ISSUES = {
    ("2016_general", "President", "District 1", "Jill Stein & Ajamu Baraka"):
        "county rows sum to 3,375 but the printed district Total is 3,374",
    ("2016_primary", "President", "", "John McAfee"):
        "county rows sum to 124 but the printed Total is 123",
    ("2002_primary", "U.S. Senate", "", "Charlie A. Matulka"):
        "Democratic ballot, nonpartisan voters: county rows sum to 562 but the printed Total is 561",
    ("2014_primary", "Auditor of Public Accounts", "", "Charlie Janssen"):
        "county rows sum to 93,262 but the printed Total is 93,212",
    ("2016_primary", "University Regents", "District 7", "Bob Phares"):
        "county rows sum to 35,549 but the printed Total is 33,549",
}
# Elections included in the published CSV (all checks pass apart from KNOWN_SOURCE_ISSUES).
PUBLISH = ["2024_general", "2024_primary", "2022_general", "2022_primary", "2020_general", "2020_primary",
           "2018_general", "2018_primary", "2016_general", "2016_primary", "2014_general", "2014_primary", "2012_general", "2012_primary",
           "2010_general", "2010_primary", "2008_general", "2006_general", "2004_general", "2004_primary", "2002_primary"]
COLUMNS = ["election_date", "election_type", "race_id", "office", "office_level", "office_as_printed", "district",
           "district_inferred",
           "term", "primary_ballot", "voter_group", "is_recount", "jurisdiction", "jurisdiction_type", "partial_county_precincts",
           "candidate", "party", "candidate_as_printed", "is_write_in", "winner", "votes", "total_derived", "ocr_derived"]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    write = "--write" in sys.argv
    stems = args or (PUBLISH if write else [s for s in ELECTIONS if s not in SCANNED])
    verbose = "-v" in sys.argv
    allrows, ok = [], True
    for stem in stems:
        rows, issues, races, skipped = (process_scanned(stem) if stem in SCANNED else process_book(stem))
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
