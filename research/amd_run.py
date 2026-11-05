import sys, pickle, warnings; warnings.filterwarnings("ignore"); sys.path.insert(0, "research")
import numpy as np, pandas as pd, strategy_lab as L, amd_study as AM, sniper_study as SN
S = sys.argv[1]
btc = pickle.load(open(f"{S}/btc5m.pkl", "rb")); eth = SN._load_zip_dir(f"{S}/ETHUSDT"); sol = SN._load_zip_dir(f"{S}/SOLUSDT")
gold = pickle.load(open(f"{S}/paxg5m.pkl", "rb")); gold = gold[gold.index.dayofweek < 5]
i5 = pickle.load(open(f"{S}/yahoo_idx5m.pkl", "rb"))
nif, bnf = (i5[k][~i5[k].index.duplicated()].tz_localize("Asia/Kolkata") for k in ("NIFTY", "BANKNIFTY"))
M = [("BTC (SMT vs ETH)", btc, eth, 0.05, "UTC", None, "2025-01-01"), ("ETH (SMT vs BTC)", eth, btc, 0.05, "UTC", None, "2025-01-01"),
     ("SOL (SMT vs BTC)", sol, btc, 0.06, "UTC", None, "2025-01-01"), ("GOLD (no SMT partner)", gold, None, 0.02, "UTC", None, "2025-01-01"),
     ("BANKNIFTY 60d (SMT vs NIFTY)", bnf, nif, 0.02, "Asia/Kolkata", 915, "2026-10-01"),
     ("NIFTY 60d (SMT vs BANKNIFTY)", nif, bnf, 0.02, "Asia/Kolkata", 915, "2026-10-01")]
rows = []
for name, x, p, C, tz, exit_hm, split in M:
    xx = L.local(x, tz)
    for htf in (15, 30, 60, 240):
        for smt in ((True, False) if p is not None else (False,)):
            for tgt in ("rr", "range"):
                s, st, tg = AM.signals(x, p, htf, 6, 12, 2.0, tgt, smt)
                t = L.simulate(xx, s, st, tg, C, 2, exit_hm, 96 if htf == 240 else 48)
                if len(t) < 10:
                    rows.append({"market": name, "htf": htf, "smt": smt, "target": tgt, "n": len(t)}); continue
                h = t["day"] < split
                rows.append({"market": name, "htf": htf, "smt": smt, "target": tgt, "n": len(t),
                             "per_wk": round(len(t) / max((t.day.max() - t.day.min()).days / 7, 1), 1), "win%": round((t.r > 0).mean() * 100),
                             "avgR": round(t.r.mean(), 3), "tune": round(t[h].r.mean(), 3) if h.any() else np.nan,
                             "test": round(t[~h].r.mean(), 3) if (~h).any() else np.nan, "gross%": round((t.pct + C).mean(), 3),
                             "stop%": round(t.stop_pct.median(), 2)})
    print(name, "done", flush=True)
d = pd.DataFrame(rows); d.to_csv(f"{S}/amd_results.csv", index=False)
pd.set_option("display.width", 220); pd.set_option("display.max_rows", 200); print(d.to_string(index=False))
