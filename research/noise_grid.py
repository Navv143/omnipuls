import sys, pickle, warnings, itertools; warnings.filterwarnings("ignore"); sys.path.insert(0, "research")
import numpy as np, pandas as pd, noise_study as N
S = sys.argv[1]
D = pickle.load(open(f"{S}/noise_data.pkl", "rb"))
CASES = [("NIFTY 1h", D[("^NSEI", "1h")], "09:15", "15:30", 0.01, 248), ("BANKNIFTY 1h", D[("^NSEBANK", "1h")], "09:15", "15:30", 0.01, 248),
         ("SPY 1h", D[("SPY", "1h")], "09:30", "16:00", 0.005, 252), ("QQQ 1h", D[("QQQ", "1h")], "09:30", "16:00", 0.005, 252),
         ("GOLD 1h", D[("GC=F", "1h")], "08:00", "17:00", 0.01, 252), ("OIL 1h", D[("CL=F", "1h")], "08:00", "17:00", 0.01, 252)]
LB, VM = (3, 5, 7, 10, 14, 20, 30), (0.5, 0.75, 1.0, 1.25, 1.5)
rows = []
for name, df, a, b, cost, py in CASES:
    x = N.sessions(df, a, b)
    for lb, vm in itertools.product(LB, VM):
        t, d = N.run(x, cost, lb, vm, None, True)
        d = d.iloc[30:]          # same start for every lookback (first 30 sessions only build the bands)
        t = t[t.day.isin(d.index)]
        st = N.stats(t, d, py)
        rows.append({"market": name, "lookback": lb, "band_x": vm, **{k: v for k, v in st.items() if k != "years"}})
    print(name, "done", flush=True)
g = pd.DataFrame(rows); g.to_csv(f"{S}/noise_grid.csv", index=False)
pd.set_option("display.width", 200)
for name in g.market.unique():
    s = g[g.market == name]
    print(f"\n===== {name}: total % (unlevered, ~2.8 years) — rows lookback days, columns band width")
    print(s.pivot(index="lookback", columns="band_x", values="total%").to_string())
    print(f"--- Sharpe"); print(s.pivot(index="lookback", columns="band_x", values="sharpe").to_string())
    s2 = s.assign(both=np.where((s["1st half%"] > 0) & (s["2nd half%"] > 0), "✓", "·"))
    print(f"--- both halves positive"); print(s2.pivot(index="lookback", columns="band_x", values="both").to_string())
    print(f"--- trades"); print(s.pivot(index="lookback", columns="band_x", values="trades").to_string())
