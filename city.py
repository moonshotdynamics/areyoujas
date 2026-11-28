"""The City of Cape Town property layer: 853,015 registered properties with an official
address (number, street, street type, suburb). Free, unthrottled, public ArcGIS REST.

Why it is here: Property24 can only be asked about a street slug it recognises
("rouwkoop-road"), while listing text says "Rouwkoop Rd". The City's street list is the
authority on what the street is actually called, so lookups use it instead of guessing.

    python city.py --fetch      # pull the street list for every Cape Town suburb (cached)
    python city.py --check      # assert the normaliser
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "city_streets.json"
API = ("https://citymaps.capetown.gov.za/agsext/rest/services/Search_Layers/"
       "SL_RGDB_PRTY/MapServer/0/query")
UA = "Mozilla/5.0 (compatible; areyoujas/1.0)"

ABBREV = {"rd": "road", "st": "street", "ave": "avenue", "av": "avenue", "cres": "crescent",
          "dr": "drive", "pl": "place", "cl": "close", "blvd": "boulevard", "str": "street",
          "la": "lane", "tce": "terrace", "pde": "parade", "hwy": "highway"}
# The City's own spelling differs from the suburb names our crawler uses.
ALIAS = {"Bo Kaap": "BO-KAAP", "Claremont Upper": "CLAREMONT", "Kenilworth Upper": "KENILWORTH",
         "Wynberg Upper": "WYNBERG NU", "Pinati": "PINATI ESTATE"}
TYPES = {"road", "street", "avenue", "crescent", "drive", "place", "close", "lane",
         "terrace", "way", "walk", "court", "parkway", "parade", "boulevard", "weg"}


def slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").lower())).strip("-")


def expand(words):
    return [ABBREV.get(w, w) for w in words]


def fetch(limit=None):
    subs = json.loads((HERE / "suburbs.json").read_text())
    streets = json.loads(OUT.read_text()) if OUT.exists() else {}
    for s in (subs[:limit] if limit else subs):
        name = s["name"]
        if name in streets:
            continue
        up = ALIAS.get(name, name.upper()).replace("'", "''")
        rows = []
        try:
            for where in (f"OFC_SBRB_NAME='{up}'", f"OFC_SBRB_NAME LIKE '%{up}%'"):
                q = {"where": where, "outFields": "STR_NAME,LU_STR_NAME_TYPE",
                     "returnDistinctValues": "true", "returnGeometry": "false", "f": "json"}
                req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q),
                                             headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    j = json.loads(r.read())
                rows = [[f["attributes"]["STR_NAME"], f["attributes"]["LU_STR_NAME_TYPE"]]
                        for f in j.get("features", [])]
                if rows:
                    break                      # exact name wins; LIKE only for renamed suburbs
        except Exception as e:
            print(f"  ! {name}: {type(e).__name__} {e}")
            continue
        streets[name] = rows
        print(f"  {name}: {len(rows)} streets")
        OUT.write_text(json.dumps(streets, indent=0, sort_keys=True))
        time.sleep(0.3)
    print(f"{len(streets)} suburbs -> {OUT.name}")


def canonical(suburb, street_slug):
    """'rouwkoop-rd' in Rondebosch -> 'rouwkoop-road', using the City's own street list.
    Falls back to the input when the suburb or the street is not in the list."""
    streets = json.loads(OUT.read_text()) if OUT.exists() else {}
    rows = streets.get(suburb) or []
    if not rows:
        return street_slug
    words = expand(street_slug.split("-"))
    want_full, want_name = slug("-".join(words)), slug("-".join(
        [w for w in words if w not in TYPES] or words))
    best = None
    for name, typ in rows:
        full = slug(f"{name} {typ or ''}")
        if full == want_full:
            return full
        if slug(name) == want_name and best is None:
            best = slug(f"{name} {typ or ''}") if typ else slug(name)
    return best or street_slug


def check():
    assert slug("12 Rouwkoop Rd") == "12-rouwkoop-rd"
    assert expand(["rouwkoop", "rd"]) == ["rouwkoop", "road"]
    print("ok: slug + abbreviation expansion")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--fetch" in sys.argv:
        n = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
        fetch(n)
    else:
        print(__doc__)
