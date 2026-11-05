"""One engine, many setups, both sides: breakouts AND their failures (sweeps / fades / reversals).

For every stock (and Nifty / Bank Nifty), every day, 5-minute candles, first signal per setup, side and day between
09:30 and 14:30. Entry at the next candle's open. Stop at the signal candle's far end (structure stop); only "small
stop" trades kept: risk between 0.1 and 0.5 ATR. Exits: 1R / 2R / 3R target or the 15:20 open (stop first in a candle).
Costs: stocks 0.12%, indices 0.03% of price per trade.

Setups (each pair = an idea and its opposite):
  pdh_break   close beyond yesterday's high / low                    | pdh_sweep  trades beyond it, closes back inside
  orb_break   close beyond the 9:15-9:30 range                       | orb_fade   trades beyond it, closes back inside
  fhr_break   close beyond the 9:15-10:15 range (after 10:15)        | fhr_fade   trades beyond it, closes back inside
  day_break   new day high / low after 10:30, close at the extreme   | day_sweep  new day low / high after 10:30, closes
                                                                       back over the old extreme (reclaim)
  vwap_cross  close back over VWAP after >= 6 candles on the other side
  gap_go      gap >= 0.5 ATR, first candle in the gap's direction    | gap_fill   gap >= 0.5 ATR, first candle against it
  ignition    volume-burst (>= 2x) candle closing at a new day extreme | ign_fade  short it back
Usage: python research/setup_scan.py fno60.pkl yahoo_idx5m.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

FIRST, LAST, EXIT = "09:30", "14:30", "15:20"
RMIN, RMAX = 0.1, 0.5


def _clean(df):
    x = df[~df.index.duplicated()].sort_index()
    hm = x.index.strftime("%H:%M")
    return x[(hm >= "09:15") & (hm <= "15:25")]


def signals_for_day(d: pd.DataFrame, P: float, PH: float, PL: float, A: float, slot: np.ndarray) -> list[tuple]:
    """(setup, side, i, stop) for one day's candles."""
    o, h, l, c, v = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close", "Volume"))
    hm = np.asarray(d.index.strftime("%H:%M"))
    n = len(d)
    if n < 10:
        return []
    ok = (hm >= FIRST) & (hm <= LAST)
    tp = (h + l + c) / 3
    cv = np.cumsum(v)
    vw = np.where(cv > 0, np.cumsum(tp * v) / np.where(cv > 0, cv, 1), c)
    hod = np.maximum.accumulate(h)
    lod = np.minimum.accumulate(l)
    phod = np.r_[np.nan, hod[:-1]]
    plod = np.r_[np.nan, lod[:-1]]
    orh, orl = h[:3].max(), l[:3].min()
    fh = hm < "10:15"
    fhh, fhl = h[fh].max(), l[fh].min()
    gap = (o[0] - P) / A
    vx = v / np.where(slot > 0, slot, np.nan)
    out = []

    def first(name, side, mask, stop):
        idx = np.flatnonzero(mask & ok)
        if len(idx):
            i = idx[0]
            out.append((name, side, i, stop[i]))

    first("pdh_break", 1, c > PH, l)
    first("pdh_break", -1, c < PL, h)
    first("pdh_sweep", -1, (h > PH) & (c < PH), h)
    first("pdh_sweep", 1, (l < PL) & (c > PL), l)
    first("orb_break", 1, c > orh, l)
    first("orb_break", -1, c < orl, h)
    first("orb_fade", -1, (h > orh) & (c < orh), h)
    first("orb_fade", 1, (l < orl) & (c > orl), l)
    late = hm >= "10:15"
    first("fhr_break", 1, late & (c > fhh), l)
    first("fhr_break", -1, late & (c < fhl), h)
    first("fhr_fade", -1, late & (h > fhh) & (c < fhh), h)
    first("fhr_fade", 1, late & (l < fhl) & (c > fhl), l)
    mid = hm >= "10:30"
    rng = np.maximum(h - l, 1e-9)
    first("day_break", 1, mid & (h > phod) & ((c - l) / rng >= 0.7), l)
    first("day_break", -1, mid & (l < plod) & ((h - c) / rng >= 0.7), h)
    first("day_sweep", 1, mid & (l < plod) & (c > plod), l)
    first("day_sweep", -1, mid & (h > phod) & (c < phod), h)
    below = pd.Series(c < vw).rolling(6).sum().shift().to_numpy() == 6
    above = pd.Series(c > vw).rolling(6).sum().shift().to_numpy() == 6
    first("vwap_cross", 1, below & (c > vw), l)
    first("vwap_cross", -1, above & (c < vw), h)
    if abs(gap) >= 0.5:
        gs = 1 if gap > 0 else -1
        first("gap_go", gs, (np.arange(n) == 3) & (np.sign(c - o) == gs), l if gs > 0 else h)
        first("gap_fill", -gs, (np.arange(n) == 3) & (np.sign(c - o) == -gs), h if gs > 0 else l)
    hot = vx >= 2
    first("ignition", 1, hot & (h > phod) & ((c - l) / rng >= 0.7), l)
    first("ignition", -1, hot & (l < plod) & ((h - c) / rng >= 0.7), h)
    first("ign_fade", -1, hot & (h > phod) & ((c - l) / rng >= 0.7), h + 0 * l)
    first("ign_fade", 1, hot & (l < plod) & ((h - c) / rng >= 0.7), l + 0 * h)
    # ign_fade: the stop is beyond the burst candle's extreme (we are against it)
    out = [(s, sd, i, (h[i] if sd < 0 else l[i]) if s == "ign_fade" else st) for s, sd, i, st in out]
    return out


def trade(d: pd.DataFrame, side: int, i: int, stop: float):
    """Returns entry, risk, and the result in R for targets 1/2/3 and hold-to-close (stop always on)."""
    if i + 1 >= len(d):
        return None
    o, h, l = d["Open"].to_numpy(), d["High"].to_numpy(), d["Low"].to_numpy()
    hm = np.asarray(d.index.strftime("%H:%M"))
    e = o[i + 1]
    risk = side * (e - stop)
    if risk <= 0:
        return None
    res = {}
    for tgt in (1, 2, 3, 99):
        r = None
        for j in range(i + 1, len(d)):
            if hm[j] >= EXIT:
                r = side * (o[j] - e) / risk
                break
            if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
                r = side * ((min(o[j], stop) if side > 0 else max(o[j], stop)) - e) / risk
                break
            if tgt < 99 and ((side > 0 and h[j] >= e + tgt * risk) or (side < 0 and l[j] <= e - tgt * risk)):
                r = tgt
                break
        if r is None:
            r = side * (d["Close"].iloc[-1] - e) / risk
        res[tgt] = r
    return e, risk, res


def scan(bars: dict, kind: str) -> pd.DataFrame:
    rows = []
    for sym, df in bars.items():
        x = _clean(df)
        if len(x) < 500:
            continue
        dd = x.index.normalize()
        hm = x.index.strftime("%H:%M")
        day = x.groupby(dd).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
        pc = day["c"].shift()
        tr = pd.concat([day["h"] - day["l"], (day["h"] - pc).abs(), (day["l"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift()
        vt = x["Volume"].groupby([dd, hm]).last().unstack()
        slot = vt.rolling(20, min_periods=10).mean().shift()
        for k, (d0, g) in enumerate(x.groupby(dd)):
            if k < 15 or not np.isfinite(atr.loc[d0]) or atr.loc[d0] <= 0:
                continue
            A, P = atr.loc[d0], pc.loc[d0]
            sl = slot.loc[d0].reindex(g.index.strftime("%H:%M")).to_numpy() if d0 in slot.index else np.full(len(g), np.nan)
            if kind == "index":
                sl = np.full(len(g), np.nan)
            for setup, side, i, stop in signals_for_day(g, P, day["h"].shift().loc[d0], day["l"].shift().loc[d0], A, sl):
                t = trade(g, side, i, stop)
                if t is None:
                    continue
                e, risk, res = t
                if not (RMIN <= risk / A <= RMAX):
                    continue
                cost = (0.12 if kind == "stock" else 0.03) / 100 * e
                row = {"day": d0, "sym": sym, "setup": setup, "side": side, "hm": g.index[i].strftime("%H:%M"),
                       "risk_atr": risk / A, "risk_pct": risk / e * 100, "atr_pct": A / P * 100,
                       "vx": (g["Volume"].iloc[i] / sl[i]) if np.isfinite(sl[i]) and sl[i] > 0 else np.nan,
                       "day_atr": side * (g["Close"].iloc[i] - P) / A}
                for tgt, r in res.items():
                    row[f"g{tgt}"] = r                       # gross R
                    row[f"n{tgt}"] = r - cost / risk         # after costs, R
                rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    idx = pickle.load(open(sys.argv[2], "rb"))
    stocks = {k: v for k, v in bars.items() if k in U.FNO_SECTOR_OF}
    s = scan(stocks, "stock")
    i = scan({"NIFTY": ix["NIFTY"], "BANKNIFTY": idx["BANKNIFTY"]}, "index")
    out = Path(sys.argv[1]).with_name("setup_scan.parquet")
    pd.concat([s.assign(kind="stock"), i.assign(kind="index")]).to_parquet(out)
    print(len(s), "stock trades,", len(i), "index trades ->", out)
