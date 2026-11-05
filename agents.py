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


CP_DIR = paths.DATA / "crypto_paper"


def btc_tick():
    """BTC NY trend pullback (btc_sniper.py), paper: checked every minute 13:25-21:15 London; the day's state to
    <data>/crypto_paper/btc_state.json, the trade (once it triggers) to record.json and Supabase crypto_paper."""
    import btc_sniper as BS
    import cryptocom as CC
    from datetime import datetime as _dt
    lt = _dt.now(BS.LDN)
    m = lt.hour * 60 + lt.minute
    if not (13 * 60 + 25 <= m <= 21 * 60 + 15):
        return
    m5, h1 = CC.candles("BTC-USD", "5m", 300), CC.candles("BTC-USD", "1h", 300)
    if m5 is None or h1 is None or m5.empty or h1.empty:
        return
    r = BS.evaluate(m5, h1)
    r["checked"] = lt.strftime("%Y-%m-%d %H:%M")
    CP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CP_DIR / "btc_state.json.tmp"
    tmp.write_text(json.dumps(r, default=str))
    os.replace(tmp, CP_DIR / "btc_state.json")
    if not r.get("signal"):
        return
    f = CP_DIR / "record.json"
    try:
        rec = json.loads(f.read_text())
    except Exception:
        rec = []
    row = {"day": r["day"], "setup": BS.NAME, "symbol": "BTCUSDT", **r["signal"], "result": r["result"],
           "exit_at": r.get("exit_at"), "exit_px": r.get("exit_px"), "r": r["r"], "pct": r["pct"]}
    old = next((x for x in rec if x["day"] == row["day"] and x["setup"] == row["setup"]), None)
    if old == row:
        return
    rec = [x for x in rec if not (x["day"] == row["day"] and x["setup"] == row["setup"])] + [row]
    f.write_text(json.dumps(rec, default=str))
    try:
        _cloud().upsert_rows("crypto_paper", [row], "day,setup")
    except Exception as e:
        log(f"crypto_paper: {e}")
    if old is None:
        log(f"BTC paper trade: {'LONG' if row['side'] > 0 else 'SHORT'} {row['entry']} stop {row['sl']} target {row['tp']}")


def _cc_5m(inst: str, end_ms: int | None = None) -> pd.DataFrame:
    import cryptocom as CC
    params = {"instrument_name": inst, "timeframe": "5m", "count": 300}
    if end_ms:
        params["end_ts"] = end_ms
    return CC._parse(CC._get("get-candlestick", params).get("data") or [])


def crash_tick():
    """Crash-candle buys (crash_buy.py), paper, every minute: keeps ~25 days of 5-min candles per market in
    <data>/crypto_paper/hist_<KEY>.parquet, writes crash_state.json and new / updated trades to record.json and
    Supabase crypto_paper (setup = '<name> HH:MM' New York time of the signal)."""
    import crash_buy as CB
    CP_DIR.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp.utcnow().tz_localize(None)
    try:
        state = json.loads((CP_DIR / "crash_state.json").read_text())
    except Exception:
        state = {}
    for key, cfg in CB.SETUPS.items():
        f = CP_DIR / f"hist_{key}.parquet"
        try:
            hist = pd.read_parquet(f)
        except Exception:
            hist = pd.DataFrame()
        if len(hist) < CB.WINDOW // 2:          # first run: page back ~21 days
            parts, end = [], int(now.timestamp() * 1000)
            for _ in range(22):
                d = _cc_5m(cfg["inst"], end)
                if d.empty:
                    break
                parts.append(d)
                end = int(d.index[0].timestamp() * 1000) - 1
                time.sleep(0.3)
            hist = pd.concat(parts) if parts else hist
        new = _cc_5m(cfg["inst"])
        hist = pd.concat([hist, new]) if not new.empty else hist
        if hist.empty:
            continue
        hist = hist[~hist.index.duplicated(keep="last")].sort_index()
        hist = hist[hist.index >= now - pd.Timedelta(days=26)]
        hist.to_parquet(f)
        done = hist[hist.index + pd.Timedelta(minutes=5) <= now]      # finished candles only
        x = CB.signals(done, cfg)
        st = state.setdefault(key, {})
        st.setdefault("since", str(now.floor("5min")))                   # paper trades count from the first run
        last = x.iloc[-1]
        st.update(name=cfg["name"], price=float(last["Close"]), ret=float(last["ret"]) if last["ret"] == last["ret"] else None,
                  sigma=float(last["sd"]) if last["sd"] == last["sd"] else None, z=cfg["z"],
                  trigger_pct=(-cfg["z"] * float(last["sd"])) if last["sd"] == last["sd"] else None,
                  as_of=str(x.index[-1] + pd.Timedelta(minutes=5)), checked=str(now))
        tr = CB.trades(x, cfg, since=pd.Timestamp(st["since"]))
        st["pending"] = next((t for t in tr if t.get("status") == "entry next candle"), None)
        rows = []
        for t in tr:
            if t.get("status") == "entry next candle":
                continue
            ny = t["signal_at"].tz_localize("UTC").tz_convert("America/New_York")
            ist = t["entry_at"].tz_localize("UTC").tz_convert("Asia/Kolkata")
            rows.append({"day": ny.strftime("%Y-%m-%d"), "setup": f"{cfg['name']} {ny:%H:%M}", "symbol": cfg["inst"], "side": 1,
                         "signal_at": ny.strftime("%H:%M"), "entry_at": f"{ny + pd.Timedelta(minutes=5):%H:%M}",
                         "entry_at_ist": ist.strftime("%d %b %H:%M"), "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
                         "stop_pct": cfg["sl"], "result": t["status"],
                         "exit_at": (t["exit_at"].tz_localize("UTC").tz_convert("Asia/Kolkata").strftime("%H:%M IST") if t["exit_at"] is not None else None),
                         "exit_px": t["exit_px"], "r": t["r"], "pct": t["pct"]})
        if rows:
            fr = CP_DIR / "record.json"
            try:
                rec = json.loads(fr.read_text())
            except Exception:
                rec = []
            have = {(x_["day"], x_["setup"]): x_ for x_ in rec}
            changed = [r_ for r_ in rows if have.get((r_["day"], r_["setup"])) != r_]
            if changed:
                for r_ in changed:
                    if (r_["day"], r_["setup"]) not in have:
                        log(f"crash buy paper trade: {r_['setup']} entry {r_['entry']} stop {r_['sl']} target {r_['tp']}")
                    have[(r_["day"], r_["setup"])] = r_
                fr.write_text(json.dumps(list(have.values()), default=str))
                try:
                    _cloud().upsert_rows("crypto_paper", changed, "day,setup")
                except Exception as e:
                    log(f"crypto_paper: {e}")
    tmp = CP_DIR / "crash_state.json.tmp"
    tmp.write_text(json.dumps(state, default=str))
    os.replace(tmp, CP_DIR / "crash_state.json")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    last = 0.0
    while True:
        if time.time() - last >= EVERY:
            last = time.time()
            try:
                st = cycle()
                save(st)
                log(f"{len(st['rows'])} markets, calls {st['calls']} in {st['seconds']}s")
            except Exception as e:
                log(f"error: {e}")
        try:
            btc_tick()
        except Exception as e:
            log(f"btc sniper: {e}")
        try:
            crash_tick()
        except Exception as e:
            log(f"crash buy: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
