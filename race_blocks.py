#!/usr/bin/env python3
"""Stage 1 of race extraction: find the result tables on a canvass-book page.

Most books (2010-2024, and the 2002 primary) draw each table with thin rectangles as grid lines. Connected
groups of those rectangles are the tables; their vertical lines are the column edges. That is far more
reliable than guessing columns from text positions, because candidate names are centred over their columns
and numbers are right-aligned within them.

A table dict has: bbox, edges (column edges), labels (text lines above the table), header (per candidate
column: list of text lines), rows [(name, precincts, {col: int})], page_number.
"""
import re

NUM = re.compile(r"^[\d,]+$")
TOTAL_RE = re.compile(r"^(total|totals|statewide|statewide total)$", re.I)
PREC_RE = re.compile(r"\s*[(/]\s*(\d+)\s*prec(?:incts?)?\.?\)?", re.I)


def center_y(w):
    return (w["top"] + w["bottom"]) / 2


def center_x(w):
    return (w["x0"] + w["x1"]) / 2


def cluster_lines(words, tol=3.5):
    out, cur, c0 = [], [], None
    for w in sorted(words, key=lambda w: (center_y(w), w["x0"])):
        c = center_y(w)
        if c0 is None or abs(c - c0) > tol:
            if cur:
                out.append(sorted(cur, key=lambda x: x["x0"]))
            cur, c0 = [], c
        cur.append(w)
    if cur:
        out.append(sorted(cur, key=lambda x: x["x0"]))
    return out


def merge_split(nums):
    out = []
    for w in nums:
        if out and w["x0"] - out[-1]["x1"] < 2.0 and NUM.match(out[-1]["text"]) and NUM.match(w["text"]):
            p = out.pop()
            w = {**p, "text": p["text"] + w["text"], "x1": w["x1"]}
        out.append(w)
    return out


def parse_row(ws):
    """(name, number words) if the line is a data row, else None."""
    i, name = 0, []
    while i < len(ws):
        if not NUM.match(ws[i]["text"]):
            name.append(ws[i]["text"])
            i += 1
        elif name and i + 1 < len(ws) and ws[i + 1]["text"].lower().startswith("precinct"):
            name.append("(%s precincts)" % ws[i]["text"])  # "Sarpy 31 precincts 4459 ..."
            i += 2
        else:
            break
    nums = merge_split(ws[i:])
    if not name or not nums or not all(NUM.match(w["text"]) for w in nums):
        return None
    name = " ".join(name).strip("* ").strip()
    if not re.match(r"^[A-Za-z]", name) or name.startswith(("Page", "General Election", "Primary Election")):
        return None
    if re.search(r"district|subdivision|\bat large\b", name, re.I):
        return None
    return name, nums


def merged_tables(inside):
    """True when one grid component holds more than one distinct table (different 'County' headers)."""
    lines = cluster_lines(inside)
    heads = []
    for ln in lines:
        idx = [i for i, w in enumerate(ln) if w["text"] == "County"]
        if not idx:
            continue
        parts = []
        for a, i in enumerate(idx):
            j = idx[a + 1] if a + 1 < len(idx) else len(ln)
            parts.append(tuple(w["text"] for w in ln[i + 1:j]))
        heads.append(parts)
    if len(heads) >= 2:  # County headers on different lines: stacked tables
        return True
    return bool(heads) and len(set(heads[0])) > 1  # side by side with different candidates


def find_tables(page):
    """Connected components of thin grid rectangles that contain the word 'County'."""
    rects = [r for r in page.rects if (r["width"] <= 2.5 or r["height"] <= 2.5) and max(r["width"], r["height"]) >= 3]
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(n), key=lambda i: rects[i]["x0"])
    tol = 1.6
    for a in range(n):
        ra = rects[order[a]]
        for b in range(a + 1, n):
            rb = rects[order[b]]
            if rb["x0"] > ra["x1"] + tol and rb["x0"] - ra["x0"] > 700:
                break
            if rb["x0"] > ra["x1"] + tol:
                continue
            if rb["x1"] >= ra["x0"] - tol and rb["top"] <= ra["bottom"] + tol and rb["bottom"] >= ra["top"] - tol:
                parent[find(order[a])] = find(order[b])
    comps = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(rects[i])
    words = page.extract_words()
    tables = []
    for rs in comps.values():
        if len(rs) < 6:
            continue
        x0, x1 = min(r["x0"] for r in rs), max(r["x1"] for r in rs)
        top, bottom = min(r["top"] for r in rs), max(r["bottom"] for r in rs)
        if x1 - x0 < 50:
            continue
        inside = [w for w in words if x0 - 1 <= center_x(w) <= x1 + 1 and top - 2 <= center_y(w) <= bottom + 2]
        if not any(parse_row(sg) for ln in cluster_lines(inside) for sg in split_segments(ln)):
            continue
        if merged_tables(inside):
            continue  # several different tables share one grid: read them from text positions instead
        vx = sorted(r["x0"] for r in rs if r["width"] <= 2.5 and r["height"] >= 4)
        edges = []
        for x in vx:
            if not edges or x - edges[-1] > 3:
                edges.append(x)
        tables.append({"bbox": (x0, top, x1, bottom), "edges": edges, "words": inside})
    return sorted(tables, key=lambda t: (t["bbox"][1], t["bbox"][0])), words


def cell_of(x, edges):
    for i in range(len(edges) - 1):
        if edges[i] - 1 <= x < edges[i + 1] + 1:
            return i
    return None


def label_phrases(words, gap=18):
    """Text lines above a table cut into phrases at wide gaps: [(x_centre, text, x0, x1)]. Two tables side by side
    share one line such as "District Fifteen        District Seventeen"; the phrases keep them apart."""
    out = []
    for ln in cluster_lines(words):
        cur = [ln[0]]
        groups = []
        for w in ln[1:]:
            if w["x0"] - cur[-1]["x1"] > gap:
                groups.append(cur)
                cur = []
            cur.append(w)
        groups.append(cur)
        for g in groups:
            out.append(((g[0]["x0"] + g[-1]["x1"]) / 2, " ".join(x["text"] for x in g), g[0]["x0"], g[-1]["x1"]))
    return out


def split_segments(ln):
    """A line holding two (name, numbers) pairs side by side -> list of word lists."""
    segs, cur, seen_num = [], [], False
    for w in ln:
        if NUM.match(w["text"]):
            seen_num = True
        elif seen_num:
            segs.append(cur)
            cur, seen_num = [], False
        cur.append(w)
    segs.append(cur)
    return segs


def parse_table(page, t, words, prev_tables):
    x0, top, x1, bottom = t["bbox"]
    edges = t["edges"]
    lines = cluster_lines(t["words"])
    first_row = None
    for i, ln in enumerate(lines):
        if any(parse_row(sg) for sg in split_segments(ln)):
            first_row = i
            break
    if first_row is None:
        return None
    ncells = len(edges) - 1
    segcounts = [[sg for sg in split_segments(ln) if parse_row(sg)] for ln in lines[first_row:]]
    # one table printed as two or three county/value column groups side by side (the same table continued)
    multi = [sc for sc in segcounts if len(sc) >= 2]
    ks = {len(parse_row(sg)[1]) for sc in multi for sg in sc}
    two_tables = any(sum(1 for sg in sc if TOTAL_RE.match(parse_row(sg)[0])) >= 2 for sc in multi)
    doubled = bool(multi) and not two_tables and len(ks) == 1
    k = next(iter(ks)) if doubled else 0
    header_words = [w for ln in lines[:first_row] for w in ln]
    header, inline = {}, []
    for ln in cluster_lines(header_words):
        # a district label printed inside the header rows ("Congressional District 03") is not a candidate
        drop = set()
        for i, w in enumerate(ln):
            if w["text"] == "District" and i + 1 < len(ln):
                drop |= {i, i + 1}
                inline.append("District " + ln[i + 1]["text"])
        per = {}
        for i, w in enumerate(ln):
            if i in drop or w["text"] in ("County", "Candidate", "Congressional", "Legislative"):
                continue
            c = cell_of(center_x(w), edges)
            if doubled and k == 1:
                c = 1
            elif doubled and c is not None and c > k:
                continue  # right-hand copy of the header
            if c is None or c < 1:
                continue
            per.setdefault(c, []).append(w["text"])
        for c, ws_ in per.items():
            if doubled and len(ws_) % 2 == 0 and ws_[: len(ws_) // 2] == ws_[len(ws_) // 2:]:
                ws_ = ws_[: len(ws_) // 2]  # the same header printed over both column pairs
            header.setdefault(c, []).append(" ".join(ws_))
    rows = []
    for ln in lines[first_row:]:
        segs = split_segments(ln) if doubled else [ln]
        for sg in segs:
            r = parse_row(sg)
            if not r:
                continue
            name, nums = r
            prec = PREC_RE.search(name)
            name = PREC_RE.sub("", name).replace("*", "").strip()
            vals = {}
            for j, w in enumerate(nums):
                c = (j + 1) if doubled else cell_of(center_x(w), edges)
                vals.setdefault(c, []).append(int(w["text"].replace(",", "")))
            rows.append((name, int(prec.group(1)) if prec else None, vals))
    if doubled:
        edges = edges[: k + 2] if len(edges) >= k + 2 else [edges[0] + i * 80 for i in range(k + 2)]
    # label lines: text above the table, within its half of the page (or the whole page for wide tables)
    mid = page.width / 2
    wide = (x1 - x0) > 0.62 * page.width or (x0 < mid - 30 and x1 > mid + 30)  # spans both halves
    lo, hi = (0, page.width) if wide else ((0, mid) if (x0 + x1) / 2 < mid else (mid, page.width))
    floor = 0
    for p in prev_tables:
        px0, ptop, px1, pbot = p["bbox"]
        if px1 > lo and px0 < hi and pbot <= top:
            floor = max(floor, pbot)
    if not wide:  # keep only label text centred over this table (a neighbour's "District 15" is not ours)
        lo, hi = max(lo, x0 - 20), min(hi, x1 + 20)
    lab_words = [w for w in words if floor <= w["top"] and w["bottom"] <= top + 1 and lo <= center_x(w) < hi]
    labels = inline + [" ".join(w["text"] for w in ln) for ln in cluster_lines(lab_words)]
    near = [w for w in words if floor <= w["top"] and w["bottom"] <= top + 1 and w["top"] >= top - 90]
    phrases = label_phrases(near)
    return {"bbox": t["bbox"], "edges": edges, "header": header, "rows": rows, "labels": labels, "phrases": phrases, "inline": inline,
            "header_lines": [" ".join(w["text"] for w in ln) for ln in lines[:first_row]]}


def page_tables(page):
    tables, words = find_tables(page)
    out = []
    for i, t in enumerate(tables):
        pt = parse_table(page, t, words, tables[:i])
        if pt:
            out.append(pt)
    from race_text_tables import text_tables
    out += text_tables(page, tables, words)
    # page-level text lines (office titles etc.) with y, for office detection
    lines = [(sum(center_y(w) for w in ln) / len(ln), " ".join(w["text"] for w in ln)) for ln in cluster_lines(words)]
    return out, lines
