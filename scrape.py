#!/usr/bin/env python3
"""AreYouJas: scrape asking prices off Property24, join to known last-sold prices.

    python scrape.py                # refresh listings.json for SUBURBS
    python build.py                 # join -> data.json (sold prices come from sold.json)

Property24 soft-blocks an IP after ~90 page fetches (503 "Server unavailable"),
so the crawl paces itself and caches every page it gets.
"""
import json
import random
import re
import sys
import time
import html as H
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "cache"

# (p24 area id, suburb slug, display name). Add a line per suburb.
SUBURBS = [
    ("8682", "rondebosch", "Rondebosch"),
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
DELAY = (2.0, 4.0)          # random pause between requests -- see module docstring


def get(url, cache_name):
    """Cached GET. Returns html, or None when Property24 says 'server unavailable'."""
    f = CACHE / cache_name
    if f.exists() and f.stat().st_size > 5000:
        return f.read_text(errors="replace")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-ZA,en"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:                      # 503 / 429 / timeout
        print(f"  ! {e} {url}", file=sys.stderr)
        return None
    if len(body) < 5000:
        print(f"  ! blocked {url}", file=sys.stderr)
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    time.sleep(random.uniform(*DELAY))
    return body


def _icon(blk, label):
    m = re.search(r'title="%s".{0,600}?<span>(\d+)</span>' % label, blk, re.S)
    return int(m.group(1)) if m else None


def _tiles(page):
    """Property24 tiles: the data-listing-number attribute appears twice per tile,
    so glue consecutive chunks that share an id back together."""
    blocks, cur, buf = [], None, ""
    for chunk in page.split('data-listing-number="')[1:]:
        m = re.match(r'(P?\d+)"', chunk)
        key = m.group(1) if m else None
        if key and key != cur:
            if cur:
                blocks.append((cur, buf))
            cur, buf = key, chunk
        else:
            buf += chunk
    if cur:
        blocks.append((cur, buf))
    return blocks


def parse_search(page, suburb):
    out = []
    for key, blk in _tiles(page):
        pr = (re.search(r'itemprop="price"[^>]*content="(\d+)"', blk)
              or re.search(r'p24_price">\s*(?:<[^>]*>\s*)*R\s*([\d\s]+)', blk))
        price = int(re.sub(r"\D", "", pr.group(1))) if pr and re.sub(r"\D", "", pr.group(1)) else None
        if not price:
            continue
        addr = re.search(r'class="p24_address">\s*([^<]*)', blk)
        img = re.search(r'(https://images\.prop24\.com/\d+/Crop\d+x\d+)', blk)
        out.append({
            "id": key.lstrip("P"), "price": price,
            "address": H.unescape(addr.group(1)).strip() if addr else None,
            "suburb": suburb,
            "image": img.group(1) if img else None,
            "beds": _icon(blk, "Bedrooms"), "baths": _icon(blk, "Bathrooms"),
            "parking": _icon(blk, "Parking Spaces"),
        })
    return out


def parse_detail(page, listing):
    """The search tile hides the street address on premium tiles; the detail page has it."""
    def f(label):
        i = page.find(f">{label}</div>")
        if i < 0:
            return None
        m = re.search(r'p24_propertyOverviewResult">\s*(?:<div class="p24_info">)?\s*(?:<a[^>]*>)?\s*([^<]{1,80})',
                      page[i:i + 500])
        return H.unescape(m.group(1)).strip() if m else None

    full = f("Street Address")                       # "9 Rouwkoop Road, Rondebosch"
    if full:
        listing["address"] = full.split(",")[0].strip()
    listing["ptype"] = f("Type of Property")
    listing["listed"] = f("Listing Date")
    erf = f("Erf Size")
    listing["erf"] = int(re.sub(r"\D", "", erf)) if erf and re.sub(r"\D", "", erf) else None
    return listing


def scrape():
    listings = {}
    for area, slug, name in SUBURBS:
        base = f"https://www.property24.com/for-sale/{slug}/cape-town/western-cape/{area}"
        page1 = get(base, f"{slug}_p1.html")
        if not page1:
            print(f"! {name}: blocked before we started")
            continue
        total = int(re.search(r'p24_bold">(\d+)</span><span>results', page1).group(1)) if re.search(
            r'p24_bold">(\d+)</span><span>results', page1) else 1
        pages = [page1] + [get(f"{base}/p{n}", f"{slug}_p{n}.html") for n in range(2, 2 + (total // 22))]
        for page in filter(None, pages):
            for l in parse_search(page, name):
                listings.setdefault(l["id"], l)
    missing = [l for l in listings.values() if not l["address"]]
    print(f"{len(listings)} listings, {len(missing)} need a detail page")
    for l in missing:
        page = get(f"https://www.property24.com/for-sale/{SUBURBS[0][1]}/cape-town/western-cape/"
                   f"{SUBURBS[0][0]}/{l['id']}", f"detail_{l['id']}.html")
        if page:
            parse_detail(page, l)
    out = HERE / "listings.json"
    out.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"),
                               "listings": list(listings.values())}, indent=1))
    print(f"wrote {out} ({len(listings)} listings, "
          f"{sum(1 for l in listings.values() if l['address'])} with an address)")


if __name__ == "__main__":
    CACHE.mkdir(exist_ok=True)
    scrape()
