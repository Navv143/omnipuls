"""Option P&L for sweep trades: ATM Nifty weekly option bought at entry, priced with India VIX (Black-Scholes)."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")
import optmodel as M
t = pd.read_csv(sys.argv[1], parse_dates=["entry_time", "exit_time"])
vix = pd.read_csv("/home/claude/udata/INDIA VIX_5minute.csv", parse_dates=["date"]).set_index("date")["close"]
def dte(d):
    wd = 3 if d < pd.Timestamp("2025-09-01") else 1
    n, x = 0, d
    while True:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: n += 1
        if x.weekday() == wd: return n
iv = vix.reindex(t.entry_time, method="ffill").values / 100
slot = lambda ts: ((ts.dt.hour * 60 + ts.dt.minute) - 555) // 5
side = np.where(t.side == "LONG", 1, -1)
dd = np.array([dte(pd.Timestamp(x).normalize()) for x in t.entry_time])
for cost in (0.015, 0.03):
    r, _ = M.option_return(t.entry.values, t.exit.values, side, dd, slot(t.entry_time).values + 1, slot(t.exit_time).values, iv, cost=cost)
    t[f"opt_{cost}"] = r
t["year"] = t.entry_time.dt.year
print("option avg % per trade @1.5% cost:", round(100*t["opt_0.015"].mean(), 2), "| @3%:", round(100*t["opt_0.03"].mean(), 2),
      "| win%:", round(100*(t["opt_0.015"] > 0).mean(), 1))
print((100*t.groupby("year")["opt_0.015"].mean()).round(1).to_string())
