"""Sold prices from Greeff's public sold listings (plain HTML, no JS).

Each sold card carries: data-id, the address in the URL slug, and .card-price.
That is an address-level sold price without touching a detail page, which is why
this is the volume source -- Property24 renders the same number as an image and
blocks the IP, Pam Golding's feed is nationwide and thin.

Caveat: this is the agency's advertised achieved price, not the Deeds Office
transfer figure. Stored with source="greeff sold" so the UI can say so.

    python greeff.py [pages]
"""
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).parent
OUT = HERE / "sold_greeff.csv"
CACHE = HERE / "cache" / "greeff"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
BASE = "https://www.greeff.co.za/results/residential/sold/cape-town/"   # Cape Town only
CARD = re.compile(r'class="property-card-sm" href="(/results/residential/for-sale/[^"]+)"(.*?)(?=class="property-card-sm"|$)', re.S)
URL_PARTS = re.compile(r"/results/residential/for-sale/([a-z0-9-]+)/([a-z0-9-]+)/[a-z0-9-]+/(\d+)(?:/([a-z0-9-]+))?/?")


def get(url, name):
    f = CACHE / name
    if f.exists() and f.stat().st_size > 3000:
        return f.read_text(errors="replace")
    req = Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip",
                               "Accept-Language": "en-ZA,en"})
    with urlopen(req, timeout=45) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
    body = raw.decode("utf-8", "replace")
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    time.sleep(0.8)
    return body


def parse(page):
    out = []
    for href, blk in CARD.findall(page):
        m = URL_PARTS.match(href)
        if not m:
            continue
        town, suburb, ident, slug = m.groups()
        price = re.search(r'card-price[^>]*>\s*R\s*([\d\s,]+)', blk)
        if not price:
            continue
        value = int(re.sub(r"\D", "", price.group(1)))
        if value < 300_000:
            continue
        address = slug.replace("-", " ").title() if slug else None
        out.append({"town": town.replace("-", " ").title(), "suburb": suburb.replace("-", " ").title(),
                    "address": address, "price": value, "id": ident,
                    "url": "https://www.greeff.co.za" + href})
    return out


def crawl(pages=40):
    rows, seen = [], set()
    for p in range(1, pages + 1):
        url = BASE + (f"?page={p}" if p > 1 else "")
        page = get(url, f"sold_p{p}.html")
        found = parse(page)
        new = [r for r in found if r["id"] not in seen]
        for r in new:
            seen.add(r["id"])
        rows += new
        cpt = sum(1 for r in rows if r["town"].lower() == "cape town")
        print(f"  page {p}: +{len(new)} (cape town total {cpt})")
        if not new:
            break
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["town", "suburb", "address", "price", "id", "url"])
        w.writeheader()
        w.writerows(rows)
    cpt = [r for r in rows if r["town"].lower() == "cape town"]
    print(f"{len(rows)} sold records ({len(cpt)} Cape Town) -> {OUT.name}")
    return rows


if __name__ == "__main__":
    rows = crawl(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
    assert rows, "no cards parsed - check the selectors"
    assert all(r["price"] > 300_000 for r in rows)
