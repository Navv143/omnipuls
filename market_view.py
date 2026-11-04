"""Market View: every important reading with what it means for a trade, in plain words (pure functions, no Streamlit).

Each reading returns a dict: {title, value, detail, meaning, tone, evidence}
- tone: +1 bullish, -1 bearish, 0 neutral / mixed
- evidence: "tested" (the setup made money after costs in testing), "edge" (research found a small effect: use as
  confirmation), "context" (not tested as a signal; describes the market). The research behind each line is in
  research/FINAL_SETUPS.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EVIDENCE = {"tested": "Tested", "edge": "Small edge", "context": "Context"}


def _f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{nd}f}"


def _clean(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    d.index = idx
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d.between_time("09:15", "15:29")


def index_read(name: str, bars: pd.DataFrame | None, fut: pd.DataFrame | None = None) -> dict | None:
    """Where the index trades today against yesterday's high/low, the opening range and VWAP, and what it means."""
    d = _clean(bars)
    if d.empty:
        return None
    day = d.index.normalize()
    days = sorted(set(day))
    today = d[day == days[-1]]
    prev = d[day == days[-2]] if len(days) > 1 else pd.DataFrame()
    last, op = float(today["Close"].iloc[-1]), float(today["Open"].iloc[0])
    hi, lo = float(today["High"].max()), float(today["Low"].min())
    pdh = float(prev["High"].max()) if not prev.empty else np.nan
    pdl = float(prev["Low"].min()) if not prev.empty else np.nan
    pdc = float(prev["Close"].iloc[-1]) if not prev.empty else np.nan
    orb = today[today.index.time < pd.Timestamp("09:30").time()]
    orh, orl = (float(orb["High"].max()), float(orb["Low"].min())) if not orb.empty else (np.nan, np.nan)
    daily = d.groupby(day).agg(h=("High", "max"), l=("Low", "min"))
    atr = float((daily["h"] - daily["l"]).iloc[-15:-1].mean()) if len(daily) > 3 else np.nan
    move_atr = (last - op) / atr if atr and not np.isnan(atr) else np.nan
    chg = (last / pdc - 1) * 100 if pdc and not np.isnan(pdc) else np.nan
    pos = (last - lo) / (hi - lo) if hi > lo else 0.5

    vwap_side = None
    f = _clean(fut)
    if not f.empty and "Volume" in f and f["Volume"].sum() > 0:
        ft = f[f.index.normalize() == days[-1]]
        if not ft.empty and ft["Volume"].sum() > 0:
            tp = (ft["High"] + ft["Low"] + ft["Close"]) / 3
            vwap = float((tp * ft["Volume"]).sum() / ft["Volume"].sum())
            vwap_side = 1 if float(ft["Close"].iloc[-1]) >= vwap else -1

    bank = "BANK" in name.upper()
    lines, tone = [], 0
    if not np.isnan(pdh) and last > pdh:
        tone = 0 if bank else 1  # Bank Nifty breaks tend to reverse: no bullish lean, wait for the fade
        lines.append("Above yesterday's high: " + (
            "Bank Nifty breaks usually fail. A close back below is the tested fade (sell)."
            if bank else "Nifty breaks often slip back. Wait for it to hold; not a signal on its own."))
    elif not np.isnan(pdl) and last < pdl:
        tone = 0 if bank else -1
        lines.append("Below yesterday's low: " + (
            "Bank Nifty breaks usually fail. A close back above is the tested fade (buy)."
            if bank else "Nifty breaks often slip back. Wait for it to hold; not a signal on its own."))
    else:
        lines.append("Inside yesterday's range: no break yet.")
    if not np.isnan(orh) and len(today) > 3:
        broke = (not np.isnan(pdh) and last > pdh) or (not np.isnan(pdl) and last < pdl)
        if last > orh:
            lines.append("Above the opening range (9:15-9:30).")
            tone = tone if (tone or broke) else 1
        elif last < orl:
            lines.append("Below the opening range (9:15-9:30).")
            tone = tone if (tone or broke) else -1
    if vwap_side is not None:
        lines.append(f"{'Buyers' if vwap_side > 0 else 'Sellers'} in control (futures "
                     f"{'above' if vwap_side > 0 else 'below'} VWAP).")
    if not np.isnan(move_atr) and abs(move_atr) >= 0.6:
        lines.append(f"Trend day forming ({move_atr:+.1f} ATR from the open): the tested option buy if futures OI "
                     "is rising.")
    evidence = "context"  # the tested signals themselves are in the plan; this card describes where price is
    return {"title": name, "value": f"{last:,.2f}", "chg": chg,
            "detail": f"{_f(chg)}% today · {(last / op - 1) * 100:+.2f}% from open · day range position "
                      f"{pos * 100:.0f}% · yday H/L {_f(pdh, 0)} / {_f(pdl, 0)}",
            "meaning": "\n".join(lines), "tone": tone, "evidence": evidence,
            "levels": {"pdh": pdh, "pdl": pdl, "orh": orh, "orl": orl, "atr": atr, "move_atr": move_atr}}


def vix_read(snap: dict | None) -> dict | None:
    if not snap:
        return None
    lvl, chg = snap.get("last"), snap.get("chg")
    if chg is not None and not np.isnan(chg) and chg >= 5:
        m, tone = (f"Fear rising fast ({chg:+.1f}%): bigger swings and dearer options. Option buyers pay more; "
                   "keep size small, trade only tested signals."), -1
    elif chg is not None and not np.isnan(chg) and chg <= -5:
        m, tone = f"Fear falling ({chg:+.1f}%): calmer market, premiums shrinking (time decay hurts option buyers).", 1
    else:
        m, tone = "Volatility steady: no special signal from fear.", 0
    if lvl and lvl >= 20:
        m += f" Level {lvl:.1f} is high: expect wide ranges."
    elif lvl and lvl <= 12:
        m += f" Level {lvl:.1f} is low: small ranges, breakouts often fail."
    return {"title": "India VIX (fear)", "value": _f(lvl), "detail": f"{_f(chg)}% today", "meaning": m,
            "tone": tone, "evidence": "context"}


def buildup_read(share: float | None) -> dict | None:
    if share is None or (isinstance(share, float) and np.isnan(share)):
        return None
    if share >= 60:
        m, tone = "New option and futures positions favour the upside: writers are betting Nifty won't fall.", 1
    elif share <= 40:
        m, tone = "New positions favour the downside: writers are betting Nifty won't rise.", -1
    else:
        m, tone = "Positions balanced: no clear side being built.", 0
    return {"title": "Nifty build-up (who is adding positions)", "value": f"{share:.0f}% bullish",
            "detail": "Option OI change (5 strikes each side) + futures OI, today", "meaning": m, "tone": tone,
            "evidence": "context"}


def breadth_read(adv: int | None, dec: int | None) -> dict | None:
    if adv is None or dec is None or adv + dec == 0:
        return None
    r = adv / (adv + dec)
    if r >= 0.65:
        m, tone = "Broad buying: most F&O stocks are up, longs have the wind behind them.", 1
    elif r <= 0.35:
        m, tone = "Broad selling: most F&O stocks are down, shorts have the wind behind them.", -1
    else:
        m, tone = "Mixed: stock picking day, the index alone tells little.", 0
    return {"title": "F&O breadth", "value": f"{adv} up / {dec} down", "detail": f"{r * 100:.0f}% of F&O stocks up",
            "meaning": m, "tone": tone, "evidence": "context"}


def flow_read(secflow: pd.DataFrame | None) -> dict | None:
    """Sector money flow (turnover split into buying / selling by where each candle closed)."""
    if secflow is None or secflow.empty or "Net Flow Cr" not in secflow:
        return None
    s = secflow.sort_values("Net Flow Cr", ascending=False)
    top, bot = s.iloc[0], s.iloc[-1]
    total = float(s["Net Flow Cr"].sum())
    m = (f"Money is going into {top['Sector']} (₹{top['Net Flow Cr']:+,.0f} Cr) and out of {bot['Sector']} "
         f"(₹{bot['Net Flow Cr']:+,.0f} Cr): favour longs in {top['Sector']}, shorts in {bot['Sector']}. "
         "Sector flow persists a little through the day.")
    return {"title": "Money flow by sector", "value": f"₹{total:+,.0f} Cr net",
            "detail": " · ".join(f"{r['Sector']} {r['Net Flow Cr']:+,.0f}" for _, r in s.head(3).iterrows()),
            "meaning": m, "tone": 1 if total > 0 else -1 if total < 0 else 0, "evidence": "edge"}


def futures_money_read(sf: pd.DataFrame | None) -> dict | None:
    """Fresh futures positions by sector (rupee value of OI change, signed by price)."""
    if sf is None or sf.empty or "Smart money (Rs cr)" not in sf:
        return None
    s = sf.sort_values("Smart money (Rs cr)", ascending=False)
    total = float(s["Smart money (Rs cr)"].sum())
    bull = s[s.get("Flow", "") == "Bullish"]["Sector"].head(3).tolist() if "Flow" in s else []
    bear = s[s.get("Flow", "") == "Bearish"]["Sector"].head(3).tolist() if "Flow" in s else []
    m = (f"Fresh futures money is net {'long' if total > 0 else 'short'} (₹{total:+,.0f} Cr)."
         + (f" Building longs: {', '.join(bull)}." if bull else "")
         + (f" Building shorts: {', '.join(bear)}." if bear else ""))
    return {"title": "Fresh futures money", "value": f"₹{total:+,.0f} Cr",
            "detail": "Value of new futures positions today, by sector", "meaning": m,
            "tone": 1 if total > 500 else -1 if total < -500 else 0, "evidence": "context"}


def chain_read(name: str, spot: float, ch: pd.DataFrame | None, max_pain: float | None = None) -> dict | None:
    """Option chain: where writers sit (support / resistance), PCR, max pain."""
    if ch is None or ch.empty or not spot:
        return None
    ce, pe = ch["CE OI"].fillna(0), ch["PE OI"].fillna(0)
    pcr = pe.sum() / ce.sum() if ce.sum() else np.nan
    res = float(ch.loc[ce.idxmax(), "Strike"])
    sup = float(ch.loc[pe.idxmax(), "Strike"])
    pe_add = ch.loc[ch["PE Chg OI"].fillna(0).idxmax(), "Strike"] if "PE Chg OI" in ch else None
    ce_add = ch.loc[ch["CE Chg OI"].fillna(0).idxmax(), "Strike"] if "CE Chg OI" in ch else None
    room_up, room_dn = (res / spot - 1) * 100, (spot / sup - 1) * 100
    if not np.isnan(pcr) and pcr >= 1.2:
        tone, mood = 1, "put writers are confident (they expect support to hold)"
    elif not np.isnan(pcr) and pcr <= 0.8:
        tone, mood = -1, "call writers are confident (they expect a cap on the upside)"
    else:
        tone, mood = 0, "writers are balanced"
    m = (f"Support {sup:,.0f} (most puts written, {room_dn:.1f}% below), resistance {res:,.0f} (most calls written, "
         f"{room_up:.1f}% above); {mood}.")
    if pe_add is not None and ce_add is not None:
        m += f" Today's new writing: puts at {pe_add:,.0f}, calls at {ce_add:,.0f}."
    return {"title": f"{name} option chain", "value": f"PCR {_f(pcr)}",
            "detail": f"Spot {spot:,.0f} · max pain {_f(max_pain, 0)}", "meaning": m, "tone": tone,
            "evidence": "context", "levels": {"support": sup, "resistance": res, "pcr": pcr}}


def activity_read(R: pd.DataFrame | None) -> dict | None:
    if R is None or R.empty or "Smart" not in R:
        return None
    bull = R[R["Smart"] >= 40].sort_values("Smart", ascending=False)
    bear = R[R["Smart"] <= -40].sort_values("Smart")
    m = ("Stocks moving on 2-3x their usual volume for the time of day tend to keep going to the close: "
         + (f"bullish {', '.join(bull['Stock'].head(4))}" if len(bull) else "no bullish ones")
         + "; " + (f"bearish {', '.join(bear['Stock'].head(4))}." if len(bear) else "no bearish ones."))
    return {"title": "Unusual activity", "value": f"{len(bull)} bullish · {len(bear)} bearish",
            "detail": "Smart score ±40 or more (volume, range, OI, order book vs the same time on 20 days)",
            "meaning": m, "tone": 1 if len(bull) > len(bear) else -1 if len(bear) > len(bull) else 0,
            "evidence": "edge"}


def trade_idea(plan_rows: list[dict], verdict: dict, reads: list[dict]) -> dict:
    """The one line that matters: a tested signal if there is one, otherwise the honest 'wait' with what to watch."""
    fired = [r for r in plan_rows if r["state"] == "fired"]
    if fired:
        return {"tone": 1, "headline": f"{len(fired)} tested signal{'s' if len(fired) > 1 else ''} live",
                "lines": [f"{r['name']}: {r['text']}" for r in fired], "evidence": "tested"}
    score = verdict.get("score", np.nan)
    label = verdict.get("label", "Waiting for data")
    bull = sum(1 for r in reads if r and r["tone"] > 0)
    bear = sum(1 for r in reads if r and r["tone"] < 0)
    watch = [r for r in plan_rows if r["state"] == "wait"]
    lines = [f"Market mood: {label}" + ("" if pd.isna(score) else f" ({score:+.0f}/100)") +
             f". Readings: {bull} bullish, {bear} bearish."]
    if pd.notna(score) and abs(score) >= 20 and (bull - bear) * np.sign(score) >= 2:
        lines.append(f"Bias {'up: look for CE / longs' if score > 0 else 'down: look for PE / shorts'} only, and "
                     "only when a tested signal below confirms. Without one, size small or stay out.")
    else:
        lines.append("Readings disagree: no trade is the right call until a tested setup fires.")
    if watch:
        lines.append("Watching: " + "; ".join(r["name"] for r in watch[:4]) + ".")
    return {"tone": int(np.sign(score)) if pd.notna(score) and abs(score) >= 20 else 0,
            "headline": "No tested signal yet", "lines": lines, "evidence": "context"}
