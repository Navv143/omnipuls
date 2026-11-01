"""Walk-forward: LightGBM learns from ALL readings which bars make a call / put trade pay; trained only on earlier
years, tested on the next year. Trades: top predictions, max 2 per day per index, no overlap (60-min hold)."""
import sys, numpy as np, pandas as pd, lightgbm as lgb, warnings
warnings.filterwarnings("ignore")
sym = sys.argv[1]
b = pd.read_parquet(f"idx5_{sym}.parquet")
b = b[(b.tm >= "09:30") & (b.tm <= "14:30") & b.atr.notna()].copy()
b["build_code"] = b.build3.map({"long_build": 2, "short_cover": 1, "none": 0, "long_unwind": -1, "short_build": -2})
for f in [c for c in b.columns if b[c].dtype == bool]:
    b[f] = b[f].astype(int)
drop = {"o", "h", "l", "c", "oi", "delta", "cum_v", "cvd", "vwap", "day_hi", "day_lo", "orh", "orl", "pdh", "pdl", "pc",
        "poi", "atr", "tm", "build3", "fwd30", "fwd60", "mfe60_up", "mfe60_dn", "opt_call", "opt_put", "prem_call",
        "prem_put", "v"}
X = [c for c in b.columns if c not in drop]
b["year"] = b.index.year; b["date"] = b.index.date
params = dict(objective="regression", learning_rate=0.03, num_leaves=15, min_data_in_leaf=400, feature_fraction=0.7,
              bagging_fraction=0.7, bagging_freq=1, lambda_l2=10, verbose=-1, num_threads=2)
out = []
imp = pd.Series(0.0, index=X)
for Y in range(2017, 2024):
    tr, te = b[b.year < Y], b[b.year == Y]
    if te.empty: continue
    preds = {}
    for side in ("call", "put"):
        m = lgb.train(params, lgb.Dataset(tr[X], tr[f"opt_{side}"].clip(-0.3, 0.5)), num_boost_round=300)
        preds[side] = m.predict(te[X]); ptr = m.predict(tr[X])
        imp += pd.Series(m.feature_importance("gain"), index=X)
        preds[side + "_thr"] = {q: np.quantile(ptr, q) for q in (0.95, 0.98, 0.99)}
    te = te.assign(p_call=preds["call"], p_put=preds["put"])
    for q in (0.95, 0.98, 0.99):
        tc, tp = preds["call_thr"][q], preds["put_thr"][q]
        last_i, per_day = -99, {}
        pos = {t: i for i, t in enumerate(te.index)}
        for i, (t, r) in enumerate(te.iterrows()):
            if i - last_i < 12 or per_day.get(r.date, 0) >= 2: continue
            side = None
            if r.p_call >= tc and r.p_call - tc >= r.p_put - tp: side = "call"
            elif r.p_put >= tp: side = "put"
            if side:
                out.append(dict(q=q, year=Y, t=t, side=side, ret=r[f"opt_{side}"], fut=r.fwd60 * (1 if side == "call" else -1)))
                last_i = i; per_day[r.date] = per_day.get(r.date, 0) + 1
T = pd.DataFrame(out)
print(f"===== {sym} walk-forward (out-of-sample 2017-2023) =====")
for q, g in T.groupby("q"):
    by = g.groupby("year").ret.mean() * 100
    print(f"top {100-q*100:.0f}% predictions: {len(g)} trades ({len(g)/6.2:.0f}/yr)  option avg {g.ret.mean()*100:+.2f}%  win {(g.ret>0).mean()*100:.0f}%  "
          f"t {g.ret.mean()/g.ret.std()*np.sqrt(len(g)):.1f} | futures 60m {g.fut.mean()*100:+.3f}% | by year " + " ".join(f"{y%100}:{v:+.1f}" for y, v in by.items()))
print("most used readings:", (imp / imp.sum() * 100).sort_values(ascending=False).head(15).round(1).to_dict())
T.to_csv(f"idx_ml_trades_{sym}.csv", index=False)
