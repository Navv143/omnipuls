"""NSE F&O stock list with lot sizes.

Downloads NSE's market-lot file once a day and keeps the last good copy in
fno_cache.json, so the app still works when NSE's site is unreachable.
Falls back to the built-in list in universe.py.
"""
import csv
import io
import json
import time
import urllib.request
from pathlib import Path

import universe as U

CACHE = Path(__file__).with_name("fno_cache.json")
URLS = [
    "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv",
    "https://archives.nseindia.com/content/fo/fo_mktlots.csv",
]
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "SYMBOL"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0 Safari/537.36",
    "Accept": "text/csv,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}


def parse_mktlots(text: str) -> dict:
    """Return {SYMBOL: lot_size} for stock underlyings."""
    out = {}
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in row]
        if len(cells) < 3:
            continue
        sym = cells[1].upper()
        if not sym or sym in INDEX_UNDERLYINGS or " " in sym:
            continue
        lot = next((int(float(c)) for c in cells[2:] if c.replace(".", "", 1).isdigit()), None)
        out[sym] = lot
    return out


def _download() -> dict:
    for url in URLS:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as r:
                data = parse_mktlots(r.read().decode("utf-8", "ignore"))
            if len(data) > 50:
                return data
        except Exception:
            continue
    return {}


def load() -> tuple[dict, str]:
    """Return ({SYMBOL: lot_size or None}, source description)."""
    try:
        cached = json.loads(CACHE.read_text())
    except Exception:
        cached = None
    if cached and time.time() - cached.get("ts", 0) < 12 * 3600:
        return cached["lots"], f"NSE contract file ({time.strftime('%d %b %Y', time.localtime(cached['ts']))})"
    fresh = _download()
    if fresh:
        try:
            CACHE.write_text(json.dumps({"ts": time.time(), "lots": fresh}))
        except Exception:
            pass
        return fresh, "NSE contract file (today)"
    if cached:
        return cached["lots"], f"NSE contract file ({time.strftime('%d %b %Y', time.localtime(cached['ts']))}, NSE unreachable now)"
    return {s: None for s in U.FNO_SECTOR_OF}, "built-in list (NSE unreachable; lot sizes unavailable)"
