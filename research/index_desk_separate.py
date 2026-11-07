"""Index Desk, bot by bot: every layer and every micro pattern as its OWN setup (no voting), on the five indices, with
the same entry and exits as the desk (index_desk.manage: next-candle entry, stop beyond the 5-candle swing 0.8-2 ATR,
TP1 1R half + stop to cost, two-candle trail, TP2 2.5R (no OI wall offline), time stop after 10 candles, 15:15).
Signals 9:30-14:30, max 2 trades per setup per index a day, one at a time. Each setup alone and with the trend filter
(price on the trade's side of EMA 21 and VWAP). Cost 0.02% of the index.

A setup passes only with >= 40 trades, avg > 0 after costs in BOTH halves, and PF > 1.2.

Usage: python research/index_desk_separate.py <yahoo_idx5m.pkl> <fno60_new.pkl>
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))
import index_desk as ID              # noqa: E402
import index_funnel as IF            # noqa: E402
import indices as IX                 # noqa: E402
from index_desk_backtest import clean  # noqa: E402

COST = 0.02


def features(ix: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    d = ix.copy()
    c, o, h, l = d["Close"], d["Open"], d["High"], d["Low"]
    day = d.index.normalize()
    g = d.groupby(day)
    d["ema9"], d["ema21"], d["ema60"] = ID.ema(c, 9), ID.ema(c, 21), ID.ema(c, 60)     # 60 x 5-min ~ 15-min EMA 20
    tp = (h + l + c) / 3
    d["vwap"] = tp.groupby(day).cumsum() / (g.cumcount() + 1)
    d["rsi"] = ID.rsi(c)
    m = ID.ema(c, 12) - ID.ema(c, 26)
    d["hist"] = m - ID.ema(m, 9)
    d["atr"] = ID.atr(d)
    d["n"] = g.cumcount()
    rng, body = h - l, (c - o).abs()
    # trend / momentum / flow states and their first bar ("turns on")
    up = (c > d["ema9"]) & (d["ema9"] > d["ema21"]) & (c > d["vwap"]) & (c > d["ema60"])
    dn = (c < d["ema9"]) & (d["ema9"] < d["ema21"]) & (c < d["vwap"]) & (c < d["ema60"])
    sig = {}
    sig["PULSE trend aligns"] = np.where(up & ~up.shift(fill_value=False), 1, np.where(dn & ~dn.shift(fill_value=False), -1, 0))
    mu = (d["rsi"] >= 55) & (d["hist"] > 0) & (d["hist"] >= d["hist"].shift())
    md = (d["rsi"] <= 45) & (d["hist"] < 0) & (d["hist"] <= d["hist"].shift())
    sig["DRIVE RSI + MACD align"] = np.where(mu & ~mu.shift(fill_value=False), 1, np.where(md & ~md.shift(fill_value=False), -1, 0))
    sig["DRIVE MACD cross"] = np.where((d["hist"] > 0) & (d["hist"].shift() <= 0), 1, np.where((d["hist"] < 0) & (d["hist"].shift() >= 0), -1, 0))
    t = table.reindex(d.index)
    fu = (t["buy_share"] > 52) & (t["net"] > t["net_before"]) & (t["breadth_up"] >= 55)
    fd = (t["buy_share"] < 48) & (t["net"] < t["net_before"]) & (t["breadth_dn"] >= 55)
    sig["RIVER flow + breadth turn on"] = np.where(fu & ~fu.shift(fill_value=False), 1, np.where(fd & ~fd.shift(fill_value=False), -1, 0))
    # micro patterns (PRISM), each alone
    orh = g["High"].transform(lambda x: x.iloc[:3].max())     # 15 min = 3 x 5-min
    orl = g["Low"].transform(lambda x: x.iloc[:3].min())
    bu, bd = (c > orh) & (d["n"] >= 3), (c < orl) & (d["n"] >= 3)
    first_bu = bu & (bu.astype(int).groupby(day).cumsum() == 1)
    first_bd = bd & (bd.astype(int).groupby(day).cumsum() == 1)
    sig["PRISM opening range break"] = np.where(first_bu, 1, np.where(first_bd, -1, 0))
    inside = (h.shift() <= h.shift(2)) & (l.shift() >= l.shift(2))
    sig["PRISM inside-bar break"] = np.where(inside & (c > h.shift()), 1, np.where(inside & (c < l.shift()), -1, 0))
    nr7 = rng.shift() == rng.shift().rolling(7).min()
    sig["PRISM NR7 break"] = np.where(nr7 & (c > h.shift()), 1, np.where(nr7 & (c < l.shift()), -1, 0))
    be = (c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift()) & (body > body.shift())
    se = (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift()) & (body > body.shift())
    sig["PRISM engulfing"] = np.where(be, 1, np.where(se, -1, 0))
    lw, uw = np.minimum(o, c) - l, h - np.maximum(o, c)
    ham = (rng > 0) & (lw >= 2 * np.maximum(body, rng * 0.1)) & (c >= l + 0.6 * rng)
    sht = (rng > 0) & (uw >= 2 * np.maximum(body, rng * 0.1)) & (c <= l + 0.4 * rng)
    sig["PRISM hammer / shooting star"] = np.where(ham, 1, np.where(sht, -1, 0))
    strong = lambda k: ((c.shift(k) > o.shift(k)) & (body.shift(k) >= 0.6 * rng.shift(k)))  # noqa: E731
    weak = lambda k: ((c.shift(k) < o.shift(k)) & (body.shift(k) >= 0.6 * rng.shift(k)))   # noqa: E731
    sig["PRISM three strong candles"] = np.where(strong(0) & strong(1) & strong(2), 1, np.where(weak(0) & weak(1) & weak(2), -1, 0))
    sig["PRISM VWAP reclaim / loss"] = np.where((c.shift() < d["vwap"].shift()) & (c > d["vwap"]), 1,
                                                np.where((c.shift() > d["vwap"].shift()) & (c < d["vwap"]), -1, 0))
    dd = d.groupby(day).agg(H=("High", "max"), L=("Low", "min"))
    pdh = pd.Series(day, index=d.index).map(dd["H"].shift())
    pdl = pd.Series(day, index=d.index).map(dd["L"].shift())
    dayhi, daylo = g["High"].cummax().shift(), g["Low"].cummin().shift()
    sig["PRISM failed break of yesterday H/L"] = np.where((dayhi > pdh) & (c.shift() > pdh) & (c <= pdh), -1,
                                                          np.where((daylo < pdl) & (c.shift() < pdl) & (c >= pdl), 1, 0))
    sig["PRISM break of yesterday H/L"] = np.where((c > pdh) & (c.shift() <= pdh), 1, np.where((c < pdl) & (c.shift() >= pdl), -1, 0))
    for k, v in sig.items():
        d["s: " + k] = v
    d["trend_up"] = (c > d["ema21"]) & (c > d["vwap"])
    d["trend_dn"] = (c < d["ema21"]) & (c < d["vwap"])
    return d


def run_setup(d: pd.DataFrame, col: str, tf: int, key: str, trend: bool) -> list:
    out = []
    hm = (d.index + pd.Timedelta(minutes=tf)).strftime("%H:%M")
    for day, g in d.groupby(d.index.normalize()):
        trs, n = [], 0
        ok = (hm[d.index.normalize() == day] >= "09:30") & (hm[d.index.normalize() == day] <= "14:30")
        for (ts, r), allowed in zip(g.iterrows(), ok):
            for x in trs:
                ID.manage(x, g[g.index <= ts])
            s = int(r[col])
            if not s or not allowed or n >= 2 or any(x.get("status") in ("waiting", "open") for x in trs):
                continue
            if trend and not (r["trend_up"] if s > 0 else r["trend_dn"]):
                continue
            a = float(r["atr"])
            if not np.isfinite(a) or a <= 0:
                continue
            last5 = g[g.index <= ts].tail(5)
            px = float(r["Close"])
            stop = float(np.clip(last5["Low"].min() - 0.1 * a, px - 2 * a, px - 0.8 * a)) if s > 0 else \
                float(np.clip(last5["High"].max() + 0.1 * a, px + 0.8 * a, px + 2 * a))
            risk = abs(px - stop)
            trs.append({"day": day, "index": key, "side": s, "signal_ts": str(ts), "plan_entry": px, "stop": stop,
                        "tp1": px + s * risk, "tp2": px + s * 2.5 * risk, "entry": None, "status": "waiting"})
            n += 1
        for x in trs:
            ID.manage(x, g)
        out += [x for x in trs if x.get("status") == "closed"]
    return out


def stats(t: pd.DataFrame, days: list) -> dict:
    if len(t) < 5:
        return {"n": len(t)}
    r = t["r"] - COST / (t["risk_pts"] / t["entry"] * 100)
    mid = days[len(days) // 2]
    h1, h2 = r[t["day"] < mid], r[t["day"] >= mid]
    pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else np.inf
    return {"n": len(r), "win%": round((r > 0).mean() * 100), "PF": round(pf, 2), "avg R": round(r.mean(), 3),
            "t": round(r.mean() / r.std() * np.sqrt(len(r)), 2), "h1": round(h1.mean(), 3), "h2": round(h2.mean(), 3),
            "total R": round(r.sum(), 1), "avg %": round((t["pct"] - COST).mean(), 3),
            "pass": bool(len(r) >= 40 and h1.mean() > 0 and h2.mean() > 0 and pf > 1.2)}


def main(argv):
    idx5 = pd.read_pickle(argv[1])
    stocks, _ = pickle.load(open(argv[2], "rb"))
    stocks = {s: clean(df) for s, df in stocks.items() if df is not None and len(df)}
    W = {k: d.get("w", {}) for k, d in IX.load().items()}
    rows, every = [], []
    days_all = None
    for k in ID.INDEXES:
        ix = clean(idx5[k])
        tf = int(pd.Series(ix.index).diff().dt.total_seconds().median() // 60)
        d = features(ix, IF.index_table(ix, stocks, W.get(k, {}), None))
        d = d[d.index.normalize() >= sorted(set(d.index.normalize()))[5]]
        days_all = sorted(set(d.index.normalize()))
        for col in [c for c in d.columns if c.startswith("s: ")]:
            for trend in (False, True):
                tr = run_setup(d, col, tf, k, trend)
                for x in tr:
                    x["setup"], x["trend"] = col[3:], trend
                every += tr
        print(f"{k} done ({len(every)} trades so far)", flush=True)
    t = pd.DataFrame(every)
    t.to_pickle(Path(argv[1]).resolve().parent / "index_separate_trades.pkl")
    for (s, tr_), z in t.groupby(["setup", "trend"]):
        rows.append({"setup": s, "trend filter": tr_, "index": "ALL 5", **stats(z, days_all)})
        for k, zz in z.groupby("index"):
            rows.append({"setup": s, "trend filter": tr_, "index": k, **stats(zz, days_all)})
    res = pd.DataFrame(rows)
    res.to_csv(Path(argv[1]).resolve().parent / "index_separate.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print("\nEVERY SETUP ALONE, all five indices together:")
    print(res[res["index"] == "ALL 5"].sort_values("avg R", ascending=False).to_string(index=False))
    print("\nPASSING (>= 40 trades, both halves > 0, PF > 1.2), any index:")
    print(res[res["pass"] == True].sort_values("avg R", ascending=False).to_string(index=False))  # noqa: E712


if __name__ == "__main__":
    main(sys.argv)
