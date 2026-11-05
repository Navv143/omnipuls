"""Momentum funnel: a simple, step-by-step watchlist for F&O stocks (pure functions, no Streamlit).

Step 1  ATR now      - today's average 5-minute true range from 9:15 to now vs the same window's average on the last
                       20 days (the day so far is more active than usual), and the last 15 minutes' true range vs the
                       same 15 minutes on those days (it is active right now).
Step 2  Sector money - the stock's sector has net money in the direction of the stock's move (in for longs, out for
                       shorts).
Step 3  Stock money  - the stock's own net money is in that direction AND still growing (net now beyond the net
                       15 minutes ago).
Stocks that pass all three go on the watchlist (long = moving up from the open, short = moving down).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULTS = {"day_x": 1.2, "now_x": 1.0, "lookback": 20, "recent": 3, "sector_rising": False}


def _clean(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df[~df.index.duplicated(keep="last")].sort_index()
    m = d.index.hour * 60 + d.index.minute
    return d[(m >= 555) & (m <= 930)]


def atr_step(df: pd.DataFrame | None, lookback: int = 20, recent: int = 3) -> dict | None:
    """Today's ATR from 9:15 to the latest candle and over the last `recent` candles, each vs the same window on the
    last `lookback` days."""
    d = _clean(df)
    if d.empty:
        return None
    day = d.index.normalize()
    pc = d["Close"].shift(1).where(day == pd.Series(day, index=d.index).shift(1).to_numpy())  # previous candle, same day
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    d = d.assign(tr=tr.fillna(d["High"] - d["Low"]), day=day, slot=d.index.strftime("%H:%M"))
    days = sorted(set(day))
    today = d[d["day"] == days[-1]]
    past = d[d["day"].isin(days[-1 - lookback:-1])]
    if today.empty or past.empty:
        return None
    last_slot = today["slot"].iloc[-1]
    upto = past[past["slot"] <= last_slot]
    usual_day = upto.groupby("day")["tr"].mean()
    slots = today["slot"].iloc[-recent:].tolist()
    usual_now = past[past["slot"].isin(slots)].groupby("day")["tr"].mean()
    if len(usual_day) < 5 or usual_day.mean() <= 0:
        return None
    o, c = float(today["Open"].iloc[0]), float(today["Close"].iloc[-1])
    prev = d[d["day"] == days[-2]]["Close"].iloc[-1] if len(days) > 1 else np.nan
    atr_day, atr_now = float(today["tr"].mean()), float(today["tr"].iloc[-recent:].mean())
    return {"price": c, "move_pct": (c / o - 1) * 100, "chg_pct": (c / prev - 1) * 100 if prev == prev else np.nan,
            "side": 1 if c > o else -1 if c < o else 0, "time": last_slot,
            "atr_day": atr_day, "atr_day_usual": float(usual_day.mean()), "day_x": atr_day / float(usual_day.mean()),
            "atr_now": atr_now, "atr_now_usual": float(usual_now.mean()) if len(usual_now) else np.nan,
            "now_x": atr_now / float(usual_now.mean()) if len(usual_now) and usual_now.mean() > 0 else np.nan,
            "range_pct": (float(today["High"].max()) - float(today["Low"].min())) / o * 100}


def flow_step(c: pd.DataFrame | None, recent: int = 3) -> dict | None:
    """The stock's net money today (₹ Cr) now and `recent` candles ago, from activity.stock_candles."""
    if c is None or c.empty or "Net Flow Cr" not in c:
        return None
    net = c["Net Flow Cr"].cumsum()
    inflow, outflow = float(c["Inflow Cr"].sum()), float(c["Outflow Cr"].sum())
    before = float(net.iloc[-1 - recent]) if len(net) > recent else 0.0
    return {"net": float(net.iloc[-1]), "net_before": before, "inflow": inflow, "outflow": outflow,
            "buy_share": inflow / (inflow + outflow) * 100 if inflow + outflow > 0 else np.nan,
            "net_series": [round(float(x), 2) for x in net.to_numpy()]}


def build(bars: dict, per: dict, sectors: dict, cfg: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(every stock with each step's result, sector money table)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    rows = []
    for s, df in bars.items():
        a = atr_step(df, cfg["lookback"], cfg["recent"])
        if not a:
            continue
        f = flow_step(per.get(s), cfg["recent"]) or {}
        rows.append({"Stock": s, "Sector": sectors.get(s, "Other"), **a, **f})
    t = pd.DataFrame(rows)
    if t.empty:
        return t, pd.DataFrame()
    for k in ("net", "net_before", "inflow", "outflow"):
        if k not in t:
            t[k] = np.nan
    sec = t.groupby("Sector").agg(sec_net=("net", "sum"), sec_net_before=("net_before", "sum"),
                                  sec_in=("inflow", "sum"), sec_out=("outflow", "sum"), stocks=("Stock", "count"))
    t = t.join(sec[["sec_net", "sec_net_before"]], on="Sector")
    side = t["side"]
    t["s1_day"] = t["day_x"] >= cfg["day_x"]
    t["s1_now"] = t["now_x"].fillna(0) >= cfg["now_x"]
    t["step1"] = t["s1_day"] & t["s1_now"] & (side != 0)
    sec_ok = np.sign(t["sec_net"].fillna(0)) == side
    if cfg["sector_rising"]:
        sec_ok &= side * (t["sec_net"] - t["sec_net_before"]) > 0
    t["step2"] = t["step1"] & sec_ok
    t["stock_net_with"] = np.sign(t["net"].fillna(0)) == side
    t["stock_net_rising"] = side * (t["net"] - t["net_before"]) > 0
    t["step3"] = t["step2"] & t["stock_net_with"] & t["stock_net_rising"]
    t["Watch"] = np.where(t["step3"], np.where(side > 0, "LONG", "SHORT"), "")
    sec = sec.reset_index()
    sec["buy_share"] = sec["sec_in"] / (sec["sec_in"] + sec["sec_out"]).replace(0, np.nan) * 100
    return t.sort_values(["step3", "step2", "step1", "day_x"], ascending=False), sec.sort_values("sec_net", ascending=False)
