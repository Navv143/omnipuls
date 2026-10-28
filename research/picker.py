"""F&O morning picker: walk-forward ML that ranks stocks at 9:15 by the chance of a 3%+ move from the open.

Train on all years before the test year (with a 10-day gap), predict the test year, repeat.
Nothing from the test year is ever seen in training.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
DATA = Path(__file__).parent / "data"

FEATURES = [
    "gap", "abs_gap", "gap_atr", "gap_vs_mkt", "gap_vs_sec", "atr_pct", "atr5_atr20", "range1", "range1_atr", "nr7",
    "inside", "ibs", "ret1", "ret3", "ret5", "ret10", "ret20", "ret60", "ret1_atr", "oc1", "vol_z", "vol_ratio5",
    "deliv_pct", "deliv_chg", "trades_z", "qty_per_trade_chg", "dist_ma20", "dist_ma50", "dist_ma200", "pos_52w",
    "dist_52wh", "rsi14", "rsi2", "streak", "rel_ret5", "rel_ret20", "sec_ret1", "sec_ret5", "sec_gap", "mkt_gap",
    "mkt_ret1", "mkt_ret5", "mkt_ret20", "mkt_dist_ma50", "mkt_range1", "vix", "vix_chg5", "vix_z", "dow",
    "days_to_expiry", "expiry_week", "abs_gap_rk", "atr_pct_rk", "vol_z_rk", "ret1_rk", "ret5_rk", "ret20_rk",
    "range1_rk", "trades_z_rk", "gap_atr_rk", "deliv_chg_rk",
]
PARAMS = dict(objective="binary", learning_rate=0.04, num_leaves=31, min_child_samples=400, feature_fraction=0.7,
              bagging_fraction=0.7, bagging_freq=1, lambda_l2=5.0, n_estimators=300, verbose=-1, n_jobs=2)


def walk_forward(p: pd.DataFrame, targets: dict, first_test_year=2015, embargo_days=10, feats=FEATURES) -> pd.DataFrame:
    p = p.copy()
    for name, y in targets.items():
        p[name] = y.astype(int)
        p["p_" + name] = np.nan
    years = sorted(p.Date.dt.year.unique())
    for yr in [y for y in years if y >= first_test_year]:
        start = pd.Timestamp(f"{yr}-01-01")
        tr = p[p.Date < start - pd.Timedelta(days=embargo_days)]
        te = p.Date.dt.year == yr
        for name in targets:
            m = lgb.LGBMClassifier(**PARAMS)
            m.fit(tr[feats], tr[name])
            p.loc[te, "p_" + name] = m.predict_proba(p.loc[te, feats])[:, 1]
    return p[p.Date.dt.year >= first_test_year]


def importance(p: pd.DataFrame, target: str, feats=FEATURES) -> pd.Series:
    m = lgb.LGBMClassifier(**PARAMS).fit(p[feats], p[target])
    return pd.Series(m.booster_.feature_importance("gain"), index=feats).sort_values(ascending=False)


# ---------------------------------------------------------------- trade simulation on daily bars

def simulate(rows: pd.DataFrame, direction: np.ndarray, stop: float, target: float, cost: float = 0.0012,
             pessimistic: bool = True) -> np.ndarray:
    """Return % P&L per trade: enter at the open, stop and target as fractions of the open, else exit at close.

    Daily bars don't show which came first when both stop and target were touched. Pessimistic = stop first.
    cost = round-trip brokerage, taxes and slippage as a fraction (0.0012 = 0.12%).
    """
    up, dn, oc = rows["up_move"].to_numpy(), rows["dn_move"].to_numpy(), rows["oc_move"].to_numpy()
    fav = np.where(direction > 0, up, dn)
    adv = np.where(direction > 0, dn, up)
    close_pnl = np.where(direction > 0, oc, -oc)
    hit_stop, hit_tgt = adv >= stop, fav >= target
    if pessimistic:
        pnl = np.where(hit_stop, -stop, np.where(hit_tgt, target, close_pnl))
    else:
        pnl = np.where(hit_tgt, target, np.where(hit_stop, -stop, close_pnl))
    return pnl - cost


def summarize(pnl: pd.Series, dates: pd.Series) -> dict:
    daily = pnl.groupby(dates.values).sum()
    eq = daily.cumsum()
    dd = (eq - eq.cummax()).min()
    yrs = max((dates.max() - dates.min()).days / 365.25, 0.1)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    return {"trades": len(pnl), "win%": round(100 * (pnl > 0).mean(), 1), "avg%": round(100 * pnl.mean(), 3),
            "pf": round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else np.inf,
            "total%/yr": round(100 * daily.sum() / yrs, 1), "maxDD%": round(100 * dd, 1),
            "sharpe": round(daily.mean() / daily.std() * np.sqrt(250), 2) if daily.std() > 0 else np.nan}


def pick_top(p: pd.DataFrame, score: str, k: int, ascending=False) -> pd.DataFrame:
    return p.sort_values(["Date", score], ascending=[True, ascending]).groupby("Date").head(k)


if __name__ == "__main__":
    import time
    t0 = time.time()
    p = pd.read_parquet(DATA / "panel.parquet")
    targets = {"up3": p.up_move >= 0.03, "dn3": p.dn_move >= 0.03,
               "up2": p.up_move >= 0.02, "dn2": p.dn_move >= 0.02}
    res = walk_forward(p, targets)
    res.to_parquet(DATA / "picker_oos.parquet")
    print(f"walk-forward done in {time.time() - t0:.0f}s, test rows {len(res)}")
    for t in targets:
        aucs = res.groupby(res.Date.dt.year).apply(lambda g: roc_auc_score(g[t], g["p_" + t]))
        print(f"AUC {t}: overall {roc_auc_score(res[t], res['p_' + t]):.3f}  by year min {aucs.min():.3f} max {aucs.max():.3f}")
