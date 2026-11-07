"""ADX inside the Super Bot: do its candidates (market-aligned) and its 3-window picks do better when the stock's ADX is
high / rising with the trade's DI? ADX(14) on 5-minute candles at the signal, and on daily candles (yesterday's value).
Each skipped pick is replaced by the next best, as live. 40 days.

Usage: python research/superbot_adx.py <fno60_new.pkl> <superbot_candidates.pkl>
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import superbot_backtest as BT   # noqa: E402
import superbot_strict as X      # noqa: E402
import superbot_windows as W     # noqa: E402

WINDOWS = [("10:00", "10:30", 2), ("11:00", "12:00", 2), ("12:00", "12:30", 2)]


def adx_frame(d):
    c, h, l = d["Close"], d["High"], d["Low"]
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    w = lambda x: x.ewm(alpha=1 / 14, adjust=False).mean()  # noqa: E731
    atr = w(tr)
    up, dn = h.diff(), -l.diff()
    pdi = 100 * w(pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=d.index)) / atr
    mdi = 100 * w(pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=d.index)) / atr
    adx = w((100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).fillna(0))
    return pd.DataFrame({"adx": adx, "pdi": pdi, "mdi": mdi, "rising": adx > adx.shift(3)})


def main(argv):
    st, _ = pickle.load(open(argv[1], "rb"))
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in st.items()}
    c = pd.read_pickle(argv[2])
    c = c[c.apply(X.RULES["with the market"], axis=1)].dropna(subset=["entry"]).reset_index(drop=True)
    A5, AD = {}, {}
    for s, b in bars.items():
        A5[s] = adx_frame(b)
        dd = b.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        AD[s] = adx_frame(dd).shift(1)
    f = []
    for _, r in c.iterrows():
        t = r["day"] + pd.Timedelta(hours=int(r["time"][:2]), minutes=int(r["time"][3:]))
        a = A5[r["stock"]]
        a = a[a.index < t]
        d = AD[r["stock"]]
        d = d[d.index <= r["day"]]
        sd = r["side"]
        f.append({"adx5": a["adx"].iloc[-1] if len(a) else np.nan,
                  "di5_ok": bool(len(a) and ((a["pdi"].iloc[-1] > a["mdi"].iloc[-1]) == (sd > 0))),
                  "rise5": bool(len(a) and a["rising"].iloc[-1]),
                  "adxd": d["adx"].iloc[-1] if len(d) else np.nan,
                  "did_ok": bool(len(d) and ((d["pdi"].iloc[-1] > d["mdi"].iloc[-1]) == (sd > 0)))})
    c = pd.concat([c, pd.DataFrame(f)], axis=1)
    nd = c["day"].nunique()

    def line(name, t):
        p = t["pct"]
        if len(p) < 10:
            return f"  {name:52s} n={len(p)}"
        pf = p[p > 0].sum() / -p[p < 0].sum()
        mid = sorted(t["day"].unique())[t["day"].nunique() // 2]
        return (f"  {name:52s} n={len(p):4d} win {(p > 0).mean() * 100:3.0f}% PF {pf:.2f} avg {p.mean():+.3f}% "
                f"t {p.mean() / p.std() * np.sqrt(len(p)):+.2f} halves {p[t['day'] < mid].mean():+.2f} / {p[t['day'] >= mid].mean():+.2f}")
    print("ALL market-aligned candidates, by 5-minute ADX at the signal:")
    for k, z in c.groupby(pd.cut(c["adx5"], [0, 20, 25, 30, 40, 100]), observed=True):
        print(line(f"5m ADX {k}", z))
    print(line("5m ADX >= 25 + rising + DI with the trade", c[(c.adx5 >= 25) & c.rise5 & c.di5_ok]))
    print(line("5m DI against the trade", c[~c.di5_ok]))
    print("by DAILY ADX (yesterday):")
    for k, z in c.groupby(pd.cut(c["adxd"], [0, 20, 25, 30, 40, 100]), observed=True):
        print(line(f"daily ADX {k}", z))
    print(line("daily DI with the trade", c[c.did_ok]))
    print(line("daily DI against the trade", c[~c.did_ok]))
    print("\n3-WINDOW PLAN with ADX filters (replaced by the next best):")
    for name, m in (("as is", slice(None)), ("5m ADX >= 25", c.adx5 >= 25), ("5m ADX >= 20", c.adx5 >= 20),
                    ("5m DI with the trade", c.di5_ok), ("5m ADX >= 25 rising + DI", (c.adx5 >= 25) & c.rise5 & c.di5_ok),
                    ("daily ADX >= 20", c.adxd >= 20), ("daily DI with the trade", c.did_ok),
                    ("daily ADX >= 20 + DI with the trade", (c.adxd >= 20) & c.did_ok)):
        t = W.run(c[m] if not isinstance(m, slice) else c, bars, WINDOWS)
        print(line(name, t) + f" | {len(t) / nd:.1f}/day, worst day {t.groupby('day')['pct'].sum().min():+.1f}%")


if __name__ == "__main__":
    main(sys.argv)
