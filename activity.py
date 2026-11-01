"""Unusual-activity / smart score for F&O stocks, candle by candle (5-minute bars).

Every reading is compared with the SAME TIME OF DAY over the previous 20 sessions, so a busy 09:15 candle is not
mistaken for unusual activity and a quiet 13:00 that is twice its normal volume is spotted.

Activity score (0-100, direction-free) - how unusual the stock is right now:
    30%  volume so far today vs the usual volume by this time            (time-based Vol x Avg)
    25%  day's range so far vs the usual range by this time               (time-based ATR)
    15%  this candle's volume vs the usual volume of this candle          (candle Vol x Avg)
    10%  this candle's range vs the usual range of this candle
    10%  opening gap vs the stock's usual gap size
    10%  futures OI change today vs its usual daily change                (when Dhan futures data is on)
  Each reading scores 0 at 1x (normal) and full marks at 4x (3x for the gap), on a log scale.

Direction (-1 to +1) - which side is in control:
    35%  move from the open in daily ATRs        25%  distance from VWAP
    15%  RSI(14) on 5-minute closes               15%  buy vs sell quantity in the order book (live quotes)
    10%  futures buildup (long buildup / short covering = up, short buildup / long unwinding = down)

Smart score = Activity x Direction (-100 to +100). Big positive = unusual activity with buyers in control.

What the history says (Nifty 100 stocks, 5-minute data 2015-2026): among the day's biggest movers, those with
time-based volume or range at 2-3x+ normal kept moving to 15:15 (+0.06% to +0.10% before costs, +0.19% since 2022 for
range 3x+), while movers on below-normal activity tended to reverse. A single big candle on its own does not predict
continuation (it often snaps back), and RSI or candle colour alone carry almost no information. Use the score to find
where real activity is, not as a buy/sell signal on its own.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACK = 20
W_ACT = {"cumvol": 0.30, "range": 0.25, "cvol": 0.15, "crng": 0.10, "gap": 0.10, "oi": 0.10}
W_DIR = {"mom": 0.35, "vwap": 0.25, "rsi": 0.15, "book": 0.15, "build": 0.10}

_BASE: dict = {}       # (sym, last hist date, rows) -> baseline dict
_FBASE: dict = {}


def lvl(x, full=4.0):
    """0 at 1x (or less), 1 at `full` x, log scale."""
    x = np.asarray(x, float)
    with np.errstate(all="ignore"):
        v = np.log(np.maximum(x, 1e-9)) / np.log(full)
    return np.clip(np.nan_to_num(v, nan=0.0), 0, 1)


def _clip1(x):
    return np.clip(np.nan_to_num(np.asarray(x, float), nan=0.0), -1, 1)


def _slot(idx) -> pd.Index:
    return pd.Index(idx.strftime("%H:%M"))


def _rsi(c: pd.Series, n=14) -> pd.Series:
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l_ = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l_.replace(0, np.nan))


def baseline(sym: str, hist: pd.DataFrame) -> dict | None:
    """Same-time-of-day averages over the last LOOKBACK sessions + daily stats. Cached per stock per day."""
    if hist is None or hist.empty:
        return None
    key = (sym, hist.index[-1], len(hist))
    if key in _BASE:
        return _BASE[key]
    h = hist.copy()
    day = h.index.normalize()
    days = day.unique()
    keep = days[-LOOKBACK:]
    h = h[day.isin(keep)]
    day = h.index.normalize()
    slot = _slot(h.index)
    tp = (h["High"] + h["Low"] + h["Close"]) / 3
    frame = pd.DataFrame({"d": day, "s": slot, "v": h["Volume"].values, "t": (h["Volume"] * tp).values,
                          "r": (h["High"] - h["Low"]).values, "hi": h["High"].values, "lo": h["Low"].values})
    piv = lambda col: frame.pivot_table(index="d", columns="s", values=col, aggfunc="sum").sort_index(axis=1)  # noqa
    v, t, r = piv("v"), piv("t"), piv("r")
    hi = frame.pivot_table(index="d", columns="s", values="hi", aggfunc="max").sort_index(axis=1)
    lo = frame.pivot_table(index="d", columns="s", values="lo", aggfunc="min").sort_index(axis=1)
    rng_sofar = hi.cummax(axis=1) - lo.cummin(axis=1)
    # daily stats from all history (ATR needs 14 days, gaps need 20)
    g = hist.groupby(hist.index.normalize())
    daily = pd.DataFrame({"o": g["Open"].first(), "h": g["High"].max(), "l": g["Low"].min(), "c": g["Close"].last()})
    pc = daily["c"].shift(1)
    tr = pd.concat([daily["h"] - daily["l"], (daily["h"] - pc).abs(), (daily["l"] - pc).abs()], axis=1).max(axis=1)
    gaps = (daily["o"] / pc - 1).abs().dropna()
    b = {
        "vol": v.mean(), "cumvol": v.fillna(0).cumsum(axis=1).mean(), "turn": t.mean(),
        "cumturn": t.fillna(0).cumsum(axis=1).mean(), "rng": r.mean(), "rng_sofar": rng_sofar.mean(),
        "atr": float(tr.tail(14).mean()), "absgap": float(gaps.tail(LOOKBACK).mean()) if len(gaps) else np.nan,
        "prev_close": float(daily["c"].iloc[-1]), "prev_high": float(daily["h"].iloc[-1]),
        "prev_low": float(daily["l"].iloc[-1]), "days": len(keep),
        "day_turn": float(t.sum(axis=1).mean()),
    }
    if len(_BASE) > 2000:
        _BASE.clear()
    _BASE[key] = b
    return b


def fut_baseline(sym: str, fhist: pd.DataFrame) -> dict | None:
    """Usual 5-minute |OI change| by time of day and usual |daily OI change %| for the stock future."""
    if fhist is None or fhist.empty or "OI" not in fhist:
        return None
    key = (sym, fhist.index[-1], len(fhist))
    if key in _FBASE:
        return _FBASE[key]
    f = fhist[fhist["OI"] > 0]
    if f.empty:
        return None
    day = f.index.normalize()
    d_oi = f["OI"].diff().where(day == pd.Series(day, index=f.index).shift(1).values)  # same-day changes only
    fr = pd.DataFrame({"d": day, "s": _slot(f.index), "x": d_oi.abs().values})
    slot_abs = fr.pivot_table(index="d", columns="s", values="x", aggfunc="sum").tail(LOOKBACK).mean()
    last_oi = f.groupby(day)["OI"].last()
    daily_pct = (last_oi.pct_change() * 100).abs().dropna().tail(LOOKBACK)
    b = {"slot_abs": slot_abs, "daily_abs_pct": float(daily_pct.mean()) if len(daily_pct) else np.nan,
         "prev_oi": float(last_oi.iloc[-1]),
         "prev_close": float(f.groupby(day)["Close"].last().iloc[-1]) if "Close" in f else np.nan}
    if len(_FBASE) > 2000:
        _FBASE.clear()
    _FBASE[key] = b
    return b


def buildup(px_chg, oi_chg) -> str:
    if px_chg is None or oi_chg is None or pd.isna(px_chg) or pd.isna(oi_chg) or oi_chg == 0:
        return ""
    if px_chg >= 0:
        return "Long buildup" if oi_chg > 0 else "Short covering"
    return "Short buildup" if oi_chg > 0 else "Long unwinding"


BUILD_DIR = {"Long buildup": 1.0, "Short covering": 0.5, "Short buildup": -1.0, "Long unwinding": -0.5, "": 0.0}


def stock_candles(sym: str, bars: pd.DataFrame, session, fut: pd.DataFrame | None = None,
                  snaps: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per 5-minute candle of `session` with every reading and the scores at that candle."""
    if bars is None or bars.empty or session is None:
        return pd.DataFrame()
    day = bars.index.normalize()
    sess = pd.Timestamp(session).normalize()
    hist, today = bars[day < sess], bars[day == sess]
    if today.empty or hist.empty:
        return pd.DataFrame()
    b = baseline(sym, hist)
    if b is None or b["days"] < 5:
        return pd.DataFrame()
    t = today[["Open", "High", "Low", "Close", "Volume"]].copy()
    s = _slot(t.index)
    tp = (t["High"] + t["Low"] + t["Close"]) / 3
    turn = t["Volume"] * tp
    t["Turnover Cr"] = turn.cumsum() / 1e7
    t["Candle Turnover Cr"] = turn / 1e7
    # money flow: each candle's turnover split into buying and selling by where it closed inside its range
    rng_c = (t["High"] - t["Low"]).values
    press = np.where(rng_c > 0, (t["Close"] - t["Open"]).values / np.where(rng_c > 0, rng_c, 1),
                     np.sign(t["Close"].diff().fillna(0).values))
    t["Inflow Cr"] = turn.values * (1 + press) / 2 / 1e7
    t["Outflow Cr"] = turn.values * (1 - press) / 2 / 1e7
    t["Net Flow Cr"] = t["Inflow Cr"] - t["Outflow Cr"]
    t["Net Flow Day Cr"] = t["Net Flow Cr"].cumsum()
    t["Usual Day Turnover Cr"] = b.get("day_turn", np.nan) / 1e7
    rr = lambda num, base: (num.values / base.reindex(s).values) if base is not None else np.nan  # noqa: E731
    with np.errstate(all="ignore"):
        t["Candle Vol x"] = rr(t["Volume"], b["vol"])
        t["Vol x (time)"] = rr(t["Volume"].cumsum(), b["cumvol"])
        t["Turnover x (time)"] = rr(turn.cumsum(), b["cumturn"])
        t["Candle Range x"] = rr(t["High"] - t["Low"], b["rng"])
        t["Range x (time)"] = rr(t["High"].cummax() - t["Low"].cummin(), b["rng_sofar"])
    o = float(t["Open"].iloc[0])
    gap = o / b["prev_close"] - 1 if b["prev_close"] else np.nan
    t["Gap %"] = gap * 100
    t["Gap x"] = abs(gap) / b["absgap"] if b["absgap"] and b["absgap"] > 0 else np.nan
    t["Chg %"] = (t["Close"] / b["prev_close"] - 1) * 100
    t["From open %"] = (t["Close"] / o - 1) * 100
    t["ATR used %"] = (t["High"].cummax() - t["Low"].cummin()) / b["atr"] * 100 if b["atr"] else np.nan
    mom_atr = (t["Close"] - o) / b["atr"] if b["atr"] else np.nan
    vwap = turn.cumsum() / t["Volume"].cumsum().replace(0, np.nan)
    t["VWAP"] = vwap
    t["vs VWAP %"] = (t["Close"] / vwap - 1) * 100
    allc = pd.concat([hist["Close"].tail(300), t["Close"]])
    t["RSI"] = _rsi(allc).reindex(t.index).values
    # futures OI
    t["OI"] = np.nan
    t["OI Chg %"] = np.nan
    t["Candle OI x"] = np.nan
    t["Buildup"] = ""
    t["OI Value Chg Cr"] = np.nan
    oi_x_day = np.full(len(t), np.nan)
    if fut is not None and not fut.empty and "OI" in fut:
        fday = fut.index.normalize()
        fb = fut_baseline(sym, fut[fday < sess])
        ft = fut[fday == sess]
        if fb is not None and not ft.empty:
            ft = ft[ft["OI"] > 0].reindex(t.index, method="ffill")
            t["OI"] = ft["OI"].values
            t["OI Chg %"] = (ft["OI"] / fb["prev_oi"] - 1).values * 100
            d_oi = ft["OI"].diff()
            d_oi.iloc[0] = ft["OI"].iloc[0] - fb["prev_oi"] if pd.notna(ft["OI"].iloc[0]) else np.nan
            with np.errstate(all="ignore"):
                t["Candle OI x"] = d_oi.abs().values / fb["slot_abs"].reindex(s).values
                if fb["daily_abs_pct"] and fb["daily_abs_pct"] > 0:
                    oi_x_day = np.abs(t["OI Chg %"].values) / fb["daily_abs_pct"]
            if "Close" in ft and pd.notna(fb["prev_close"]):
                fpx = (ft["Close"] / fb["prev_close"] - 1).values * 100
                fclose = ft["Close"].values
            else:  # OI-only futures data (near + next month combined): use the stock's own move and price
                fpx = t["Chg %"].values
                fclose = t["Close"].values
            t["Fut Chg %"] = fpx
            t["OI Value Chg Cr"] = (ft["OI"].values - fb["prev_oi"]) * fclose / 1e7
            t["Buildup"] = [buildup(p, q) for p, q in zip(fpx, t["OI Chg %"].values)]
    # order book from live-quote snapshots (last snapshot inside each candle)
    t["Buy Qty"] = np.nan
    t["Sell Qty"] = np.nan
    if snaps is not None and not snaps.empty:
        sn = snaps[snaps["sym"] == sym].dropna(subset=["bq", "sq"])
        if not sn.empty:
            sn = sn.set_index("ts").sort_index()
            sn = sn[sn.index.normalize() == sess]
            if not sn.empty:
                ends = t.index + pd.Timedelta(minutes=5)
                pos = np.searchsorted(sn.index.values, ends.values, side="left") - 1
                ok = pos >= 0
                t.loc[ok, "Buy Qty"] = sn["bq"].values[pos[ok]]
                t.loc[ok, "Sell Qty"] = sn["sq"].values[pos[ok]]
                t.iloc[-1, t.columns.get_loc("Buy Qty")] = sn["bq"].iloc[-1]    # latest reading for the live candle
                t.iloc[-1, t.columns.get_loc("Sell Qty")] = sn["sq"].iloc[-1]
    with np.errstate(all="ignore"):
        t["Buy/Sell"] = t["Buy Qty"] / t["Sell Qty"].replace(0, np.nan)
        book = (t["Buy Qty"] - t["Sell Qty"]) / (t["Buy Qty"] + t["Sell Qty"])
    # ---- scores
    parts = {"cumvol": lvl(t["Vol x (time)"]), "range": lvl(t["Range x (time)"]), "cvol": lvl(t["Candle Vol x"]),
             "crng": lvl(t["Candle Range x"]), "gap": lvl(t["Gap x"], 3.0) * np.ones(len(t)), "oi": lvl(oi_x_day)}
    have_oi = np.isfinite(oi_x_day)
    wsum = sum(W_ACT[k] for k in W_ACT if k != "oi") + np.where(have_oi, W_ACT["oi"], 0)
    act = sum(W_ACT[k] * parts[k] for k in W_ACT) / wsum * 100
    atr_pct = b["atr"] / b["prev_close"] * 100 if b["prev_close"] else np.nan
    dparts = {"mom": _clip1(mom_atr / 0.75), "vwap": _clip1(t["vs VWAP %"] / (0.25 * atr_pct)),
              "rsi": _clip1((t["RSI"] - 50) / 20), "book": _clip1(book / 0.3),
              "build": np.array([BUILD_DIR.get(x, 0.0) for x in t["Buildup"]])}
    have = {"mom": np.ones(len(t), bool), "vwap": np.isfinite(t["vs VWAP %"].values), "rsi": np.isfinite(t["RSI"].values),
            "book": np.isfinite(book.values), "build": (t["Buildup"] != "").values}
    dw = sum(np.where(have[k], W_DIR[k], 0) for k in W_DIR)
    direction = sum(np.where(have[k], W_DIR[k] * dparts[k], 0) for k in W_DIR) / np.where(dw > 0, dw, np.nan)
    t["Activity"] = np.round(act, 0)
    t["Direction"] = np.round(direction, 2)
    t["Smart"] = np.round(act * direction, 0)
    t["Time"] = t.index.strftime("%H:%M")
    return t


def signals_text(r) -> str:
    out = []
    g = lambda k: r.get(k) if pd.notna(r.get(k)) else None  # noqa: E731
    if (x := g("Vol x (time)")) and x >= 2:
        out.append(f"Volume {x:.1f}x for the time")
    if (x := g("Range x (time)")) and x >= 2:
        out.append(f"Range {x:.1f}x")
    if (x := g("Candle Vol x")) and x >= 3:
        out.append(f"Candle volume {x:.1f}x")
    if (x := g("Gap x")) and x >= 2 and g("Gap %") is not None:
        out.append(f"Gap {r['Gap %']:+.1f}% ({x:.1f}x usual)")
    if (x := g("OI Chg %")) is not None and abs(x) >= 5:
        out.append(f"OI {x:+.0f}% {r.get('Buildup') or ''}".strip())
    if (x := g("Buy/Sell")) and (x >= 2 or x <= 0.5):
        out.append(f"Buyers {x:.1f}x sellers" if x >= 2 else f"Sellers {1 / x:.1f}x buyers")
    if (x := g("ATR used %")) and x >= 100:
        out.append(f"Used {x:.0f}% of ATR")
    return " · ".join(out)


def rank(bars: dict, session, futs: dict | None = None, snaps: pd.DataFrame | None = None,
         sectors: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Latest-candle ranking for every stock, today's unusual candles across stocks, and per-stock candle tables."""
    rows, events, per = [], [], {}
    for sym, df in bars.items():
        try:
            c = stock_candles(sym, df, session, (futs or {}).get(sym), snaps)
        except Exception:
            continue
        if c.empty:
            continue
        per[sym] = c
        last = c.iloc[-1].to_dict()
        last.update({"Stock": sym, "Sector": (sectors or {}).get(sym, ""), "Price": last["Close"],
                     "Peak Smart": c["Smart"].abs().max() * np.sign(c.loc[c["Smart"].abs().idxmax(), "Smart"]),
                     "Signals": ""})
        last["Signals"] = signals_text(last)
        rows.append(last)
        ev = c[(c["Candle Vol x"] >= 3) | (c["Candle Range x"] >= 2.5) | (c["Candle OI x"] >= 4)]
        for ts, e in ev.iterrows():
            events.append({"Time": e["Time"], "Stock": sym, "Candle": "Green" if e["Close"] >= e["Open"] else "Red",
                           "Candle Vol x": e["Candle Vol x"], "Candle Range x": e["Candle Range x"],
                           "Candle OI x": e["Candle OI x"], "Candle Turnover Cr": e["Candle Turnover Cr"],
                           "Price": e["Close"], "Chg %": e["Chg %"], "Vol x (time)": e["Vol x (time)"],
                           "Smart": e["Smart"], "_ts": ts})
    R = pd.DataFrame(rows)
    E = pd.DataFrame(events)
    if not R.empty:
        R = R.sort_values("Smart", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    if not E.empty:
        E = E.sort_values(["_ts", "Candle Vol x"], ascending=[False, False]).drop(columns="_ts").reset_index(drop=True)
    return R, E, per


HOW = """
Every reading is compared with the **same time of day over the previous 20 sessions**, so a naturally busy 09:15
candle is not flagged, while a 13:00 candle at twice its normal volume is.

**Activity score (0 to 100, either direction): how unusual the stock is right now**

| Weight | Reading |
|---|---|
| 30% | Volume so far today ÷ usual volume by this time (time-based Vol × Avg) |
| 25% | Day's range so far ÷ usual range by this time (time-based ATR) |
| 15% | This candle's volume ÷ usual volume of this candle |
| 10% | This candle's range ÷ usual range of this candle |
| 10% | Opening gap ÷ the stock's usual gap size |
| 10% | Futures OI change today ÷ its usual daily change (Dhan only) |

Each reading scores 0 at 1× (normal) and full marks at 4× (3× for the gap), on a log scale.
Readings that are missing (for example OI on Yahoo) are left out and the weights re-balanced.

**Direction (−1 to +1): which side is in control**

| Weight | Reading |
|---|---|
| 35% | Move from today's open, in daily ATRs |
| 25% | Distance above / below VWAP |
| 15% | RSI(14) on 5-minute closes |
| 15% | Buy ÷ sell quantity waiting in the order book (live quotes, Dhan) |
| 10% | Futures buildup: long buildup / short covering = up, short buildup / long unwinding = down |

**Smart score = Activity × Direction (−100 to +100).** +60 means very unusual activity with buyers in control;
−60 the same with sellers in control. *Peak today* is the strongest reading the stock reached during the session.

**What 11 years of data says** (Nifty 100 stocks, 5-minute bars, 2015–2026): among the day's biggest movers, those
running at 2–3× or more of their usual volume or range for the time of day kept moving in the same direction to 15:15
(+0.06% to +0.10% on average before costs; +0.19% since 2022 when range was 3×+). Big movers on *below-normal*
activity tended to reverse. A single big candle on its own does **not** predict continuation (it often snaps back),
and RSI or candle colour alone carry almost no information.
Use the score to find where real activity is and to confirm a move — not as a buy/sell signal on its own.
"""



# ---------------------------------------------------------------- money flow (inflow / outflow)

FLOW_HOW = """
**How money flow is measured.** Each 5-minute candle's turnover (volume × average price, in ₹ crore) is split into
*buying* and *selling* by where the candle closed inside its range: a candle closing at its high counts 100% as inflow,
one closing at its low 100% as outflow, one closing mid-range half and half. **Net flow = inflow − outflow.**
*Flow % of usual* is net flow divided by the stock's normal full-day turnover, so a ₹50 Cr inflow into a small stock
ranks above ₹50 Cr into HDFC Bank. *Futures OI value change* is new money that entered (+) or left (−) the stock's
nearest future, with the buildup telling you whether it went long or short.

**Where is money going *from* and *to*?** Exchanges don't publish who sold to whom. What we can see is which sectors
and stocks are taking net money in and which are giving it up over the same period; the rotation chart pairs the two
sides in proportion to their size. Read it as "money is leaving these, money is arriving in these".

**What 11 years of data says** (Nifty 100 stocks, 5-minute bars, 2015–2026): sectors with the biggest inflow so far
outperform those with the biggest outflow for the rest of the day, but only slightly (about +0.04% to the close, a
little stronger since 2022). For single stocks, flow adds almost nothing beyond the price move itself and slightly
reverses over the next 30–60 minutes. So money flow tells you **where the action and the rotation are**; it is not a
buy/sell signal on its own.
"""


def flow_window(per: dict, start_time: str | None = None) -> pd.DataFrame:
    """Per-stock inflow / outflow / net flow from `start_time` (HH:MM, inclusive) to the last candle."""
    rows = []
    for sym, c in per.items():
        if c is None or c.empty or "Net Flow Cr" not in c:
            continue
        w = c if start_time is None else c[c["Time"] >= start_time]
        if w.empty:
            continue
        last = c.iloc[-1]
        usual = last.get("Usual Day Turnover Cr")
        inflow, outflow = float(w["Inflow Cr"].sum()), float(w["Outflow Cr"].sum())
        net = inflow - outflow
        rows.append({"Stock": sym, "Price": last["Close"], "Chg %": last["Chg %"],
                     "Inflow Cr": inflow, "Outflow Cr": outflow, "Net Flow Cr": net,
                     "Buy share %": inflow / (inflow + outflow) * 100 if inflow + outflow > 0 else np.nan,
                     "Window Turnover Cr": inflow + outflow, "Turnover Cr": last["Turnover Cr"],
                     "Turnover x (time)": last.get("Turnover x (time)"),
                     "Flow % of usual": net / usual * 100 if usual and usual > 0 else np.nan,
                     "OI Value Chg Cr": last.get("OI Value Chg Cr"), "Buildup": last.get("Buildup", ""),
                     "Smart": last.get("Smart")})
    return pd.DataFrame(rows)


def sector_flow(stocks: pd.DataFrame) -> pd.DataFrame:
    if stocks.empty:
        return pd.DataFrame()
    g = stocks.groupby("Sector")
    out = pd.DataFrame({"Inflow Cr": g["Inflow Cr"].sum(), "Outflow Cr": g["Outflow Cr"].sum(),
                        "Net Flow Cr": g["Net Flow Cr"].sum(), "Stocks": g.size(),
                        "Stocks with inflow": g["Net Flow Cr"].apply(lambda x: int((x > 0).sum())),
                        "Avg Chg %": g["Chg %"].mean(),
                        "OI Value Chg Cr": g["OI Value Chg Cr"].sum(min_count=1)})
    out["Buy share %"] = out["Inflow Cr"] / (out["Inflow Cr"] + out["Outflow Cr"]) * 100
    out["Top inflow stock"] = g.apply(lambda d: d.loc[d["Net Flow Cr"].idxmax(), "Stock"] if len(d) else "")
    out["Top outflow stock"] = g.apply(lambda d: d.loc[d["Net Flow Cr"].idxmin(), "Stock"] if len(d) else "")
    return out.sort_values("Net Flow Cr", ascending=False).reset_index()


def sector_timeline(per: dict, sectors: dict, bucket_min: int = 30) -> pd.DataFrame:
    """Net flow (₹ Cr) by sector and time bucket: rows = bucket start HH:MM, columns = sectors."""
    parts = []
    for sym, c in per.items():
        if c is None or c.empty or "Net Flow Cr" not in c:
            continue
        idx = c.index
        base = idx.normalize() + pd.Timedelta(hours=9, minutes=15)
        k = ((idx - base) // pd.Timedelta(minutes=bucket_min)).astype(int)
        lab = (base + pd.to_timedelta(k * bucket_min, unit="m")).strftime("%H:%M")
        parts.append(pd.DataFrame({"b": lab, "sec": sectors.get(sym, "Other"), "f": c["Net Flow Cr"].values}))
    if not parts:
        return pd.DataFrame()
    d = pd.concat(parts)
    return d.pivot_table(index="b", columns="sec", values="f", aggfunc="sum").sort_index()


def rotation_links(sec: pd.DataFrame, max_each: int = 6) -> list[tuple[str, str, float]]:
    """Pair net-outflow sectors with net-inflow sectors in proportion (for a Sankey picture)."""
    if sec.empty:
        return []
    outs = sec[sec["Net Flow Cr"] < 0].nsmallest(max_each, "Net Flow Cr")
    ins = sec[sec["Net Flow Cr"] > 0].nlargest(max_each, "Net Flow Cr")
    if outs.empty or ins.empty:
        return []
    tot_in = ins["Net Flow Cr"].sum()
    links = []
    for _, o in outs.iterrows():
        for _, i in ins.iterrows():
            links.append((o["Sector"], i["Sector"], float(-o["Net Flow Cr"] * i["Net Flow Cr"] / tot_in)))
    return links
