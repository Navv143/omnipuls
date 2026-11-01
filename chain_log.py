"""Our own option history: Nifty and Bank Nifty option chains every 5 minutes in market hours, so option selling
(and buying) can be tested on real prices later. Dhan's expired-options data does not work for this account, and
nothing else free gives Indian option prices, so the only way to get them is to record them.

Each snapshot: the 2 nearest expiries, the 12 strikes each side of the money, call and put LTP, bid, ask, OI,
volume, IV, delta and theta, with the spot. Rows build up in memory and are written every 30 minutes (and after the
close) to chain_log/<YYYY-MM>/<YYYY-MM-DD>.csv.gz on the private repo's `logs` branch (needs [github] token in
Secrets; Streamlit Cloud forgets local files on restart). Writing to `logs` never restarts the app.
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

import dhan as D

IST = timezone(timedelta(hours=5, minutes=30))
INDICES = {"NIFTY": 13, "BANKNIFTY": 25}
EVERY = 300          # seconds between snapshots
FLUSH = 1800         # seconds between writes to GitHub
STRIKES = 12
KEEP = ["LTP", "Bid", "Ask", "OI", "Volume", "IV", "Delta", "Theta"]
STATUS = {"snaps": 0, "rows": 0, "last": "", "error": "", "written": ""}


def _market_open(now: datetime) -> bool:
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"


def snapshot(cfg=None, expiries: dict | None = None) -> list[dict]:
    now = datetime.now(IST)
    rows = []
    for name, sid in INDICES.items():
        exps = (expiries or {}).get(name) or D.expiries(sid, "IDX_I", cfg)
        live = [e for e in exps if str(e) >= now.strftime("%Y-%m-%d")][:2]
        for exp in live:
            spot, ch = D.option_chain(sid, "IDX_I", exp, cfg)
            if ch.empty:
                continue
            ch = ch.assign(dist=(ch["Strike"] - spot).abs()).nsmallest(2 * STRIKES + 1, "dist").sort_values("Strike")
            for _, r in ch.iterrows():
                row = {"time": now.strftime("%Y-%m-%d %H:%M"), "index": name, "expiry": exp, "spot": spot,
                       "strike": r["Strike"]}
                for side in ("CE", "PE"):
                    for k in KEEP:
                        row[f"{side}_{k}"] = r.get(f"{side} {k}")
                rows.append(row)
            time.sleep(3.1)  # Dhan: one option-chain call every 3 seconds
    return rows


def _write(day: str, rows: list[dict], gh: dict):
    """Append rows to the day's gzipped CSV on the logs branch (read, merge, write)."""
    repo, branch = gh.get("repo", "Navv143/omnipuls"), gh.get("branch", "logs")
    path = f"chain_log/{day[:7]}/{day}.csv.gz"
    h = {"Authorization": f"Bearer {gh['token']}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    r = requests.get(url, params={"ref": branch}, headers=h, timeout=30)
    old, sha = pd.DataFrame(), None
    if r.status_code == 200:
        body = r.json()
        sha = body["sha"]
        raw = base64.b64decode(body["content"]) if body.get("content") else \
            requests.get(body["download_url"], headers=h, timeout=60).content
        old = pd.read_csv(io.BytesIO(gzip.decompress(raw)))
    elif r.status_code != 404:
        raise RuntimeError(f"GitHub read {r.status_code}: {r.text[:120]}")
    df = pd.concat([old, pd.DataFrame(rows)], ignore_index=True).drop_duplicates(["time", "index", "expiry", "strike"])
    buf = gzip.compress(df.to_csv(index=False).encode("utf-8"))
    payload = {"message": f"chain log {day} ({len(df)} rows)", "branch": branch,
               "content": base64.b64encode(buf).decode()}
    if sha:
        payload["sha"] = sha
    w = requests.put(url, headers=h, data=json.dumps(payload), timeout=60)
    if w.status_code not in (200, 201):
        raise RuntimeError(f"GitHub write {w.status_code}: {w.text[:120]}")
    STATUS["written"] = f"{day} {datetime.now(IST):%H:%M} ({len(df)} rows)"


def run(box: dict, cfg_fn, gh_fn):
    """Loop until box['stop']: snapshot every 5 minutes in market hours, flush every 30 minutes and after the close."""
    buffer, last_flush, exp_day, expiries = [], time.time(), None, {}
    while not box.get("stop"):
        now = datetime.now(IST)
        try:
            if _market_open(now):
                day = now.strftime("%Y-%m-%d")
                if exp_day != day:
                    expiries = {n: D.expiries(s, "IDX_I", cfg_fn()) for n, s in INDICES.items()}
                    exp_day = day
                rows = snapshot(cfg_fn(), expiries)
                buffer += rows
                STATUS.update(snaps=STATUS["snaps"] + 1, rows=STATUS["rows"] + len(rows), last=now.strftime("%H:%M"))
            gh = gh_fn()
            closing = buffer and not _market_open(now)
            if buffer and gh.get("token") and (time.time() - last_flush >= FLUSH or closing):
                day = buffer[0]["time"][:10]
                _write(day, [r for r in buffer if r["time"].startswith(day)], gh)
                buffer = [r for r in buffer if not r["time"].startswith(day)]
                last_flush = time.time()
            elif closing and not gh.get("token"):
                buffer = []  # nowhere to keep it
            STATUS["error"] = ""
        except Exception as e:
            STATUS["error"] = f"{now:%H:%M} {e}"[:200]
        wait = EVERY - (time.time() % EVERY) if _market_open(now) else 300
        while wait > 0 and not box.get("stop"):
            time.sleep(min(5, wait))
            wait -= 5


def start(box: dict, cfg_fn, gh_fn) -> threading.Thread:
    t = threading.Thread(target=run, args=(box, cfg_fn, gh_fn), daemon=True, name="chain-log")
    t.start()
    return t
