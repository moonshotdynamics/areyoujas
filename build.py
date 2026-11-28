#!/usr/bin/env python3
"""Join asks to solds -> data.json for index.html.

sold.json is the scarce bit: {address_key: {price, year, source}}. Addresses are
matched case/punctuation-insensitively. The audit CSV is a bulk fallback of
transfers that never had a listing we tracked.
"""
import csv
import json
import re
import time
from pathlib import Path

HERE = Path(__file__).parent


def key(address):
    return re.sub(r"[^A-Z0-9 ]", "", (address or "").upper()).strip()


def load_sold():
    """Keyed by suburb + address. Address alone collides across Cape Town
    ("2 Glen Avenue" is in a dozen suburbs) and a wrong sold price is worse than none."""
    out = {}
    f = HERE / "sold.json"
    if f.exists():
        for k, v in json.loads(f.read_text()).items():
            out[key(v.get("suburb", "")) + "|" + key(k)] = v
    # agency sold listings (address + advertised achieved price, no transfer date)
    f = HERE / "sold_greeff.csv"
    if f.exists():
        for row in csv.DictReader(f.open()):
            if not row.get("address"):
                continue
            k = key(row.get("suburb", "")) + "|" + key(row["address"])
            out.setdefault(k, {"price": int(row["price"]), "year": None,
                               "suburb": row.get("suburb", ""), "source": "greeff sold"})
    # deeds transfers via ErfCheck: keyed "suburb|address" already, and verified
    # address-for-address before it was written (see erfcheck.py)
    f = HERE / "sold_erfcheck.json"
    if f.exists():
        for k, v in json.loads(f.read_text()).items():
            suburb, _, address = k.partition("|")
            out.setdefault(key(suburb) + "|" + key(address),
                           {"price": v["price"], "year": v.get("year"), "size": v.get("size"),
                            "suburb": v.get("suburb", suburb), "source": v["source"]})
    # bulk transfers pulled from published audit lists
    f = HERE / "sold_audit.csv"
    if f.exists():
        for row in csv.DictReader(f.open()):
            k = key(row.get("suburb", "")) + "|" + key(row["address"])
            out.setdefault(k, {"price": int(row["price"]), "year": int(row["year"]),
                               "size": int(row["size"]) if row.get("size") else None,
                               "suburb": row.get("suburb", ""), "source": row.get("source", "audit")})
    return out


def main():
    sold = load_sold()
    data = json.loads((HERE / "listings.json").read_text())
    year_now = time.gmtime().tm_year
    seen = set()
    cards = []
    for l in data["listings"]:
        sig = (l.get("price"), l.get("image"), l.get("beds"))   # P24 relists the same unit
        if sig in seen:
            continue
        seen.add(sig)
        if isinstance(l.get("erf"), str):                       # "433 m²" -> 433
            digits = re.sub(r"\D", "", l["erf"])
            l["erf"] = int(digits) if digits else None
        s = sold.get(key(l.get("suburb", "")) + "|" + key(l.get("address")))
        card = dict(l)
        card["sold"] = card["sold_year"] = card["jump"] = card["per_year"] = None
        # agency prices are advertised, not deeds-verified. They drive a jump, but the card
        # says which source it came from -- a wrong unlabelled jump is the one thing this
        # site cannot survive.
        # sold == asking is the same listing seen twice, not a markup: nothing to show
        if s and l.get("price") and s.get("price") != l["price"]:
            card["sold"] = s["price"]
            card["sold_year"] = s["year"]
            card["sold_source"] = s.get("source")
            card["jump"] = round(100 * (l["price"] - s["price"]) / s["price"])
            if s.get("year"):
                card["per_year"] = round(card["jump"] / max(1, year_now - s["year"]))
        card["suburb"] = l.get("suburb") or None
        card["url"] = ("https://www.property24.com/for-sale/%s/cape-town/western-cape/%s/%s"
                       % (l.get("slug", "rondebosch"), "8682", l["id"]))
        if not card["sold"]:
            continue                       # no past sale, no card: pairs are the entire product
        cards.append(card)

    matched = [c for c in cards if c["sold"]]
    stats = {
        "scanned": len(seen),
        "listings": len(cards),
        "matched": len(matched),
        "suburbs": len({c.get("suburb") or "Unknown" for c in cards}),
        "biggest_jump": max((c["jump"] for c in matched), default=None),
        "median_ask": sorted(c["price"] for c in cards)[len(cards) // 2] if cards else None,
    }
    out = {"generated": time.strftime("%Y-%m-%d"), "stats": stats,
           "listings": cards, "sold": sorted(
               [{"address": k, **v} for k, v in sold.items()], key=lambda x: -x["price"])}
    (HERE / "data.json").write_text(json.dumps(out, indent=1))

    # one self-contained file: no server, no CORS, drops straight on any static host
    html = (HERE / "index.html").read_text()
    inline = "Promise.resolve(" + json.dumps(out).replace("</", "<\\/") + ")"
    if 'fetch("data.json").then(r => r.json())' in html:
        html = html.replace('fetch("data.json").then(r => r.json())', inline)
    (HERE / "dist").mkdir(exist_ok=True)
    (HERE / "dist" / "index.html").write_text(html)
    print(f"{len(cards)} listings, {len(matched)} with a sold price -> data.json + dist/index.html")


if __name__ == "__main__":
    main()
