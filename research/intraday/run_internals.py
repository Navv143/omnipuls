import numpy as np, pandas as pd, warnings, lightgbm as lgb; warnings.filterwarnings("ignore")
from engine import Data
import internals as IN
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 200)
d = Data()
FEATS = ["breadth_up_dir", "breadth_vwap_dir", "breadth_div", "pct_new_ext", "range_x", "vol_x", "vol_x_6", "net_z_dir",
         "cvd_div", "heavy_dir", "vwap_dist_dir", "day_move_dir", "move12_dir", "rsi_dir", "slot_t", "risk_atr"]
for index, cost in (("NIFTY 50", 6), ("NIFTY BANK", 12)):
    f = IN.build(d, index); ev = IN.events(d, index, f)
    ev["net"] = ev.pts - cost; ev["netR"] = ev.net / ev.risk; a = ev.date < "2022"
    ev.to_parquet(f"internals_events_{index.split()[-1]}.parquet")
    print(f"\n==================== {index}: {len(ev)} new 1-hour high/low events ({len(ev)/11.2:.0f}/yr)")
    print(f"FADE ALL: win {100*(ev.pts>0).mean():.1f}%  gross {ev.pts.mean():.1f} pts  net {ev.net.mean():.1f} pts  | 15-21 {ev.net[a].mean():.1f}  22-26 {ev.net[~a].mean():.1f}")
    print("Feature quintiles: avg NET points per fade (Q1 low .. Q5 high), in-sample | out-of-sample")
    for c in FEATS:
        try:
            q = pd.qcut(ev[c].rank(method="first"), 5, labels=False)
        except Exception:
            continue
        i = ev[a].groupby(q[a]).net.mean().round(1).tolist(); o = ev[~a].groupby(q[~a]).net.mean().round(1).tolist()
        print(f"  {c:17s} in {i}  | out {o}")
    # walk-forward model: predict net R of the fade
    params = dict(objective="huber", alpha=1.0, learning_rate=0.03, num_leaves=15, min_data_in_leaf=150, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=10, verbose=-1, seed=3, deterministic=True, num_threads=2)
    ev["pred"] = np.nan; y = ev.netR.clip(-3, 4)
    for yr in range(2018, 2027):
        tr = ev.date < pd.Timestamp(f"{yr}-01-01") - pd.Timedelta(days=14); te = ev.date.dt.year == yr
        m = lgb.train(params, lgb.Dataset(ev.loc[tr, FEATS], y[tr]), 300)
        ev.loc[te, "pred"] = m.predict(ev.loc[te, FEATS])
        # threshold = 70th percentile of in-sample predictions of the training years
        ev.loc[te, "thr"] = np.quantile(m.predict(ev.loc[tr, FEATS]), 0.7)
    oos = ev[ev.pred.notna()]
    sel = oos[oos.pred > oos.thr]
    yrs = sel.net.groupby(sel.date.dt.year).sum()
    print(f"MODEL (walk-forward, 2018-26 all out-of-sample): all fades {oos.net.mean():.1f} net pts (n={len(oos)}) | "
          f"model-picked top 30%: n={len(sel)} ({len(sel)/9.3:.0f}/yr) win {100*(sel.pts>0).mean():.1f}% net {sel.net.mean():.1f} pts, "
          f"t {sel.net.mean()/sel.net.std()*np.sqrt(len(sel)):.2f}, years + {(yrs>0).sum()}/{len(yrs)}, total {sel.net.sum():.0f}")
    print("  by year:", sel.net.groupby(sel.date.dt.year).mean().round(1).to_dict())
    imp = pd.Series(m.feature_importance("gain"), index=FEATS).sort_values(ascending=False)
    print("  most useful readings:", (imp / imp.sum()).round(2).head(8).to_dict())
    oos.to_parquet(f"internals_oos_{index.split()[-1]}.parquet")
