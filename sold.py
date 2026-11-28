"""Fill sold.json: for every listing address, find its Property24 values page and
decode the last-sold price/year (see ocr.py for why that needs decoding at all).

    python sold.py            # crawl the addresses in listings.json
    python sold.py --check    # run the whole path against cached pages, assert known answer

Property24 blocks an IP after roughly 90 page fetches, so this paces itself, caches
every page and simply resumes next run. Run it from a different box if the home IP
is serving 503s.
"""
import json
import re
import sys
from pathlib import Path

import city
import ocr
from scrape import get, CACHE

HERE = Path(__file__).parent
SOLD = HERE / "sold.json"
AREA, SUBURB = "8682", "rondebosch"


# Property24 throttles an IP near 90 fetches: cap a run, and remember the addresses that
# have no sale on record so each night starts where the last one stopped instead of again.
COUNT = [0]
BUDGET = [80]
BLOCKED = [False]                                  # a 503 is not "no sale on record"
FAILS = [0]                                        # one 404 is a bad slug, two in a row is a block


def _get(url, name):
    f = CACHE / name
    if f.exists() and f.stat().st_size > 5000:
        return get(url, name)                       # cached: free
    if COUNT[0] >= BUDGET[0]:
        return None
    COUNT[0] += 1
    html = get(url, name)
    if html is None:                               # failed fetch: could be a 404 or a 503
        FAILS[0] += 1
        BLOCKED[0] = FAILS[0] >= 2
    else:
        FAILS[0] = 0
    return html


def norm(address):
    return re.sub(r"[^A-Z0-9 ]", "", (address or "").upper()).strip()


def parse_address(addr):
    """'9 Rouwkoop Road' -> ('9', 'rouwkoop-road'). None for unit/complex names
    ('Unit B 125 Milner Road'), which have no erf-level values page of their own."""
    m = re.match(r"(\d+[A-Za-z]?)\s+(.+)$", (addr or "").strip())
    if not m:
        return None
    street = re.sub(r"[^a-z ]", "", m.group(2).lower()).strip().replace(" ", "-")
    return m.group(1).lower(), street


def street_map(street_slug, slug=SUBURB, area=AREA):
    """{'9-rouwkoop-road': [hash, ...]} from one or more pages of the street's values list."""
    slugs, page = {}, 1
    while True:
        url = (f"https://www.property24.com/property-values/{street_slug}/"
               f"{slug}/cape-town/western-cape/{area}" + (f"/p{page}" if page > 1 else ""))
        name = f"street_{slug}_{street_slug}_p{page}.html"
        if not (CACHE / name).exists():            # pages cached before suburbs were per-address
            old = CACHE / f"street_{street_slug}_p{page}.html"
            if old.exists():
                (CACHE / name).write_text(old.read_text(errors="replace"))
        html = _get(url, name)
        if not html:
            break
        # /property-values/9-rouwkoop-road/rondebosch/cape-town/western-cape/<hash>
        found = re.findall(rf"/property-values/(\d+[a-z]?-{re.escape(street_slug)})/"
                           rf"{re.escape(slug)}/cape-town/western-cape/([0-9a-z]{{20,}})", html)
        new = {}
        for key, h in found:
            new.setdefault(key, [])
            if h not in new[key]:
                new[key].append(h)
        if not new or new == slugs:
            break
        for k, v in new.items():
            slugs.setdefault(k, [])
            slugs[k] += [h for h in v if h not in slugs[k]]
        page += 1
    return slugs


def lookup(num, street_slug, slugs, slug=SUBURB, area=AREA):
    """Decode the values page(s) for one address; prefer the first page with a sale."""
    candidates = slugs.get(f"{num}-{street_slug}", [])
    for h in candidates:
        url = (f"https://www.property24.com/property-values/{num}-{street_slug}/"
               f"{slug}/cape-town/western-cape/{h}")
        html = _get(url, f"values_{slug}_{num}-{street_slug}_{h[:12]}.html")
        if not html:
            continue
        r = ocr.read(html)
        if r["unknown"]:
            # unlabelled glyphs: dumped for a one-time labelling pass, value is not trusted
            todo = json.loads(ocr.LABELS.with_name("glyphs_unknown.json").read_text()) \
                if ocr.LABELS.with_name("glyphs_unknown.json").exists() else {}
            for bits in r["unknown"]:
                todo[ocr.h64(bits)] = ocr.art(bits)
            ocr.LABELS.with_name("glyphs_unknown.json").write_text(json.dumps(todo, indent=1))
            print(f"  ? unlabelled glyphs on {num} {street_slug} ({r['text']}) -> glyphs_unknown.json")
            continue
        if r["sold"]:
            return {"price": r["sold"], "year": r["year"], "source": "property24 deeds"}
    return None


def crawl(budget=80):
    """Look up the deeds sold price for every address we hold. Suburb-aware: the values
    URL carries the listing's own suburb, which is the difference between a hit and a
    wasted request."""
    BUDGET[0] = budget
    data = json.loads((HERE / "listings.json").read_text())
    subs = {s["name"]: (s["slug"], s["area"]) for s in
            json.loads((HERE / "suburbs.json").read_text())}
    sold = json.loads(SOLD.read_text()) if SOLD.exists() else {}
    have = {norm(k) for k in sold}
    missf = HERE / "sold_misses.json"          # addresses with no sale on record
    misses = set(json.loads(missf.read_text())) if missf.exists() else set()

    jobs = {}
    for l in data["listings"]:
        parsed = parse_address(l.get("address"))
        if not parsed or l.get("suburb") not in subs:
            continue
        if norm(l["address"]) in have or norm(l["address"]) in misses:
            continue
        slug, area = subs[l["suburb"]]
        street = city.canonical(l["suburb"], parsed[1])     # "rouwkoop-rd" -> "rouwkoop-road"
        jobs.setdefault((slug, area, street), []).append((parsed[0], l["address"], l["suburb"]))

    for (slug, area, street), items in sorted(jobs.items()):
        if COUNT[0] >= budget:
            break
        slugs = street_map(street, slug, area)
        for num, addr, suburb in sorted(items):
            if COUNT[0] >= budget:
                break
            hit = lookup(num, street, slugs, slug, area)
            if hit:
                hit["suburb"] = suburb
                sold[addr] = hit
                have.add(norm(addr))
                print(f"  {addr} ({suburb}): R{hit['price']:,} ({hit['year']})")
            elif not BLOCKED[0]:
                misses.add(norm(addr))             # page loaded, no sale: safe to skip for good
        SOLD.write_text(json.dumps(sold, indent=1, sort_keys=True))
        if not BLOCKED[0]:
            missf.write_text(json.dumps(sorted(misses), indent=1))
        if BLOCKED[0]:
            print("  503 - stopping; nothing marked as 'no sale'")
            break
    print(f"{COUNT[0]} fetches | {len(sold)} addresses with a sold price -> sold.json")


def check():
    """Whole path on the cached 9 Rouwkoop page; fails loudly if the decode breaks."""
    page = Path("/tmp/p24_addr.html")
    if not page.exists():
        sys.exit("no cached 9 Rouwkoop page to check against")
    r = ocr.read(page.read_text(errors="replace"))
    assert r["sold"] == 4750000, r
    assert r["year"] == 2025, r
    assert not r["unknown"], r["unknown"]
    assert parse_address("9 Rouwkoop Road") == ("9", "rouwkoop-road")
    assert parse_address("34 Albion Rd") == ("34", "albion-rd")
    assert parse_address("Unit B 125 Milner Road") is None
    slugs = street_map("rouwkoop-road")
    assert "9-rouwkoop-road" in slugs, slugs
    print("ok: 9 Rouwkoop -> R4,750,000 (2025); address parsing works")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        crawl(int(next((a.split("=")[1] for a in sys.argv if a.startswith("--budget=")), 80)))
