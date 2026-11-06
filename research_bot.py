"""Research Bot: type any stock or index, get a complete report: trend, EMA levels, VWAP, classic pivots and CPR,
support and resistance (swing levels on daily and intraday candles, clustered), momentum (RSI, MACD, ATR), the
news, futures OI / option-chain readings when available, and a trade plan for both directions (entry, stop,
targets, reward/risk) - with the levels drawn on the charts.

Pure functions on candles (no Streamlit): analyze(daily, intraday, ...) -> dict. The app page draws it.
Information, not investment advice: levels and plans are mechanical readings of the chart.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

import numpy as np
import pandas as pd


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _rsi(c: pd.Series, n: int = 14) -> float:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    r = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return float(r.iloc[-1]) if len(r) and np.isfinite(r.iloc[-1]) else np.nan


def _atr(d: pd.DataFrame, n: int = 14) -> float:
    pc = d["Close"].shift()
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    v = tr.rolling(n).mean().iloc[-1]
    return float(v) if np.isfinite(v) else np.nan


def _adx(d: pd.DataFrame, n: int = 14) -> float:
    h, l, c = d["High"], d["Low"], d["Close"]
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=d.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=d.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    v = dx.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return float(v) if np.isfinite(v) else np.nan


def _swings(d: pd.DataFrame, k: int) -> tuple[list, list]:
    H, L = d["High"].to_numpy(), d["Low"].to_numpy()
    hi, lo = [], []
    for i in range(k, len(d) - k):
        if H[i] == H[i - k:i + k + 1].max():
            hi.append((d.index[i], float(H[i])))
        if L[i] == L[i - k:i + k + 1].min():
            lo.append((d.index[i], float(L[i])))
    return hi, lo


def _cluster(levels: list[tuple[float, str]], tol: float) -> list[dict]:
    """Merge nearby levels (within tol) into zones; strength = how many touches / sources."""
    out = []
    for px, src in sorted(levels):
        if out and px - out[-1]["lo"] <= tol:        # a zone is at most `tol` wide (no chaining)
            z = out[-1]
            z["hi"], z["n"] = max(z["hi"], px), z["n"] + 1
            z["px"] = (z["px"] * (z["n"] - 1) + px) / z["n"]
            z["src"].add(src)
        else:
            out.append({"px": px, "lo": px, "hi": px, "n": 1, "src": {src}})
    return out


def pivots(h: float, l: float, c: float) -> dict:
    """Classic floor pivots and the CPR from the previous session's high / low / close."""
    p = (h + l + c) / 3
    bc = (h + l) / 2
    tc = 2 * p - bc
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l), "R3": h + 2 * (p - l),
            "S3": l - 2 * (h - p), "CPR top": max(tc, bc), "CPR bottom": min(tc, bc)}


def news(query: str, n: int = 8) -> list[dict]:
    """Latest headlines from Google News (India edition) for the name."""
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Omnipuls research bot)"})
        root = ET.fromstring(urllib.request.urlopen(req, timeout=12).read())
    except Exception:
        return []
    out = []
    junk = re.compile(r"share price (today|live)|live nse|stock price (&|and) chart|price chart|quote", re.I)
    for it in root.iter("item"):
        title = html.unescape(it.findtext("title") or "")
        if junk.search(title):
            continue
        src = it.findtext("{*}source") or (it.find("source").text if it.find("source") is not None else "")
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        try:
            when = pd.Timestamp(it.findtext("pubDate")).tz_convert("Asia/Kolkata")
        except Exception:
            when = None
        out.append({"title": title, "source": src or "", "link": it.findtext("link") or "", "time": when})
        if len(out) >= n:
            break
    return out


def analyze(daily: pd.DataFrame, intra: pd.DataFrame | None = None, oi: dict | None = None, chain: dict | None = None,
            now: datetime | None = None) -> dict:
    """daily: OHLCV, a year or more; intra: today's (and recent) intraday candles; oi: futures OI readings
    {oi, oi_chg, buildup, fut_chg}; chain: option-chain readings {pcr, max_pain, call_wall, put_wall}."""
    d = daily.dropna(subset=["Close"]).copy()
    if len(d) < 30:
        raise ValueError("not enough daily history")
    c = d["Close"]
    px = float(intra["Close"].iloc[-1]) if intra is not None and len(intra) else float(c.iloc[-1])
    A = _atr(d)
    ema = {n: float(_ema(c, n).iloc[-1]) for n in (9, 20, 50, 100, 200) if len(c) >= n}
    # ---- trend
    above = sum(px > v for v in ema.values())
    stack_up = all(ema.get(a, np.nan) > ema.get(b, np.nan) for a, b in ((20, 50), (50, 200)) if a in ema and b in ema)
    stack_dn = all(ema.get(a, np.nan) < ema.get(b, np.nan) for a, b in ((20, 50), (50, 200)) if a in ema and b in ema)
    adx = _adx(d)
    slope20 = (ema.get(20, np.nan) / float(_ema(c, 20).iloc[-6]) - 1) * 100 if len(c) > 25 else np.nan
    if stack_up and px > ema.get(20, px):
        trend, tone = "Uptrend", 1
    elif stack_dn and px < ema.get(20, px):
        trend, tone = "Downtrend", -1
    else:
        trend, tone = "Sideways / mixed", 0
    strength = "strong" if adx >= 25 else "weak" if adx < 18 else "moderate"
    # ---- momentum
    macd = _ema(c, 12) - _ema(c, 26)
    sig = _ema(macd, 9)
    mom = {"RSI 14": _rsi(c), "MACD": float(macd.iloc[-1]), "MACD signal": float(sig.iloc[-1]),
           "MACD hist": float(macd.iloc[-1] - sig.iloc[-1]), "ADX 14": adx, "ATR 14": A, "ATR %": A / px * 100}
    # ---- previous session, pivots, 52 weeks
    today = intra.index[-1].normalize() if intra is not None and len(intra) else None
    dd = d[d.index.normalize() < today] if today is not None else d.iloc[:-1]
    prev = dd.iloc[-1] if len(dd) else d.iloc[-2]
    piv = pivots(float(prev["High"]), float(prev["Low"]), float(prev["Close"]))
    yr = d.tail(252)
    info = {"Price": px, "Prev close": float(prev["Close"]), "Change %": (px / float(prev["Close"]) - 1) * 100,
            "Prev high": float(prev["High"]), "Prev low": float(prev["Low"]), "52w high": float(yr["High"].max()),
            "52w low": float(yr["Low"].min()),
            "From 52w high %": (px / float(yr["High"].max()) - 1) * 100}
    # ---- intraday: VWAP, opening range, day high / low
    vw = None
    if intra is not None and len(intra):
        t = intra[intra.index.normalize() == intra.index[-1].normalize()]
        if len(t):
            tp = (t["High"] + t["Low"] + t["Close"]) / 3
            vol = t["Volume"].replace(0, np.nan) if "Volume" in t else None
            if vol is not None and vol.notna().any():
                vw = (tp * vol).cumsum() / vol.cumsum()
            orb = t[t.index.strftime("%H:%M") < "09:30"]
            info.update({"Day open": float(t["Open"].iloc[0]), "Day high": float(t["High"].max()),
                         "Day low": float(t["Low"].min()), "VWAP": float(vw.iloc[-1]) if vw is not None else np.nan,
                         "15-min high": float(orb["High"].max()) if len(orb) else np.nan,
                         "15-min low": float(orb["Low"].min()) if len(orb) else np.nan,
                         "Gap %": (float(t["Open"].iloc[0]) / float(prev["Close"]) - 1) * 100})
    # ---- support / resistance: daily swings (last ~6 months), intraday swings (recent days), pivots, prev H/L, EMAs
    lv = []
    sh, sl = _swings(d.tail(130), 3)
    lv += [(p, "daily swing high") for _, p in sh] + [(p, "daily swing low") for _, p in sl]
    if intra is not None and len(intra) > 30:
        ih, il = _swings(intra.tail(400), 4)
        lv += [(p, "intraday swing") for _, p in ih + il]
    lv += [(piv[k], f"pivot {k}") for k in ("P", "R1", "R2", "S1", "S2")]
    lv += [(info["Prev high"], "prev day high"), (info["Prev low"], "prev day low"),
           (info["52w high"], "52w high"), (info["52w low"], "52w low")]
    lv += [(v, f"EMA {n}") for n, v in ema.items() if n in (50, 200)]
    lv = [(p, s) for p, s in lv if np.isfinite(p) and abs(p / px - 1) < 0.15]
    zones = _cluster(lv, tol=0.25 * A if np.isfinite(A) else px * 0.003)
    for z in zones:
        z["score"] = z["n"] + len(z["src"])
        z["src"] = ", ".join(sorted(z["src"]))
    sup = sorted([z for z in zones if z["px"] < px], key=lambda z: -z["px"])[:4]
    res = sorted([z for z in zones if z["px"] > px], key=lambda z: z["px"])[:4]
    # ---- bias: trend + VWAP + momentum + OI
    score = tone * 2 + (1 if vw is not None and px > info["VWAP"] else -1 if vw is not None else 0) \
        + (1 if mom["MACD hist"] > 0 else -1) + (1 if mom["RSI 14"] > 55 else -1 if mom["RSI 14"] < 45 else 0)
    if oi and oi.get("buildup") in ("Long buildup", "Short covering"):
        score += 1
    elif oi and oi.get("buildup") in ("Short buildup", "Long unwinding"):
        score -= 1
    bias = "Bullish" if score >= 2 else "Bearish" if score <= -2 else "Neutral"
    # ---- plans for both directions
    r1 = res[0]["px"] if res else px + A
    s1 = sup[0]["px"] if sup else px - A
    long_entry = max(px, r1) if bias != "Bullish" else px
    long_stop = (s1 if s1 < long_entry - 0.3 * A else long_entry - A) if np.isfinite(A) else s1
    long_t = [z["px"] for z in res if z["px"] > long_entry + 0.3 * A][:2] or [long_entry + 1.5 * A, long_entry + 2.5 * A]
    short_entry = min(px, s1) if bias != "Bearish" else px
    short_stop = (r1 if r1 > short_entry + 0.3 * A else short_entry + A) if np.isfinite(A) else r1
    short_t = [z["px"] for z in sup if z["px"] < short_entry - 0.3 * A][:2] or [short_entry - 1.5 * A, short_entry - 2.5 * A]

    def plan(side, entry, stop, tg, how):
        risk = abs(entry - stop)
        return {"side": side, "entry": entry, "stop": stop, "t1": tg[0], "t2": tg[1] if len(tg) > 1 else np.nan,
                "risk_pct": risk / entry * 100 if entry else np.nan,
                "rr1": abs(tg[0] - entry) / risk if risk else np.nan, "how": how}
    plans = [
        plan("BUY", long_entry, long_stop, long_t,
             "trend and VWAP agree: buy a pullback that holds VWAP / the nearest support" if bias == "Bullish"
             else f"only on a 5-min close above {r1:,.2f} (nearest resistance), stop below the support"),
        plan("SELL", short_entry, short_stop, short_t,
             "trend and VWAP agree: sell a bounce that fails at VWAP / the nearest resistance" if bias == "Bearish"
             else f"only on a 5-min close below {s1:,.2f} (nearest support), stop above the resistance")]
    # intraday plan (research_bot_backtest.py: daily-level stops / targets are too wide for one day; this one is sized
    # on today's candles): only when the bias and VWAP agree, stop at the last hour's swing, target 2R, out at 15:20
    intraday_plan = None
    if intra is not None and len(intra) and bias != "Neutral" and np.isfinite(info.get("VWAP", np.nan)):
        sd = 1 if bias == "Bullish" else -1
        t = intra[intra.index.normalize() == intra.index[-1].normalize()]
        if sd * (px - info["VWAP"]) > 0 and len(t) >= 6:
            sw = float(t["Low"].tail(12).min()) if sd > 0 else float(t["High"].tail(12).max())
            if sd * (px - sw) > 0:
                risk = abs(px - sw)
                intraday_plan = {"side": "BUY" if sd > 0 else "SELL", "entry": px, "stop": sw, "t1": px + sd * 2 * risk,
                                 "t2": px + sd * 3 * risk, "risk_pct": risk / px * 100, "rr1": 2.0,
                                 "how": "intraday: at market while price holds the VWAP side; stop at the last hour's "
                                        "swing; target 2R; out by 15:20"}
    return {"price": px, "trend": trend, "intraday_plan": intraday_plan, "strength": strength, "tone": tone, "slope20": slope20, "ema": ema,
            "above_emas": above, "n_emas": len(ema), "momentum": mom, "info": info, "pivots": piv,
            "support": sup, "resistance": res, "bias": bias, "score": score, "plans": plans, "oi": oi or {},
            "chain": chain or {}, "vwap_series": vw}


def chain_summary(ch: pd.DataFrame, spot: float) -> dict:
    """PCR, max pain and the strikes with the most call / put open interest (option writers' walls)."""
    if ch is None or ch.empty or "Strike" not in ch:
        return {}
    ce, pe = ch.get("CE OI"), ch.get("PE OI")
    if ce is None or pe is None:
        return {}
    k = ch["Strike"].to_numpy()
    ceo, peo = ce.fillna(0).to_numpy(), pe.fillna(0).to_numpy()
    pain = [((np.maximum(0, s - k) * ceo).sum() + (np.maximum(0, k - s) * peo).sum()) for s in k]
    above, below = ch[ch["Strike"] >= spot], ch[ch["Strike"] <= spot]
    return {"PCR": float(peo.sum() / ceo.sum()) if ceo.sum() else np.nan, "Max pain": float(k[int(np.argmin(pain))]),
            "Call wall (resistance)": float(above.loc[above["CE OI"].idxmax(), "Strike"]) if len(above) else np.nan,
            "Put wall (support)": float(below.loc[below["PE OI"].idxmax(), "Strike"]) if len(below) else np.nan}


def clean_query(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("&", "and")).strip()
