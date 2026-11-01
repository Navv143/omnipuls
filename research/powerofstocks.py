"""Power of Stocks (Subasish Pani) setups, coded as they are commonly described, tested after costs.

E. 5 EMA. SELL on 5-minute candles: an "alert candle" sits fully ABOVE the 5 EMA (its low above the EMA); if the
   next candle breaks the alert candle's low -> sell there; stop at the alert candle's high; target 3x the risk.
   If the next candle does not break it and is itself fully above the EMA, it becomes the new alert candle.
   BUY on 15-minute candles: the mirror (alert candle fully below the 5 EMA, buy above its high).
   Variants: target 1:2; both sides on 5-min; both sides on 15-min. Out at 15:15; one trade at a time.
F. Traffic light. The first pair of back-to-back opposite-colour candles (green-red or red-green), ignoring the 9:15
   candle on 1-minute charts; a later candle CLOSING above the pair's high -> buy, below its low -> sell, at that
   close; stop at the other side of the pair; target 2x risk; at most 3 trades a day; out at 15:20; pairs wider than
   100 Nifty points (250 Bank Nifty, 2% stocks) skipped. On 1, 5 and 15-minute candles.
Data: Nifty and Bank Nifty 1-minute Oct 2025 - Oct 2026 (made into 5 and 15-minute too) and 5-minute Dec 2021 -
Oct 2026; 206 F&O stocks 5-minute (and 15-minute) last 1 year. Costs: Nifty 2 pts, Bank Nifty 5, stocks 0.06%.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\powerofstocks.py
"""
from __future__ import annotations

import glob
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from jha_orderblock import COST, manage, naive, summary  # noqa: E402

MAXW = {"NIFTY": ("pts", 100), "BANKNIFTY": ("pts", 250), "STOCK": ("pct", 2.0)}


def bars(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    df = naive(df)
    if tf == 1:
        return df
    b = df.resample(f"{tf}min", origin="start_day", offset="15min").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])
    t = b.index.strftime("%H:%M")
    return b[(t >= "09:15") & (t <= "15:29")]


def _cost(kind, e):
    unit, c = COST[kind]
    return c if unit == "pts" else e * c / 100


def ema5(df: pd.DataFrame, tf: int, name: str, kind: str, sides=(1, -1), rr=3.0) -> list[dict]:
    b = bars(df, tf)
    E = b["Close"].ewm(span=5, adjust=False).mean().to_numpy()
    rows = []
    days = b.index.normalize()
    pos = 0
    for d in days.unique():
        m = (days == d)
        idx = np.flatnonzero(m)
        O, H, L, C = (b[c].to_numpy(float)[idx] for c in ("Open", "High", "Low", "Close"))
        e5 = E[idx]
        hm = b.index[idx].strftime("%H:%M").to_numpy()
        free = 0
        for k in range(1, len(C)):
            if hm[k] > "14:45" or k < free:
                continue
            a = k - 1  # alert candle
            for side in sides:
                alert = (L[a] > e5[a]) if side < 0 else (H[a] < e5[a])
                if not alert:
                    continue
                trig = L[a] if side < 0 else H[a]
                if not ((side < 0 and L[k] < trig) or (side > 0 and H[k] > trig)):
                    continue
                e = min(trig, O[k]) if side < 0 else max(trig, O[k])
                stop = H[a] if side < 0 else L[a]
                risk = side * (e - stop)
                if risk <= 0:
                    continue
                tg = e + side * rr * risk
                if (side > 0 and L[k] <= stop) or (side < 0 and H[k] >= stop):
                    px, how, j_end = stop, "stop", k
                else:
                    px, how = manage(H, L, C, hm, k, side, e, stop, tg)
                    j_end = next((j for j in range(k + 1, len(C)) if (side > 0 and (L[j] <= stop or H[j] >= tg)) or
                                  (side < 0 and (H[j] >= stop or L[j] <= tg)) or hm[j] >= "15:14"), len(C) - 1)
                pts = side * (px - e) - _cost(kind, e)
                rows.append({"method": f"5 EMA {tf}m", "market": name, "kind": kind, "date": d, "side": side,
                             "time": hm[k], "entry": e, "risk": risk, "how": how, "pts": pts, "pct": 100 * pts / e,
                             "R": pts / risk})
                free = j_end + 1
                break
    return rows


def traffic(df: pd.DataFrame, tf: int, name: str, kind: str, rr=2.0) -> list[dict]:
    b = bars(df, tf)
    rows = []
    days = b.index.normalize()
    unit, mx = MAXW[kind]
    for d in days.unique():
        g = b[days == d]
        O, H, L, C = (g[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
        hm = g.index.strftime("%H:%M").to_numpy()
        start = 1 if tf == 1 else 0
        trades, k0 = 0, start
        while trades < 3:
            pair = None
            for j in range(k0 + 1, len(C)):
                if hm[j] > "14:45":
                    break
                if np.sign(C[j] - O[j]) * np.sign(C[j - 1] - O[j - 1]) < 0:
                    pair = j
                    break
            if pair is None:
                break
            hi, lo = max(H[pair], H[pair - 1]), min(L[pair], L[pair - 1])
            width = hi - lo if unit == "pts" else 100 * (hi - lo) / C[pair]
            ent = None
            for k in range(pair + 1, len(C)):
                if hm[k] > "14:45":
                    break
                if C[k] > hi or C[k] < lo:
                    ent = k
                    break
            if ent is None:
                break
            if width > mx:
                k0 = ent
                continue
            side = 1 if C[ent] > hi else -1
            e = C[ent]
            stop = lo if side > 0 else hi
            risk = side * (e - stop)
            tg = e + side * rr * risk
            px, how = manage(H, L, C, hm, ent, side, e, stop, tg, out="15:19")
            j_end = next((j for j in range(ent + 1, len(C)) if (side > 0 and (L[j] <= stop or H[j] >= tg)) or
                          (side < 0 and (H[j] >= stop or L[j] <= tg)) or hm[j] >= "15:19"), len(C) - 1)
            pts = side * (px - e) - _cost(kind, e)
            rows.append({"method": f"Traffic light {tf}m", "market": name, "kind": kind, "date": d, "side": side,
                         "time": hm[ent], "entry": e, "risk": risk, "how": how, "pts": pts, "pct": 100 * pts / e,
                         "R": pts / risk})
            trades += 1
            k0 = j_end
    return rows


def main():
    n1 = pickle.loads((HERE / "cache" / "y1m_IDX_13.pkl").read_bytes())
    b1 = pickle.loads((HERE / "cache" / "y1m_IDX_25.pkl").read_bytes())
    idx5 = {name: pickle.loads(open(sorted(glob.glob(str(HERE / "cache" / f"IDX_I_{sid}_5_1800_*.pkl")))[-1], "rb").read())
            for name, sid in (("NIFTY", 13), ("BANKNIFTY", 25))}
    from bigbars_dhan import load_cache
    _, raw = load_cache()
    raw = {s: naive(d) for s, d in raw.items()}
    raw = {s: d[d.index >= d.index.max() - pd.Timedelta(days=365)] for s, d in raw.items()}
    out = []

    def run(label, fn):
        T = pd.DataFrame(fn())
        summary(T, label)
        if not T.empty:
            for name, X in T.groupby("market"):
                y = X.groupby(pd.to_datetime(X["date"]).dt.year)["R"].mean().round(2)
                if len(y) > 2:
                    print(f"  {name} avg R by year: {y.to_dict()}")
        out.append(T.assign(test=label))

    run("=== E. 5 EMA as taught: SELL 5-min, BUY 15-min, 1:3 (index 5 years, stocks 1 year)", lambda: sum(
        [ema5(d, 5, n, n, sides=(-1,)) + ema5(d, 15, n, n, sides=(1,)) for n, d in idx5.items()], []) + sum(
        [ema5(d, 5, "F&O stocks", "STOCK", sides=(-1,)) + ema5(d, 15, "F&O stocks", "STOCK", sides=(1,))
         for d in raw.values()], []))
    run("=== E. 5 EMA, both sides 5-min, 1:2", lambda: sum(
        [ema5(d, 5, n, n, rr=2.0) for n, d in idx5.items()], []) + sum(
        [ema5(d, 5, "F&O stocks", "STOCK", rr=2.0) for d in raw.values()], []))
    run("=== E. 5 EMA, both sides 15-min, 1:3", lambda: sum(
        [ema5(d, 15, n, n) for n, d in idx5.items()], []) + sum(
        [ema5(d, 15, "F&O stocks", "STOCK") for d in raw.values()], []))
    run("=== E. 5 EMA as taught on 1-year 1-minute index data made into 5 / 15-min", lambda:
        ema5(n1, 5, "NIFTY", "NIFTY", sides=(-1,)) + ema5(n1, 15, "NIFTY", "NIFTY", sides=(1,)) +
        ema5(b1, 5, "BANKNIFTY", "BANKNIFTY", sides=(-1,)) + ema5(b1, 15, "BANKNIFTY", "BANKNIFTY", sides=(1,)))
    run("=== F. Traffic light, 1-min (index, last 1 year)", lambda:
        traffic(n1, 1, "NIFTY", "NIFTY") + traffic(b1, 1, "BANKNIFTY", "BANKNIFTY"))
    run("=== F. Traffic light, 5-min (index 5 years, stocks 1 year)", lambda: sum(
        [traffic(d, 5, n, n) for n, d in idx5.items()], []) + sum(
        [traffic(d, 5, "F&O stocks", "STOCK") for d in raw.values()], []))
    run("=== F. Traffic light, 15-min (index 5 years, stocks 1 year)", lambda: sum(
        [traffic(d, 15, n, n) for n, d in idx5.items()], []) + sum(
        [traffic(d, 15, "F&O stocks", "STOCK") for d in raw.values()], []))
    pd.concat(out).to_csv(HERE / "results" / "powerofstocks.csv", index=False)


if __name__ == "__main__":
    main()
