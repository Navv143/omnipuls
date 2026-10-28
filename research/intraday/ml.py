"""Walk-forward LightGBM: predict the stock's move from the decision time to 15:20 (in ATR units).
Train on all years before the test year (10-trading-day embargo), predict the test year. 2017 -> 2026."""
import sys
import numpy as np
import pandas as pd
import lightgbm as lgb

from panel import feature_cols

k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
p = pd.read_parquet(f"/home/claude/bt/panel_k{k}.parquet")
feats = feature_cols(p)
MODE = sys.argv[2] if len(sys.argv) > 2 else "xs"
if MODE == "xs":
    market = {"nifty_gap", "nifty_ret_k", "bank_gap", "bank_ret_k", "vix_prev", "vix_open_chg", "dow"}
    feats = [f for f in feats if f not in market]
    r = p["ret_eod_atr"].clip(-4, 4)
    y = r - r.groupby(p["date"]).transform("mean")
else:
    y = p["ret_eod_atr"].clip(-4, 4)
params = dict(objective="huber", alpha=1.0, learning_rate=0.03, num_leaves=31, min_data_in_leaf=800,
              feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10, verbose=-1, seed=7,
              deterministic=True, num_threads=8)
preds = []
imp = 0
days = np.sort(p["date"].unique())
for yr in range(2017, 2027):
    test = p["date"].dt.year == yr
    start = pd.Timestamp(f"{yr}-01-01")
    cut = days[max(np.searchsorted(days, start) - 10, 0)]
    train = p["date"] < cut
    m = lgb.train(params, lgb.Dataset(p.loc[train, feats], y[train]), num_boost_round=400)
    pr = m.predict(p.loc[test, feats])
    preds.append(pd.Series(pr, index=p.index[test]))
    imp = imp + pd.Series(m.feature_importance("gain"), index=feats)
    ic = np.corrcoef(pr, y[test])[0, 1]
    print(yr, "rows", test.sum(), "IC %.3f" % ic, flush=True)
p["pred"] = pd.concat(preds)
p = p[p["pred"].notna()]
p.to_parquet(f"/home/claude/bt/ml_oos_k{k}_{MODE}.parquet")
print((imp / imp.sum()).sort_values(ascending=False).head(20).round(3).to_string())
