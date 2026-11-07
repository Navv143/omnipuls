"""Small fixed-point momentum trades: Nifty 25 / 30 pts, Bank Nifty 50 / 70, BTC 400 / 500, gold $6 / $7, with tight
stops (0.6x or 1.0x the target) and a time limit. Triggers fixed in advance:
  A  opening-range break (Indian: first 15 min; BTC / gold: first 30 min after 07:00 UTC London and 13:30 UTC New York)
  B  break of the previous 15-min candle's high / low, only on the VWAP side
  C  momentum burst: a candle with range >= 2x ATR(14) closing in its top / bottom 20% -> enter its direction
  D  VWAP reclaim / loss with a strong body (>= 0.5 ATR)
  E  first-hour (Indian: 9:15-10:15) low / high break, tight fixed stop
  F  EMA 9 > 21 (or <) and price pulled back to EMA 9 -> break of the pullback candle
Entry: A, B, E at the level (stop order; a gap fills at the candle's open); C, D, F at the next candle's open. Stop
checked first inside every candle (a candle that touches both counts as a loss). Time limit: Indian 60 min (and out by
15:15, entries 9:30-14:45); BTC / gold 2 hours. Costs a round trip: Nifty 3 pts, Bank Nifty 6 pts, BTC 0.05%, gold $0.5.
Max 4 trades a day per setup, one at a time.

Usage: python research/scalp_points.py <scratchpad dir>
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def prep(df):
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d = d.droplevel(1, axis=1)
    idx = pd.DatetimeIndex(d.index)
    d.index = idx if idx.tz is None else idx.tz_convert("Asia/Kolkata").tz_localize(None)
    d = d[d.index.second == 0]
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def utc_to_ist(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = (idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx) + pd.Timedelta(hours=5, minutes=30)
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def signals(d: pd.DataFrame, india: bool, tf: int) -> dict:
    """{setup: list of (bar index i, side, entry price or None=next open)} — i is the bar where the trigger happens."""
    o, h, l, c = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx = d.index
    day = idx.normalize()
    hm = idx.strftime("%H:%M")
    pc = d["Close"].shift()
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().to_numpy()
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    v = d["Volume"].fillna(0)
    g = pd.Series(day, index=idx)
    vw = ((tp * v).groupby(g).cumsum() / v.groupby(g).cumsum().replace(0, np.nan))
    vw = vw.fillna(tp.groupby(g).cumsum() / (d.groupby(g).cumcount() + 1)).to_numpy()
    e9 = d["Close"].ewm(span=9, adjust=False).mean().to_numpy()
    e21 = d["Close"].ewm(span=21, adjust=False).mean().to_numpy()
    S = {k: [] for k in "ABCDEF"}
    n = len(d)
    # per-day ranges
    starts = np.r_[0, np.nonzero(day[1:] != day[:-1])[0] + 1]
    ends = np.r_[starts[1:], n]
    for a, b in zip(starts, ends):
        dd = idx[a]
        sess = [("09:15", 15)] if india else [("12:30", 30), ("19:00", 30)]     # IST: 07:00 / 13:30 UTC
        for st, mins in sess:
            t0 = dd.normalize() + pd.Timedelta(hours=int(st[:2]), minutes=int(st[3:]))
            w = [i for i in range(a, b) if t0 <= idx[i] < t0 + pd.Timedelta(minutes=mins)]
            if len(w) < 2:
                continue
            hi, lo = h[w].max(), l[w].min()
            for i in range(w[-1] + 1, min(b, w[-1] + 1 + (180 // tf))):
                if h[i] > hi and l[i] < lo:
                    break
                if h[i] > hi:
                    S["A"].append((i, 1, max(o[i], hi)))
                    break
                if l[i] < lo:
                    S["A"].append((i, -1, min(o[i], lo)))
                    break
        if india:
            t0 = dd.normalize() + pd.Timedelta(hours=9, minutes=15)
            w = [i for i in range(a, b) if t0 <= idx[i] < t0 + pd.Timedelta(hours=1)]
            if len(w) >= 2:
                hi, lo = h[w].max(), l[w].min()
                done = set()
                for i in range(w[-1] + 1, b):
                    if hm[i] > "14:45" or len(done) == 2:
                        break
                    if h[i] > hi and 1 not in done and not l[i] < lo:
                        S["E"].append((i, 1, max(o[i], hi)))
                        done.add(1)
                    elif l[i] < lo and -1 not in done and not h[i] > hi:
                        S["E"].append((i, -1, min(o[i], lo)))
                        done.add(-1)
    # B: previous completed 15-min candle break, on the VWAP side
    q = d.resample("15min", origin="start_day", offset="15min" if india else None).agg(AGG).dropna(subset=["Close"])
    qh = q["High"].reindex(q.index + pd.Timedelta(minutes=15))   # value known from the next 15-min block
    qh.index = q.index + pd.Timedelta(minutes=15)
    ql = q["Low"].copy()
    ql.index = q.index + pd.Timedelta(minutes=15)
    qh = q["High"].copy()
    qh.index = q.index + pd.Timedelta(minutes=15)
    ph = qh.reindex(idx, method="ffill").to_numpy()
    plo = ql.reindex(idx, method="ffill").to_numpy()
    last_b = -10
    for i in range(1, n):
        if not np.isfinite(ph[i]) or i - last_b < 3:
            continue
        if h[i] > ph[i] and c[i - 1] <= ph[i] and c[i - 1] > vw[i - 1]:
            S["B"].append((i, 1, max(o[i], ph[i])))
            last_b = i
        elif l[i] < plo[i] and c[i - 1] >= plo[i] and c[i - 1] < vw[i - 1]:
            S["B"].append((i, -1, min(o[i], plo[i])))
            last_b = i
    for i in range(15, n):
        if not np.isfinite(atr[i - 1]) or atr[i - 1] <= 0:
            continue
        rg = h[i] - l[i]
        if rg >= 2 * atr[i - 1]:
            if c[i] >= l[i] + 0.8 * rg:
                S["C"].append((i, 1, None))
            elif c[i] <= l[i] + 0.2 * rg:
                S["C"].append((i, -1, None))
        body = abs(c[i] - o[i])
        if body >= 0.5 * atr[i - 1]:
            if c[i - 1] < vw[i - 1] and c[i] > vw[i] and c[i] > o[i]:
                S["D"].append((i, 1, None))
            elif c[i - 1] > vw[i - 1] and c[i] < vw[i] and c[i] < o[i]:
                S["D"].append((i, -1, None))
        # F: trend pullback to EMA9, then break of the pullback candle (i-1)
        if e9[i - 1] > e21[i - 1] and l[i - 1] <= e9[i - 1] and c[i - 1] > e21[i - 1] and h[i] > h[i - 1]:
            S["F"].append((i, 1, max(o[i], h[i - 1])))
        elif e9[i - 1] < e21[i - 1] and h[i - 1] >= e9[i - 1] and c[i - 1] < e21[i - 1] and l[i] < l[i - 1]:
            S["F"].append((i, -1, min(o[i], l[i - 1])))
    return S


def simulate(d, sigs, target, stop, cost, india, limit_min, tf):
    o, h, l, c = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx = d.index
    day = idx.normalize()
    hm = idx.strftime("%H:%M")
    out, busy, per_day = [], -1, {}
    for i, s, lvl in sorted(sigs):
        if i <= busy:
            continue
        if india and not ("09:30" <= hm[i] <= "14:45"):
            continue
        if per_day.get(day[i], 0) >= 4:
            continue
        if lvl is None:
            if i + 1 >= len(d) or day[i + 1] != day[i]:
                continue
            e, k0 = o[i + 1], i + 1
        else:
            e, k0 = lvl, i
        st, tg = e - s * stop, e + s * target
        end = idx[k0] + pd.Timedelta(minutes=limit_min)
        x, j = None, k0
        while j < len(d):
            if idx[j] >= end or day[j] != day[k0] or (india and hm[j] >= "15:15"):
                x = o[j] if day[j] == day[k0] else c[j - 1]
                break
            if lvl is not None and j == k0:
                # the trigger candle: after the level was crossed only the move beyond it counts; stop if it went back
                hit_s = (l[j] <= st) if s > 0 else (h[j] >= st)
                hit_t = (h[j] >= tg) if s > 0 else (l[j] <= tg)
                if hit_s:
                    x = st
                    break
                if hit_t:
                    x = tg
                    break
                j += 1
                continue
            if (l[j] <= st) if s > 0 else (h[j] >= st):
                x = min(o[j], st) if s > 0 else max(o[j], st)
                break
            if (h[j] >= tg) if s > 0 else (l[j] <= tg):
                x = max(o[j], tg) if s > 0 else min(o[j], tg)
                break
            j += 1
        if x is None:
            x, j = c[-1], len(d) - 1
        c_pts = cost[1] if isinstance(cost, tuple) else (cost if cost >= 1 else e * cost / 100)
        out.append((idx[i], s * (x - e) - c_pts))
        busy = j
        per_day[day[i]] = per_day.get(day[i], 0) + 1
    return pd.Series([p for _, p in out], index=[t for t, _ in out], dtype=float)


def main(argv):
    S = Path(argv[1])
    pdd = pd.read_pickle(S / "pdf_data.pkl")
    idx5 = pd.read_pickle(S / "yahoo_idx5m.pkl")
    btc = utc_to_ist(pd.read_pickle(S / "btc5m.pkl"))
    gold = utc_to_ist(pd.read_pickle(S / "paxg5m.pkl"))
    gold = gold[gold.index.dayofweek < 5]
    mk = [("Nifty 2m (31 d)", prep(pdd[("NIFTY", "2m")]), True, 2, (25, 30), 3.0),
          ("Bank Nifty 2m (31 d)", prep(pdd[("BANKNIFTY", "2m")]), True, 2, (50, 70), 6.0),
          ("Nifty 5m (60 d)", prep(idx5["NIFTY"]), True, 5, (25, 30), 3.0),
          ("Bank Nifty 5m (60 d)", prep(idx5["BANKNIFTY"]), True, 5, (50, 70), 6.0),
          ("BTC 5m (3.5 y)", btc, False, 5, (400, 500), 0.05),
          ("Gold 5m (3.5 y)", gold, False, 5, (6, 7), ("pts", 0.5))]
    names = {"A": "opening-range break", "B": "prev 15-min candle break, VWAP side", "C": "momentum burst candle",
             "D": "VWAP reclaim / loss, strong body", "E": "first-hour high / low break", "F": "EMA 9/21 pullback break"}
    if "--only" in argv:
        mk = [m for m in mk if argv[argv.index("--only") + 1].lower() in m[0].lower()]
    rows = []
    for name, d, india, tf, targets, cost in mk:
        if india:
            d = d[(d.index.strftime("%H:%M") >= "09:15") & (d.index.strftime("%H:%M") < "15:30")]
        sig = signals(d, india, tf)
        for k, sg in sig.items():
            if not sg:
                continue
            for T in targets:
                for sm in (0.6, 1.0):
                    x = simulate(d, sg, T, T * sm, cost, india, 60 if india else 120, tf)
                    if len(x) < 10:
                        continue
                    mid = x.index[len(x) // 2]
                    pf = x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else np.inf
                    nd = len(set(x.index.normalize()))
                    rows.append({"market": name, "setup": f"{k} {names[k]}", "target": T, "stop": round(T * sm, 1),
                                 "trades": len(x), "per day": round(len(x) / max(nd, 1), 1),
                                 "win%": round((x > 0).mean() * 100), "PF": round(pf, 2),
                                 "net pts/trade": round(x.mean(), 2), "t": round(x.mean() / x.std() * np.sqrt(len(x)), 2),
                                 "h1": round(x[x.index < mid].mean(), 2), "h2": round(x[x.index >= mid].mean(), 2),
                                 "total pts": round(x.sum(), 1),
                                 "pass": bool(len(x) >= 40 and x[x.index < mid].mean() > 0 and x[x.index >= mid].mean() > 0 and pf > 1.15)})
        print(name, "done", flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(S / "scalp_points.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    for m in R["market"].unique():
        print(f"\n=== {m} ===")
        print(R[R["market"] == m].sort_values("net pts/trade", ascending=False).drop(columns="market").to_string(index=False))
    print("\nPASSING (>= 40 trades, both halves > 0, PF > 1.15):")
    print(R[R["pass"] == True].sort_values("t", ascending=False).to_string(index=False))  # noqa: E712


if __name__ == "__main__":
    main(sys.argv)
