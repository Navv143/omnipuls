"""Momentum funnel: a simple, step-by-step watchlist for F&O stocks (pure functions, no Streamlit).

Step 1  ATR now      - today's average 5-minute true range from 9:15 to now vs the same window's average on the last
                       20 days (the day so far is more active than usual), and the last 15 minutes' true range vs the
                       same 15 minutes on those days (it is active right now).
Step 2  Range now    - today's high-low from 9:15 to now vs the usual high-low of the same window (last 20 days).
Step 3  Sector money - the stock's sector has net money in the direction of the stock's move (in for longs, out for
                       shorts).
Step 4  Stock money  - the stock's own net money is in that direction AND still growing (net now beyond the net
                       15 minutes ago).
Stocks that pass all four go on the watchlist (long = moving up from the open, short = moving down).

Suggested: the watchlist ranked by a score that adds what the momentum study found (research/MOMENTUM_STUDY.md):
moving with the market (against it lost at every decision time), room left to the 20-day high / low, and a quiet
yesterday (after a wide day continuation failed). Stocks against the market are never suggested.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULTS = {"day_x": 1.2, "now_x": 1.0, "range_x": 1.2, "lookback": 20, "recent": 3, "sector_rising": False}


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
    # range so far vs the usual range of the same window
    rng_today = float(today["High"].max() - today["Low"].min())
    usual_rng = upto.groupby("day").apply(lambda g: g["High"].max() - g["Low"].min())
    # daily context: ATR 14, room to the 20-day high / low, yesterday's range
    daily = d.groupby("day").agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    pcd = daily["c"].shift(1)
    trd = pd.concat([daily["h"] - daily["l"], (daily["h"] - pcd).abs(), (daily["l"] - pcd).abs()], axis=1).max(axis=1)
    atr14 = float(trd.iloc[-15:-1].mean()) if len(trd) > 5 else np.nan
    hi20, lo20 = float(daily["h"].iloc[-21:-1].max()), float(daily["l"].iloc[-21:-1].min())
    side = 1 if c > o else -1 if c < o else 0
    room = ((hi20 - c) if side > 0 else (c - lo20)) / atr14 if atr14 and atr14 > 0 and side else np.nan
    prev_rng = float(daily["h"].iloc[-2] - daily["l"].iloc[-2]) / atr14 if atr14 and len(daily) > 1 else np.nan
    atr_day, atr_now = float(today["tr"].mean()), float(today["tr"].iloc[-recent:].mean())
    return {"price": c, "move_pct": (c / o - 1) * 100, "chg_pct": (c / prev - 1) * 100 if prev == prev else np.nan,
            "side": side, "time": last_slot,
            "atr_day": atr_day, "atr_day_usual": float(usual_day.mean()), "day_x": atr_day / float(usual_day.mean()),
            "atr_now": atr_now, "atr_now_usual": float(usual_now.mean()) if len(usual_now) else np.nan,
            "now_x": atr_now / float(usual_now.mean()) if len(usual_now) and usual_now.mean() > 0 else np.nan,
            "range_pct": rng_today / o * 100, "range_x": rng_today / float(usual_rng.mean()) if usual_rng.mean() > 0 else np.nan,
            "room_atr": room, "prev_rng_atr": prev_rng, "gap_pct": (o / prev - 1) * 100 if prev == prev else np.nan}


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


def flow_from_bars(df: pd.DataFrame | None) -> pd.DataFrame:
    """Today's money flow per candle from 5-minute bars, the same split as activity.stock_candles: each candle's
    turnover (volume x typical price) into buying and selling by where it closed inside its range."""
    d = _clean(df)
    if d.empty:
        return pd.DataFrame()
    t = d[d.index.normalize() == d.index.normalize().max()]
    turn = t["Volume"] * (t["High"] + t["Low"] + t["Close"]) / 3
    rng = (t["High"] - t["Low"]).to_numpy()
    press = np.where(rng > 0, (t["Close"] - t["Open"]).to_numpy() / np.where(rng > 0, rng, 1),
                     np.sign(t["Close"].diff().fillna(0).to_numpy()))
    return pd.DataFrame({"Inflow Cr": turn.to_numpy() * (1 + press) / 2 / 1e7,
                         "Outflow Cr": turn.to_numpy() * (1 - press) / 2 / 1e7}, index=t.index).assign(
        **{"Net Flow Cr": lambda x: x["Inflow Cr"] - x["Outflow Cr"]})


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
    t = t.reset_index(drop=True)
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
    t["step2"] = t["step1"] & (t["range_x"].fillna(0) >= cfg["range_x"])
    t["step3"] = t["step2"] & sec_ok
    t["stock_net_with"] = np.sign(t["net"].fillna(0)) == side
    t["stock_net_rising"] = side * (t["net"] - t["net_before"]) > 0
    t["step4"] = t["step3"] & t["stock_net_with"] & t["stock_net_rising"]
    t["Watch"] = np.where(t["step4"], np.where(side > 0, "LONG", "SHORT"), "")
    # market direction (average F&O move from the open) and the suggestion score
    mkt = float(t["move_pct"].mean())
    t["mkt_move"] = mkt
    t["mkt_with"] = np.sign(mkt) == side
    tot = (t["inflow"] + t["outflow"]).replace(0, np.nan)
    flow_with = np.where(side > 0, t["inflow"], t["outflow"]) / tot
    sec_tot = (t["Sector"].map(sec["sec_in"]) + t["Sector"].map(sec["sec_out"])).replace(0, np.nan)
    sec_with = np.where(side > 0, t["Sector"].map(sec["sec_in"]), t["Sector"].map(sec["sec_out"])) / sec_tot
    cap = lambda x, hi: np.clip(np.nan_to_num(x.astype(float)), 0, hi) / hi  # noqa: E731
    score = (20 * cap(t["day_x"] - 1, 1.5) + 15 * cap(t["range_x"] - 1, 1.5) + 10 * cap(t["now_x"] - 0.5, 1.5)
             + 20 * cap(pd.Series(flow_with) - 0.5, 0.3) + 10 * cap(pd.Series(sec_with) - 0.5, 0.15)
             + 15 * t["mkt_with"].astype(float) + 5 * (t["room_atr"].fillna(0) >= 0.36)
             + 5 * (t["prev_rng_atr"].fillna(1) <= 0.81) - 10 * (t["prev_rng_atr"].fillna(1) >= 1.25))
    t["flow_with"], t["sec_with"], t["score"] = flow_with * 100, np.asarray(sec_with, dtype=float) * 100, np.round(score, 0)
    t["suggest"] = t["step4"] & t["mkt_with"]

    def why(r):
        out = [f"ATR {r['day_x']:.1f}x and range {r['range_x']:.1f}x usual"]
        out.append(f"{r['flow_with']:.0f}% of its money {'buying' if r['side'] > 0 else 'selling'}")
        out.append("market moving the same way" if r["mkt_with"] else "AGAINST the market (lost in the study)")
        if r["room_atr"] == r["room_atr"]:
            out.append(f"{r['room_atr']:.1f} ATR to the 20-day {'high' if r['side'] > 0 else 'low'}"
                       if r["room_atr"] > 0 else f"beyond the 20-day {'high' if r['side'] > 0 else 'low'}")
        if r["prev_rng_atr"] == r["prev_rng_atr"]:
            out.append("quiet yesterday" if r["prev_rng_atr"] <= 0.81 else
                       "wide day yesterday (continuation often fails)" if r["prev_rng_atr"] >= 1.25 else "")
        return " · ".join(x for x in out if x)
    t["why"] = t.apply(why, axis=1)
    sec = sec.reset_index()
    sec["buy_share"] = sec["sec_in"] / (sec["sec_in"] + sec["sec_out"]).replace(0, np.nan) * 100
    t = t.sort_values(["step4", "score"], ascending=False)
    return t, sec.sort_values("sec_net", ascending=False)
