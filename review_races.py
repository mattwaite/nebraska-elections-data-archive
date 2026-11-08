#!/usr/bin/env python3
"""List what is still wrong in a scanned book's race extraction and make contact sheets to read the cells by eye.

python3 review_races.py <stem>            # problems, each with the table id [page, slot, ordinal] and cell ids
python3 review_races.py <stem> sheet P S O  # picture of table (page P, slot S, ordinal O) for hand reading
"""
import sys

from PIL import Image

from cell_ocr import page_image
import extract_races as X


def main():
    stem = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == "sheet":
        p, s, o = (int(v) for v in sys.argv[3:6])
        tables = X.collect(stem)
        t = next(t for t in tables if tuple(t["tkey"]) == (p, s, o))
        x0, top, x1, bottom = t["bbox"]
        img = page_image(stem, p)
        sc = 500 / 72
        crop = img.crop((int(max(x0, 0) * sc), int((top - 40) * sc), int(min(x1 + 8, 612) * sc), int((bottom + 6) * sc)))
        crop = crop.resize((crop.width * 7 // 10, crop.height * 7 // 10))
        out = f"/private/tmp/review_{stem}_{p}_{s}_{o}.png"
        crop.save(out)
        print(out, crop.size)
        for ri, (name, prec, vals) in enumerate(t["rows"]):
            print(ri, name, {c: v[0] for c, v in vals.items()})
        return
    rows, issues, races, skipped = X.process_scanned(stem)
    problems = X.validate(stem, races, rows)
    print(len(problems), "problems")
    for k, msg in problems:
        tk = sorted({tuple(r["_tkey"]) for r in rows if X.candidate_key(r) == k and r.get("_tkey")})
        print(k[0], k[1], "|", k[6][:30], "|", msg, "| tables", tk)


if __name__ == "__main__":
    main()
