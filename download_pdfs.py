#!/usr/bin/env python3
"""Download general/primary election results PDFs from sos.nebraska.gov/previous-elections."""
import csv, hashlib, html, re, sys, time, urllib.request
from pathlib import Path
from urllib.parse import quote, urljoin

BASE = "https://sos.nebraska.gov/previous-elections"
OUT = Path(__file__).parent / "pdfs"
UA = {"User-Agent": "Mozilla/5.0 (NebraskaElectionDataArchive research project)"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

def links():
    page = get(BASE).decode("utf-8", "replace")
    for m in re.finditer(r'<a [^>]*href="([^"]*\.pdf)"[^>]*>(.*?)</a>', page, re.S | re.I):
        text = html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        yield " ".join(text.split()), html.unescape(m.group(1))

def classify(text, href):
    t = text.lower()
    if "special" in t or "special" in href.lower():
        return None
    if not re.search(r"official results|election results|canvass", t):
        return None
    kind = "primary" if "primary" in t or "primary" in href.lower() else "general" if "general" in t or "gen" in href.lower() else None
    if kind is None:
        return None
    y = re.search(r"/elections/(\d{4})/", href) or re.search(r"(20\d\d)", text + href)
    return (y.group(1), kind) if y else None

def main():
    OUT.mkdir(exist_ok=True)
    rows, seen = [], set()
    for text, href in links():
        c = classify(text, href)
        if not c or href in seen:
            continue
        seen.add(href)
        year, kind = c
        url = urljoin(BASE, quote(href, safe="/%:"))
        dest = OUT / f"{year}_{kind}.pdf"
        if not dest.exists():
            data = get(url)
            if not data.startswith(b"%PDF"):
                print("NOT A PDF:", url, file=sys.stderr); continue
            dest.write_bytes(data); time.sleep(1)
        data = dest.read_bytes()
        rows.append(dict(year=year, election=kind, file=dest.name, bytes=len(data),
                         sha256=hashlib.sha256(data).hexdigest(), link_text=text, source_url=url))
        print(dest.name, len(data))
    rows.sort(key=lambda r: (r["year"], r["election"]))
    with open(OUT.parent / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

if __name__ == "__main__":
    main()
