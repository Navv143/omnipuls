import sys, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
sym = sys.argv[1]
b = pd.read_parquet(f"idx5_{sym}.parquet")
b = b[(b.tm >= "09:30") & (b.tm <= "14:30") & b.atr.notna()]
yr = b.index.year
print(f"===== {sym}: {len(b)} bars 09:30-14:30 =====")
print("Buy a call / put at a random bar: avg option P&L %", round(b.opt_call.mean()*100, 2), round(b.opt_put.mean()*100, 2),
      "| win%", round((b.opt_call > 0).mean()*100, 1), round((b.opt_put > 0).mean()*100, 1))
# --- A. What is common at cumulative-delta flips?
feats = ["rsi", "rsi_d3", "macd_hist_atr", "vwap_atr", "ema_gap_atr", "bb_pctb", "bb_bw_rank", "vol_x", "range_x",
         "oi_chg3", "from_open_atr", "day_range_used", "cvd_n", "mins"]
flags = ["macd_flip_up", "macd_flip_dn", "ema_cross_up", "ema_cross_dn", "sweep_low", "sweep_high", "break_up", "break_dn"]
for ev, side in (("dlt_flip_up", "call"), ("dlt_flip_dn", "put")):
    e = b[b[ev]]
    print(f"\n--- {ev}: {len(e)} events ({len(e)/len(np.unique(b.index.date)):.2f}/day). Option {side}: avg {e['opt_'+side].mean()*100:+.2f}%  win {(e['opt_'+side]>0).mean()*100:.0f}%  (random bar {b['opt_'+side].mean()*100:+.2f}%)")
    print("   median at event vs all bars:", {f: (round(e[f].median(), 2), round(b[f].median(), 2)) for f in feats})
    print("   flag frequency within +-2 bars, event vs all:", {f: (round(e[f].mean()*100, 1), round(b[f].mean()*100, 1)) for f in flags})
    print("   buildup at event:", e.build3.value_counts(normalize=True).round(2).to_dict(), "all:", b.build3.value_counts(normalize=True).round(2).to_dict())
# --- B. single features: option P&L by quintile (call / put)
print("\n--- Option P&L by feature quintile (Q1 low .. Q5 high), call | put, avg % per trade")
rows = []
for f in feats + ["dlt3", "dlt6", "dlt12", "oi_chg_day", "gap", "vix", "d_pdh_atr", "d_pdl_atr", "body"]:
    q = pd.qcut(b[f], 5, labels=False, duplicates="drop")
    cm = b.groupby(q).opt_call.mean()*100; pm = b.groupby(q).opt_put.mean()*100
    rows.append([f] + [f"{x:+.1f}" for x in cm.values] + ["|"] + [f"{x:+.1f}" for x in pm.values])
print(pd.DataFrame(rows).to_string(index=False, header=False))
print("\n--- Flags: option P&L when flag true (call | put) vs base")
for f in flags:
    s = b[b[f]]
    print(f"{f:14s} n={len(s):6d} call {s.opt_call.mean()*100:+.2f}  put {s.opt_put.mean()*100:+.2f}")
for k, s in b.groupby("build3"):
    print(f"build3={k:12s} n={len(s):6d} call {s.opt_call.mean()*100:+.2f}  put {s.opt_put.mean()*100:+.2f}")
