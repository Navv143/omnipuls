"""Momentum funnel: a simple, step-by-step watchlist for F&O stocks (pure functions, no Streamlit).

Step 1  ATR now      - today's average 5-minute true range from 9:15 to now vs the same window's average on the last
                       20 days (the day so far is more active than usual), and the last 15 minutes' true range vs the
                       same 15 minutes on those days (it is active right now).
Step 2  Range now    - today's high-low from 9:15 to now vs the usual high-low of the same window (last 20 days).
Step 3  Sector money - the stock's sector has net money in the direction of the stock's move (in for longs, out for
                       shorts).
Step 4  Stock money  - the stock's own net money is in that direction AND still growing (net now beyond the net
                       15 minutes ago).
Step 5  Market       - from the momentum study (research/MOMENTUM_STUDY.md): moving the same way as the market (the
                       average F&O move from the open; against it lost at every decision time) and not the day after
                       a wide day (yesterday's range ≥ 1.25 ATR: continuation failed in both test periods).
Stocks that pass all five = suggested watchlist (long = up from the open, short = down), ranked by a 0-100 score.
Steps 1-4 without step 5 = "on watch".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import candles as _C

DEFAULTS = {"day_x": 1.2, "now_x": 1.0, "range_x": 1.2, "wide_yday": 1.25, "lookback": 20, "recent": 3,
            "sector_rising": False}


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
            "room_atr": room, "prev_rng_atr": prev_rng, "gap_pct": (o / prev - 1) * 100 if prev == prev else np.nan,
            "atr14": atr14, "swing_low": float(today["Low"].iloc[-6:].min()), "swing_high": float(today["High"].iloc[-6:].max())}


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
    # step 5 (from the momentum study): with the market, and not the day after a wide day
    t["calm_yday"] = ~(t["prev_rng_atr"].fillna(1) >= cfg["wide_yday"])
    t["step5"] = t["step4"] & t["mkt_with"] & t["calm_yday"]
    t["suggest"] = t["step5"]
    t["Watch"] = np.where(t["step5"], np.where(side > 0, "LONG", "SHORT"), np.where(t["step4"], "on watch", ""))
    # quality flags (research/funnel_winners.py, 1,890 signals: all three = 72% wins, +0.30R vs +0.05R; to be confirmed
    # live): market moving with the trade from the open, the stock did not gap the trade's way, not chasing a spike
    t["mkt_prev"] = float(t["chg_pct"].mean()) if "chg_pct" in t else np.nan
    gap_atr = side * t["gap_pct"].fillna(0) / 100 * t["price"] / t["atr14"].replace(0, np.nan)
    t["gap_atr"] = gap_atr
    t["q_mkt"] = (side * mkt) >= QUALITY["mkt_with"]
    t["q_gap"] = gap_atr.fillna(0) <= QUALITY["gap_atr"]
    t["q_calm"] = t["now_x"].fillna(0) <= QUALITY["now_x"]
    t["quality"] = t[["q_mkt", "q_gap", "q_calm"]].sum(axis=1).astype(int)

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
    t["quality_note"] = t.apply(quality_note, axis=1)
    plans = [trade_plan(int(r["side"]), float(r["price"]), r.get("atr14"), r.get("swing_low"), r.get("swing_high"))
             for _, r in t.iterrows()]
    for k in ("entry", "sl", "tp1", "tp2", "risk_pct"):
        t[k] = [p[k] if p else np.nan for p in plans]
    sec = sec.reset_index()
    sec["buy_share"] = sec["sec_in"] / (sec["sec_in"] + sec["sec_out"]).replace(0, np.nan) * 100
    t = t.sort_values(["step5", "step4", "score"], ascending=False)
    return t, sec.sort_values("sec_net", ascending=False)


PLAN = {"min_atr": 0.3, "max_atr": 0.6, "buffer_atr": 0.1, "tp1_r": 1.0, "tp2_r": 2.0}


QUALITY = {"mkt_with": 0.55, "gap_atr": 0.13, "now_x": 1.82}


def quality_note(r) -> str:
    """'Q2/3: market ✓ · no gap ✓ · calm ✗' for a funnel row (the three quality flags)."""
    try:
        parts = [f"market {'✓' if r['q_mkt'] else '✗'}", f"no gap {'✓' if r['q_gap'] else '✗'}",
                 f"calm {'✓' if r['q_calm'] else '✗'}"]
        return f"Q{int(r['quality'])}/3: " + " · ".join(parts)
    except Exception:
        return ""


def trade_plan(side: int, entry: float, atr14: float, swing_low: float, swing_high: float, cfg: dict | None = None) -> dict | None:
    """Entry at the signal price; stop just beyond the last 30 minutes' swing low (long) / high (short), kept between
    0.3 and 0.6 of the daily ATR; targets at 1R and 2R; exit at 15:15 if neither is hit."""
    c = {**PLAN, **(cfg or {})}
    if not side or not atr14 or not np.isfinite(atr14) or atr14 <= 0 or not np.isfinite(entry):
        return None
    raw = (entry - swing_low + c["buffer_atr"] * atr14) if side > 0 else (swing_high - entry + c["buffer_atr"] * atr14)
    risk = float(np.clip(raw if np.isfinite(raw) else c["max_atr"] * atr14, c["min_atr"] * atr14, c["max_atr"] * atr14))
    sl = entry - side * risk
    return {"side": "LONG" if side > 0 else "SHORT", "entry": round(entry, 2), "sl": round(sl, 2),
            "tp1": round(entry + side * c["tp1_r"] * risk, 2), "tp2": round(entry + side * c["tp2_r"] * risk, 2),
            "risk_pct": round(risk / entry * 100, 2), "exit": "15:15"}


def simulate(side: int, entry: float, sl: float, tp1: float, tp2: float, after: pd.DataFrame, cost_pct: float = 0.12) -> dict:
    """Walk the candles after entry: stop first if a candle touches both; half off at TP1 (stop to entry), rest at TP2
    or the 15:15 close. Result in R and % after costs."""
    risk = abs(entry - sl)
    if after is None or after.empty or risk <= 0:
        return {}
    m = after.index.hour * 60 + after.index.minute
    after = after[m <= 915]
    half, stop, done = None, sl, None
    for _, b in after.iterrows():
        lo, hi = float(b["Low"]), float(b["High"])
        hit_stop = lo <= stop if side > 0 else hi >= stop
        hit1 = hi >= tp1 if side > 0 else lo <= tp1
        hit2 = hi >= tp2 if side > 0 else lo <= tp2
        if hit_stop:
            done = stop
            break
        if half is None and hit1:
            half, stop = tp1, entry
        if half is not None and hit2:
            done = tp2
            break
    if done is None:
        done = float(after["Close"].iloc[-1]) if len(after) else entry
    exit_px = done if half is None else (half + done) / 2
    r = side * (exit_px - entry) / risk
    pct = side * (exit_px / entry - 1) * 100 - cost_pct
    outcome = ("stop" if done == sl and half is None else "TP2" if done == tp2 else
               "TP1 then stop at entry" if half is not None and done == entry else "TP1 then 15:15" if half is not None else "15:15")
    return {"r": round(r, 2), "pct": round(pct, 3), "outcome": outcome}


def manage(side: int, entry: float, sl: float, tp1: float, tp2: float, after: pd.DataFrame, cost_pct: float = 0.12) -> dict:
    """Live management after a signal, re-checked on every 5-minute candle:
    - stop hit -> exit;  target 1 -> book half, stop to entry, then TRAIL (stop = the best close minus 1R, never below
      entry);  target 2 -> book the rest;
    - momentum slowing (before target 1): once 0.5R+ in profit, two candles in a row closing against the trade AND a
      close back through the 5-minute EMA 9 -> exit; after target 1 the rest rides the 1R trailing stop;
    - 15:15 -> exit whatever is left (no position is carried overnight).
    Returns the latest price, the move in points / % / R, the best and worst R so far, the current stop, the advice
    for now, and the result of these exits (r / pct after costs) once closed."""
    risk = abs(entry - sl)
    if after is None or after.empty or not risk or not np.isfinite(risk):
        return {}
    a = after[(after.index.hour * 60 + after.index.minute) <= 915]
    if a.empty:
        a = after.iloc[:1]
    ema9 = after["Close"].ewm(span=9, adjust=False).mean()
    stop, half, best, worst = sl, None, 0.0, 0.0
    done, how, when, against = None, "", "", 0
    for ts, b in a.iterrows():
        hi, lo, cl = float(b["High"]), float(b["Low"]), float(b["Close"])
        fav = (hi - entry) if side > 0 else (entry - lo)
        adv = (lo - entry) if side > 0 else (entry - hi)
        best, worst = max(best, fav / risk), min(worst, adv / risk)
        if (lo <= stop) if side > 0 else (hi >= stop):
            done, how = stop, ("trailing stop" if half is not None and stop != entry else "stop at entry" if half is not None else "stop")
            when = ts
            break
        if half is None and ((hi >= tp1) if side > 0 else (lo <= tp1)):
            half, stop = tp1, entry
        if half is not None and ((hi >= tp2) if side > 0 else (lo <= tp2)):
            done, how, when = tp2, "target 2", ts
            break
        if half is not None:  # trail: keep 1R below the best close, never below entry
            trail = (cl - risk) if side > 0 else (cl + risk)
            stop = max(stop, trail) if side > 0 else min(stop, trail)
        against = against + 1 if side * (cl - float(b["Open"])) < 0 else 0
        if half is None and best >= 0.5 and against >= 2 and side * (cl - float(ema9.loc[ts])) < 0:  # before target 1 only
            done, how, when = cl, "momentum slowed", ts
            break
    last = a.iloc[-1]
    ltp = float(after["Close"].iloc[-1])
    end_of_day = (a.index[-1].hour * 60 + a.index[-1].minute) >= 915
    if done is None and end_of_day:
        done, how, when = float(last["Close"]), "15:15 exit", a.index[-1]
    r_now = side * (ltp - entry) / risk
    out = {"ltp": ltp, "move_pts": side * (ltp - entry), "move_pct": side * (ltp / entry - 1) * 100, "r_now": round(r_now, 2),
           "best_r": round(best, 2), "worst_r": round(worst, 2), "stop_now": round(stop, 2), "half_booked": half is not None,
           "as_of": (after.index[-1] + pd.Timedelta(minutes=_C.TF)).strftime("%H:%M")}
    if done is not None:
        exit_px = done if half is None else (half + done) / 2
        out.update(closed=True, exit_how=how,
                   exit_at=("15:15" if how == "15:15 exit" else (when + pd.Timedelta(minutes=_C.TF)).strftime("%H:%M")) if hasattr(when, "strftime") else "",
                   exit_r=round(side * (exit_px - entry) / risk, 2), exit_pct=round(side * (exit_px / entry - 1) * 100 - cost_pct, 3))
        out["advice"] = (f"CLOSED · {how} · {out['exit_r']:+.2f}R" if how == "15:15 exit" else
                         f"CLOSED · {how} at {out['exit_at']} · {out['exit_r']:+.2f}R")
    else:
        out["closed"] = False
        recent = after["Close"].iloc[-3:]
        slowing = len(recent) >= 3 and side * (recent.iloc[-1] - recent.iloc[0]) < 0 and r_now > 0
        if half is not None:
            out["advice"] = f"HOLD rest · half booked at target 1 · trail stop {stop:,.2f}"
        elif r_now >= 0.5 and slowing:
            out["advice"] = f"TIGHTEN · {r_now:+.1f}R but the last 15 min turned against: lock profit (stop to entry)"
        elif r_now <= -0.7:
            out["advice"] = f"CAUTION · near the stop {stop:,.2f} ({r_now:+.1f}R)"
        else:
            out["advice"] = f"HOLD · stop {stop:,.2f} · target 1 {tp1:,.2f}"
    return out
