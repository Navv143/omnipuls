"""AI Desk - Intraday: the same six agents as desk_agents.py, tuned for intraday trades in crypto (BTC, ETH, SOL), gold
(XAU), silver, copper, crude oil, natural gas and forex (EUR, GBP, JPY, AUD, INR vs the dollar). Pure functions.

Layer by layer (each agent has one job; NOVA concludes):
1. ATLAS  session & regime - which session is live (Asia / London / London-NY overlap / New York / quiet; weekend =
                             crypto only), the dollar index's 1-hour trend, Bitcoin's 1h / 4h trend, and a bias per class
                             (crypto follows Bitcoin; gold, metals and energy lean against the dollar; forex with / against it).
2. VEGA   charts           - 1-hour trend (EMA 20 / 50) + 15-minute setup: pullback to the 15-min EMA 20 in the 1h trend,
                             break of the last 4-hour range with volume, VWAP reclaim / rejection. Skips a move that has
                             already run > 1.2 daily ATR from the day's open (our studies: stretched moves stop paying).
3. ORION  news             - headlines scored bullish / bearish, high-impact catalysts flagged (Fed, CPI, jobs, OPEC, ETF...).
4. LUNA   crowd            - 15-min RSI extremes, the last 4 hours' move vs its normal size (z-score), crypto Fear & Greed;
                             a crowded move counts against.
5. TITAN  risk             - stop beyond the 15-min swing (1.0-2.5 x 15-min ATR), target 2R or the next level, R/R >= 1.5,
                             volatility <= 2x normal, correlation <= 0.75, max 4 trades and 1 per class, no new trade in a
                             quiet session or within 1 hour of the daily close (21:00 UTC) for non-crypto markets.
6. NOVA   final call       - TRADE only when the setup, regime, news and crowd agree (3 of 4, none against) and TITAN passes;
                             WAIT when they conflict; REJECT when risk fails or two agents are against.

Analysis rules, not back-tested setups: every TRADE call is paper-tracked on 15-min candles (target first = win, stop
first = loss, else closed after 8 hours / at the daily close) so the desk is judged on its own record.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import desk_agents as DA

IST = timezone(timedelta(hours=5, minutes=30))
UNIVERSE = {
    "Crypto": {"BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana"},
    "Gold & metals": {"GC=F": "Gold (XAU)", "SI=F": "Silver", "HG=F": "Copper"},
    "Energy": {"CL=F": "Crude oil", "NG=F": "Natural gas"},
    "Forex": {"EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "AUDUSD=X": "AUD/USD",
              "USDINR=X": "USD/INR"},
}
MACRO = {"DX-Y.NYB": "US dollar index"}
CLASS_OF = {s: c for c, d in UNIVERSE.items() for s in d}
NAME_OF = {**{s: n for d in UNIVERSE.values() for s, n in d.items()}, **MACRO}
AGENTS = {
    "ATLAS": ("Session & regime", "Live session, dollar and Bitcoin trend: a bias per class."),
    "VEGA": ("Charts", "1-hour trend + 15-minute setup: pullback, range break, VWAP."),
    "ORION": ("News", "Scores the latest headlines and flags high-impact catalysts."),
    "LUNA": ("Crowd", "RSI extremes, stretched 4-hour moves, crypto fear & greed."),
    "TITAN": ("Risk", "Stop, target, R/R, volatility, correlation, session and exposure. Can reject any trade."),
    "NOVA": ("Final call", "All five reports, one decision: TRADE, WAIT or REJECT."),
}
SESSIONS = [(0, 7, "Asia"), (7, 12, "London"), (12, 16, "London-NY overlap"), (16, 21, "New York"), (21, 24, "Quiet")]
GOOD = {"Crypto": {"London", "London-NY overlap", "New York", "Asia"},
        "Gold & metals": {"London", "London-NY overlap", "New York"},
        "Energy": {"London", "London-NY overlap", "New York"},
        "Forex": {"London", "London-NY overlap", "New York"}}


def _clean(df):
    d = DA._clean(df)
    return d


def session(now_utc: datetime) -> str:
    if now_utc.weekday() >= 5:
        return "Weekend"
    h = now_utc.hour
    return next(n for a, b, n in SESSIONS if a <= h < b)


def _trend(c: pd.Series) -> int:
    if len(c) < 60:
        return 0
    e20, e50 = DA.ema(c, 20), DA.ema(c, 50)
    if c.iloc[-1] > e20.iloc[-1] > e50.iloc[-1] and e20.iloc[-1] > e20.iloc[-4]:
        return 1
    if c.iloc[-1] < e20.iloc[-1] < e50.iloc[-1] and e20.iloc[-1] < e20.iloc[-4]:
        return -1
    return 0


def _h4(h: pd.DataFrame) -> pd.Series:
    return h["Close"].resample("4h").last().dropna()

# ---------------------------------------------------------------- 1. ATLAS


def atlas(m15: dict, h1: dict, now_utc: datetime) -> dict:
    ses = session(now_utc)
    dx = _clean(h1.get("DX-Y.NYB"))
    dxy = _trend(dx["Close"]) if len(dx) else 0
    b = _clean(h1.get("BTC-USD"))
    btc1, btc4 = (_trend(b["Close"]), _trend(_h4(b))) if len(b) else (0, 0)
    btc = int(np.sign(btc1 + btc4))
    notes = [f"session: {ses}",
             f"dollar index 1h {'up' if dxy > 0 else 'down' if dxy < 0 else 'flat'}",
             f"Bitcoin 1h {['down', 'flat', 'up'][btc1 + 1]}, 4h {['down', 'flat', 'up'][btc4 + 1]}"]
    bias = {"Crypto": btc, "Gold & metals": -dxy, "Energy": -dxy, "Forex": dxy}
    return {"session": ses, "dxy": dxy, "btc": btc, "bias": bias, "notes": notes,
            "regime": f"{ses} · USD {['weak', 'flat', 'strong'][dxy + 1]} · crypto {['down', 'flat', 'up'][btc + 1]}"}


def atlas_bias(sym: str, a: dict) -> int:
    cls = CLASS_OF.get(sym)
    b = a["bias"].get(cls, 0)
    if cls == "Forex":
        return b if sym.startswith("USD") else -b
    return b

# ---------------------------------------------------------------- 2. VEGA


def vega(sym: str, m15: pd.DataFrame, h1: pd.DataFrame, now_utc: datetime) -> dict | None:
    d, h = _clean(m15), _clean(h1)
    if len(d) < 80 or len(h) < 60:
        return None
    c = d["Close"]
    last = float(c.iloc[-1])
    e20 = DA.ema(c, 20)
    a15 = DA.atr(d)
    atr15 = float(a15.iloc[-1])
    atr_x = atr15 / float(a15.tail(480).mean()) if a15.tail(480).mean() > 0 else np.nan
    daily = h.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    datr = float(DA.atr(daily).iloc[-1]) if len(daily) > 15 else np.nan
    day = d[d.index.normalize() == d.index[-1].normalize()]
    day_open = float(day["Open"].iloc[0]) if len(day) else last
    move_datr = (last - day_open) / datr if datr and np.isfinite(datr) else 0.0
    vol = d["Volume"].fillna(0)
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    if len(day) and vol.loc[day.index].sum() > 0:
        vwap = float((tp.loc[day.index] * vol.loc[day.index]).sum() / vol.loc[day.index].sum())
    else:
        vwap = float(tp.loc[day.index].mean()) if len(day) else last
    vol_x = float(vol.iloc[-1] / vol.iloc[-21:-1].mean()) if vol.iloc[-21:-1].mean() > 0 else np.nan
    t1 = _trend(h["Close"])
    rng = d.iloc[-17:-1]
    rh, rl = float(rng["High"].max()), float(rng["Low"].min())
    r14 = float(DA.rsi(c).iloc[-1])
    setup, side = "", 0
    if last > rh and (not np.isfinite(vol_x) or vol_x >= 1.3):
        setup, side = "Break above the last 4-hour range", 1
    elif last < rl and (not np.isfinite(vol_x) or vol_x >= 1.3):
        setup, side = "Break below the last 4-hour range", -1
    elif t1 > 0 and float(d["Low"].iloc[-2:].min()) <= e20.iloc[-1] + 0.2 * atr15 and last > e20.iloc[-1] and last > vwap:
        setup, side = "Pullback to the 15-min EMA 20 in the 1h uptrend", 1
    elif t1 < 0 and float(d["High"].iloc[-2:].max()) >= e20.iloc[-1] - 0.2 * atr15 and last < e20.iloc[-1] and last < vwap:
        setup, side = "Pullback to the 15-min EMA 20 in the 1h downtrend", -1
    elif t1 > 0 and c.iloc[-2] < vwap < last:
        setup, side = "VWAP reclaimed in the 1h uptrend", 1
    elif t1 < 0 and c.iloc[-2] > vwap > last:
        setup, side = "VWAP lost in the 1h downtrend", -1
    stretched = bool(side and side * move_datr > 1.2)
    status = "SETUP" if side and side == t1 and not stretched else "WATCH" if side else "NONE"
    if stretched:
        setup += f" (already {side * move_datr:.1f} daily ATR from the open: stretched)"
    score = 40 * t1 + 25 * side + (15 * side if np.isfinite(vol_x) and vol_x >= 1.5 else 0) + (10 * side if (last > vwap) == (side > 0) else 0)
    swing_lo, swing_hi = float(d["Low"].iloc[-6:].min()), float(d["High"].iloc[-6:].max())
    return {"symbol": sym, "name": NAME_OF.get(sym, sym), "class": CLASS_OF.get(sym, ""), "price": last,
            "chg_1d": (last / day_open - 1) * 100, "chg_1h": DA._ret(c, 4), "chg_4h": DA._ret(c, 16),
            "trend": t1, "trend_txt": {1: "▲ up", -1: "▼ down", 0: "sideways"}[t1], "atr": atr15, "atr_pct": atr15 / last * 100,
            "atr_x": atr_x, "vol_x": vol_x, "rsi": r14, "vwap": vwap, "ema20": float(e20.iloc[-1]),
            "range_hi": rh, "range_lo": rl, "support": min(rl, swing_lo), "resistance": max(rh, swing_hi),
            "swing_lo": swing_lo, "swing_hi": swing_hi, "move_datr": move_datr, "setup": setup, "side": side,
            "status": status, "score": int(score), "as_of": str(d.index[-1]),
            "spark": [round(float(x), 6) for x in c.tail(64)]}

# ---------------------------------------------------------------- 4. LUNA


def luna(v: dict, m15: pd.DataFrame, fng: dict | None) -> dict:
    c = _clean(m15)["Close"]
    r16 = c.pct_change(16)
    sd = float(c.pct_change().tail(1000).std() * math.sqrt(16)) if len(c) > 200 else np.nan
    z = float(r16.iloc[-1] / sd) if sd and np.isfinite(sd) and sd > 0 else np.nan
    crowd = 1 if v["rsi"] >= 60 and (z if np.isfinite(z) else 0) > 0.5 else -1 if v["rsi"] <= 40 and (z if np.isfinite(z) else 0) < -0.5 else 0
    hype = (np.isfinite(z) and abs(z) >= 2.5) or v["rsi"] >= 78 or v["rsi"] <= 22
    notes = []
    if hype:
        notes.append("stretched 4-hour move / RSI extreme: late to the party")
    if fng and v["class"] == "Crypto":
        val = fng.get("value")
        notes.append(f"crypto fear & greed {val} ({fng.get('label')})")
        if val is not None and ((val >= 80 and v["side"] > 0) or (val <= 20 and v["side"] < 0)):
            hype = True
    vote = 0 if hype else crowd
    if hype and v["side"] and crowd == v["side"]:
        vote = -v["side"]
    label = "Hype" if hype else "Bullish crowd" if crowd > 0 else "Bearish crowd" if crowd < 0 else "Neutral"
    return {"label": label, "vote": vote, "z4h": round(z, 2) if np.isfinite(z) else None, "hype": bool(hype), "notes": notes}

# ---------------------------------------------------------------- 5. TITAN


def titan(v: dict, a: dict, capital: float, risk_pct: float, approved: list, returns: pd.DataFrame,
          now_utc: datetime, max_total: int = 4, max_class: int = 1) -> dict:
    side = v["side"] or v["trend"] or 1
    e, atr15 = v["price"], v["atr"]
    if side > 0:
        stop = float(np.clip(v["swing_lo"] - 0.25 * atr15, e - 2.5 * atr15, e - 1.0 * atr15))
        lvl = v["resistance"] if v["resistance"] > e else None
    else:
        stop = float(np.clip(v["swing_hi"] + 0.25 * atr15, e + 1.0 * atr15, e + 2.5 * atr15))
        lvl = v["support"] if v["support"] < e else None
    risk = abs(e - stop)
    target = e + side * 2 * risk
    if lvl is not None and abs(lvl - e) >= 1.5 * risk and abs(lvl - e) < 2 * risk:
        target = float(lvl)                    # the next level, if it still gives 1.5R+
    rr = abs(target - e) / risk if risk else 0
    max_loss = capital * risk_pct / 100
    qty = max_loss / risk if risk else 0
    corr = 0.0
    if approved and v["symbol"] in returns:
        cs = [abs(returns[v["symbol"]].corr(returns[x["symbol"]])) for x in approved if x["symbol"] in returns]
        corr = float(np.nanmax(cs)) if cs else 0.0
    same_cls = sum(1 for x in approved if x["class"] == v["class"])
    ses = a["session"]
    late = v["class"] != "Crypto" and now_utc.hour >= 20
    ses_ok = ses in GOOD.get(v["class"], set()) and not late
    checks = [
        ("Session", ses_ok, f"{ses}" + (" · within 1 hour of the daily close" if late else "")
         + ("" if ses_ok else f" · {v['class']} trades only in " + ", ".join(sorted(GOOD.get(v['class'], [])))),
         0.5 if ses_ok else 1.2),
        ("Maximum loss", (len(approved) + 1) * risk_pct <= 3, f"{max_loss:,.0f} at the stop ({risk / atr15:.1f}x 15-min ATR); "
         f"all stops {(len(approved) + 1) * risk_pct:.1f}% of capital (limit 3%)", (len(approved) + 1) * risk_pct / 3),
        ("Correlation", corr <= 0.75, f"max {corr:.2f} with the other approved trades", corr / 0.75 if corr else 0),
        ("Exposure", len(approved) < max_total and same_cls < max_class,
         f"{len(approved)} approved, {same_cls} in {v['class']} (max {max_total}, {max_class} per class)",
         max(len(approved) / max_total, same_cls / max_class)),
        ("Risk / reward", rr >= 1.5, f"{rr:.1f}R", 1.5 / max(rr, 0.01)),
        ("Volatility", not (np.isfinite(v["atr_x"]) and v["atr_x"] > 2.0),
         f"15-min ATR {v['atr_x']:.1f}x its 5-day average" if np.isfinite(v["atr_x"]) else "ATR n/a",
         (v["atr_x"] / 2.0) if np.isfinite(v["atr_x"]) else 0.5),
    ]
    return {"side": int(side), "entry": float(e), "stop": float(stop), "target": float(target), "rr": round(float(rr), 2),
            "qty": float(qty), "max_loss": float(max_loss),
            "checks": [{"name": n, "pass": bool(p), "text": t, "load": round(float(min(max(l, 0), 1.5)), 2)} for n, p, t, l in checks],
            "pass": all(p for _, p, _, _ in checks)}

# ---------------------------------------------------------------- the desk


def run_desk(m15: dict, h1: dict, news_fn=None, fng: dict | None = None, capital: float = 1_000_000,
             risk_pct: float = 0.5, now_utc: datetime | None = None) -> dict:
    now_utc = now_utc or datetime.now(timezone.utc)
    a = atlas(m15, h1, now_utc)
    vs = [x for x in (vega(s, m15.get(s), h1.get(s), now_utc) for s in CLASS_OF) if x]
    if a["session"] == "Weekend":                      # FX / metals / energy are closed: only crypto is live
        vs = [x for x in vs if x["class"] == "Crypto"]
    rets = pd.DataFrame({x["symbol"]: _clean(m15[x["symbol"]])["Close"].pct_change().tail(192).reset_index(drop=True)
                         for x in vs})
    rows, approved = [], []
    for v in sorted(vs, key=lambda x: -abs(x["score"])):
        atl = atlas_bias(v["symbol"], a)
        ori = DA.orion(v["symbol"], news_fn(v["symbol"]) if (news_fn and v["side"]) else []) if v["side"] else None
        lun = luna(v, m15[v["symbol"]], fng)
        tit = titan(v, a, capital, risk_pct, approved, rets, now_utc) if v["side"] else None
        nv = DA.nova(v, atl, ori, lun, tit)
        if nv["call"] == "TRADE":
            approved.append(v)
        rows.append({**v, "atlas": atl, "orion": ori, "luna": lun, "titan": tit, "nova": nv})
    calls = pd.Series([r["nova"]["call"] for r in rows]).value_counts().to_dict() if rows else {}
    return {"updated": datetime.now(IST).isoformat(timespec="seconds"), "atlas": a, "fng": fng, "rows": rows,
            "calls": calls, "capital": capital, "risk_pct": risk_pct, "kind": "intraday"}


def score_calls(calls: list[dict], m15: dict, hours: int = 8) -> list[dict]:
    """Paper-track TRADE calls on 15-min candles: stop first = loss, target first = win; otherwise closed at the
    price after `hours` hours, or at 21:00 UTC (the daily close) for non-crypto markets."""
    for c in calls:
        if c.get("result"):
            continue
        d = _clean(m15.get(c["symbol"]))
        t0 = pd.Timestamp(c["time"])
        t0 = t0.tz_convert("UTC").tz_localize(None) if t0.tzinfo else t0
        d = d[d.index >= t0.floor("15min") + pd.Timedelta(minutes=15)]
        if d.empty:
            continue
        s, end = c["side"], t0 + pd.Timedelta(hours=hours)
        if c.get("class") != "Crypto":
            close = t0.normalize() + pd.Timedelta(hours=21)
            end = min(end, close if close > t0 else close + pd.Timedelta(days=1))
        for ts, b in d.iterrows():
            if ts >= end:
                c["result"], c["exit"], c["exit_at"] = "time-out", float(b["Open"]), str(ts)
                break
            if (b["Low"] <= c["stop"]) if s > 0 else (b["High"] >= c["stop"]):
                c["result"], c["exit"], c["exit_at"] = "loss", c["stop"], str(ts)
                break
            if (b["High"] >= c["target"]) if s > 0 else (b["Low"] <= c["target"]):
                c["result"], c["exit"], c["exit_at"] = "win", c["target"], str(ts)
                break
        if c.get("result"):
            c["exit"] = float(c["exit"])
            c["r"] = round(float(s * (c["exit"] - c["entry"]) / abs(c["entry"] - c["stop"])), 2)
            c["pct"] = round(float(s * (c["exit"] / c["entry"] - 1) * 100), 3)
    return calls
