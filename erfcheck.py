"""Deeds Office sold prices for Cape Town houses, via ErfCheck (erfcheck.co.za).

Free tier returns erf, township, extent and the last registered transfer (price + year).
Municipal value is paywalled, so we don't ask for it.

Rules learned the hard way, encoded here:
  * Houses only. Apartments, townhouses, complexes and industrial stands are noise.
  * Only clean "<number> <street>" addresses. Anything with a unit/complex prefix before
    the number resolves to the wrong erf or nothing at all.
  * Never trust the match: the returned record must carry the same street number, the
    same street, and a RESIDENTIAL category. One wrong jump discredits the whole site.
  * Polite by design: 15 s between lookups, a per-run budget, cache-first, and addresses
    that turned up nothing are remembered so we never ask twice.

    python erfcheck.py --budget=20     # look up houses, newest demand first
    python erfcheck.py --check         # assert the address cleaner and the match guard
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import city

HERE = Path(__file__).parent
OUT = HERE / "sold_erfcheck.json"
MISSES = HERE / "erfcheck_misses.json"
API = "https://erfcheck.co.za/api/lookup?address="
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
PAUSE = 15
HOUSE_KINDS = ("house",)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def clean(address):
    """'48 Francolin Road' -> ('48', 'francolin road'); anything messier -> None."""
    a = (address or "").strip()
    if not a or "," in a or "(" in a or re.search(r"\b(unit|penthouse|suite|shop|stand)\b", a, re.I):
        return None                       # complex / unit: not a house, and never resolves cleanly
    m = re.match(r"^(\d+[A-Za-z]?)\s+(.+?)(?:,\s*[^,]+)?$", a)
    if not m:
        return None
    num, street = m.group(1), m.group(2)
    words = city.expand(city.slug(street).split("-"))
    return num, " ".join(words)


def same_street(a, b):
    """'Rouwkoop Rd' is 'Rouwkoop Road' is 'rouwkoop-road'."""
    def flat(s):
        return " ".join(city.expand(city.slug(s).split("-")))
    return flat(a) == flat(b)


def fetch(address, suburb):
    url = API + urllib.parse.quote(f"{address}, {suburb}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read().decode("utf-8", "replace")
    events = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                events.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                pass
    return next((e["property"] for e in events if isinstance(e, dict) and "property" in e), None), events


def capped(events):
    """Their free tier allows 10 live lookups an hour. Being throttled is not 'no record' --
    writing it as one would silently skip houses forever."""
    for e in events:
        if isinstance(e, dict) and (e.get("upgrade") == "pro" or "allowed per hour" in str(e.get("message", ""))):
            m = re.search(r"opens at (\d{1,2}):(\d{2})", str(e.get("message", "")))
            wait = 900
            if m:                                   # times are SAST (UTC+2)
                now = time.gmtime()
                target = (int(m.group(1)) * 60 + int(m.group(2))) * 60 - 7200
                wait = (target - (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec)) % 86400 or 3600
            return True, min(max(wait, 60), 3600) + 20
    return False, 0


def verified(prop, num, street):
    """The record has to be the house we asked about, and it has to be a house."""
    if not prop:
        return None
    li = prop.get("latest") or {}
    price = li.get("lastSoldPrice")
    if not price:
        return None
    addr = prop.get("address") or {}
    if norm(addr.get("streetNumber")) != norm(num):
        return None
    if not same_street(addr.get("street"), street):
        return None
    if "RESIDENTIAL" not in (li.get("category") or "").upper():
        return None
    return {"price": int(price), "year": li.get("lastSoldYear"),
            "size": li.get("sizeSqm"), "erf": (prop.get("identifiers") or {}).get("erf"),
            "source": "deeds (ErfCheck)", "checked": time.strftime("%Y-%m-%d")}


def crawl(budget=20, for_hours=0):
    listings = json.loads((HERE / "listings.json").read_text())["listings"]
    sold = json.loads(OUT.read_text()) if OUT.exists() else {}
    misses = set(json.loads(MISSES.read_text())) if MISSES.exists() else set()
    done = set(sold) | {m.split("|", 1)[1] for m in misses if "|" in m}

    jobs = []
    for l in listings:
        if (l.get("kind") or "").lower() not in HOUSE_KINDS:
            continue
        if not l.get("address") or not l.get("suburb"):
            continue
        c = clean(l["address"])
        if not c or f"{l['suburb']}|{l['address']}" in sold:
            continue
        jobs.append((l, c))
    jobs.sort(key=lambda j: -(j[0].get("price") or 0))

    spent = 0
    for l, (num, street) in jobs:
        if spent >= budget:
            break
        key = f"{l['suburb']}|{l['address']}"
        if key in misses or key in sold:
            continue
        spent += 1
        try:
            prop, events = fetch(f"{num} {street}", l["suburb"])
        except Exception as e:
            print(f"  ! {l['address']}: {type(e).__name__} {e}")
            time.sleep(PAUSE)
            continue
        throttled, wait = capped(events)
        if throttled:
            deadline = time.time() + for_hours * 3600
            if time.time() + wait > deadline:
                MISSES.unlink(missing_ok=True)      # stale misses may have been throttles, not absences
                print(f"  hourly cap hit; stopping after {spent - 1} lookups "
                      f"(next window in {wait // 60} min)")
                break
            print(f"  hourly cap; sleeping {wait // 60} min for the next window")
            time.sleep(wait)
            continue
        hit = verified(prop, num, street)
        if hit:
            hit["suburb"] = l["suburb"]
            hit["address"] = l["address"]
            sold[key] = hit
            OUT.write_text(json.dumps(sold, indent=1, sort_keys=True))
            print(f"  {l['address']} ({l['suburb']}): R{hit['price']:,} ({hit['year']}) "
                  f"vs ask R{l['price']:,}")
        else:
            reason = "no record" if not prop else "not a verified house match"
            misses.add(key)
            MISSES.write_text(json.dumps(sorted(misses), indent=1))
            print(f"  - {l['address']} ({l['suburb']}): {reason}")
        time.sleep(PAUSE)
    print(f"{spent} lookups | {len(sold)} houses with a deeds price -> {OUT.name}")


def check():
    assert clean("9 Rouwkoop Road") == ("9", "rouwkoop road")
    assert clean("17A Main Rd") == ("17A", "main road")
    assert clean("Unit 4, 12 Long Street") is None
    assert clean("3 Bosch Lane (17-19 Rugby Rd)") is None
    assert same_street("Rouwkoop Rd", "Rouwkoop Road")
    ok = {"address": {"streetNumber": "9", "street": "Rouwkoop Road"},
          "latest": {"lastSoldPrice": 4750000, "lastSoldYear": 2025, "category": "RESIDENTIAL"}}
    assert verified(ok, "9", "rouwkoop road")["price"] == 4750000
    assert verified({**ok, "latest": {**ok["latest"], "category": "BUSINESS AND COMMERCIAL"}},
                    "9", "rouwkoop road") is None        # commercial erf is not the house
    assert verified({**ok, "address": {"streetNumber": "48", "street": "Rouwkoop Road"}},
                    "9", "rouwkoop road") is None        # wrong number
    print("ok: cleaner, street match, residential guard")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        crawl(int(next((a.split("=")[1] for a in sys.argv if a.startswith("--budget=")), 20)),
              float(next((a.split("=")[1] for a in sys.argv if a.startswith("--for-hours=")), 0)))
