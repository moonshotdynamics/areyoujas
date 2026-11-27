"""Address-level sold prices from Pam Golding's public sold listings.

Property24 hides sold prices in PNGs and blocks our IP; Pam Golding publishes them
as JSON-LD on each sold listing, with the suburb in the URL slug, e.g.
/property-details/house-sold-rondebosch/kw1750640

Caveat that must survive into the UI: an agency's "sold" price is what they
advertise as achieved, not the Deeds Office transfer figure. Label the source.

    python agencies.py            # scan sold pages, keep our suburbs -> sold_agency.csv
"""
import csv
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).parent
OUT = HERE / "sold_agency.csv"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
SUBURBS = ("rondebosch", "claremont", "newlands", "constantia", "wynberg", "plumstead",
           "tokai", "kenilworth", "bergvliet", "meadowridge", "lansdowne", "observatory")
SLUG = re.compile(r"(/property-details/[a-z]+-sold-(" + "|".join(SUBURBS) + r")/[a-z0-9]+)")


def get(url, cache_dir=HERE / "cache" / "pg"):
    f = cache_dir / (re.sub(r"[^a-z0-9]+", "-", url.lower())[-90:] + ".html")
    if f.exists() and f.stat().st_size > 5000:
        return f.read_text(errors="replace")
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "en-ZA,en"})
    with urlopen(req, timeout=45) as r:
        body = r.read().decode("utf-8", "replace")
    cache_dir.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    time.sleep(0.7)
    return body


def parse(html):
    """-> {'address', 'suburb', 'price', 'sold'} or None. Reads JSON-LD only."""
    for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        if "RealEstateListing" not in block:
            continue
        data = json.loads(block)
        for node in data.get("@graph", [data]):
            blob = json.dumps(node)
            if '"streetAddress"' not in blob:
                continue
            addr = re.search(r'"streetAddress":\s*"([^"]+)"', blob)
            suburb = re.search(r'"addressLocality":\s*"([^"]+)"', blob)
            price = re.search(r'"price":\s*"?(\d{6,})', blob)
            sold = "SoldOut" in blob
            if addr and price:
                return {"address": addr.group(1).strip(),
                        "suburb": (suburb.group(1) if suburb else "").strip(),
                        "price": int(price.group(1)), "sold": sold}
    return None


def crawl(max_pages=25, want=80):
    seen, rows = set(), []
    for page in range(1, max_pages + 1):
        html = get(f"https://www.pamgolding.co.za/properties-sold?page={page}")
        hits = [(path, sub) for path, sub in SLUG.findall(html) if path not in seen]
        print(f"  page {page}: {len(hits)} in-suburb")
        for path, _sub in hits:
            seen.add(path)
            url = "https://www.pamgolding.co.za" + path
            r = parse(get(url))
            if r:
                rows.append({**r, "source": "pamgolding", "url": url})
        if len(rows) >= want:
            break
    uniq, kept = set(), []
    for r in rows:
        k = (r["address"].lower(), r["price"])
        if k not in uniq:
            uniq.add(k)
            kept.append(r)
    rows = kept
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["address", "suburb", "price", "sold", "source", "url"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} sold records -> {OUT.name}")
    return rows


if __name__ == "__main__":
    rows = crawl()
    # ponytail: the sold feed is nationwide and thin for the southern suburbs (~1 hit per 25 pages),
    # so this is not in the nightly cron yet. Wire it in once a suburb-scoped URL exists.
    assert all(r["price"] > 500_000 for r in rows), [r for r in rows if r["price"] <= 500_000]
    assert all(r["address"] for r in rows)
