"""Two more popular YouTube styles, coded in their usual textbook form and tested after costs.

C. Liquidity sweep reversal (the "sweep" / SMC style). 5-minute candles. A candle's wick goes beyond the latest swing
   high (or low) or yesterday's high (or low) - where stops sit - but the candle CLOSES back inside: trade the other
   way at that close. Stop just past the wick (+ a small buffer), target 2x risk, out at 15:15 (Indian markets).
   Variants: swing levels only, yesterday's levels only, and needing a 1.5x average-range sweep candle.
   Data: Nifty and Bank Nifty 5-minute Dec 2021 - Oct 2026; 206 F&O stocks 5-minute last 1 year;
   Nifty / Bank Nifty 1-minute last 1 year (swing levels).
D. London-session continuation on gold (the forex / gold style). Gold (PAXG, tracks XAU) 5-minute, Binance,
   last 2 years. Asian range = 00:00-07:00 UTC high / low. 07:00-10:00 UTC: first 5-min close beyond it -> trade
   that way; stop at the range middle; target 2x risk; out at 16:00 UTC. Also the opposite (fade the first break).
   Cost: 0.5 $ a round trip (XAUUSD spread + fees).

Usage (Omnipuls folder): .venv\\Scripts\\python research\\sweep_london.py
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
from jha_orderblock import COST, manage, naive, summary, swings  # noqa: E402

pd.set_option("display.width", 250)


def sweeps(df: pd.DataFrame, name: str, kind: str, levels="both", big=False, rr=2.0, buf_frac=0.1) -> list[dict]:
    rows = []
    df = naive(df)
    days = df.index.normalize()
    prev = None
    for d in days.unique():
        g = df[days == d]
        if len(g) < 40:
            prev = g
            continue
        pdh, pdl = (prev["High"].max(), prev["Low"].min()) if prev is not None and len(prev) else (np.nan, np.nan)
        prev = g
        O, H, L, C = (g[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
        hm = g.index.strftime("%H:%M").to_numpy()
        rng = H - L
        avg = pd.Series(rng).shift(1).rolling(20, min_periods=6).mean().to_numpy()
        sh, sl = swings(H, L)
        free = 0
        taken = set()
        for k in range(3, len(C)):
            if hm[k] > "14:30":
                break
            if k < free:
                continue
            for side in (1, -1):  # side = trade direction; a sell after a high is swept
                lv = []
                if levels in ("both", "swing"):
                    s = [j for j in np.flatnonzero(sl if side > 0 else sh) if j + 2 < k]
                    if s:
                        lv.append(("swing", L[s[-1]] if side > 0 else H[s[-1]]))
                if levels in ("both", "pd") and np.isfinite(pdh):
                    lv.append(("pd", pdl if side > 0 else pdh))
                for lname, lvl in lv:
                    if (side, lname, round(lvl, 2)) in taken:
                        continue
                    swept = (L[k] < lvl and C[k] > lvl) if side > 0 else (H[k] > lvl and C[k] < lvl)
                    if not swept or (big and not (np.isfinite(avg[k]) and rng[k] >= 1.5 * avg[k])):
                        continue
                    # the level must not have been broken already earlier today (a fresh sweep)
                    if side > 0 and np.nanmin(L[:k]) < lvl or side < 0 and np.nanmax(H[:k]) > lvl:
                        continue
                    taken.add((side, lname, round(lvl, 2)))
                    e = C[k]
                    wick = L[k] if side > 0 else H[k]
                    stop = wick - side * buf_frac * (avg[k] if np.isfinite(avg[k]) else rng[k])
                    risk = side * (e - stop)
                    if risk <= 0:
                        continue
                    tg = e + side * rr * risk
                    px, how = manage(H, L, C, hm, k, side, e, stop, tg)
                    unit, c = COST[kind]
                    cost = c if unit == "pts" else e * c / 100
                    pts = side * (px - e) - cost
                    rows.append({"method": f"sweep {levels}{' big' if big else ''}", "market": name, "kind": kind,
                                 "date": d, "side": side, "time": hm[k], "level": lname, "entry": e, "risk": risk,
                                 "how": how, "pts": pts, "pct": 100 * pts / e, "R": pts / risk})
                    free = k + 1
                    break
    return rows


def london(px: pd.DataFrame, fade=False, rr=2.0, cost=0.5) -> pd.DataFrame:
    rows = []
    days = px.index.normalize()
    for d in days.unique():
        g = px[days == d]
        hm = g.index.strftime("%H:%M").to_numpy()
        asia = g[hm < "07:00"]
        if len(asia) < 70:
            continue
        hi, lo = asia["High"].max(), asia["Low"].min()
        mid = (hi + lo) / 2
        O, H, L, C = (g[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
        for k in np.flatnonzero((hm >= "07:00") & (hm < "10:00")):
            br = 1 if C[k] > hi else -1 if C[k] < lo else 0
            if not br:
                continue
            side = -br if fade else br
            e = C[k]
            stop = mid if not fade else (np.max(H[:k + 1]) + 0.5 if side < 0 else np.min(L[:k + 1]) - 0.5)
            risk = side * (e - stop)
            if risk <= 0:
                break
            tg = e + side * rr * risk
            p, how = manage(H, L, C, hm, k, side, e, stop, tg, out="15:55")
            pts = side * (p - e) - cost
            rows.append({"method": "London fade" if fade else "London continuation", "market": "GOLD", "kind": "GOLD",
                         "date": d, "side": side, "time": hm[k], "entry": e, "risk": risk, "how": how, "pts": pts,
                         "pct": 100 * pts / e, "R": pts / risk})
            break
    return pd.DataFrame(rows)


def main():
    out = []
    idx5 = {}
    for name, sid in (("NIFTY", 13), ("BANKNIFTY", 25)):
        idx5[name] = pickle.loads(open(sorted(glob.glob(str(HERE / "cache" / f"IDX_I_{sid}_5_1800_*.pkl")))[-1], "rb").read())
    from bigbars_dhan import load_cache
    _, raw = load_cache()
    raw = {s: naive(d) for s, d in raw.items()}
    raw = {s: d[d.index >= d.index.max() - pd.Timedelta(days=365)] for s, d in raw.items()}
    for v in (dict(levels="both"), dict(levels="swing"), dict(levels="pd"), dict(levels="both", big=True)):
        rows = []
        for name, d in idx5.items():
            rows += sweeps(d, name, name, **v)
        for s, d in raw.items():
            rows += sweeps(d, "F&O stocks (1 year)", "STOCK", **v)
        T = pd.DataFrame(rows)
        summary(T, f"=== C. Liquidity sweep reversal, 5-min, {v}")
        for name, X in T.groupby("market"):
            y = X.groupby(pd.to_datetime(X["date"]).dt.year)["R"].mean().round(2)
            print(f"  {name} avg R by year: {y.to_dict()}")
        out.append(T)
    rows = []
    for name, sid in (("NIFTY (1-min)", 13), ("BANKNIFTY (1-min)", 25)):
        d1 = pickle.loads((HERE / "cache" / f"y1m_IDX_{sid}.pkl").read_bytes())
        rows += sweeps(d1, name, name.split()[0], levels="swing")
    T = pd.DataFrame(rows)
    summary(T, "=== C. Liquidity sweep reversal, 1-min, swing levels")
    out.append(T)
    gold = pickle.loads((HERE / "cache" / "binance_PAXGUSDT_5m_730.pkl").read_bytes())
    for fade in (False, True):
        T = london(gold, fade=fade)
        summary(T, f"=== D. Gold London {'fade' if fade else 'continuation'}, 2R (pts = $)")
        out.append(T)
    pd.concat(out).to_csv(HERE / "results" / "sweep_london.csv", index=False)


if __name__ == "__main__":
    main()
