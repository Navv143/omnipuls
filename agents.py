"""AI Desk runner (started and kept alive by recorder.py): every 15 minutes, 24/7, it loads daily and hourly candles
for every market in desk_agents.UNIVERSE (Yahoo; crypto falls back to Crypto.com), the headlines for instruments with
a setup and the crypto Fear & Greed index, runs the six agents, and writes <data>/agents/state.json. Every TRADE call
is paper-tracked (calls.json, Supabase desk_calls)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import pandas as pd
import requests

import desk_agents as DA
import paths

OUT = paths.DATA / "agents"
EVERY = int(os.environ.get("AGENTS_EVERY", 900))
CAPITAL = float(os.environ.get("AGENTS_CAPITAL", 1_000_000))
RISK_PCT = float(os.environ.get("AGENTS_RISK_PCT", 1.0))
IST = DA.IST


def log(msg: str):
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} agents: {msg}", flush=True)


def _download(symbols: list, period: str, interval: str) -> dict:
    import yfinance as yf
    out = {}
    try:
        raw = yf.download(symbols, period=period, interval=interval, group_by="ticker", auto_adjust=False,
                          threads=True, progress=False)
    except Exception as e:
        log(f"yahoo {interval}: {e}")
        return out
    if raw is None or raw.empty:
        return out
    for s in symbols:
        try:
            df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(how="all")
            if not df.empty:
                out[s] = df
        except Exception:
            continue
    return out


def load_data() -> tuple[dict, dict]:
    syms = list(DA.CLASS_OF) + list(DA.MACRO)
    daily = _download(syms, "1y", "1d")
    hourly = _download(list(DA.CLASS_OF), "60d", "1h")
    try:  # crypto: Crypto.com when Yahoo has nothing
        import cryptocom as CC
        for s in DA.UNIVERSE["Crypto"]:
            if s not in daily:
                d = CC.candles(s, "1d", 300)
                if d is not None and not d.empty:
                    daily[s] = d
            if s not in hourly:
                h = CC.candles(s, "1h", 500)
                if h is not None and not h.empty:
                    hourly[s] = h
    except Exception as e:
        log(f"crypto.com: {e}")
    return daily, hourly


_news_cache: dict = {}


def news(symbol: str) -> list:
    hit = _news_cache.get(symbol)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    items = []
    try:
        import yfinance as yf
        for n in (yf.Ticker(symbol).news or [])[:8]:
            c = n.get("content", n)
            url = None
            for k in ("canonicalUrl", "clickThroughUrl"):
                if isinstance(c.get(k), dict) and c[k].get("url"):
                    url = c[k]["url"]
                    break
            pub = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
            if c.get("title"):
                items.append({"title": c["title"], "url": url or c.get("link"), "publisher": pub,
                              "when": str(c.get("pubDate") or c.get("providerPublishTime") or "")[:16]})
    except Exception:
        pass
    _news_cache[symbol] = (time.time(), items)
    return items


def fear_greed() -> dict | None:
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()["data"][0]
        return {"value": int(r["value"]), "label": r["value_classification"]}
    except Exception:
        return None


def _cloud():
    import cloudstore
    if not cloudstore.enabled():
        try:
            import streamlit as st
            sb = dict(st.secrets.get("supabase") or {})
            cloudstore.configure(sb.get("url"), sb.get("key"))
        except Exception:
            cloudstore.configure(None, None)
    return cloudstore


def _calls() -> list:
    try:
        return json.loads((OUT / "calls.json").read_text())
    except Exception:
        return []


def track(state: dict, hourly: dict):
    """New TRADE calls join the paper record (one open call per symbol); open calls are scored."""
    calls = _calls()
    open_syms = {c["symbol"] for c in calls if not c.get("result")}
    for r in state["rows"]:
        if r["nova"]["call"] == "TRADE" and r["symbol"] not in open_syms:
            t = r["titan"]
            calls.append({"time": state["updated"], "symbol": r["symbol"], "name": r["name"], "class": r["class"],
                          "side": t["side"], "entry": round(t["entry"], 6), "stop": round(t["stop"], 6),
                          "target": round(t["target"], 6), "rr": t["rr"], "setup": r["setup"]})
    DA.score_calls(calls, hourly)
    calls = calls[-500:]
    (OUT / "calls.json").write_text(json.dumps(calls, default=str))
    try:
        _cloud().upsert_rows("desk_calls", [{**c, "side": int(c["side"])} for c in calls[-50:]], "time,symbol")
    except Exception as e:
        log(f"Supabase: {e}")
    done = [c for c in calls if c.get("result")]
    state["record"] = {"calls": len(calls), "open": sum(1 for c in calls if not c.get("result")), "closed": len(done),
                       "wins": sum(1 for c in done if c["result"] == "win"),
                       "avg_r": round(float(sum(c.get("r", 0) for c in done) / len(done)), 2) if done else None}
    state["recent_calls"] = calls[-30:][::-1]


def cycle() -> dict:
    t0 = time.time()
    daily, hourly = load_data()
    if len(daily) < 10:
        raise RuntimeError(f"only {len(daily)} markets loaded (Yahoo down?)")
    state = DA.run_desk(daily, hourly, news, fear_greed(), CAPITAL, RISK_PCT)
    track(state, hourly)
    state["seconds"] = round(time.time() - t0)
    state["loaded"] = {"daily": len(daily), "hourly": len(hourly)}
    return state


def save(state: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "state.json.tmp"
    tmp.write_text(json.dumps(state, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    os.replace(tmp, OUT / "state.json")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            st = cycle()
            save(st)
            log(f"{len(st['rows'])} markets, calls {st['calls']} in {st['seconds']}s")
        except Exception as e:
            log(f"error: {e}")
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
