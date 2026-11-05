"""Closing picks (buy near the close, sell next day): what the last 15-30 minutes say at ~15:15, for the indices and
F&O stocks (pure functions, no Streamlit).

Indices (Nifty, Bank Nifty): a close in the top 20% of the day's range has been followed by a higher next open
(10 years daily: Nifty +0.14% vs +0.11% on any day, up 70% of the time, 10 of 11 years; Bank Nifty +0.20%, 69%,
11 of 11; a strong day of 1+ ATR closing at the high: Nifty +0.18%, 76%, 11 of 11). Plan: buy at 15:15-15:25, sell
at the next day's open. The last 30 minutes' index money, breadth change, futures OI build-up and option writing are
shown as confirmation (to be tested on the recorded picks).

Stocks: late strength did NOT carry over in the first test (58 days: last-30-minute inflow + close near the high
-0.12% at the next open after costs): stock picks are listed with their readings, labelled untested, and recorded.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CUT = "15:15"


def _today(df: pd.DataFrame | None, cutoff: str = CUT) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    d = df[~df.index.duplicated(keep="last")].sort_index()
    d = d[(d.index.strftime("%H:%M") >= "09:15") & (d.index.strftime("%H:%M") <= "15:29")]
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()
    day = d.index.normalize()
    days = sorted(set(day))
    t = d[day == days[-1]]
    t = t[t.index.strftime("%H:%M") < cutoff]
    prev = d[day == days[-2]] if len(days) > 1 else pd.DataFrame()
    return t, prev


def _flow(x: pd.DataFrame) -> tuple[float, float]:
    if x.empty or "Volume" not in x:
        return 0.0, 0.0
    turn = x["Volume"] * (x["High"] + x["Low"] + x["Close"]) / 3
    rng = (x["High"] - x["Low"]).replace(0, np.nan)
    press = ((x["Close"] - x["Open"]) / rng).fillna(0)
    return float((turn * (1 + press) / 2).sum() / 1e7), float((turn * (1 - press) / 2).sum() / 1e7)


def stock_readings(sym: str, df: pd.DataFrame, cutoff: str = CUT) -> dict | None:
    t, prev = _today(df, cutoff)
    if len(t) < 30 or prev.empty:
        return None
    pc = float(prev["Close"].iloc[-1])
    hi, lo, c = float(t["High"].max()), float(t["Low"].min()), float(t["Close"].iloc[-1])
    end = t.index[-1]
    l30, l15 = t[t.index > end - pd.Timedelta(minutes=30)], t[t.index > end - pd.Timedelta(minutes=15)]
    i30, o30 = _flow(l30)
    i15, o15 = _flow(l15)
    iday, oday = _flow(t)
    hist = df[df.index.normalize() < t.index.normalize().max()]
    slot = hist[(hist.index.strftime("%H:%M") >= l30.index[0].strftime("%H:%M")) &
                (hist.index.strftime("%H:%M") <= l30.index[-1].strftime("%H:%M"))]
    usual_v30 = slot.groupby(slot.index.normalize())["Volume"].sum().tail(20).mean() if not slot.empty else np.nan
    return {"symbol": sym, "price": c, "time": (end + pd.Timedelta(minutes=5)).strftime("%H:%M"),
            "ret_day": (c / pc - 1) * 100, "ret_30": (c / float(l30["Open"].iloc[0]) - 1) * 100,
            "clv": (c - lo) / (hi - lo) if hi > lo else 0.5,
            "net_30": i30 - o30, "net_15": i15 - o15, "flow_30": i30 / (i30 + o30) * 100 if i30 + o30 > 0 else 50.0,
            "net_day": iday - oday, "vol_30_x": float(l30["Volume"].sum()) / usual_v30 if usual_v30 else np.nan}


def stock_picks(bars: dict, sectors: dict, cutoff: str = CUT, top: int = 10) -> pd.DataFrame:
    """Every F&O stock's last 30 minutes, ranked: money in the last 30 / 15 minutes, close location, volume, and the
    sector's money in the last 30 minutes (labelled untested)."""
    rows = [r for r in (stock_readings(s, b, cutoff) for s, b in bars.items() if s in sectors) if r]
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["sector"] = t["symbol"].map(sectors)
    t["sec_net_30"] = t.groupby("sector")["net_30"].transform("sum")
    side = np.where((t["flow_30"] >= 55) & (t["net_30"] > 0), 1, np.where((t["flow_30"] <= 45) & (t["net_30"] < 0), -1, 0))
    t["side"] = side
    cl_w = np.where(side > 0, t["clv"], 1 - t["clv"])
    t["score"] = np.round(np.clip(np.abs(t["flow_30"] - 50) * 2, 0, 40) + 25 * cl_w
                          + np.clip(t["vol_30_x"].fillna(1) - 1, 0, 2) * 10
                          + 15 * (np.sign(t["sec_net_30"]) == side) + 10 * (np.sign(t["net_15"]) == side), 0)
    t = t[t["side"] != 0].sort_values("score", ascending=False)

    def why(r):
        s = r["side"]
        return (f"last 30 min ₹{r['net_30']:+,.1f} Cr ({r['flow_30']:.0f}% buying) · last 15 min ₹{r['net_15']:+,.1f} Cr · "
                f"close at {r['clv'] * 100:.0f}% of the day's range · volume {r['vol_30_x']:.1f}x usual · sector "
                f"₹{r['sec_net_30']:+,.0f} Cr {'with' if np.sign(r['sec_net_30']) == s else 'against'}")
    if len(t):
        t["why"] = t.apply(why, axis=1)
    return pd.concat([t[t["side"] > 0].head(top), t[t["side"] < 0].head(max(top // 2, 3))])


def index_pick(name: str, ix: pd.DataFrame, stocks: dict, weights: dict, fut: pd.DataFrame | None = None,
               writers_30: dict | None = None, cutoff: str = CUT) -> dict | None:
    """Index closing read: where it closes in the day's range (the tested part) and the last 30 minutes' index money,
    breadth change, futures OI and option writing (confirmation)."""
    t, prev = _today(ix, cutoff)
    if len(t) < 30 or prev.empty:
        return None
    d = ix[~ix.index.duplicated(keep="last")].sort_index()
    dd = d.groupby(d.index.normalize()).agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    pcs = dd["c"].shift(1)
    trd = pd.concat([dd["h"] - dd["l"], (dd["h"] - pcs).abs(), (dd["l"] - pcs).abs()], axis=1).max(axis=1)
    atr = float(trd.iloc[-15:-1].mean())
    pc = float(prev["Close"].iloc[-1])
    hi, lo, c = float(t["High"].max()), float(t["Low"].min()), float(t["Close"].iloc[-1])
    clv = (c - lo) / (hi - lo) if hi > lo else 0.5
    ret_atr = (c - pc) / atr if atr else np.nan
    end = t.index[-1]
    # constituents: money in the last 30 minutes (weighted) and breadth vs yesterday now vs 30 minutes ago
    net30 = up_now = up_then = wsum = 0.0
    for s_, w in (weights or {}).items():
        sr = stock_readings(s_, stocks.get(s_), cutoff) if stocks.get(s_) is not None else None
        if not sr:
            continue
        net30 += sr["net_30"] * w / 100
        b, bp = _today(stocks[s_], cutoff)
        then = b[b.index <= end - pd.Timedelta(minutes=30)]
        pcs_ = float(bp["Close"].iloc[-1])
        up_now += w * (float(b["Close"].iloc[-1]) > pcs_)
        up_then += w * (float(then["Close"].iloc[-1]) > pcs_) if not then.empty else 0
        wsum += w
    br_now = up_now / wsum * 100 if wsum else np.nan
    br_chg = (up_now - up_then) / wsum * 100 if wsum else np.nan
    oi = {}
    if fut is not None and not fut.empty and "OI" in fut:
        ft, _ = _today(fut, cutoff)
        if len(ft) > 7 and ft["OI"].fillna(0).any():
            o = ft["OI"].replace(0, np.nan).ffill()
            then = ft[ft.index <= end - pd.Timedelta(minutes=30)]
            if not then.empty:
                d_oi = float(o.iloc[-1] - o.loc[then.index[-1]])
                d_px = float(ft["Close"].iloc[-1] - then["Close"].iloc[-1])
                import index_levels as LV
                oi = {"oi_30_pct": d_oi / float(o.loc[then.index[-1]]) * 100 if o.loc[then.index[-1]] else None,
                      "buildup_30": LV.buildup(d_px, d_oi)}
    tested = clv >= 0.8
    strong = tested and ret_atr >= 1 and clv >= 0.9
    conf = []
    if net30 > 0:
        conf.append("index money in (last 30 min)")
    if br_chg == br_chg and br_chg > 0:
        conf.append("breadth rising")
    if oi.get("buildup_30") in ("Long build-up", "Short covering"):
        conf.append(f"futures {oi['buildup_30'].lower()}")
    if writers_30 and (writers_30.get("pe", 0) > writers_30.get("ce", 0)):
        conf.append("more puts written than calls (last 30 min)")
    verdict = ("BUY for the next open (strong close: tested)" if strong else
               "BUY for the next open (close near the high: tested)" if tested else
               "NO TRADE (not closing near the high)")
    return {"name": name, "price": c, "time": (end + pd.Timedelta(minutes=5)).strftime("%H:%M"), "clv": clv,
            "ret_day": (c / pc - 1) * 100, "ret_atr": ret_atr, "net_30": net30, "breadth": br_now, "breadth_chg_30": br_chg,
            **oi, "writers_30": writers_30 or {}, "tested": tested, "strong": strong, "verdict": verdict,
            "confirmations": conf, "side": 1 if tested else 0}


def score_next_day(price: float, side: int, nxt: pd.DataFrame) -> dict:
    """Result of a closing pick on the next day: at the open (9:15 candle's open) and at the close, after costs
    (0.12% stocks / 0.02% index futures are applied by the caller's choice of cost)."""
    if nxt is None or nxt.empty or not side:
        return {}
    o, c = float(nxt["Open"].iloc[0]), float(nxt["Close"].iloc[-1])
    return {"next_open": o, "next_close": c, "open_pct": side * (o / price - 1) * 100, "close_pct": side * (c / price - 1) * 100,
            "next_high_pct": side * ((nxt["High"].max() if side > 0 else nxt["Low"].min()) / price - 1) * 100}
