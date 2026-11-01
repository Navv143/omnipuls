"""Index constituents and weights for the index money-flow view.

Order of preference (cached for the day in index_cache.json):
 1. NSE live: constituents + free-float market cap from NSE's index API (weights = ffmc share), for the NSE indices.
 2. NSE constituent CSVs (names only): weights taken from the built-in table where known, the rest share the remainder.
 3. Built-in table below.
Sensex (BSE) always uses the built-in table.

Built-in weights: published index weights as of 29 Oct 2026 (Nifty 50, Nifty Bank, Nifty Financial Services, Sensex).
Nifty Midcap Select: top 10 from NSE's 30 Oct 2026 factsheet; the other 15 names/weights are approximate (Sept 2026)
and are replaced by the live NSE list whenever NSE is reachable. Index reviews happen in March and September.
"""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

import requests

CACHE = Path(__file__).with_name("index_cache.json")
AS_OF = "29 Oct 2026"

# key -> (display name, Dhan IDX_I security id, NSE API name, NSE constituent CSV names)
INDEXES = {
    "NIFTY": ("Nifty 50", 13, "NIFTY 50", ["ind_nifty50list.csv"]),
    "BANKNIFTY": ("Bank Nifty", 25, "NIFTY BANK", ["ind_niftybanklist.csv"]),
    "FINNIFTY": ("Fin Nifty", 27, "NIFTY FINANCIAL SERVICES", ["ind_niftyfinancelist.csv"]),
    "MIDCPNIFTY": ("Midcap Select", 442, "NIFTY MIDCAP SELECT", ["ind_niftymidcapselect_list.csv",
                                                                  "ind_niftymidcapselectlist.csv"]),
    "SENSEX": ("Sensex", 51, None, []),
}

BUILTIN = {
    "NIFTY": {
        "HDFCBANK": 10.54, "ICICIBANK": 8.81, "RELIANCE": 7.52, "BHARTIARTL": 5.12, "LT": 4.17, "SBIN": 3.79,
        "INFY": 3.41, "AXISBANK": 3.32, "KOTAKBANK": 2.84, "BAJFINANCE": 2.53, "M&M": 2.51, "ITC": 2.43,
        "ETERNAL": 2.26, "TCS": 1.97, "SUNPHARMA": 1.88, "TITAN": 1.84, "HINDUNILVR": 1.57, "TATASTEEL": 1.48,
        "MARUTI": 1.47, "NTPC": 1.46, "ADANIPORTS": 1.36, "BEL": 1.32, "HINDALCO": 1.32, "SHRIRAMFIN": 1.29,
        "BSE": 1.24, "HCLTECH": 1.22, "ULTRACEMCO": 1.22, "JSWSTEEL": 1.17, "POWERGRID": 1.13, "BAJAJ-AUTO": 1.12,
        "GRASIM": 1.11, "INDIGO": 1.05, "ASIANPAINT": 1.04, "COALINDIA": 0.97, "BAJAJFINSV": 0.96, "ADANIENT": 0.96,
        "EICHERMOT": 0.94, "NESTLEIND": 0.92, "TECHM": 0.91, "ONGC": 0.85, "APOLLOHOSP": 0.85, "TRENT": 0.83,
        "SBILIFE": 0.74, "CIPLA": 0.74, "DRREDDY": 0.73, "MAXHEALTH": 0.70, "JIOFIN": 0.68, "TATACONSUM": 0.60,
        "TMPV": 0.56, "HDFCLIFE": 0.54},
    "BANKNIFTY": {
        "HDFCBANK": 31.49, "ICICIBANK": 26.33, "SBIN": 11.33, "AXISBANK": 9.91, "KOTAKBANK": 8.50,
        "FEDERALBNK": 2.25, "AUBANK": 1.66, "INDUSINDBK": 1.64, "IDFCFIRSTB": 1.50, "BANKBARODA": 1.20,
        "CANBK": 1.14, "PNB": 1.09, "YESBANK": 1.03, "UNIONBANK": 0.91},
    "FINNIFTY": {
        "HDFCBANK": 26.31, "ICICIBANK": 22.00, "SBIN": 9.47, "AXISBANK": 8.28, "KOTAKBANK": 7.10,
        "BAJFINANCE": 6.31, "SHRIRAMFIN": 3.23, "BSE": 3.11, "BAJAJFINSV": 2.41, "SBILIFE": 1.85, "JIOFIN": 1.70,
        "CHOLAFIN": 1.68, "HDFCLIFE": 1.34, "PFC": 1.12, "MFSL": 0.88, "ICICIGI": 0.88, "RECLTD": 0.87,
        "MUTHOOTFIN": 0.70, "SBICARD": 0.41, "LICHSGFIN": 0.39},
    "MIDCPNIFTY": {   # top 10 official (30 Oct 2026); rest approximate
        "FEDERALBNK": 6.65, "MCX": 6.45, "INDHOTEL": 5.65, "PAYTM": 5.58, "HEROMOTOCO": 5.32, "PERSISTENT": 5.21,
        "BHEL": 4.47, "INDUSINDBK": 4.37, "AUBANK": 3.98, "GVT&D": 3.95,
        "POLICYBZR": 3.9, "DIXON": 3.7, "SUZLON": 3.5, "BHARATFORG": 3.4, "LUPIN": 3.3, "NAUKRI": 3.2,
        "ASHOKLEY": 3.0, "INDUSTOWER": 3.0, "FORTIS": 3.0, "POLYCAB": 2.9, "AUROPHARMA": 2.8, "MARICO": 2.7,
        "SWIGGY": 2.4, "SRF": 2.3, "HINDPETRO": 2.2},
    "SENSEX": {
        "HDFCBANK": 12.86, "ICICIBANK": 10.75, "RELIANCE": 9.17, "BHARTIARTL": 6.25, "LT": 5.09, "SBIN": 4.63,
        "INFY": 4.16, "AXISBANK": 4.04, "KOTAKBANK": 3.47, "BAJFINANCE": 3.08, "M&M": 3.06, "ITC": 2.97,
        "ETERNAL": 2.76, "TCS": 2.41, "SUNPHARMA": 2.29, "TITAN": 2.24, "HINDUNILVR": 1.92, "TATASTEEL": 1.81,
        "MARUTI": 1.79, "NTPC": 1.78, "ADANIPORTS": 1.66, "BEL": 1.61, "HCLTECH": 1.49, "ULTRACEMCO": 1.49,
        "POWERGRID": 1.37, "INDIGO": 1.28, "ASIANPAINT": 1.27, "BAJAJFINSV": 1.18, "TECHM": 1.11, "TRENT": 1.02},
}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0 Safari/537.36", "Accept": "*/*", "Referer": "https://www.nseindia.com/"}


def _norm(w: dict) -> dict:
    tot = sum(v for v in w.values() if v and v > 0)
    return {k: v / tot * 100 for k, v in w.items()} if tot > 0 else w


def _nse_api(sess: requests.Session, name: str) -> dict:
    r = sess.get("https://www.nseindia.com/api/equity-stockIndices", params={"index": name}, headers=UA, timeout=10)
    data = r.json().get("data", [])
    out = {}
    for d in data:
        sym = str(d.get("symbol", "")).upper()
        if not sym or sym == name.upper() or d.get("priority") == 1:
            continue
        ff = d.get("ffmc")
        try:
            ff = float(ff)
        except (TypeError, ValueError):
            ff = None
        out[sym] = ff
    return out


def _nse_csv(sess: requests.Session, files: list) -> list:
    for f in files:
        for base in ("https://nsearchives.nseindia.com/content/indices/", "https://archives.nseindia.com/content/indices/",
                     "https://niftyindices.com/IndexConstituent/"):
            try:
                r = sess.get(base + f, headers=UA, timeout=5)
                if r.status_code != 200 or "Symbol" not in r.text[:500]:
                    continue
                rows = list(csv.DictReader(io.StringIO(r.text)))
                syms = [str(x.get("Symbol", "")).strip().upper() for x in rows if x.get("Symbol")]
                if len(syms) >= 10:
                    return syms
            except Exception:
                return []   # unreachable: don't try the other mirrors
    return []


def _fetch_live(budget: float = 20.0) -> dict:
    """Best effort, at most ~`budget` seconds in total (NSE often blocks cloud servers)."""
    out = {}
    t0 = time.time()
    sess = requests.Session()
    try:
        sess.get("https://www.nseindia.com/", headers=UA, timeout=6)
        api_ok = True
    except Exception:
        api_ok = False
    for key, (_, _, api, files) in INDEXES.items():
        if api is None or time.time() - t0 > budget:
            continue
        w, src = {}, ""
        if api_ok:
            try:
                raw = _nse_api(sess, api)
                if len(raw) >= 10 and all(v for v in raw.values()):
                    w, src = _norm(raw), "NSE live (free-float market cap)"
            except Exception:
                api_ok = False
        if not w and time.time() - t0 < budget:
            syms = _nse_csv(sess, files)
            if syms:
                known = {s: BUILTIN[key][s] for s in syms if s in BUILTIN[key]}
                rest = [s for s in syms if s not in known]
                left = max(100 - sum(known.values()), 0.5 * len(rest))
                w = _norm({**known, **{s: left / len(rest) for s in rest}} if rest else known)
                src = "NSE constituent list" + (f" ({len(rest)} weights estimated)" if rest else "")
        if w:
            out[key] = {"w": w, "src": src}
    return out


def load(max_age_h: float = 12) -> dict:
    """{key: {"name", "id", "w": {symbol: weight %}, "src"}} for the five indices."""
    try:
        cached = json.loads(CACHE.read_text())
    except Exception:
        cached = None
    live = None
    if cached and time.time() - cached.get("ts", 0) < max_age_h * 3600:
        live = cached.get("data", {})
    else:
        try:
            live = _fetch_live()
        except Exception:
            live = {}
        if live:
            try:
                CACHE.write_text(json.dumps({"ts": time.time(), "data": live}))
            except Exception:
                pass
        elif cached:
            live = cached.get("data", {})
    out = {}
    for key, (name, sid, _, _) in INDEXES.items():
        got = (live or {}).get(key)
        if got and got.get("w"):
            out[key] = {"name": name, "id": sid, "w": got["w"], "src": got["src"]}
        else:
            out[key] = {"name": name, "id": sid, "w": _norm(BUILTIN[key]),
                        "src": f"built-in weights ({AS_OF}" + (", partly approximate)" if key == "MIDCPNIFTY" else ")")}
    return out


def all_members() -> list:
    return sorted({s for d in BUILTIN.values() for s in d})
