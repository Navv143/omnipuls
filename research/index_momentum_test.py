"""Index momentum vs trap (5-minute): every candle, over the last 15 minutes, is the index moving AND its stocks' net
money rising AND breadth (vs yesterday) rising AND ATR rising? -> trade with it. Price moving while money and breadth go
the other way -> 'trap' (stop hunt): test fading it. Entry next candle's open, funnel.trade_plan stop / targets, 15:15.
Usage: python research/index_momentum_test.py <stocks_5m.pkl> <indices_5m.pkl>"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import funnel as FN  # noqa: E402
import index_funnel as IF  # noqa: E402
import indices as IX  # noqa: E402

K = 3  # candles in the window (15 minutes)


def table(ix, stocks, w):
    t = IF.index_table(ix, stocks, w, None)
    if t.empty:
        return t
    # breadth vs YESTERDAY's close at every candle (share of the index weight up)
    up = pd.Series(0.0, index=t.index)
    tot = 0.0
    for s, wt in w.items():
        b = IF._clean(stocks.get(s))
        if b.empty:
            continue
        bd = b.index.normalize()
        pcs = b.groupby(bd)["Close"].last().shift(1)
        ch = b["Close"] / pcs.reindex(bd).to_numpy() - 1
        up = up.add((ch.reindex(t.index) > 0).astype(float) * wt, fill_value=0)
        tot += wt
    t["br_y"] = up / tot * 100
    dd = t.groupby("day").agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    pc = dd["c"].shift(1)
    tr = pd.concat([dd["h"] - dd["l"], (dd["h"] - pc).abs(), (dd["l"] - pc).abs()], axis=1).max(axis=1)
    t["atr14"] = t["day"].map(tr.rolling(14).mean().shift(1))
    g = t.groupby("day")
    t["d_px"] = t["Close"] - g["Close"].shift(K)
    t["d_net"] = t["net"] - g["net"].shift(K)
    t["d_br"] = t["br_y"] - g["br_y"].shift(K)
    t["d_atr"] = t["now_x"] - g["now_x"].shift(K)
    t["swl"] = g["Low"].transform(lambda x: x.rolling(6, min_periods=1).min())
    t["swh"] = g["High"].transform(lambda x: x.rolling(6, min_periods=1).max())
    return t


def trades(t, mask, side, first_only=True):
    out = []
    t = t[mask.fillna(False) & (t["m"] + 5 >= 570) & (t["m"] + 5 <= 840) & t["atr14"].notna()
          & (t["day"] < T_FULL["day"].max())]  # finished days only
    busy_until = {}
    for ts, r in t.iterrows():
        day = r["day"]
        if first_only and day in busy_until:
            continue
        if not first_only and busy_until.get(day, pd.Timestamp.min) >= ts:
            continue
        s = int(side.loc[ts])
        if not s:
            continue
        bars = T_FULL[(T_FULL["day"] == day) & (T_FULL.index > ts)]
        if bars.empty:
            continue
        e = float(bars["Open"].iloc[0])
        p = FN.trade_plan(s, e, float(r["atr14"]), float(r["swl"]), float(r["swh"]))
        res = FN.simulate(s, e, p["sl"], p["tp1"], p["tp2"], bars, cost_pct=0.02)
        if not res:
            continue
        out.append({"day": day, "ts": ts, "side": s, **res})
        busy_until[day] = bars.index[-1] if first_only else ts + pd.Timedelta(minutes=60)
    return pd.DataFrame(out)


def rep(tr, label):
    if tr.empty or len(tr) < 6:
        print(f"  {label:60s} n {len(tr)}")
        return
    d = tr.groupby("day")["pct"].mean()
    days = np.sort(tr["day"].unique())
    mid = days[len(days) // 2]
    tt = lambda x: x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else 0  # noqa: E731
    print(f"  {label:60s} n {len(tr):3d} {tr['pct'].mean():+.3f}% {tr['r'].mean():+.2f}R win {(tr['pct'] > 0).mean() * 100:3.0f}% "
          f"| by day t {tt(d):+.1f} | halves {d[d.index < mid].mean():+.3f}/{d[d.index >= mid].mean():+.3f}")


if __name__ == "__main__":
    stocks = pickle.load(open(sys.argv[1], "rb"))
    ixs = pickle.load(open(sys.argv[2], "rb"))
    W = {k: IX._norm(v) for k, v in IX.BUILTIN.items()}
    allm, allt = [], []
    for k in IF.INDEXES:
        if k not in ixs:
            continue
        T = table(ixs[k], stocks, W[k])
        T_FULL = T
        pmove = T["d_px"].abs() >= 0.10 * T["atr14"]
        side = np.sign(T["d_px"].fillna(0)).astype(int)
        mom = pmove & (np.sign(T["d_net"]) == side) & (np.sign(T["d_br"]) == side) & (T["d_atr"] > 0) & (T["now_x"] >= 1.0)
        trap = pmove & (np.sign(T["d_net"]) == -side) & (np.sign(T["d_br"]) == -side)
        print(f"\n{IF.INDEXES[k]}")
        a = trades(T, mom, side); rep(a, "MOMENTUM: price + money + breadth + ATR rising (first a day)")
        b = trades(T, mom, side, first_only=False); rep(b, "MOMENTUM, every signal (1 h apart)")
        c = trades(T, trap, -side); rep(c, "TRAP: price up, money+breadth down -> fade (first a day)")
        d_ = trades(T, pmove, side); rep(d_, "baseline: any 15-min move >= 0.1 ATR (first a day)")
        allm.append(a.assign(ix=k)); allt.append(c.assign(ix=k))
    print("\nALL INDICES")
    rep(pd.concat(allm), "MOMENTUM (first a day)")
    rep(pd.concat(allt), "TRAP fade (first a day)")
