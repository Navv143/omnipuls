"""Index Desk (index_desk.py) replayed on past candles: all seven layers at every closed candle, exactly as live
(SHIELD and ORACLE included; trades managed with index_desk.manage: stop, TP1 half + stop to cost, two-candle trail,
TP2, time stop after 10 candles, 15:15). Costs 0.02% of the index a round trip (index futures / options slippage proxy).

No option-chain / futures-OI history offline, so VAULT is neutral (ORACLE then needs the other four to agree).

Usage: python research/index_desk_backtest.py <yahoo_idx5m.pkl {index: 5-min}> <fno60_new.pkl (stocks, ...)>
       (5-minute candles: the live desk runs on 3-minute; the rules are the same in candles)
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import index_desk as ID      # noqa: E402
import index_funnel as IF    # noqa: E402
import indices as IX         # noqa: E402

COST = 0.02


def clean(d):
    d = d.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    d = d[(d.index.second == 0) & (d.index.strftime("%H:%M") >= "09:15") & (d.index.strftime("%H:%M") < "15:30")]
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def run_index(key, ix, stocks, weights, tf):
    table = IF.index_table(ix, stocks, weights, None)          # causal per row (cumulative within the day)
    heavy = {s: stocks[s] for s, _ in sorted(weights.items(), key=lambda kv: -kv[1])[:5] if s in stocks}
    days = sorted(set(ix.index.normalize()))[5:]
    trades, calls = [], {}
    for day in days:
        today = ix[ix.index.normalize() == day]
        day_tr = []
        for ts in today.index[3:]:
            close_hm = (ts + pd.Timedelta(minutes=tf)).strftime("%H:%M")
            cut = ix[ix.index <= ts]
            for x in day_tr:
                ID.manage(x, cut[cut.index.normalize() == day])
            busy = any(x.get("status") in ("waiting", "open") for x in day_tr)
            row = table.loc[ts] if ts in table.index else None
            hv = {s: b[(b.index <= ts) & (b.index >= day)] for s, b in heavy.items()}
            r = ID.read_index(key, cut.tail(1500), None, {}, {}, row, hv, weights, close_hm, len(day_tr), False, busy)
            if not r:
                continue
            c = r["oracle"]["call"]
            calls[c] = calls.get(c, 0) + 1
            if c == "TRADE":
                sh = r["shield"]
                day_tr.append({"day": day, "index": key, "side": sh["side"], "signal_at": close_hm, "signal_ts": str(ts),
                               "plan_entry": sh["entry"], "stop": sh["stop"], "tp1": sh["tp1"], "tp2": sh["tp2"],
                               "entry": None, "status": "waiting",
                               "trigger": ", ".join(p["name"] for p in r["prism"]["patterns"] if p["fresh"]),
                               "votes": r["oracle"]["votes"]})
        for x in day_tr:
            ID.manage(x, today)
        trades += day_tr
    return trades, calls


def report(t: pd.DataFrame, nd: int) -> str:
    c = t[t["status"] == "closed"].copy()
    if c.empty:
        return "no closed trades"
    c["net_r"] = c["r"] - COST / (c["risk_pts"] / c["entry"] * 100)
    c["net_pct"] = c["pct"] - COST
    p = c["net_r"]
    mid = sorted(c["day"].unique())[c["day"].nunique() // 2]
    pf = p[p > 0].sum() / -p[p < 0].sum() if (p < 0).any() else np.inf
    out = [f"ALL: {len(c)} trades on {nd} days ({len(c) / nd:.1f}/day) | win {(p > 0).mean() * 100:.0f}% | PF {pf:.2f} | "
           f"avg {p.mean():+.3f}R ({c['net_pct'].mean():+.3f}% of the index) | t {p.mean() / p.std() * np.sqrt(len(p)):+.2f} | "
           f"halves {p[c['day'] < mid].mean():+.3f}R / {p[c['day'] >= mid].mean():+.3f}R | total {p.sum():+.1f}R",
           "by exit: " + ", ".join(f"{k} {len(z)} ({z['net_r'].mean():+.2f}R)" for k, z in c.groupby("result")),
           "by index: " + ", ".join(f"{k} {len(z)} (win {(z['net_r'] > 0).mean() * 100:.0f}%, {z['net_r'].mean():+.2f}R)"
                                    for k, z in c.groupby("index")),
           "by side: " + ", ".join(f"{'long' if k > 0 else 'short'} {len(z)} ({z['net_r'].mean():+.2f}R)" for k, z in c.groupby("side")),
           "by hour: " + ", ".join(f"{k} {len(z)} ({z['net_r'].mean():+.2f}R)" for k, z in c.groupby(c["signal_at"].str[:2] + "h")),
           "by month: " + ", ".join(f"{k} {z['net_r'].sum():+.1f}R" for k, z in c.groupby(pd.to_datetime(c["day"]).dt.strftime("%b")))]
    trig = c.assign(tr=c["trigger"].str.split(", ")).explode("tr")
    out.append("by trigger pattern: " + ", ".join(f"{k} {len(z)} ({z['net_r'].mean():+.2f}R)"
                                                 for k, z in trig.groupby("tr") if len(z) >= 3))
    return "\n".join(out)


def main(argv):
    idx5 = pd.read_pickle(argv[1])
    stocks, _ = pickle.load(open(argv[2], "rb"))
    stocks = {s: clean(df) for s, df in stocks.items() if df is not None and len(df)}
    W = {k: d.get("w", {}) for k, d in IX.load().items()}
    alltr, allc = [], {}
    for k in ID.INDEXES:
        if k not in idx5:
            continue
        ix = clean(idx5[k])
        tf = int(pd.Series(ix.index).diff().dt.total_seconds().median() // 60)
        tr, calls = run_index(k, ix, stocks, W.get(k, {}), tf)
        alltr += tr
        for a, b in calls.items():
            allc[a] = allc.get(a, 0) + b
        print(f"{k}: {len(tr)} trades, calls {calls}", flush=True)
    t = pd.DataFrame(alltr)
    t.to_pickle(Path(argv[1]).resolve().parent / "index_desk_bt.pkl")
    nd = len(set(pd.to_datetime(t["day"]))) if len(t) else 0
    days = len(set(clean(idx5["NIFTY"]).index.normalize())) - 5
    print(f"\ncalls over all candles: {allc}")
    print(report(t, days) if len(t) else "no trades")
    _ = nd


if __name__ == "__main__":
    main(sys.argv)
