"""Decode the last-sold price/year Property24 renders as inline base64 PNGs.

Those two numbers are the only un-scrapeable part of a Property24 values page:
they ship as images, not text. The render is deterministic and the figures are
tabular, so:

  * split each line into words at wide gaps, then into equal character cells
    (advance = word width / char count),
  * crop each cell to its ink, normalise to an 8x10 bitmap,
  * hash it -> exact glyph identity.

One lesson is enough to label the alphabet (see learn()). Unknown glyphs are
dumped as ASCII so a human can label them once, in labels.json.

    python ocr.py learn page.html "R 4 750 000" "2025"   # bootstrap labels
    python ocr.py page.html                              # -> sold/year
"""
import base64
import hashlib
import io
import json
import re
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
LABELS = HERE / "labels.json"
ADVANCE = 9.6          # px per character in this font at this size
CELL = (8, 10)         # normalised glyph grid


def images(html):
    return re.findall(r'src="data:image/png;base64,([^"]+)"', html.replace("&#x2B;", "+"))


def line(html, idx):
    im = Image.open(io.BytesIO(base64.b64decode(images(html)[idx]))).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, im).convert("L")


def cells(img, thresh=200):
    """-> [normalised glyph bitmap] in reading order."""
    w, h = img.size
    px = img.load()
    ink = [any(px[x, y] < thresh for y in range(h)) for x in range(w)]

    words, x = [], 0
    while x < w:                                    # words = runs with gap < 4px
        if not ink[x]:
            x += 1
            continue
        s, gap = x, 0
        while x < w and gap < 4:
            gap = gap + 1 if not ink[x] else 0
            x += 1
        words.append((s, x - gap))

    out = []
    for s, e in words:
        n = max(1, round((e - s) / ADVANCE))
        step = (e - s) / n
        for i in range(n):
            cs, ce = int(round(s + i * step)), int(round(s + (i + 1) * step))
            ys = [y for y in range(h) if any(px[c, y] < thresh for c in range(cs, ce))]
            xs = [c for c in range(cs, ce) if any(px[c, y] < thresh for y in range(h))]
            if not xs or not ys:
                continue
            out.append(bitmap(img.crop((xs[0], ys[0], xs[-1] + 1, ys[-1] + 1))))
    return out


def bitmap(box):
    g = box.resize(CELL, Image.LANCZOS)
    px = g.load()
    return "".join("1" if px[x, y] < 140 else "0" for y in range(CELL[1]) for x in range(CELL[0]))


def h64(bits):
    return hashlib.sha1(bits.encode()).hexdigest()[:12]


def art(bits):
    w, h = CELL
    return "\n".join(bits[y * w:(y + 1) * w].replace("0", ".").replace("1", "#") for y in range(h))


def _labels():
    return json.loads(LABELS.read_text()) if LABELS.exists() else {}


def learn(html, price_truth, year_truth):
    """Map glyph hashes to characters using one page whose numbers are already known."""
    labels = _labels()
    for idx, truth in ((0, year_truth), (1, price_truth)):
        chars = [c for c in truth if not c.isspace()]
        glyphs = cells(line(html, idx))
        if len(chars) != len(glyphs):
            raise SystemExit(f"image {idx}: {len(glyphs)} glyphs vs {len(chars)} chars in {truth!r}")
        for ch, bits in zip(chars, glyphs):
            labels[h64(bits)] = ch
    LABELS.write_text(json.dumps(labels, indent=1, sort_keys=True))
    return labels


def read(html, labels=None):
    """-> {'sold', 'year', 'text', 'unknown'}"""
    labels = labels if labels is not None else _labels()
    unknown = []

    def decode(idx):
        out = ""
        for bits in cells(line(html, idx)):
            ch = labels.get(h64(bits))
            if ch is None:
                unknown.append(bits)
                out += "?"
            else:
                out += ch
        return out

    year, price = decode(0), decode(1)
    digits = re.sub(r"\D", "", price)                 # "R4750000" -> 4750000
    # a "?" means an unlabelled glyph: never guess money. Label it, then re-run.
    clean = not unknown
    return {"sold": int(digits) if clean and len(digits) >= 6 else None,
            "year": int(year) if clean and re.fullmatch(r"20\d\d", year) else None,
            "text": f"{price} / {year}", "unknown": unknown}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[0] == "learn":
        print(f"labelled {len(learn(Path(args[1]).read_text(errors='replace'), args[2], args[3]))} glyphs")
    else:
        r = read(Path(args[0]).read_text(errors="replace"))
        print(json.dumps({"sold": r["sold"], "year": r["year"], "text": r["text"],
                          "unknown": len(r["unknown"])}, indent=1))
        for bits in r["unknown"]:
            print(art(bits), "\n")
