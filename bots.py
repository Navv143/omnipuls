"""Omnipuls bots: five bots that watch the market all day on the server (started and kept alive by recorder.py).

Every 5 minutes in market hours they fetch today's 5-minute candles for every F&O stock, the indices, the index
futures (for OI) and India VIX, and each bot writes its flags:

1. Index bot      - Nifty, Bank Nifty, Fin Nifty, Midcap Select, Sensex: move in ATR, the constituents' money flow,
                    MACD state, futures OI build-up; and today's signal of a passed index rule (Setup Finder).
2. Sector bot     - money flow by sector (₹ crore, buying share), where money rotates from and to, sector vs market.
3. Sector movers  - each sector's top gainers and losers and whether their money flow and volume back the move.
4. F&O unusual    - every F&O stock: unusual volume, range, money flow, open = high / low; and today's first
                    signals of the passed stock rule (Setup Finder).
5. Master bot     - collects the others' flags and checks each idea against the balance: market money, Nifty, the
                    stock's sector, India VIX and the tested rules. It passes an idea only when they agree, and logs
                    every idea (Supabase bot_ideas) with its result at the close, so the bots can be scored later.

After 16:30 (once a day, or when the app asks) it runs the Setup Finder research (bot.py) in its own process.
State for the app: <data>/bots/state.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

import bot as B
import paths

IST = B.IST
OUT = paths.DATA / "bots"
REQUEST = paths.state("bot_request")
EVERY = int(os.environ.get("BOTS_EVERY", 300))
RESEARCH_AFTER = os.environ.get("BOTS_RESEARCH_AFTER", "16:30")
LIVE_DAYS = 45            # history kept for the live readings (20-day usual volume, 14-day ATR)
STATUS: dict = {"started": None, "errors": []}


def log(msg: str):
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} bots: {msg}", flush=True)


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"

# ---------------------------------------------------------------- data


class Market:
    """History (from the Setup Finder cache, or 45 days) plus today's candles, refreshed every cycle."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.syms = B.universe(cfg)
        self.hist: dict = {}
        self.today: dict = {}
        self.fut: dict = {}
        self.weights: dict = {}

    def load(self):
        stocks, indices = B.load_history(self.cfg, days=LIVE_DAYS if not B.CACHE.exists() else B.HISTORY_DAYS,
                                         symbols=self.syms + [("INDIAVIX", "IDX_I", 21, "INDEX")])
        cut = pd.Timestamp.now() - pd.Timedelta(days=LIVE_DAYS)
        self.hist = {k: v[v.index >= cut] for k, v in {**stocks, **indices}.items()}
        try:
            import indices as IX
            self.weights = {k: d.get("w", {}) for k, d in IX.load().items()}
        except Exception:
            self.weights = {}
        log(f"history: {len(self.hist)} symbols")

    def refresh(self):
        import dhan as D
        for sym, seg, sid, ins in self.syms + [("INDIAVIX", "IDX_I", 21, "INDEX")]:
            try:
                d = B.clean(D.intraday(seg, sid, ins, 5, 1, self.cfg))
            except D.DhanError as e:
                if e.code == "NETWORK":
                    raise
                continue
            if not d.empty:
                self.today[sym] = d[d.index.normalize() == d.index.normalize().max()]
        try:
            futs = D.nearest_futures("NSE_FNO", "FUTIDX", list(B.INDEX_IDS), self.cfg)
            for k, f in futs.items():
                d = B.clean(D.intraday("NSE_FNO", f["id"], "FUTIDX", 5, 2, self.cfg))
                if not d.empty:
                    self.fut[k] = d
        except Exception as e:
            log(f"index futures: {e}")

    def bars(self, sym: str) -> pd.DataFrame:
        h, t = self.hist.get(sym, pd.DataFrame()), self.today.get(sym, pd.DataFrame())
        if t.empty:
            return h
        h = h[h.index.normalize() < t.index.normalize().min()] if not h.empty else h
        return pd.concat([h, t])

    def stock_bars(self) -> dict:
        return {s: self.bars(s) for s, seg, _, _ in self.syms if seg != "IDX_I"}

# ---------------------------------------------------------------- the five bots


def _tone_word(t: int) -> str:
    return "bullish" if t > 0 else "bearish" if t < 0 else "neutral"


def latest_rows(T: dict) -> pd.DataFrame:
    """The latest candle of each stock from a today-only table."""
    if not T:
        return pd.DataFrame()
    cols = ["sym", "m", "move", "move_atr", "range_x", "vol_x", "flow_share", "flow_x", "net_cr", "chg", "o_eq_l",
            "o_eq_h", "price", "atr", "sec_flow", "mkt_flow"]
    df = pd.DataFrame({c: T[c] for c in cols})
    df = df.groupby("sym").tail(1).copy()
    df["stock"] = T["names"][df["sym"].to_numpy()]
    df["sector"] = T["sector_of"][df["sym"].to_numpy()]
    return df


def index_bot(mkt: Market, research: dict | None) -> dict:
    flags = []
    for k, name in B.INDEX_NAMES.items():
        bars = mkt.bars(k)
        w = mkt.weights.get(k) or {}
        flow = B.constituent_flow({s: mkt.bars(s) for s in w}, w) if w else pd.DataFrame()
        t = B.candle_table(k, bars, flow, keep_all_days=False) if not bars.empty else {}
        if not t.get("n"):
            continue
        i = -1
        mv, fs = float(t["move_atr"][i]), float(t["flow_share"][i])
        c = B.clean(bars)["Close"]
        m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
        sd = np.sign(m - m.ewm(span=9, adjust=False).mean())
        today = sd[sd.index.normalize() == sd.index.normalize().max()]
        cross = today[(today != today.shift()) & (today != 0)].index
        macd = f"MACD {'up' if sd.iloc[-1] > 0 else 'down'}" + (f" since {cross[-1]:%H:%M}" if len(cross) else "")
        oi_txt, oi_dir = "", 0
        f = mkt.fut.get(k)
        if f is not None and "OI" in f and f["OI"].notna().any():
            fd = f.index.normalize()
            prev = f[fd < fd.max()]
            tod = f[fd == fd.max()]
            if not prev.empty and not tod.empty and prev["OI"].iloc[-1] > 0:
                d_oi = tod["OI"].iloc[-1] / prev["OI"].iloc[-1] - 1
                up = tod["Close"].iloc[-1] >= prev["Close"].iloc[-1]
                label = ("long build-up" if d_oi > 0 else "short covering") if up else \
                        ("short build-up" if d_oi > 0 else "long unwinding")
                oi_dir = (1 if up else -1) if d_oi > 0 else (1 if up else -1) * 0.5
                oi_txt = f"futures {label} (OI {d_oi * 100:+.1f}%)"
        votes = [np.sign(mv) if abs(mv) >= 0.3 else 0, 1 if fs >= 0.55 else -1 if fs <= 0.45 else 0,
                 float(sd.iloc[-1]), np.sign(oi_dir)]
        tone = int(np.sign(sum(votes))) if abs(sum(votes)) >= 2 else 0
        sig = ""
        best = ((research or {}).get("indices", {}).get(k) or {}).get("best")
        if best:
            T1 = {kk: v for kk, v in t.items() if kk != "n"}
            T1["sym"] = np.zeros(t["n"], dtype=np.int32)
            T1["vol_x"] = np.ones(t["n"], dtype=np.float32)
            T1["sec_flow"] = T1["mkt_flow"] = T1["flow_share"]
            side = np.sign(T1["move"]).astype(np.int8)
            sel = B.first_signals(T1, B.rule_mask(T1, best["rule"], side), 99)
            if len(sel):
                j = sel[0]
                sig = f"TESTED SIGNAL {'BUY' if side[j] > 0 else 'SELL'} at {int(T1['m'][j]) // 60:02d}:{int(T1['m'][j]) % 60:02d}"
        flags.append({"name": name, "key": k, "tone": tone, "signal": sig, "value": f"{float(t['price'][i]):,.2f}",
                      "text": f"{mv:+.2f} ATR from open · money {fs * 100:.0f}% buying · {macd}"
                              + (f" · {oi_txt}" if oi_txt else "")})
    return {"name": "Index bot", "flags": flags}


def sector_bot(L: pd.DataFrame) -> dict:
    if L.empty:
        return {"name": "Sector bot", "flags": []}
    g = L.groupby("sector").agg(net_cr=("net_cr", "sum"), buying=("flow_share", "mean"), move=("chg", "mean"),
                                n=("stock", "count")).sort_values("net_cr", ascending=False)
    mkt_move = float(L["chg"].mean())
    flags = []
    for sec, r in g.iterrows():
        if r["n"] < 2:
            continue
        tone = 1 if r["buying"] >= 0.53 and r["net_cr"] > 0 else -1 if r["buying"] <= 0.47 and r["net_cr"] < 0 else 0
        flags.append({"name": sec, "tone": tone, "value": f"₹{r['net_cr']:+,.0f} Cr",
                      "text": f"{r['buying'] * 100:.0f}% buying · avg move {r['move'] * 100:+.2f}% "
                              f"({(r['move'] - mkt_move) * 100:+.2f}% vs market) · {int(r['n'])} stocks"})
    top_in = [f["name"] for f in flags if f["tone"] > 0][:3]
    top_out = [f["name"] for f in flags if f["tone"] < 0][-3:]
    note = (f"Money moving from {', '.join(top_out) or '—'} into {', '.join(top_in) or '—'}.")
    return {"name": "Sector bot", "flags": flags, "note": note}


def movers_bot(L: pd.DataFrame) -> dict:
    flags = []
    if L.empty:
        return {"name": "Sector movers", "flags": flags}
    for sec, g in L.groupby("sector"):
        g = g.sort_values("chg")
        for _, r in pd.concat([g.tail(2), g.head(2)]).drop_duplicates("stock").iterrows():
            side = 1 if r["chg"] > 0 else -1
            backed = (r["flow_share"] >= 0.55 if side > 0 else r["flow_share"] <= 0.45) and r["vol_x"] >= 1.5
            flags.append({"name": r["stock"], "sector": sec, "side": side, "tone": side if backed else 0,
                          "backed": bool(backed), "value": f"{r['chg'] * 100:+.2f}%",
                          "text": f"{sec} · money {r['flow_share'] * 100:.0f}% buying · volume {r['vol_x']:.1f}x usual"
                                  + (" · opened at the low" if r["o_eq_l"] else " · opened at the high" if r["o_eq_h"] else "")
                                  + (" · BACKED by money" if backed else "")})
    flags.sort(key=lambda f: (not f["backed"], -abs(float(f["value"].rstrip("%")))))
    return {"name": "Sector movers", "flags": flags}


def unusual_bot(L: pd.DataFrame, T: dict, research: dict | None) -> dict:
    flags = []
    for _, r in L.iterrows():
        why = []
        if r["vol_x"] >= 2.5:
            why.append(f"volume {r['vol_x']:.1f}x usual")
        if r["range_x"] >= 1.5:
            why.append(f"range {r['range_x']:.1f}x the usual day")
        if abs(r["flow_x"]) >= 0.15:
            why.append(f"net money {r['flow_x'] * 100:+.0f}% of a usual day's turnover")
        if (r["o_eq_l"] and r["move"] > 0) or (r["o_eq_h"] and r["move"] < 0):
            why.append("opened at the " + ("low" if r["o_eq_l"] else "high"))
        if len(why) >= 2 or (why and abs(r["move_atr"]) >= 0.8):
            side = 1 if r["move"] > 0 else -1
            agree = (r["flow_share"] >= 0.55) if side > 0 else (r["flow_share"] <= 0.45)
            flags.append({"name": r["stock"], "sector": r["sector"], "side": side, "tone": side if agree else 0,
                          "value": f"{r['chg'] * 100:+.2f}%", "text": " · ".join(why)})
    flags.sort(key=lambda f: -len(f["text"]))
    signals = []
    best = (research or {}).get("best")
    if best and T:
        signals = B.live_signals(best["rule"], T)
    return {"name": "F&O unusual", "flags": flags[:40], "signals": signals}


def master_bot(L: pd.DataFrame, idx: dict, sec: dict, mov: dict, unu: dict, vix_chg: float | None) -> dict:
    """An idea passes only when the tested rule fired AND at least 3 of 4 balance checks agree; 3+ checks without
    the tested rule = watch."""
    nifty = next((f for f in idx["flags"] if f.get("key") == "NIFTY"), None)
    sec_tone = {f["name"]: f["tone"] for f in sec["flags"]}
    mkt = float(L["flow_share"].mean()) if not L.empty else 0.5
    cands = {}
    for s in unu.get("signals", []):
        cands[(s["stock"], 1 if s["side"] == "BUY" else -1)] = {"source": "Tested rule (Setup Finder)", "rule": True,
                                                                  "time": s["time"], "price": s["price"], "stop": s["stop"]}
    for f in mov["flags"]:
        if f.get("backed"):
            cands.setdefault((f["name"], f["side"]), {"source": "Sector mover backed by money", "rule": False})
    for f in unu["flags"]:
        if f["tone"] != 0:
            cands.setdefault((f["name"], f["side"]), {"source": "Unusual activity", "rule": False})
    rows = L.set_index("stock") if not L.empty else pd.DataFrame()
    ideas = []
    for (stock, side), c in cands.items():
        if stock not in rows.index:
            continue
        r = rows.loc[stock]
        checks = {"market money": bool((mkt >= 0.51) if side > 0 else (mkt <= 0.49)),
                  "Nifty not against": bool(nifty is None or nifty["tone"] != -side),
                  "sector money": bool(sec_tone.get(r["sector"], 0) == side),
                  "VIX calm": bool(vix_chg is None or vix_chg < 5)}
        ok = sum(checks.values())
        status = "passed" if c["rule"] and ok >= 3 else "watch" if ok >= 3 else None
        if not status:
            continue
        ideas.append({"stock": stock, "side": "BUY" if side > 0 else "SELL", "status": status, "source": c["source"],
                      "price": c.get("price", round(float(r["price"]), 2)), "stop": c.get("stop"),
                      "time": c.get("time", f"{int(r['m']) // 60:02d}:{int(r['m']) % 60:02d}"),
                      "sector": r["sector"], "checks": checks, "agree": f"{ok}/4",
                      "why": f"{c['source']}; " + ", ".join(k for k, v in checks.items() if v)})
    ideas.sort(key=lambda x: (x["status"] != "passed", -int(x["agree"][0])))
    return {"name": "Master bot", "ideas": ideas[:25],
            "note": f"Market money {mkt * 100:.0f}% buying" + (f" · India VIX {vix_chg:+.1f}%" if vix_chg is not None else "")}

# ---------------------------------------------------------------- idea log (Supabase) and scoring at the close


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


def log_ideas(day: str, ideas: list, seen: dict):
    """Logs an idea the first time it shows and again whenever its status changes (watch -> passed). seen keeps the
    first sighting (time and price, for scoring) with the latest status."""
    new = []
    for i in ideas:
        k = (i["stock"], i["side"])
        if k not in seen:
            seen[k] = dict(i)
            new.append(seen[k])
        elif seen[k]["status"] != i["status"]:
            seen[k].update(status=i["status"], checks=i["checks"], why=i["why"])
            new.append(seen[k])
    if not new:
        return
    rows = [{"day": day, "stock": i["stock"], "side": i["side"], "status": i["status"], "first_at": i["time"],
             "price": float(i["price"]), "checks": i["checks"], "reasons": i["why"]} for i in new]
    _cloud().upsert_rows("bot_ideas", rows, "day,stock,side")


def score_ideas(day: str, mkt: Market, seen: dict) -> list:
    """At the close: each idea's result from its first price to 15:20 (no stop), for scoring the bots."""
    out = []
    for (stock, side), i in seen.items():
        b = mkt.today.get(stock)
        if b is None or b.empty:
            continue
        ex = b[b.index.strftime("%H:%M") <= "15:15"]["Close"]
        if ex.empty:
            continue
        s = 1 if side == "BUY" else -1
        res = s * (float(ex.iloc[-1]) / float(i["price"]) - 1) * 100
        out.append({"day": day, "stock": stock, "side": side, "status": i["status"], "first_at": i["time"],
                    "price": float(i["price"]), "checks": i["checks"], "reasons": i["why"],
                    "result_pct": round(res - 0.12, 3)})
    if out:
        _cloud().upsert_rows("bot_ideas", out, "day,stock,side")
    return out

# ---------------------------------------------------------------- loop


def cycle(mkt: Market) -> dict:
    import universe as U
    research = B.latest()
    T = B.build_table(mkt.stock_bars(), U.FNO_SECTOR_OF, keep_all_days=False)
    L = latest_rows(T)
    vix = mkt.bars("INDIAVIX")
    vix_chg = None
    if not vix.empty:
        dd = vix.index.normalize()
        if (dd < dd.max()).any():
            vix_chg = float(vix["Close"].iloc[-1] / vix[dd < dd.max()]["Close"].iloc[-1] - 1) * 100
    idx, sec = index_bot(mkt, research), sector_bot(L)
    mov, unu = movers_bot(L), unusual_bot(L, T, research)
    master = master_bot(L, idx, sec, mov, unu, vix_chg)
    return {"updated": datetime.now(IST).isoformat(timespec="seconds"), "bots": {"index": idx, "sector": sec,
            "movers": mov, "unusual": unu, "master": master}}


def save(state: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    os.replace(tmp, OUT / "state.json")


def research_due(now: datetime) -> bool:
    if market_open(now):
        return False
    if REQUEST.exists():
        return True
    last = (B.latest() or {}).get("run_at", "")[:10]
    return now.strftime("%H:%M") >= RESEARCH_AFTER and last != now.strftime("%Y-%m-%d")


def run_research():
    REQUEST.unlink(missing_ok=True)
    log("Setup Finder research: starting")
    r = subprocess.run([sys.executable, str(paths.HERE / "bot.py")], cwd=str(paths.HERE), timeout=4 * 3600)
    log(f"Setup Finder research: finished (exit {r.returncode})")
    if r.returncode != 0 and not (B.BOT_DIR / "latest.json").exists():
        B.BOT_DIR.mkdir(parents=True, exist_ok=True)
        (B.BOT_DIR / "latest.json").write_text(json.dumps({"run_at": datetime.now(IST).isoformat(timespec="seconds"),
                                                           "error": "research run failed"}))


def main():
    import dhan as D
    STATUS["started"] = datetime.now(IST).isoformat(timespec="seconds")
    cfg = D.load_config()
    while not D.configured(cfg):
        log("waiting for Dhan (no client_id / access_token)")
        time.sleep(60)
        cfg = D.load_config()
    mkt = Market(cfg)
    mkt.load()
    day, seen, scored, last = None, {}, False, 0.0
    while True:
        now = datetime.now(IST)
        try:
            if now.strftime("%Y-%m-%d") != day:
                day, seen, scored = now.strftime("%Y-%m-%d"), {}, False
                mkt.today = {}
                if mkt.hist:
                    mkt.load()   # yesterday joins the history
            if market_open(now) and time.time() - last >= EVERY:
                last = time.time()
                mkt.cfg = D.load_config()   # the token the app or recorder renewed
                mkt.refresh()
                state = cycle(mkt)
                save(state)
                log_ideas(day, state["bots"]["master"]["ideas"], seen)
            if not market_open(now) and now.weekday() < 5 and now.strftime("%H:%M") >= "15:35" and not scored:
                scored = True
                if seen:
                    log(f"scored {len(score_ideas(day, mkt, seen))} ideas")
            if research_due(now):
                run_research()
        except Exception as e:
            STATUS["errors"] = (STATUS["errors"] + [f"{now:%d %b %H:%M} {e}"[:200]])[-10:]
            log(f"error: {e}")
            time.sleep(30)
        time.sleep(15)


if __name__ == "__main__":
    main()
