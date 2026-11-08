#!/usr/bin/env python3
"""Text-only table finder for pages (or page halves) that are not drawn with grid lines.

Used for the 2004 and 2008 books and for the odd half-page table without a grid. Tables are anchored on the
word "County" in a header line: label lines sit above it, candidate names on and below it, then a TOTAL row and
county rows. Candidate names are centred over their columns, so names are matched to columns with a small
dynamic program that cuts the name words into contiguous groups, one per column, minimising the distance
between each group's centre and the column's centre (blank columns allowed).
"""
import re

from race_blocks import NUM, PREC_RE, to_int, center_x, center_y, cluster_lines, parse_row, split_segments

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


def merge_precinct_lines(lines):
    """'Cedar*' on one line and '5 precincts 1029 388 ...' on the next are one county row."""
    out = []
    SECOND = {"Red": "Willow", "Scotts": "Bluff", "Keya": "Paha", "Box": "Butte"}
    for ln in lines:
        txt = [w["text"] for w in ln]
        # a two-word county name wrapped onto two lines: "Red" / "Willow 3190 ..."
        if out and len(txt) == 1 and out[-1] and SECOND.get(out[-1][0]["text"]) == txt[0] and len(out[-1]) > 1:
            out[-1] = [out[-1][0], ln[0]] + out[-1][1:]  # "Red 4129 ..." then "Willow" on the next line
            continue
        if out and [w["text"] for w in out[-1]] and len(out[-1]) == 1 and SECOND.get(out[-1][0]["text"]) == txt[0]:
            out[-1] = out[-1] + ln
            continue
        if (out and len(txt) >= 3 and txt[0].isdigit() and txt[1].lower().startswith("precinct")
                and all(NUM.match(x) for x in txt[2:])
                and not any(NUM.match(w["text"]) for w in out[-1]) and len(out[-1]) <= 3):
            out[-1] = out[-1] + [{**ln[0], "text": "(%s precincts)" % txt[0]}] + ln[2:]
            continue
        out.append(ln)
    return out


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
    mid = page.width / 2
    if any(s < mid - 60 for s in starts) and any(s > mid - 60 for s in starts):
        right = min(s for s in starts if s > mid - 60)
        starts, bounds = [0, right], [0, min(mid, right - 3), page.width + 1]  # two tables side by side
    else:
        starts, bounds = [0], [0, page.width + 1]  # one (possibly wide) table per band
    out = []
    for bi in range(len(starts)):
        lo, hi = bounds[bi], bounds[bi + 1]
        seg = [w for w in words if lo <= w["x0"] < hi]
        pre, rows, run = [], [], None
        lines = merge_precinct_lines(cluster_lines(seg))
        seq = lines + [None]
        for li, ln in enumerate(seq):
            r = parse_row(ln) if ln else None
            txt = " ".join(w["text"] for w in ln) if ln else ""
            segs = [sg for sg in split_segments(ln) if parse_row(sg)] if (ln and not r) else []
            if len(segs) >= 2 and len({len(parse_row(sg)[1]) for sg in segs}) == 1:
                # two county/value column groups side by side: the same table continued in the right half
                if run is None:
                    run = {"pre": pre, "rows": [], "lines": [], "seg": []}
                for k, sg in enumerate(segs):
                    run["rows"].append(parse_row(sg))
                    run["seg"].append(k)
                run["lines"].append(segs[0])
                continue
            if r:
                if run is None:
                    run = {"pre": pre, "rows": [], "lines": [], "seg": []}
                run["rows"].append(r)
                run["seg"].append(0)
                run["lines"].append(ln)
                continue
            nxt = seq[li + 1] if li + 1 < len(seq) else None
            if (getattr(page, "is_ocr", False) and run is not None and ln and nxt and parse_row(nxt) and any(re.fullmatch(r"[\d,]+", w["text"]) for w in ln)
                    and center_y(ln[0]) - center_y(run["lines"][-1][0]) <= 18):
                # a row whose county name OCR lost: keep it, with a placeholder name, so its numbers still count
                run["rows"].append(("#", None))
                run["seg"].append(0)
                run["lines"].append(ln)
                run.setdefault("noisy_lines", {})[len(run["rows"]) - 1] = ln
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
    if known < 0.7 * len(names) or len(names) < 1:
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
    noisy = [i for i, r in enumerate(run["rows"]) if r[1] is None]
    seg_all = run.get("seg") or [0] * len(run["rows"])
    real = [(r, k) for r, k in zip(run["rows"], seg_all) if r[1] is not None]
    ncol = max(len(r[1]) for r, _ in real)
    full = [r for r, k in real if len(r[1]) == ncol and k == 0] or [r for r, _ in real if len(r[1]) == ncol]
    centers, rights = [], []
    for c in range(ncol):
        xs = sorted(center_x(r[1][c]) for r in full)
        centers.append(xs[len(xs) // 2])
        xr = sorted(r[1][c]["x1"] for r in full)
        rights.append(xr[len(xr) // 2])
    for i in noisy:  # lines whose county name was lost: numbers sitting under a column's right edge belong to it
        cells = [None] * ncol
        for w in run["noisy_lines"][i]:
            if re.fullmatch(r"[\d,]+", w["text"]):
                j = min(range(ncol), key=lambda k: abs(w["x1"] - rights[k]))
                if abs(w["x1"] - rights[j]) <= 9:
                    cells[j] = w
        run["rows"][i] = ("#", [c if c is not None else {"text": "?", "x0": rights[j] - 6, "x1": rights[j], "top": run["noisy_lines"][i][0]["top"],
                                                          "bottom": run["noisy_lines"][i][0]["bottom"]} for j, c in enumerate(cells)])
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
    rows, boxes = [], []
    for name, nums in run["rows"]:
        prec = PREC_RE.search(name)
        name = PREC_RE.sub("", name).replace("*", "").strip()
        pm = re.search(r"\((\d+)\s+precincts?\)", name)
        vals, box = {}, {}
        if len(nums) == ncol:
            for j, w in enumerate(nums):
                vals[j + 1] = [to_int(w["text"])]
                box[j + 1] = (w["x0"], w["top"], w["x1"], w["bottom"])
        else:  # blank cells: place by nearest column centre
            for w in nums:
                j = min(range(ncol), key=lambda k: abs(center_x(w) - centers[k]))
                vals.setdefault(j + 1, []).append(to_int(w["text"]))
                box[j + 1] = (w["x0"], w["top"], w["x1"], w["bottom"])
        rows.append((name, int(prec.group(1)) if prec else None, vals))
        boxes.append(box)
    y_top = pre[ci][0] if ci < len(pre) else (center_y(run["lines"][0][0]) - 6)
    y_bot = center_y(run["lines"][-1][0])
    sx = (lo + min(hi, page.width)) / 2
    return {"phrases": [(sx, l) for l in labels], "bbox": (lo, y_top, hi if hi < page.width else page.width, y_bot), "edges": edges, "header": header,
            "rows": rows, "boxes": boxes, "labels": labels, "header_lines": [" ".join(w["text"] for w in ln) for ln in header_lines],
            "text_only": True}
