"""Global Intraday Desk, setup by setup: every VEGA setup as its OWN strategy per market (no voting), adding one filter
at a time: alone -> + not stretched (move from the day's open <= 1.2 daily ATR) -> + ATLAS regime (crypto with
Bitcoin's 1h + 4h trend, metals / energy against the dollar's 1h trend, forex with / against it) -> + active session
(London / overlap / New York for non-crypto). Exits as the desk: stop beyond the 6-candle swing (1-2.5x 15-min ATR),
target 2R, out after 8 hours (non-crypto at 21:00 UTC); next-candle entry; stop checked first. Costs: crypto 0.08%,
forex 0.01%, commodities 0.03%. One trade at a time per setup per market.

A setup passes only with >= 40 trades, avg R > 0 in BOTH halves, and PF > 1.2.

Usage: python research/global_desk_separate.py <pdf_data.pkl> [--long]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))
import desk_agents as DA                    # noqa: E402
import desk_intraday as DI                  # noqa: E402
from global_desk_backtest import MAP, COST, yget   # noqa: E402

GOOD = {"London", "London-NY overlap", "New York"}


def trend_series(h: pd.DataFrame) -> pd.Series:
    """1h trend (+1 / -1 / 0) known at the END of each hour (index shifted by 1h)."""
    c = h["Close"]
    e20, e50 = DA.ema(c, 20), DA.ema(c, 50)
    t = np.where((c > e20) & (e20 > e50) & (e20 > e20.shift(3)), 1, np.where((c < e20) & (e20 < e50) & (e20 < e20.shift(3)), -1, 0))
    s = pd.Series(t, index=h.index + pd.Timedelta(hours=1))
    return s


def h4_trend(h: pd.DataFrame) -> pd.Series:
    c4 = h["Close"].resample("4h").last().dropna()
    e20, e50 = DA.ema(c4, 20), DA.ema(c4, 50)
    t = np.where((c4 > e20) & (e20 > e50), 1, np.where((c4 < e20) & (e20 < e50), -1, 0))
    return pd.Series(t, index=c4.index + pd.Timedelta(hours=4))


def at(series: pd.Series, idx: pd.DatetimeIndex) -> np.ndarray:
    return series.reindex(series.index.union(idx)).ffill().reindex(idx).fillna(0).to_numpy()


def signals(sym: str, m: pd.DataFrame, h: pd.DataFrame, dxy: pd.Series | None, btc: tuple | None) -> pd.DataFrame:
    d = m.copy()
    c, hi, lo, v = d["Close"], d["High"], d["Low"], d["Volume"].fillna(0)
    close_t = d.index + pd.Timedelta(minutes=15)                     # signal known at the candle's close
    d["atr"] = DA.atr(d)
    e20 = DA.ema(c, 20)
    day = d.index.normalize()
    tp = (hi + lo + c) / 3
    vw = (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum().replace(0, np.nan)
    vw = vw.fillna(tp.groupby(day).cumsum() / (d.groupby(day).cumcount() + 1))
    t1 = at(trend_series(h), close_t)
    daily = h.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    datr = DA.atr(daily).shift(1)
    datr_b = pd.Series(day, index=d.index).map(datr).to_numpy()
    dopen = d.groupby(day)["Open"].transform("first")
    move = ((c - dopen) / datr_b).to_numpy()
    rh, rl = hi.shift(1).rolling(16).max(), lo.shift(1).rolling(16).min()
    vx = (v / v.shift(1).rolling(20).mean()).to_numpy()
    volok = ~(np.isfinite(vx)) | (vx >= 1.3) | (v.rolling(20).sum().to_numpy() == 0)
    S = {}
    S["4h range break (volume)"] = np.where((c > rh) & volok, 1, np.where((c < rl) & volok, -1, 0))
    S["4h range break (any volume)"] = np.where(c > rh, 1, np.where(c < rl, -1, 0))
    S["pullback to 15m EMA20 in 1h trend"] = np.where((t1 > 0) & (lo.rolling(2).min() <= e20 + 0.2 * d["atr"]) & (c > e20) & (c > vw), 1,
                                                       np.where((t1 < 0) & (hi.rolling(2).max() >= e20 - 0.2 * d["atr"]) & (c < e20) & (c < vw), -1, 0))
    S["VWAP reclaim / loss in 1h trend"] = np.where((t1 > 0) & (c.shift() < vw) & (c > vw), 1, np.where((t1 < 0) & (c.shift() > vw) & (c < vw), -1, 0))
    tp1 = pd.Series(t1, index=d.index)
    S["1h trend turns on"] = np.where((tp1 > 0) & (tp1.shift() <= 0), 1, np.where((tp1 < 0) & (tp1.shift() >= 0), -1, 0))
    cls = DI.CLASS_OF[sym]
    if cls == "Crypto" and btc is not None:
        b1, b4 = at(btc[0], close_t), at(btc[1], close_t)
        bias = np.sign(b1 + b4)
    elif dxy is not None:
        dx = at(dxy, close_t)
        bias = dx * (1 if sym.startswith("USD") else -1) if cls == "Forex" else -dx
    else:
        bias = np.zeros(len(d))
    hrs = close_t.hour
    ses = np.where(close_t.dayofweek >= 5, "Weekend",
                   np.select([hrs < 7, hrs < 12, hrs < 16, hrs < 21], ["Asia", "London", "London-NY overlap", "New York"], "Quiet"))
    d["bias"], d["move"], d["session"] = bias, move, ses
    for k, s in S.items():
        d["s: " + k] = s
    return d


def simulate(d: pd.DataFrame, col: str, sym: str, level: int) -> list:
    """level 0 alone, 1 + not stretched, 2 + regime, 3 + active session."""
    cls = DI.CLASS_OF[sym]
    cost = COST[cls]
    o, h, l, c = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    a, sig = d["atr"].to_numpy(), d[col].to_numpy()
    mv, bias, ses = d["move"].to_numpy(), d["bias"].to_numpy(), d["session"].to_numpy()
    idx = d.index
    out, i, n = [], 30, len(d)
    while i < n - 1:
        s = int(sig[i])
        if not s or not np.isfinite(a[i]) or a[i] <= 0:
            i += 1
            continue
        if level >= 1 and np.isfinite(mv[i]) and s * mv[i] > 1.2:
            i += 1
            continue
        if level >= 2 and bias[i] != s:
            i += 1
            continue
        if level >= 3 and ((cls != "Crypto" and ses[i] not in GOOD) or (cls != "Crypto" and (idx[i] + pd.Timedelta(minutes=15)).hour >= 20)):
            i += 1
            continue
        if cls != "Crypto" and ses[i] == "Weekend":
            i += 1
            continue
        sw_lo, sw_hi = l[max(0, i - 5):i + 1].min(), h[max(0, i - 5):i + 1].max()
        px = c[i]
        stop = float(np.clip(sw_lo - 0.25 * a[i], px - 2.5 * a[i], px - a[i])) if s > 0 else float(np.clip(sw_hi + 0.25 * a[i], px + a[i], px + 2.5 * a[i]))
        e = o[i + 1]
        stop += e - px
        risk = abs(e - stop)
        tg = e + s * 2 * risk
        t0 = idx[i] + pd.Timedelta(minutes=15)
        end = t0 + pd.Timedelta(hours=8)
        if cls != "Crypto":
            cl = t0.normalize() + pd.Timedelta(hours=21)
            end = min(end, cl if cl > t0 else cl + pd.Timedelta(days=1))
        x, j = None, i + 1
        while j < n:
            if idx[j] >= end or (idx[j] - idx[j - 1]) > pd.Timedelta(hours=6):
                x = o[j] if idx[j] >= end and (idx[j] - idx[j - 1]) <= pd.Timedelta(hours=6) else c[j - 1]
                break
            if (l[j] <= stop) if s > 0 else (h[j] >= stop):
                x = min(o[j], stop) if s > 0 else max(o[j], stop)
                break
            if (h[j] >= tg) if s > 0 else (l[j] <= tg):
                x = max(o[j], tg) if s > 0 else min(o[j], tg)
                break
            j += 1
        if x is None:
            x, j = c[-1], n - 1
        out.append({"time": t0, "symbol": sym, "class": cls, "side": s,
                    "r": s * (x - e) / risk - cost / (risk / e * 100), "pct": s * (x / e - 1) * 100 - cost})
        i = j + 1
    return out


def stats(t: pd.DataFrame, mid) -> dict:
    if len(t) < 5:
        return {"n": len(t)}
    r = t["r"]
    h1, h2 = r[t["time"] < mid], r[t["time"] >= mid]
    pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else np.inf
    return {"n": len(r), "win%": round((r > 0).mean() * 100), "PF": round(pf, 2), "avg R": round(r.mean(), 3),
            "t": round(r.mean() / r.std() * np.sqrt(len(r)), 2), "h1": round(h1.mean(), 3), "h2": round(h2.mean(), 3),
            "total R": round(r.sum(), 1), "pass": bool(len(r) >= 40 and h1.mean() > 0 and h2.mean() > 0 and pf > 1.2)}


def main(argv):
    data = pd.read_pickle(argv[1])
    long = "--long" in argv
    if long:
        m15 = {"BTC-USD": data[("BTC", "15m")], "GC=F": data[("PAXG_GOLD", "15m")]}
        h1 = {"BTC-USD": data[("BTC", "1h")], "GC=F": data[("PAXG_GOLD", "1h")]}
    else:
        m15, h1 = {}, {}
        for k, s in MAP.items():
            if (k, "15m") in data:
                m15[s], h1[s] = data[(k, "15m")], data[(k, "1h")]
        for s in ("BTC-USD", "ETH-USD", "SOL-USD", "AUDUSD=X"):
            a_, b_ = yget(s, "15m", "60d"), yget(s, "1h", "730d")
            if a_ is not None and b_ is not None:
                m15[s], h1[s] = a_, b_
    dx = yget("DX-Y.NYB", "1h", "730d")
    m15 = {s: DA._clean(x) for s, x in m15.items()}
    h1 = {s: DA._clean(x) for s, x in h1.items()}
    dxy = trend_series(DA._clean(dx)) if dx is not None else None
    btc = (trend_series(h1["BTC-USD"]), h4_trend(h1["BTC-USD"])) if "BTC-USD" in h1 else None
    allt = []
    for s, m in m15.items():
        if s not in DI.CLASS_OF:
            continue
        d = signals(s, m, h1[s], dxy, btc)
        if long:
            d = d[d.index >= "2023-02-01"]
        for col in [c for c in d.columns if c.startswith("s: ")]:
            for lv in range(4):
                for x in simulate(d, col, s, lv):
                    x["setup"], x["level"] = col[3:], ["alone", "+ not stretched", "+ regime", "+ session"][lv]
                    allt.append(x)
        print(f"{s} done", flush=True)
    t = pd.DataFrame(allt)
    mid = t["time"].sort_values().iloc[len(t) // 2]
    rows = []
    for (st, lv), z in t.groupby(["setup", "level"]):
        rows.append({"setup": st, "filters": lv, "market": "ALL", **stats(z, mid)})
        for k, zz in z.groupby("class"):
            rows.append({"setup": st, "filters": lv, "market": k, **stats(zz, mid)})
        for k, zz in z.groupby("symbol"):
            rows.append({"setup": st, "filters": lv, "market": k, **stats(zz, mid)})
    res = pd.DataFrame(rows)
    tag = "long" if long else "60d"
    res.to_csv(Path(argv[1]).resolve().parent / f"global_separate_{tag}.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(f"\n{'2023-2026 BTC + GOLD' if long else '60 DAYS, ALL MARKETS'}: every setup, all markets together")
    print(res[res["market"] == "ALL"].sort_values("avg R", ascending=False).to_string(index=False))
    print("\nPASSING (>= 40 trades, both halves > 0, PF > 1.2):")
    print(res[res["pass"] == True].sort_values("avg R", ascending=False).to_string(index=False))  # noqa: E712


if __name__ == "__main__":
    main(sys.argv)
