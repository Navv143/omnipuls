"""AI Desk: six agents that read the Indian market first (indices, stocks), then crypto, forex, commodities and the rupee, and
make one call per instrument: TRADE, WAIT or REJECT. Pure functions, no Streamlit.

ATLAS  market     - the Indian market's regime: Nifty and Bank Nifty trend, India VIX, the rupee; a bias for each class
                    (crypto follows Bitcoin's trend; the dollar index is context for commodities and currencies).
VEGA   charts     - trend (EMA 20/50/200 daily + hourly), volume vs its average, ATR vs its average, support and
                    resistance from swing points, RSI; finds the setup: breakout, pullback in trend, bounce at support /
                    rejection at resistance.
ORION  news       - the latest headlines for each instrument with a setup, scored bullish / bearish, high-impact
                    catalysts flagged (rates, earnings, regulation, war, ETF...).
LUNA   crowd      - is the move crowded or hype? RSI extremes, the 5-day move against its normal size (z-score), the
                    class breadth, and the crypto Fear & Greed index. Popular is not the same as correct.
TITAN  risk       - position size for the risk per trade, stop beyond support / resistance, reward-to-risk, volatility,
                    correlation with the other approved trades, exposure per class. Can reject any trade.
NOVA   final call - TRADE only when the setup, market, news and crowd agree and TITAN passes; WAIT when they
                    conflict; REJECT when risk fails or two agents are against.

These are analysis rules, not backtested setups: every TRADE call is paper-tracked (target / stop / 3-day time-out)
so the desk can be judged on its own record.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))

UNIVERSE = {  # Indian market first, then crypto, forex, commodities and the rupee (no US / foreign stocks or indices)
    "Indian indices": {"^NSEI": "Nifty 50", "^NSEBANK": "Bank Nifty", "NIFTY_FIN_SERVICE.NS": "Fin Nifty",
                       "NIFTY_MID_SELECT.NS": "Midcap Select", "^BSESN": "Sensex", "^CNXIT": "Nifty IT"},
    "Indian stocks": {"RELIANCE.NS": "Reliance", "HDFCBANK.NS": "HDFC Bank", "ICICIBANK.NS": "ICICI Bank",
                      "SBIN.NS": "SBI", "AXISBANK.NS": "Axis Bank", "KOTAKBANK.NS": "Kotak Bank", "INFY.NS": "Infosys",
                      "TCS.NS": "TCS", "BHARTIARTL.NS": "Bharti Airtel", "LT.NS": "L&T", "ITC.NS": "ITC",
                      "BAJFINANCE.NS": "Bajaj Finance", "MARUTI.NS": "Maruti", "SUNPHARMA.NS": "Sun Pharma",
                      "TITAN.NS": "Titan", "ADANIENT.NS": "Adani Enterprises"},
    "Crypto": {"BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana", "XRP-USD": "XRP",
               "BNB-USD": "BNB", "DOGE-USD": "Dogecoin"},
    "Forex": {"EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "AUDUSD=X": "AUD/USD"},
    "Commodities": {"GC=F": "Gold", "SI=F": "Silver", "CL=F": "Crude oil", "NG=F": "Natural gas", "HG=F": "Copper"},
    "Currency (INR)": {"USDINR=X": "USD/INR", "EURINR=X": "EUR/INR", "GBPINR=X": "GBP/INR", "JPYINR=X": "JPY/INR"},
}
MACRO = {"^INDIAVIX": "India VIX", "DX-Y.NYB": "US dollar index"}  # context only: not traded
CLASS_OF = {s: c for c, d in UNIVERSE.items() for s in d}
NAME_OF = {**{s: n for d in UNIVERSE.values() for s, n in d.items()}, **MACRO}
AGENTS = {
    "ATLAS": ("Market", "Reads the global regime and gives each asset class a bias."),
    "VEGA": ("Charts", "Trend, volume, ATR, support and resistance: finds the setup."),
    "ORION": ("News", "Scores the latest headlines and flags high-impact catalysts."),
    "LUNA": ("Crowd", "Bullish, bearish or just hype: crowding and fear & greed."),
    "TITAN": ("Risk", "Position size, max loss, reward/risk, volatility, correlation. Can reject any trade."),
    "NOVA": ("Final call", "All five reports, one decision: TRADE, WAIT or REJECT."),
}

# ---------------------------------------------------------------- indicators


def _clean(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d.columns = [str(c).title() for c in d.columns]
    if "Close" not in d:
        return pd.DataFrame()
    if "Volume" not in d:
        d["Volume"] = 0.0
    idx = pd.DatetimeIndex(d.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    d.index = idx
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d.dropna(subset=["Close"])


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(d: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = d["Close"].shift(1)
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    ch = s.diff()
    up, dn = ch.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-ch.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _ret(s: pd.Series, n: int) -> float:
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100 if len(s) > n else np.nan


def _pivots(d: pd.DataFrame, w: int = 3, look: int = 90) -> tuple[list, list]:
    x = d.tail(look)
    hi, lo = x["High"].to_numpy(), x["Low"].to_numpy()
    highs = [hi[i] for i in range(w, len(x) - w) if hi[i] == hi[i - w:i + w + 1].max()]
    lows = [lo[i] for i in range(w, len(x) - w) if lo[i] == lo[i - w:i + w + 1].min()]
    return highs, lows

# ---------------------------------------------------------------- ATLAS: market regime


def atlas(daily: dict) -> dict:
    """The Indian market's regime (Nifty, Bank Nifty, India VIX, the rupee) and a bias (+1 / 0 / -1) per class; the
    dollar index is used only as context for gold, commodities and currencies."""
    def trend(sym, n=50):
        d = _clean(daily.get(sym))
        if len(d) < n + 5:
            return 0, np.nan
        c = d["Close"]
        return (1 if c.iloc[-1] > ema(c, n).iloc[-1] else -1), _ret(c, 5)

    nif, nif5 = trend("^NSEI")
    bnk, bnk5 = trend("^NSEBANK")
    inr, inr5 = trend("USDINR=X")
    dxy, dxy5 = trend("DX-Y.NYB")
    btc, btc5 = trend("BTC-USD")
    ivx = _clean(daily.get("^INDIAVIX"))
    iv_lvl = float(ivx["Close"].iloc[-1]) if not ivx.empty else np.nan
    iv5 = _ret(ivx["Close"], 5) if len(ivx) > 6 else np.nan
    risk, notes = float(nif + 0.5 * bnk), []
    notes.append(f"Nifty {'above' if nif > 0 else 'below'} its 50-day average" + (f" ({nif5:+.1f}% 5d)" if np.isfinite(nif5) else ""))
    notes.append(f"Bank Nifty {'above' if bnk > 0 else 'below'}" + (f" ({bnk5:+.1f}% 5d)" if np.isfinite(bnk5) else ""))
    if np.isfinite(iv_lvl):
        risk += 1 if iv_lvl < 13 else -1 if iv_lvl > 18 else 0
        if np.isfinite(iv5) and iv5 > 15:
            risk -= 1
        notes.append(f"India VIX {iv_lvl:.1f}" + (f" ({iv5:+.0f}% 5d)" if np.isfinite(iv5) else ""))
    if inr:
        risk -= 0.5 * inr  # a weakening rupee usually means foreign money leaving
        notes.append(f"rupee {'weakening' if inr > 0 else 'strengthening'}" + (f" (USD/INR {inr5:+.1f}% 5d)" if np.isfinite(inr5) else ""))
    regime = "Risk-on" if risk >= 1.5 else "Risk-off" if risk <= -1.5 else "Mixed"
    r = 1 if regime == "Risk-on" else -1 if regime == "Risk-off" else 0
    bias = {
        "Indian indices": r, "Indian stocks": r,
        "Crypto": btc,                                   # crypto follows its own trend (Bitcoin vs its 50-day average)
        "Forex": dxy,                                    # +1 = dollar up: long USD/xxx, short xxx/USD
        "Commodities": int(np.sign(-dxy)),               # a weaker dollar lifts gold, silver, crude
        "Currency (INR)": int(np.sign(inr + 0.5 * dxy)),  # +1 = rupee weakening: long USD/INR
    }
    india = {"nifty_trend": nif, "nifty_5d": nif5, "india_vix": iv_lvl, "bank_trend": bnk}
    return {"regime": regime, "score": round(risk, 1), "bias": bias, "dxy": dxy, "notes": [n for n in notes if n],
            "india": india, "inr_5d": inr5, "btc_trend": btc}


def atlas_bias(sym: str, a: dict) -> int:
    cls = CLASS_OF.get(sym)
    b = a["bias"].get(cls, 0)
    if cls == "Forex":
        return b if sym.startswith("USD") else -b
    if cls == "Currency (INR)":
        return b if sym.endswith("INR=X") else -b
    if cls == "Commodities" and sym in ("CL=F", "NG=F"):  # energy: dollar plus the general mood
        return int(np.sign(b + a["bias"].get("Indian indices", 0) * 0.5))
    return b

# ---------------------------------------------------------------- VEGA: charts


def vega(sym: str, daily: pd.DataFrame, hourly: pd.DataFrame | None = None) -> dict | None:
    d = _clean(daily)
    if len(d) < 120:
        return None
    c = d["Close"]
    last = float(c.iloc[-1])
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    a = atr(d)
    a14 = float(a.iloc[-1])
    atr_x = a14 / float(a.tail(100).mean()) if a.tail(100).mean() > 0 else np.nan
    vol = d["Volume"]
    vol_x = float(vol.tail(3).mean() / vol.tail(23).head(20).mean()) if vol.tail(23).head(20).mean() > 0 else np.nan
    r14 = float(rsi(c).iloc[-1])
    up = last > e50.iloc[-1] > e200.iloc[-1] and e20.iloc[-1] > e20.iloc[-6]
    dn = last < e50.iloc[-1] < e200.iloc[-1] and e20.iloc[-1] < e20.iloc[-6]
    trend = 1 if up else -1 if dn else 0
    h = _clean(hourly)
    h_tr = 0
    if len(h) > 60:
        hc = h["Close"]
        h_tr = 1 if hc.iloc[-1] > ema(hc, 50).iloc[-1] and hc.iloc[-1] > ema(hc, 20).iloc[-1] else \
            -1 if hc.iloc[-1] < ema(hc, 50).iloc[-1] and hc.iloc[-1] < ema(hc, 20).iloc[-1] else 0
    highs, lows = _pivots(d)
    res = min([x for x in highs if x > last * 1.002], default=float(d["High"].tail(60).max()))
    sup = max([x for x in lows if x < last * 0.998], default=float(d["Low"].tail(60).min()))
    hi20, lo20 = float(d["High"].iloc[-21:-1].max()), float(d["Low"].iloc[-21:-1].min())
    vol_ok = (not np.isfinite(vol_x)) or vol_x >= 1.2
    setup, side = "", 0
    if last > hi20 and vol_ok and trend >= 0:
        setup, side = "Breakout above the 20-day high", 1
    elif last < lo20 and vol_ok and trend <= 0:
        setup, side = "Breakdown below the 20-day low", -1
    elif trend > 0 and abs(last - e20.iloc[-1]) <= a14 and h_tr >= 0:
        setup, side = "Pullback to the 20-day average in an uptrend", 1
    elif trend < 0 and abs(last - e20.iloc[-1]) <= a14 and h_tr <= 0:
        setup, side = "Bounce into the 20-day average in a downtrend", -1
    elif trend >= 0 and (last - sup) <= 0.6 * a14:
        setup, side = "At support", 1
    elif trend <= 0 and (res - last) <= 0.6 * a14:
        setup, side = "At resistance", -1
    score = 40 * trend + 20 * h_tr + 25 * side + (15 * side if np.isfinite(vol_x) and vol_x >= 1.3 else 0)
    status = "SETUP" if side and side == trend else "WATCH" if side else "NONE"
    return {"symbol": sym, "name": NAME_OF.get(sym, sym), "class": CLASS_OF.get(sym, ""), "price": last,
            "chg_1d": _ret(c, 1), "chg_5d": _ret(c, 5), "chg_20d": _ret(c, 20), "trend": trend, "hourly": h_tr,
            "atr": a14, "atr_pct": a14 / last * 100, "atr_x": atr_x, "vol_x": vol_x, "rsi": r14,
            "support": sup, "resistance": res, "setup": setup, "side": side, "status": status, "score": int(score),
            "spark": [round(float(x), 6) for x in c.tail(60)]}

# ---------------------------------------------------------------- ORION: news

BULL = r"beat|beats|surge|soar|rall(y|ies)|record high|upgrade|approv|wins|strong demand|buyback|rate cut|cuts rates|" \
       r"inflows?|bullish|jumps?|gains?|rebound|outperform|raises guidance|stimulus|etf approval|deal"
BEAR = r"miss|misses|plunge|slump|tumble|downgrade|ban|probe|lawsuit|fraud|outflows?|bearish|falls?|drops?|slides?|" \
       r"cuts guidance|rate hike|hikes rates|sanction|war|default|recession|selloff|sell-off|warns?|weak demand|tariff"
IMPACT = r"fed|rbi|ecb|rate|inflation|cpi|jobs|payroll|earnings|results|guidance|sec|regulat|ban|etf|war|opec|" \
         r"tariff|sanction|budget|gdp|default|merger|acquisition"


def orion(sym: str, items: list[dict]) -> dict:
    """Headlines scored: +1 bullish words, -1 bearish words; high impact if a catalyst word appears."""
    scored = []
    for n in items[:8]:
        t = (n.get("title") or "").lower()
        if not t:
            continue
        s = len(re.findall(BULL, t)) - len(re.findall(BEAR, t))
        scored.append({"title": n.get("title"), "url": n.get("url"), "when": n.get("when"), "publisher": n.get("publisher"),
                       "score": int(np.sign(s)), "impact": bool(re.search(IMPACT, t))})
    tot = sum(x["score"] for x in scored)
    hi = [x for x in scored if x["impact"] and x["score"]]
    return {"score": int(np.sign(tot)) if abs(tot) >= 1 else 0, "net": tot, "n": len(scored),
            "high_impact": hi[:2], "headlines": scored[:5]}

# ---------------------------------------------------------------- LUNA: crowd


def luna(v: dict, daily: pd.DataFrame, breadth: float | None, fng: dict | None) -> dict:
    d = _clean(daily)
    c = d["Close"]
    r5 = c.pct_change(5)
    sd = float(c.pct_change().tail(250).std() * math.sqrt(5)) if len(c) > 60 else np.nan
    z = float(r5.iloc[-1] / sd) if sd and np.isfinite(sd) and sd > 0 else np.nan
    crowd = 1 if v["rsi"] >= 60 and (z if np.isfinite(z) else 0) > 0.5 else -1 if v["rsi"] <= 40 and (z if np.isfinite(z) else 0) < -0.5 else 0
    hype = (np.isfinite(z) and abs(z) >= 2.2) or v["rsi"] >= 76 or v["rsi"] <= 24
    notes = []
    if hype:
        notes.append("crowded / stretched move: popular is not the same as correct")
    if fng and v["class"] == "Crypto":
        val = fng.get("value")
        notes.append(f"crypto fear & greed {val} ({fng.get('label')})")
        if val is not None and val >= 75:
            hype = hype or v["side"] > 0
        elif val is not None and val <= 25 and v["side"] < 0:
            hype = True
    if breadth is not None:
        notes.append(f"{breadth:.0f}% of {v['class'].lower()} above their 50-day average")
    vote = 0 if hype else crowd
    if hype and v["side"] and crowd == v["side"]:
        vote = -v["side"]  # contrarian: the crowd is already all-in on this side
    label = "Hype" if hype else "Bullish crowd" if crowd > 0 else "Bearish crowd" if crowd < 0 else "Neutral"
    return {"label": label, "vote": vote, "z5": round(z, 2) if np.isfinite(z) else None, "hype": bool(hype),
            "notes": notes}

# ---------------------------------------------------------------- TITAN: risk


def titan(v: dict, capital: float, risk_pct: float, approved: list, returns: pd.DataFrame,
          max_total: int = 6, max_class: int = 2) -> dict:
    side = v["side"] or v["trend"] or 1
    a = v["atr"]
    entry = v["price"]
    if side > 0:  # stop just beyond support, kept between 0.75 and 2 ATR away
        stop = float(np.clip(v["support"] - 0.25 * a, entry - 2 * a, entry - 0.75 * a))
        target = v["resistance"] if v["resistance"] > entry else entry + 2 * (entry - stop)
    else:
        stop = float(np.clip(v["resistance"] + 0.25 * a, entry + 0.75 * a, entry + 2 * a))
        target = v["support"] if v["support"] < entry else entry - 2 * (stop - entry)
    target = float(target)
    risk_ps = abs(entry - stop)
    rr = abs(target - entry) / risk_ps if risk_ps else 0
    if rr < 1.5:  # the nearest level is too close: aim for 2R and say so
        target = entry + side * 2 * risk_ps
        rr_note = "nearest level too close, target set at 2R"
    else:
        rr_note = ""
    max_loss = capital * risk_pct / 100
    qty = max_loss / risk_ps if risk_ps else 0
    notional = qty * entry
    corr = 0.0
    if approved and v["symbol"] in returns:
        cs = [abs(returns[v["symbol"]].corr(returns[x["symbol"]])) for x in approved if x["symbol"] in returns]
        corr = float(np.nanmax(cs)) if cs else 0.0
    same_cls = sum(1 for x in approved if x["class"] == v["class"])
    checks = [
        ("Position size", notional <= capital * 0.5, f"{qty:,.4g} units · ₹/$ {notional:,.0f} ({notional / capital * 100:.0f}% of capital)",
         min(notional / (capital * 0.5), 1.5)),
        ("Maximum loss", (len(approved) + 1) * max_loss <= capital * 0.04,
         f"{max_loss:,.0f} at the stop ({risk_ps / a:.1f} ATR); all stops together {(len(approved) + 1) * risk_pct:.1f}% of capital (limit 4%)",
         (len(approved) + 1) * max_loss / (capital * 0.04)),
        ("Correlation", corr <= 0.75, f"max {corr:.2f} with the other approved trades", corr / 0.75 if corr else 0),
        ("Portfolio exposure", len(approved) < max_total and same_cls < max_class,
         f"{len(approved)} trades open, {same_cls} in {v['class']}", max(len(approved) / max_total, same_cls / max_class)),
        ("Risk / reward", abs(target - entry) / risk_ps >= 1.5 if risk_ps else False, f"{abs(target - entry) / risk_ps:.1f}R"
         + (f" ({rr_note})" if rr_note else ""), 1.5 / max(abs(target - entry) / risk_ps, 0.01) if risk_ps else 1.5),
        ("Volatility", not (np.isfinite(v["atr_x"]) and v["atr_x"] > 1.8), f"ATR {v['atr_x']:.1f}x its 100-day average"
         if np.isfinite(v["atr_x"]) else "ATR n/a", (v["atr_x"] / 1.8) if np.isfinite(v["atr_x"]) else 0.5),
    ]
    return {"side": int(side), "entry": float(entry), "stop": float(stop), "target": float(target),
            "rr": round(float(abs(target - entry) / risk_ps), 2) if risk_ps else 0.0,
            "qty": float(qty), "max_loss": float(max_loss), "checks": [{"name": n, "pass": bool(p), "text": t, "load": round(float(min(max(l, 0), 1.5)), 2)}
                                                          for n, p, t, l in checks],
            "pass": all(p for _, p, _, _ in checks)}

# ---------------------------------------------------------------- NOVA: final call


def nova(v: dict, atl: int, ori: dict | None, lun: dict, tit: dict | None) -> dict:
    side = v["side"]
    if not side:
        return {"call": "NO SETUP", "why": "No chart setup: nothing to decide.", "agree": 0, "against": 0, "votes": {}}
    votes = {"VEGA": side if v["status"] == "SETUP" else 0, "ATLAS": atl, "ORION": (ori or {}).get("score", 0),
             "LUNA": lun["vote"]}
    agree = sum(1 for x in votes.values() if x == side)
    against = sum(1 for x in votes.values() if x == -side)
    risk_ok = bool(tit and tit["pass"])
    if tit and not risk_ok:
        failed = ", ".join(c["name"].lower() for c in tit["checks"] if not c["pass"])
        return {"call": "REJECT", "why": f"TITAN rejected: {failed}. No trade is also a decision.", "agree": agree,
                "against": against, "votes": votes}
    if against >= 2:
        return {"call": "REJECT", "why": f"{against} agents against the setup.", "agree": agree, "against": against,
                "votes": votes}
    if v["status"] == "SETUP" and agree >= 3 and against == 0:
        return {"call": "TRADE", "why": f"{agree}/4 agents agree, none against, risk passed.", "agree": agree,
                "against": against, "votes": votes}
    con = [k for k, x in votes.items() if x == -side]
    return {"call": "WAIT", "why": ("Signals conflict (" + ", ".join(con) + " against)" if con else
                                    f"Only {agree}/4 agree") + ": wait for confirmation.", "agree": agree,
            "against": against, "votes": votes}

# ---------------------------------------------------------------- the desk


def run_desk(daily: dict, hourly: dict, news_fn=None, fng: dict | None = None, capital: float = 1_000_000,
             risk_pct: float = 1.0) -> dict:
    """All six agents over the universe. daily / hourly: {yahoo symbol: OHLCV}; news_fn(symbol) -> headlines."""
    a = atlas(daily)
    vs = [x for x in (vega(s, daily.get(s), hourly.get(s)) for s in CLASS_OF) if x]
    breadth = {}
    for cls in UNIVERSE:
        xs = [x for x in vs if x["class"] == cls]
        ok = []
        for x in xs:
            d = _clean(daily.get(x["symbol"]))
            ok.append(d["Close"].iloc[-1] > ema(d["Close"], 50).iloc[-1])
        breadth[cls] = 100 * sum(ok) / len(ok) if ok else None
    rets = pd.DataFrame({x["symbol"]: _clean(daily[x["symbol"]])["Close"].pct_change().tail(60).reset_index(drop=True)
                         for x in vs})
    rows, approved = [], []
    for v in sorted(vs, key=lambda x: -abs(x["score"])):
        atl = atlas_bias(v["symbol"], a)
        ori = orion(v["symbol"], news_fn(v["symbol"]) if (news_fn and v["side"]) else []) if v["side"] else None
        lun = luna(v, daily[v["symbol"]], breadth.get(v["class"]), fng)
        tit = titan(v, capital, risk_pct, approved, rets) if v["side"] else None
        nv = nova(v, atl, ori, lun, tit)
        if nv["call"] == "TRADE":
            approved.append(v)
        rows.append({**v, "atlas": atl, "orion": ori, "luna": lun, "titan": tit, "nova": nv})
    calls = pd.Series([r["nova"]["call"] for r in rows]).value_counts().to_dict() if rows else {}
    return {"updated": datetime.now(IST).isoformat(timespec="seconds"), "atlas": a, "breadth": breadth, "fng": fng,
            "rows": rows, "calls": calls, "capital": capital, "risk_pct": risk_pct}


def score_calls(calls: list[dict], hourly: dict, now: datetime | None = None, days: int = 3) -> list[dict]:
    """Paper-track TRADE calls: target first = win, stop first = loss, else the result after `days`."""
    now = now or datetime.now(IST)
    for c in calls:
        if c.get("result"):
            continue
        h = _clean(hourly.get(c["symbol"]))
        t0 = pd.Timestamp(c["time"]).tz_convert("UTC").tz_localize(None) if pd.Timestamp(c["time"]).tzinfo else pd.Timestamp(c["time"])
        h = h[h.index > t0]
        if h.empty:
            continue
        s = c["side"]
        for _, b in h.iterrows():
            hit_t = b["High"] >= c["target"] if s > 0 else b["Low"] <= c["target"]
            hit_s = b["Low"] <= c["stop"] if s > 0 else b["High"] >= c["stop"]
            if hit_s:
                c["result"], c["exit"] = "loss", c["stop"]
                break
            if hit_t:
                c["result"], c["exit"] = "win", c["target"]
                break
        if not c.get("result") and (now - pd.Timestamp(c["time"]).to_pydatetime()).days >= days:
            c["result"], c["exit"] = "time-out", float(h["Close"].iloc[-1])
        if c.get("result"):
            c["exit"] = float(c["exit"])
            c["r"] = round(float(s * (c["exit"] - c["entry"]) / abs(c["entry"] - c["stop"])), 2)
    return calls
