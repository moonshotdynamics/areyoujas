"""Fetch the photo gallery for listings that only have a cover image.

Property24 detail pages carry the whole gallery as image ids at several sizes:
  images.prop24.com/<id>/Ensure1280x720   (big, for the lightbox)
  images.prop24.com/<id>/Crop525x350      (cover, already in listings.json)

Detail pages are the rate-limited part of this site (~90 fetches then 503), so
this runs on a budget and resumes: listings that already have "images" are
skipped, and every page is cached on disk.

    python galleries.py 30
"""
import json
import random
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).parent
CACHE = HERE / "cache" / "detail"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
IMG = re.compile(r'images\.prop24\.com/(\d{6,})/Ensure1280x720')
LIST = re.compile(r'Listing number: P24-(\d+), Image number: (\d+)')


def gallery(html):
    """Ordered, deduped image ids from the main gallery block, best effort."""
    # every gallery <img> says "Listing number: P24-<id>, Image number: <n>", so take the
    # listing with the most images and order by n -- a plain image-id scrape would scoop up
    # the "similar properties" strip underneath.
    pairs = re.findall(r'images\.prop24\.com/(\d{6,})/[^"\']*[^>]*alt="Listing number: P24-(\d+), '
                       r'Image number: (\d+)"', html)
    by = {}
    for img, lid, n in pairs:
        by.setdefault(lid, {})[int(n)] = img
    if not by:
        return []
    best = max(by.values(), key=len)
    return [best[k] for k in sorted(best)][:10]


def main(budget=30):
    data = json.loads((HERE / "listings.json").read_text())
    listings = data["listings"]
    urls = {c["id"]: c["url"] for c in json.loads((HERE / "data.json").read_text())["listings"]
            if c.get("url")}          # builds the listing URL the crawler uses
    subs = {s["name"]: (s["slug"], s["area"]) for s in json.loads((HERE / "suburbs.json").read_text())}
    todo = [l for l in listings if not l.get("images")]
    random.shuffle(todo)
    todo.sort(key=lambda l: 0 if l.get("suburb") == "Rondebosch" else 1)
    CACHE.mkdir(parents=True, exist_ok=True)
    got = 0
    for l in todo[:budget]:
        f = CACHE / f"{l['id']}.html"
        if f.exists() and f.stat().st_size > 5000:
            html = f.read_text(errors="replace")
        else:
            url = urls.get(l["id"])
            if not url and l.get("suburb") in subs:      # listings newer than the last build
                slug, area = subs[l["suburb"]]
                url = f"https://www.property24.com/for-sale/{slug}/cape-town/western-cape/{area}/{l['id']}"
            try:
                assert url, f"no listing URL for {l['id']}"
                req = Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
                with urlopen(req, timeout=40) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        import gzip
                        raw = gzip.decompress(raw)
                html = raw.decode("utf-8", "replace")
                f.write_text(html)
                time.sleep(random.uniform(2.0, 4.0))
            except Exception as e:
                print("  !", l["id"], type(e).__name__, e)
                if "503" in str(e):
                    # P24 throttles by IP: the crawl and this script share one address, so
                    # stop the run instead of digging the hole deeper. Cached pages keep the work.
                    print("  503 - backing off, stopping this run (resume later, cache is warm)")
                    break
                time.sleep(8)
                continue
        ids = gallery(html)
        if len(ids) >= 2:
            l["images"] = [f"https://images.prop24.com/{i}/Ensure1280x720" for i in ids]
            l["thumbs"] = [f"https://images.prop24.com/{i}/Crop525x350" for i in ids]
            got += 1
    (HERE / "listings.json").write_text(json.dumps(data, indent=1))
    have = sum(1 for l in listings if l.get("images"))
    print(f"{got} galleries fetched | {have}/{len(listings)} listings have galleries")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
