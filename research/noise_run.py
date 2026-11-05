import sys, pickle, warnings; warnings.filterwarnings("ignore"); sys.path.insert(0, "research")
import numpy as np, pandas as pd, noise_study as N, sniper_study as SN
S = sys.argv[1]
D = pickle.load(open(f"{S}/noise_data.pkl", "rb"))
half = lambda st: {f"{h:02d}:{m:02d}" for h in range(24) for m in (int(st[3:]) % 30, int(st[3:]) % 30 + 30)}
CASES = [  # name, df, session start, end, cost/side, checks, days/yr
    ("SPY 1h (2023-26)", D[("SPY", "1h")], "09:30", "16:00", 0.005, None, 252),
    ("QQQ 1h (2023-26)", D[("QQQ", "1h")], "09:30", "16:00", 0.005, None, 252),
    ("SPY 5m 30-min checks (60d)", D[("SPY", "5m")], "09:30", "16:00", 0.005, half("09:30"), 252),
    ("QQQ 5m 30-min checks (60d)", D[("QQQ", "5m")], "09:30", "16:00", 0.005, half("09:30"), 252),
    ("NIFTY 1h (2023-26)", D[("^NSEI", "1h")], "09:15", "15:30", 0.01, None, 248),
    ("BANKNIFTY 1h (2023-26)", D[("^NSEBANK", "1h")], "09:15", "15:30", 0.01, None, 248),
    ("NIFTY 5m 30-min checks (60d)", D[("^NSEI", "5m")], "09:15", "15:30", 0.01, half("09:15"), 248),
    ("BANKNIFTY 5m 30-min checks (60d)", D[("^NSEBANK", "5m")], "09:15", "15:30", 0.01, half("09:15"), 248),
    ("GOLD fut 1h, 08-17 NY (2024-26)", D[("GC=F", "1h")], "08:00", "17:00", 0.01, None, 252),
    ("OIL fut 1h, 08-17 NY (2024-26)", D[("CL=F", "1h")], "08:00", "17:00", 0.01, None, 252),
]
btc = pickle.load(open(f"{S}/btc5m.pkl", "rb")); eth = SN._load_zip_dir(f"{S}/ETHUSDT")
CASES += [("BTC 5m UTC day, 30-min checks (2023-26)", btc, "00:00", "23:59", 0.025, half("00:00"), 365),
          ("ETH 5m UTC day, 30-min checks (2023-26)", eth, "00:00", "23:59", 0.025, half("00:00"), 365)]
rows = []
for name, df, a, b, cost, chk, py in CASES:
    x = N.sessions(df, a, b)
    for vwap in (True, False):
        t, d = N.run(x, cost, 14, 1.0, chk, vwap)
        st = N.stats(t, d, py)
        # benchmark: long from the open to the close every day
        bh = x.groupby("day").apply(lambda g: (g.Close.iloc[-1] / g.Open.iloc[0] - 1) * 100).loc[d.index] if len(d) else pd.Series(dtype=float)
        rows.append({"market": name, "trail": "band+VWAP" if vwap else "band only", **{k: v for k, v in st.items() if k != "years"},
                     "intraday buy&hold %": round(bh.sum(), 1), "years": st.get("years")})
    print(name, "done", flush=True)
pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 80)
print(pd.DataFrame(rows).to_string(index=False))
pd.DataFrame(rows).to_csv(f"{S}/noise_results.csv", index=False)
