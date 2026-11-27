# Are You Jas? — Cape Town

What a property last sold for, versus what it's asking now. One static page, one small server, no framework.

```
scrape.py   Property24 listings  -> listings.json   (cached, self-pacing)
sold.py     values pages + OCR   -> sold.json       (the hard part)
build.py    join + rules         -> data.json, dist/index.html
app.py      serves dist/ + /api/reacts (sqlite)
ocr.py      decodes P24's image-rendered sold prices
```

## Refresh

```bash
python scrape.py     # asking prices      (~1.5 min per suburb, 3s/request)
python sold.py       # last sold prices   (slow: 2 pages per address)
python build.py      # -> dist/index.html, data.json
```

`python sold.py --check` and `node tests/render_check.mjs` are the two checks; both must pass before a deploy.

## Why there is an OCR file

Property24 renders last-sold price and year as base64 PNGs, never as text. The render is deterministic and the figures are tabular: cells are cut at a fixed advance, each glyph is cropped, normalised to 8×10 and hashed. `labels.json` holds hash → character.

6 characters were learnt from 9 Rouwkoop Road (`python ocr.py learn page.html "R 4 750 000" "2025"`). Any unlabelled glyph stops the decode (a `?` is never guessed into a price) and is dumped into `glyphs_unknown.json` as ASCII — label it once, it never comes back. Expect a labelling pass on the first crawl of a new price range (digits 1,3,6,8,9 are not yet in `labels.json`).

## Hosting

Railway. `railway.json` + `Procfile` are ready:

- **Web**: `python app.py` — serves `dist/index.html` and the reaction API.
- **Cron** (daily, 03:00): `python scrape.py && python sold.py && python build.py`
- **Volume** at `/data`, `DB_PATH=/data/reacts.db`, `sold.json`/`cache/` on the same volume so runs resume where they stopped.

Run the crawler from the server, not your laptop: Property24 soft-blocks an IP after ~90 page fetches (503 "Server unavailable") and the block outlives an hour. A different egress is the whole fix.

## Rules of the road

- Asking prices: public listings, always link back to the Property24 page.
- Sold prices: Deeds Office data via Property24 + published audit lists (Real Estate Insider). Clearly attributed, no implied accuracy guarantee.
- Reactions only — no free-text comments, no accounts, no IPs stored. That keeps POPIA and defamation out of it.
