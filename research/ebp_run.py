import sys, pickle, warnings; warnings.filterwarnings("ignore"); sys.path.insert(0, "research")
import numpy as np, pandas as pd, ebp_study as E, sniper_study as SN
S = sys.argv[1]
mk = {"BTC": (pickle.load(open(f"{S}/btc5m.pkl", "rb")), 0.05), "ETH": (SN._load_zip_dir(f"{S}/ETHUSDT"), 0.05),
      "SOL": (SN._load_zip_dir(f"{S}/SOLUSDT"), 0.06), "GOLD": (pickle.load(open(f"{S}/paxg5m.pkl", "rb")), 0.02)}
mk["GOLD"] = (mk["GOLD"][0][mk["GOLD"][0].index.dayofweek < 5], 0.02)
i5 = pickle.load(open(f"{S}/yahoo_idx5m.pkl", "rb")); h1 = pickle.load(open(f"{S}/yahoo1h.pkl", "rb"))
print("indian keys", list(i5)[:6], type(h1), list(h1)[:4] if isinstance(h1, dict) else "")
rows = []
VAR = [("market", "dol"), ("mid", "dol"), ("market", "rr1"), ("market", "rr2"), ("mid", "rr2")]
def run(mname, df, C, tfs, split="2025-01-01"):
    for tf in tfs:
        x = E.resample(df, tf)
        for ent, tgt in VAR:
            t = E.ebp_trades(x, C, ent, "dol" if tgt == "dol" else "rr", 1.0 if tgt == "rr1" else 2.0)
            if len(t) < 20:
                continue
            tt = pd.to_datetime(t["t"]); h = tt < pd.Timestamp(split, tz=tt.dt.tz) if tt.dt.tz is not None else tt < pd.Timestamp(split)
            weeks = max((tt.max() - tt.min()).days / 7, 1)
            rows.append({"market": mname, "tf": tf, "entry": ent, "target": tgt, "n": len(t), "per_wk": round(len(t) / weeks, 1),
                         "win%": round((t.r > 0).mean() * 100), "avgR": round(t.r.mean(), 3), "tune": round(t[h].r.mean(), 3) if h.any() else np.nan,
                         "test": round(t[~h].r.mean(), 3) if (~h).any() else np.nan, "stop%": round(t.stop_pct.median(), 2),
                         "gross_pct": round((t.pct + C).mean(), 3)})
for m, (df, C) in mk.items():
    run(m, df, C, ["5min", "15min", "1h", "4h", "1D"]); print(m, "done", flush=True)
for k, nm in (("NIFTY", "NIFTY"), ("BANKNIFTY", "BANKNIFTY")):
    if k in i5: run(nm + " (60d)", i5[k], 0.02, ["5min", "15min"], split="2026-10-01")
    if isinstance(h1, dict) and k in h1: run(nm + " (2y)", h1[k], 0.02, ["1h", "1D"], split="2025-11-01")
d = pd.DataFrame(rows); d.to_csv(f"{S}/ebp_results.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
print(d.to_string(index=False))
