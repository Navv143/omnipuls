"""Big-player footprints on crypto around the session opens (the stock finding from candle_study.py, tried on BTC / ETH
/ SOL 5-minute Binance candles).

Sessions (UTC): Asia 00:00, London 07:00, New York 13:30. At open + 45 minutes, in the direction of the move since the
session opened ("its way"), count the footprints on the candles since the open:
  trap_first    first went >= 0.2 ATR the other way beyond the session open, then reversed past it
  absorption    a >= 2x-usual-volume candle with a small body (< 30% of range) the other way that did not give way
  strong_closes average close location >= 0.65 (<= 0.35 for down)
  vol_with      >= 65% of the volume on candles going its way
  wick_reject   rejection wicks the other way >= 1.5x the wicks its way
Enter at the next candle's open, hold 6 hours (or stop 1 ATR), costs 0.05% (also shown at 0.10%). ATR = 14-day daily.
Results by year, last 12 and 6 months (current conditions count most).
Usage: python research/crypto_footprint.py <scratch dir with btc5m.pkl, ETHUSDT/, SOLUSDT/>
"""
from __future__ import annotations

import glob
import pickle
import sys
import zipfile

import numpy as np
import pandas as pd

SESSIONS = {"Asia": "00:00", "London": "07:00", "New York": "13:30"}
FP = ["trap_first", "absorption", "strong_closes", "vol_with", "wick_reject"]


def load_zip_dir(d: str) -> pd.DataFrame:
    parts = []
    for f in sorted(glob.glob(f"{d}/*.zip")):
        with zipfile.ZipFile(f) as z:
            with z.open(z.namelist()[0]) as fh:
                x = pd.read_csv(fh, header=None, usecols=range(6))
        if not str(x.iloc[0, 0]).isdigit():
            x = x.iloc[1:]
        x.columns = ["t", "Open", "High", "Low", "Close", "Volume"]
        t = pd.to_numeric(x["t"])
        unit = "us" if t.iloc[0] > 1e14 else "ms"
        x.index = pd.to_datetime(t, unit=unit, utc=True)
        parts.append(x[["Open", "High", "Low", "Close", "Volume"]].astype(float))
    return pd.concat(parts).sort_index().loc[lambda d: ~d.index.duplicated()]


def rows_for(sym: str, x: pd.DataFrame, wait: int = 9, hold: int = 72) -> list[dict]:
    x = x.copy()
    x.index = x.index.tz_convert("UTC").tz_localize(None)
    day = x.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    pc = day["Close"].shift()
    tr = pd.concat([day["High"] - day["Low"], (day["High"] - pc).abs(), (day["Low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift()
    hm = x.index.strftime("%H:%M")
    slot = x["Volume"].groupby([x.index.normalize(), hm]).last().unstack().rolling(20, min_periods=10).mean().shift()
    o, h, l, c, v = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "Volume"))
    pos = {t: i for i, t in enumerate(x.index)}
    out = []
    for d0 in day.index[20:]:
        A = atr.get(d0)
        if not (A and np.isfinite(A) and A > 0):
            continue
        for sess, t in SESSIONS.items():
            ts = d0 + pd.Timedelta(hours=int(t[:2]), minutes=int(t[3:]))
            i0 = pos.get(ts)
            if i0 is None or i0 + wait + hold >= len(x):
                continue
            seg = slice(i0, i0 + wait)
            hh, ll, cc, oo, vv = h[seg], l[seg], c[seg], o[seg], v[seg]
            O = oo[0]
            ci = cc[-1]
            mv = (ci - O) / A
            sd = 1 if mv >= 0 else -1
            rng = np.maximum(hh - ll, 1e-12)
            body = cc - oo
            up_w, lo_w = hh - np.maximum(oo, cc), np.minimum(oo, cc) - ll
            clv = (cc - ll) / rng
            sl = slot.loc[d0].reindex(hm[seg]).to_numpy() if d0 in slot.index else np.full(wait, np.nan)
            if sd > 0:
                trap = ll.min() <= O - 0.2 * A and ci > O
                absorb = any(vv[j] >= 2 * sl[j] and abs(body[j]) < 0.3 * rng[j] and lo_w[j] > up_w[j] for j in range(wait) if np.isfinite(sl[j]))
                wick = lo_w.sum() >= 1.5 * max(up_w.sum(), 1e-12)
                strong = clv.mean() >= 0.65
            else:
                trap = hh.max() >= O + 0.2 * A and ci < O
                absorb = any(vv[j] >= 2 * sl[j] and abs(body[j]) < 0.3 * rng[j] and up_w[j] > lo_w[j] for j in range(wait) if np.isfinite(sl[j]))
                wick = up_w.sum() >= 1.5 * max(lo_w.sum(), 1e-12)
                strong = clv.mean() <= 0.35
            vol_with = vv[np.sign(body) == sd].sum() / max(vv.sum(), 1e-12) >= 0.65
            e = o[i0 + wait]
            stop = e - sd * A
            res = None
            for j in range(i0 + wait, i0 + wait + hold):
                if (sd > 0 and l[j] <= stop) or (sd < 0 and h[j] >= stop):
                    res = -A / e * 100
                    break
            if res is None:
                res = sd * (c[i0 + wait + hold - 1] / e - 1) * 100
            out.append({"day": d0, "sym": sym, "session": sess, "sd": sd, "mv": mv, "ret": res, "trap_first": trap,
                        "absorption": absorb, "strong_closes": strong, "vol_with": vol_with, "wick_reject": wick})
    return out


if __name__ == "__main__":
    S = sys.argv[1]
    data = {"BTC": pickle.load(open(f"{S}/btc5m.pkl", "rb")), "ETH": load_zip_dir(f"{S}/ETHUSDT"),
            "SOL": load_zip_dir(f"{S}/SOLUSDT")}
    rows = []
    for k, x in data.items():
        rows += rows_for(k, x)
    t = pd.DataFrame(rows)
    t["fp"] = t[FP].sum(axis=1)
    end = t["day"].max()
    t.to_parquet(f"{S}/crypto_fp.parquet")
    print(f"{len(t)} session signals, {t.day.min():%Y-%m} to {end:%Y-%m}")
    for cost in (0.05, 0.10):
        print(f"\n== cost {cost:.2f}% ==")
        for k in (0, 3, 4, 5):
            q = t[t["fp"] >= k]
            r = q["ret"] - cost
            yrs = " ".join(f"{y}:{r[q.day.dt.year == y].mean():+.3f}" for y in sorted(q.day.dt.year.unique()))
            l12, l6 = r[q.day >= end - pd.DateOffset(months=12)], r[q.day >= end - pd.DateOffset(months=6)]
            print(f"  footprints >= {k}: n={len(q):5d} avg {r.mean():+.3f}% win {(r > 0).mean() * 100:.0f}% | {yrs} | "
                  f"last 12m {l12.mean():+.3f}% (n {len(l12)}) last 6m {l6.mean():+.3f}% (n {len(l6)})")
        for sess in SESSIONS:
            for sym in ("BTC", "ETH", "SOL"):
                q = t[(t["fp"] >= 4) & (t["session"] == sess) & (t["sym"] == sym)]
                r = q["ret"] - cost
                l6 = r[q.day >= end - pd.DateOffset(months=6)]
                print(f"    fp>=4 {sess:8s} {sym}: n={len(q):4d} avg {r.mean():+.3f}% win {(r > 0).mean() * 100:.0f}% last 6m {l6.mean():+.3f}% (n {len(l6)})")
