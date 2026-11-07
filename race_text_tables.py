#!/usr/bin/env python3
"""Text-only table finder for pages (or page halves) that are not drawn with grid lines.

Used for the 2004 and 2008 books and for the odd half-page table without a grid. Tables are anchored on the
word "County" in a header line: label lines sit above it, candidate names on and below it, then a TOTAL row and
county rows. Candidate names are centred over their columns, so names are matched to columns with a small
dynamic program that cuts the name words into contiguous groups, one per column, minimising the distance
between each group's centre and the column's centre (blank columns allowed).
"""
import re

from race_blocks import NUM, PREC_RE, center_x, center_y, cluster_lines, parse_row, split_segments

TITLE_LINE = re.compile(r"^(member of|public service|state |united states|president|governor|secretary|attorney|"
                        r"auditor|university|page\b|general election|primary election|term|vote for|elected|"
                        r"statutory|legislat|congressional|u\.s\.|for )", re.I)
PRECINCT_LINE = re.compile(r"^\d+\s+precincts?$", re.I)


def assign_groups(tokens, centers, rights, blank_cost=45.0):
    """Partition x-sorted name tokens into len(centers) contiguous groups (possibly empty)."""
    m, n = len(tokens), len(centers)
    INF = float("inf")
    # best[j][i]: min cost placing the first i tokens in the first j columns
    best = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for j in range(1, n + 1):
        for i in range(m + 1):
            for k in range(i + 1):  # tokens k..i-1 go to column j
                if best[j - 1][k] == INF:
                    continue
                if k == i:
                    cost = blank_cost
                else:
                    c = (tokens[k]["x0"] + tokens[i - 1]["x1"]) / 2
                    cost = min(abs(c - centers[j - 1]), abs(tokens[i - 1]["x1"] - rights[j - 1]))
                if best[j - 1][k] + cost < best[j][i]:
                    best[j][i] = best[j - 1][k] + cost
                    back[j][i] = k
    groups, i = [], m
    for j in range(n, 0, -1):
        k = back[j][i]
        groups.append(tokens[k:i])
        i = k
    return list(reversed(groups))


def slot_starts(words):
    xs = sorted(w["x0"] for w in words if w["text"] == "County")
    out = []
    for x in xs:
        if not out or x - out[-1] > 8:
            out.append(x)
    return out


def text_tables(page, grid_tables, all_words):
    def inside(w):
        return any(t["bbox"][0] - 1 <= center_x(w) <= t["bbox"][2] + 1 and
                   t["bbox"][1] - 2 <= center_y(w) <= t["bbox"][3] + 2 for t in grid_tables)

    words = [w for w in all_words if not inside(w)]
    starts = slot_starts(words) or [0]
    bounds = [s - 3 for s in starts] + [page.width + 1]
    out = []
    for bi in range(len(starts)):
        lo, hi = bounds[bi], bounds[bi + 1]
        seg = [w for w in words if lo <= w["x0"] < hi]
        pre, rows, run = [], [], None
        lines = cluster_lines(seg)
        for ln in lines + [None]:
            r = parse_row(ln) if ln else None
            txt = " ".join(w["text"] for w in ln) if ln else ""
            if r:
                if run is None:
                    run = {"pre": pre, "rows": [], "lines": []}
                run["rows"].append(r)
                run["lines"].append(ln)
                continue
            if run is not None and ln and PRECINCT_LINE.match(txt):
                run["rows"][-1] = (run["rows"][-1][0] + " (" + txt + ")", run["rows"][-1][1])
                continue
            if run is not None:
                t = build(page, run, starts[bi], lo, hi)
                if t:
                    out.append(t)
                run, pre = None, []
            if ln:
                pre.append((center_y(ln[0]), ln))
    return out


def build(page, run, x0, lo, hi):
    from ocr_registration import COUNTIES
    names = [re.sub(r"\s*\(.*", "", r[0]) for r in run["rows"]]
    known = sum(1 for n in names if n in COUNTIES or n.lower() in ("total", "totals", "statewide"))
    if known < 0.7 * len(names) or len(names) < 2:
        return None
    pre = run["pre"]
    ci = None
    for i, (_, ln) in enumerate(pre):
        if ln[0]["text"] == "County":
            ci = i
    if ci is None:
        # no "County" anchor: either a continuation page (no header) or a half-page table whose header sits
        # in the lines just above its first row
        first_y = center_y(run["lines"][0][0])
        near = [(y, ln) for y, ln in pre if first_y - y <= 45]
        header_lines, labels = [], [" ".join(w["text"] for w in ln) for _, ln in pre]
        for _, ln in near:
            txt = " ".join(w["text"] for w in ln)
            if TITLE_LINE.match(txt):
                continue
            toks = []
            skip = False
            for i, w in enumerate(ln):
                if skip:
                    skip = False
                    continue
                if w["text"] == "District" and i + 1 < len(ln):
                    labels.append("District " + ln[i + 1]["text"])
                    skip = True
                    continue
                toks.append(w)
            if toks:
                header_lines.append(toks)
        ci = len(pre)
    else:
        header_lines = [ln for _, ln in pre[ci:]]
        labels = [" ".join(w["text"] for w in ln) for _, ln in pre[:ci]]
    # column centres: median number centre per column over the rows
    ncol = max(len(r[1]) for r in run["rows"])
    full = [r for r in run["rows"] if len(r[1]) == ncol]
    centers, rights = [], []
    for c in range(ncol):
        xs = sorted(center_x(r[1][c]) for r in full)
        centers.append(xs[len(xs) // 2])
        xr = sorted(r[1][c]["x1"] for r in full)
        rights.append(xr[len(xr) // 2])
    mids = [(centers[i] + centers[i + 1]) / 2 for i in range(ncol - 1)]
    spacing = (centers[-1] - centers[0]) / (ncol - 1) if ncol > 1 else 80
    edges = [lo, centers[0] - spacing / 2] + mids + [centers[-1] + spacing / 2]
    # header: each line's name tokens cut into one group per column
    header = {}
    for ln in header_lines:
        toks = [w for w in ln if w["text"] not in ("County", "Candidate")]
        if not toks:
            continue
        for j, grp in enumerate(assign_groups(toks, centers, rights)):
            if grp:
                header.setdefault(j + 1, []).append(" ".join(w["text"] for w in grp))
    rows = []
    for name, nums in run["rows"]:
        prec = PREC_RE.search(name)
        name = PREC_RE.sub("", name).strip()
        pm = re.search(r"\((\d+)\s+precincts?\)", name)
        vals = {}
        if len(nums) == ncol:
            for j, w in enumerate(nums):
                vals[j + 1] = [int(w["text"].replace(",", ""))]
        else:  # blank cells: place by nearest column centre
            for w in nums:
                j = min(range(ncol), key=lambda k: abs(center_x(w) - centers[k]))
                vals.setdefault(j + 1, []).append(int(w["text"].replace(",", "")))
        rows.append((name, int(prec.group(1)) if prec else None, vals))
    y_top = pre[ci][0] if ci < len(pre) else (center_y(run["lines"][0][0]) - 6)
    y_bot = center_y(run["lines"][-1][0])
    return {"bbox": (lo, y_top, hi if hi < page.width else page.width, y_bot), "edges": edges, "header": header,
            "rows": rows, "labels": labels, "header_lines": [" ".join(w["text"] for w in ln) for ln in header_lines],
            "text_only": True}
