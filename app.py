#!/usr/bin/env python3
"""AreYouJas server: serves the built page and counts reactions.

Stdlib only -- http.server + sqlite3. No accounts, no cookies, no IPs stored
(rate limiting hashes the IP with a per-process salt, in memory, and forgets it).

    PORT=8000 python app.py
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
DB = Path(os.environ.get("DB_PATH", HERE / "reacts.db"))
KINDS = ("jas", "yoh", "lol")
PORT = int(os.environ.get("PORT", 8000))
SALT = os.urandom(16)
_last = {}                      # hashed ip -> last write time
_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS reacts (
                      listing TEXT, kind TEXT, n INTEGER DEFAULT 0,
                      PRIMARY KEY (listing, kind))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS receipts (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      suburb TEXT, address TEXT, bought INTEGER, year INTEGER,
                      asking INTEGER, ts INTEGER)""")
    return conn


def receipts(limit=200):
    with db() as c:
        rows = c.execute("""SELECT id, suburb, address, bought, year, asking FROM receipts
                            ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    return [{"id": r[0], "suburb": r[1], "address": r[2], "bought": r[3],
             "year": r[4], "asking": r[5]} for r in rows]


def counts():
    with db() as c:
        rows = c.execute("SELECT listing, kind, n FROM reacts").fetchall()
    out = {}
    for listing, kind, n in rows:
        out.setdefault(listing, {})[kind] = n
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "areyoujas"

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if ctype == "application/json" else "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/reacts"):
            return self._send(200, counts())
        if self.path.startswith("/api/receipts"):
            return self._send(200, receipts())
        if self.path.startswith("/healthz"):
            data = HERE / "data.json"
            n = len(json.loads(data.read_text())["listings"]) if data.exists() else 0
            return self._send(200, {"ok": True, "listings": n, "reacted": len(counts())})
        page = HERE / "dist" / "index.html"
        if not page.exists():
            return self._send(503, {"error": "run build.py first"})
        return self._send(200, page.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path == "/api/receipt":
            return self.post_receipt()
        if self.path != "/api/react":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(min(n, 2000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "bad json"})
        listing, kind = str(body.get("id", "")), str(body.get("kind", ""))
        if not re.fullmatch(r"\d{6,12}", listing) or kind not in KINDS:
            return self._send(400, {"error": "bad id or kind"})

        # ponytail: one write per IP per 2s, in memory; move to a real limiter if this ever gets traffic
        ip = hashlib.sha256(SALT + self.client_address[0].encode()).hexdigest()
        with _lock:
            if time.time() - _last.get(ip, 0) < 2:
                return self._send(429, {"error": "slow down"})
            _last[ip] = time.time()

        with db() as c:
            c.execute("""INSERT INTO reacts (listing, kind, n) VALUES (?, ?, 1)
                         ON CONFLICT(listing, kind) DO UPDATE SET n = n + 1""", (listing, kind))
            c.commit()
            n = c.execute("SELECT n FROM reacts WHERE listing=? AND kind=?", (listing, kind)).fetchone()[0]
        return self._send(200, {"id": listing, "kind": kind, "n": n})

    def post_receipt(self):
        """A receipt from the owner: what they paid, when, and what it is asking now.
        The only source of sold prices that cannot be throttled, bought or sued."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(min(n, 2000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "bad json"})
        try:
            suburb = str(body["suburb"]).strip()[:60]
            address = str(body["address"]).strip()[:80]
            bought, year, asking = int(body["bought"]), int(body["year"]), int(body["asking"])
        except (KeyError, TypeError, ValueError):
            return self._send(400, {"error": "suburb, address, bought, year, asking required"})
        if not (3 <= len(suburb) and 3 <= len(address)):
            return self._send(400, {"error": "suburb and address too short"})
        if not (50_000 <= bought <= 500_000_000) or not (50_000 <= asking <= 500_000_000):
            return self._send(400, {"error": "prices out of range"})
        if not (1980 <= year <= time.gmtime().tm_year):
            return self._send(400, {"error": "year out of range"})

        ip = hashlib.sha256(SALT + self.client_address[0].encode()).hexdigest()
        with _lock:
            if time.time() - _last.get("r" + ip, 0) < 30:      # one receipt per IP per 30s
                return self._send(429, {"error": "slow down"})
            _last["r" + ip] = time.time()

        with db() as c:
            dup = c.execute("""SELECT 1 FROM receipts WHERE lower(address)=lower(?)
                               AND lower(suburb)=lower(?) AND year=?""",
                            (address, suburb, year)).fetchone()
            if dup:                                            # ponytail: exact dup only; fuzzy later
                return self._send(409, {"error": "already on the board"})
            c.execute("""INSERT INTO receipts (suburb, address, bought, year, asking, ts)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (suburb, address, bought, year, asking, int(time.time())))
            c.commit()
        return self._send(200, {"ok": True, "n": len(receipts())})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if not (HERE / "dist" / "index.html").exists():      # platform may skip the build step
        subprocess.run([sys.executable, "build.py"], cwd=HERE, check=False)
    print(f"areyoujas on :{PORT}  db={DB}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
