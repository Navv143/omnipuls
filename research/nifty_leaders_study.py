"""Nifty leg + leaders: when Nifty breaks out of its last-hour range in the middle of the day (11:00-14:00), buy (short)
the strongest (weakest) stocks that are quiet and near their day's high (low), in the strongest (weakest) sector.

Trigger: a Nifty 5-min candle closes above the high (below the low) of the previous `look` candles; first per side and
day. Picks at that candle (move_panel from move_finder.py, short side mirrored): already >= 0.5 ATR on the day the
same way, above (below) VWAP, last 30 minutes <= 0.35 ATR wide, <= 0.3 ATR from the day's high (low); ranked by sector
strength then strength vs Nifty; top `k`. Entry at the next candle's open, stop first, 0.12% costs (Nifty 0.03%).
Usage: python research/nifty_leaders_study.py fno60.pkl move_panel.parquet
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from move_finder import mirrored  # noqa: E402


def nifty_triggers(nifty: pd.DataFrame, look: int = 12, first: str = "11:00", last: str = "14:00",
                   min_brk: float = 0.0) -> pd.DataFrame:
    n = nifty[~nifty.index.duplicated()].sort_index()
    rows = []
    for day, g in n.groupby(n.index.normalize()):
        hm = g.index.strftime("%H:%M")
        hi = g["High"].rolling(look).max().shift()
        lo = g["Low"].rolling(look).min().shift()
        for side, brk in ((1, (g["Close"] - hi) / g["Close"] * 100), (-1, (lo - g["Close"]) / g["Close"] * 100)):
            m = (brk > min_brk) & (hm >= first) & (hm <= last)
            if m.any():
                i = int(np.flatnonzero(m.to_numpy())[0])
                if i + 1 < len(g):
                    e = g["Open"].iloc[i + 1]
                    post = g.iloc[i + 1:]
                    r = {}
                    for lim in (60, 120, 999):
                        k = post[post.index < post.index[0] + pd.Timedelta(minutes=lim)]
                        k = k[k.index.strftime("%H:%M") < "15:20"]
                        r[f"n_ret_{lim}"] = side * (k["Close"].iloc[-1] / e - 1) * 100 - 0.03
                    rows.append({"day": day, "side": side, "hm": hm[i], **r})
    return pd.DataFrame(rows)


def picks(panel_m: pd.DataFrame, trig: pd.DataFrame, k: int = 3, need_quiet: bool = True) -> pd.DataFrame:
    key = panel_m.set_index(["day", "hm", "side"]).sort_index()
    out = []
    for tr in trig.itertuples(index=False):
        try:
            c = key.loc[(tr.day, tr.hm, tr.side)].reset_index()
        except KeyError:
            continue
        c = c[(c["day_atr"] >= 0.5) & (c["vwap_dist"] > 0)]
        if need_quiet:
            c = c[(c["tight6"] <= 0.35) & (c["hod_dist"] <= 0.3)]
        if c.empty:
            continue
        c = c.sort_values(["sec_day", "rel"], ascending=False).head(k)
        out.append(c.assign(day=tr.day, hm=tr.hm, side=tr.side))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def sim(bars: dict, p: pd.DataFrame, tp: float, sl: float, lim: int) -> pd.Series:
    res = []
    cache = {}
    for r in p.itertuples(index=False):
        if r.sym not in cache:
            x = bars[r.sym]
            cache[r.sym] = x[~x.index.duplicated()].sort_index()
        x = cache[r.sym]
        d = x[x.index.normalize() == r.day]
        hm = d.index.strftime("%H:%M")
        i = np.flatnonzero(hm == r.hm)
        if not len(i) or i[0] + 1 >= len(d):
            res.append(np.nan)
            continue
        post = d.iloc[i[0] + 1:]
        e = post["Open"].iloc[0]
        A = r.atr_pct / 100 * e
        stop, tgt = e - r.side * sl * A, e + r.side * tp * A
        out = None
        end = post.index[0] + pd.Timedelta(minutes=lim)
        last = e
        for ts, b in post.iterrows():
            if ts >= end or ts.strftime("%H:%M") >= "15:20":
                out = b["Open"]
                break
            if (r.side > 0 and b["Low"] <= stop) or (r.side < 0 and b["High"] >= stop):
                out = stop
                break
            if (r.side > 0 and b["High"] >= tgt) or (r.side < 0 and b["Low"] <= tgt):
                out = tgt
                break
            last = b["Close"]
        if out is None:
            out = last
        res.append(r.side * (out / e - 1) * 100 - 0.12)
    return pd.Series(res, index=p.index)


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    pm = mirrored(pd.read_parquet(sys.argv[2]))
    pm = pm[np.isfinite(pm["atr_pct"])]
    days = sorted(pm["day"].unique())[14:]               # ATR / volume history ready
    pm = pm[pm["day"].isin(days)]
    half = days[len(days) // 2]
    for look in (12, 6):  # 60 and 30 minutes
        trig = nifty_triggers(ix["NIFTY"], look)
        trig = trig[trig["day"].isin(days)]
        for s in (1, -1):
            t = trig[trig["side"] == s]
            print(f"\nNifty {'UP' if s > 0 else 'DOWN'} breakout of last {look * 5} min (11:00-14:00): {len(t)} days of {len(days)}; "
                  f"Nifty itself 60m {t.n_ret_60.mean():+.3f}% 120m {t.n_ret_120.mean():+.3f}% close {t.n_ret_999.mean():+.3f}%")
            for quiet in (True, False):
                p = picks(pm, t, 3, quiet)
                if p.empty:
                    continue
                for tp, sl, lim in ((0.75, 0.3, 60), (1.0, 0.4, 120), (1.5, 0.5, 999), (9, 0.5, 999), (9, 9, 60), (9, 9, 120), (9, 9, 999)):
                    r = sim(bars, p, tp, sl, lim)
                    a, b = r[p["day"] < half].mean(), r[p["day"] >= half].mean()
                    lab = f"tp {tp} sl {sl} {lim if lim < 999 else 'close'}" if tp < 9 or sl < 9 else f"no stop, hold {lim if lim < 999 else 'close'}"
                    print(f"  {'quiet leaders' if quiet else 'any leaders  '} {lab:22s} n={len(r):3d} avg {r.mean():+.3f}% "
                          f"halves {a:+.3f}/{b:+.3f} win {(r > 0).mean() * 100:.0f}%")
