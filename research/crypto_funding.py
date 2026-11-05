"""Fade the crowd: crypto funding-rate extremes (Binance USD-M perpetuals, 8-hour funding, 2023-2026).

Funding = what the crowded side pays every 8 hours. When it is extreme vs its own recent past (top / bottom 5% of the
last 90 days), take the other side at the next 5-minute open after the funding time; hold 24 h / 72 h, stop 1.5 ATR
(14-day daily). Also the "follow the crowd" side for comparison. Costs 0.10% round trip (taker both ways, plus
the funding the position pays or earns over the hold is NOT included - it favours the fader).
Usage: python research/crypto_funding.py <scratch dir with funding/*.zip, btc5m.pkl, ETHUSDT/, SOLUSDT/>
"""
from __future__ import annotations

import glob
import pickle
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crypto_footprint import load_zip_dir  # noqa: E402

COST = 0.10


def funding(d: str, sym: str) -> pd.Series:
    parts = []
    for f in sorted(glob.glob(f"{d}/funding/{sym}USDT-fundingRate-*.zip")):
        with zipfile.ZipFile(f) as z:
            with z.open(z.namelist()[0]) as fh:
                x = pd.read_csv(fh)
        x.columns = [c.strip().lower() for c in x.columns]
        tcol = next(c for c in x.columns if "time" in c)
        rcol = next(c for c in x.columns if "rate" in c and "interval" not in c)
        parts.append(pd.Series(pd.to_numeric(x[rcol]).values, index=pd.to_datetime(pd.to_numeric(x[tcol]), unit="ms")))
    s = pd.concat(parts).sort_index()
    return s[~s.index.duplicated()]


def test(px: pd.DataFrame, fr: pd.Series, sym: str, q: float = 0.05, hold_h: int = 24, mode: str = "fade") -> pd.DataFrame:
    px = px.copy()
    if px.index.tz is not None:
        px.index = px.index.tz_convert("UTC").tz_localize(None)
    day = px.resample("1D").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()
    pc = day["Close"].shift()
    atr = pd.concat([day["High"] - day["Low"], (day["High"] - pc).abs(), (day["Low"] - pc).abs()], axis=1).max(axis=1).rolling(14).mean().shift()
    hi = fr.rolling(270, min_periods=90).quantile(1 - q).shift()       # 90 days of 8-hour fundings
    lo = fr.rolling(270, min_periods=90).quantile(q).shift()
    rows, busy_until = [], pd.Timestamp(0)
    o, h, l, c = (px[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx = px.index
    for t, r in fr.items():
        if t < busy_until or not np.isfinite(hi.get(t, np.nan)):
            continue
        crowd = 1 if r >= hi[t] and r > 0 else (-1 if r <= lo[t] and r < 0 else 0)
        if not crowd:
            continue
        side = -crowd if mode == "fade" else crowd
        i = idx.searchsorted(t)
        n = hold_h * 12
        if i + n >= len(idx):
            continue
        A = atr.asof(t)
        if not (A and np.isfinite(A)):
            continue
        e = o[i]
        stop = e - side * 1.5 * A
        res = None
        for j in range(i, i + n):
            if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
                res = -1.5 * A / e * 100
                break
        if res is None:
            res = side * (c[i + n - 1] / e - 1) * 100
        rows.append({"t": t, "sym": sym, "side": side, "funding": r, "ret": res - COST})
        busy_until = idx[i + n - 1]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    S = sys.argv[1]
    px = {"BTC": pickle.load(open(f"{S}/btc5m.pkl", "rb")), "ETH": load_zip_dir(f"{S}/ETHUSDT"), "SOL": load_zip_dir(f"{S}/SOLUSDT")}
    for mode in ("fade", "follow"):
        for hold in (24, 72):
            allr = []
            for k, x in px.items():
                allr.append(test(x, funding(S, k), k, 0.05, hold, mode))
            t = pd.concat(allr)
            end = t["t"].max()
            yrs = " ".join(f"{y}:{t[t.t.dt.year == y].ret.mean():+.2f}" for y in sorted(t.t.dt.year.unique()))
            l12 = t[t.t >= end - pd.DateOffset(months=12)]
            l6 = t[t.t >= end - pd.DateOffset(months=6)]
            print(f"{mode:6s} hold {hold:2d}h: n={len(t):3d} avg {t.ret.mean():+.3f}% win {(t.ret > 0).mean() * 100:.0f}% | {yrs} | "
                  f"12m {l12.ret.mean():+.3f}% (n {len(l12)}) 6m {l6.ret.mean():+.3f}% (n {len(l6)}) | "
                  f"crowd long (we short) {t[t.side < 0].ret.mean() if mode == 'fade' else t[t.side > 0].ret.mean():+.3f}% "
                  f"crowd short {t[t.side > 0].ret.mean() if mode == 'fade' else t[t.side < 0].ret.mean():+.3f}% | "
                  + " ".join(f"{s}:{t[t.sym == s].ret.mean():+.2f}" for s in px))
