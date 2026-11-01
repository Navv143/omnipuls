import numpy as np, pandas as pd, itertools, warnings, sys; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/bt")
import swing1m as S, optmodel as M
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 200)
vix = pd.read_csv("/home/claude/udata/INDIA VIX_5minute.csv", parse_dates=["date"]).set_index("date")["close"]
COST = 0.0003  # 0.03% of price per round trip (futures: STT + charges + slippage)
def dte(dd):
    wd = 3 if dd < pd.Timestamp("2025-09-01") else 1; n, x = 0, dd
    while True:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: n += 1
        if x.weekday() == wd: return n
rows = []
for sym in ("NIFTY", "BANKNIFTY"):
    df = S.load(sym)
    print(sym, len(df), df.dt.min().date(), df.dt.max().date(), df.dt.dt.date.nunique(), "days", flush=True)
    for N, sm, rr, hold, vm in itertools.product((2, 3, 5), ("swing", "candle"), (1.5, 2.0, None), (30, 60), (None, 1.5)):
        t = S.run(df, N=N, stop_mode=sm, rr=rr, hold=hold, vol_mult=vm)
        if len(t) < 100: continue
        net = t.pts - COST * t.entry; a = t.date < "2020-01-01"; ys = net.groupby(t.date.dt.year).sum()
        rows.append({"index": sym, "swing N": N, "stop": sm, "target": rr or "none", "max hold": hold, "vol filter": vm or "-",
                     "trades": len(t), "win%": round(100 * (t.pts > 0).mean(), 1), "gross pts": round(t.pts.mean(), 2),
                     "net pts": round(net.mean(), 2), "net %": round(100 * (net / t.entry).mean(), 3),
                     "t": round(net.mean() / net.std() * np.sqrt(len(t)), 2), "2015-19": round(net[a].mean(), 2),
                     "2020-23": round(net[~a].mean(), 2), "yrs +": f"{(ys > 0).sum()}/{len(ys)}", "avg mins": round(t.mins.mean())})
    print(sym, "done", flush=True)
out = pd.DataFrame(rows); out.to_csv("swing1m_grid.csv", index=False)
for sym in ("NIFTY", "BANKNIFTY"):
    x = out[out["index"] == sym]
    print(f"\n{sym}: {len(x)} versions | positive after costs: {(x['net pts'] > 0).sum()} | median net pts {x['net pts'].median()}")
    print(x.sort_values("net %", ascending=False).head(8).to_string(index=False))
    print("paper-standard version (N=3, stop at opposite swing, 2R, 60 min, no filter):")
    print(x[(x["swing N"] == 3) & (x["stop"] == "swing") & (x["target"] == 2.0) & (x["max hold"] == 60) & (x["vol filter"] == "-")].to_string(index=False))
