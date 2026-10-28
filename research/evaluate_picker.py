"""Evaluate the out-of-sample F&O picks against simple rules and random choice."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from picker import simulate, summarize

D = Path(__file__).parent / "data"
RNG = np.random.default_rng(7)


def selections(p: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, np.ndarray]]:
    """name -> (picked rows, direction +1/-1). One or two picks per day."""
    out = {}
    p = p.copy()
    p["p_mover"] = p["p_up3"] + p["p_dn3"]
    p["p_edge"] = p["p_up3"] - p["p_dn3"]
    p["rand"] = RNG.random(len(p))
    for k in (1, 2):
        s = p.sort_values(["Date", "p_mover"], ascending=[True, False]).groupby("Date").head(k)
        out[f"ML mover top{k} (direction = higher of up/down)"] = (s, np.where(s.p_up3 >= s.p_dn3, 1, -1))
        s = p.sort_values(["Date", "p_up3"], ascending=[True, False]).groupby("Date").head(k)
        out[f"ML long-only top{k}"] = (s, np.ones(len(s)))
        s = p.sort_values(["Date", "p_dn3"], ascending=[True, False]).groupby("Date").head(k)
        out[f"ML short-only top{k}"] = (s, -np.ones(len(s)))
        s = p.sort_values(["Date", "atr_pct"], ascending=[True, False]).groupby("Date").head(k)
        out[f"Rule: highest ATR%, gap direction top{k}"] = (s, np.where(s.gap >= 0, 1, -1))
        s = p.sort_values(["Date", "abs_gap"], ascending=[True, False]).groupby("Date").head(k)
        out[f"Rule: biggest gap, go with gap top{k}"] = (s, np.where(s.gap >= 0, 1, -1))
        out[f"Rule: biggest gap, fade gap top{k}"] = (s, np.where(s.gap >= 0, -1, 1))
        s = p.sort_values(["Date", "vol_z"], ascending=[True, False]).groupby("Date").head(k)
        out[f"Rule: volume surge yesterday, follow yesterday top{k}"] = (s, np.where(s.oc1 >= 0, 1, -1))
        s = p.sort_values(["Date", "rand"]).groupby("Date").head(k)
        out[f"Random stock, random side top{k}"] = (s, np.where(RNG.random(len(s)) > .5, 1, -1))
    return out


def hit_table(sel) -> pd.DataFrame:
    rows = []
    for name, (s, dirn) in sel.items():
        fav = np.where(dirn > 0, s.up_move, s.dn_move)
        adv = np.where(dirn > 0, s.dn_move, s.up_move)
        cl = np.where(dirn > 0, s.oc_move, -s.oc_move)
        rows.append({"selection": name, "picks": len(s),
                     "moved 3%+ my way": round(100 * (fav >= .03).mean(), 1),
                     "moved 3%+ either way": round(100 * ((s.up_move >= .03) | (s.dn_move >= .03)).mean(), 1),
                     "went 1% against first-or-later": round(100 * (adv >= .01).mean(), 1),
                     "avg open->close my way %": round(100 * cl.mean(), 3),
                     "median favorable %": round(100 * np.median(fav), 2), "median adverse %": round(100 * np.median(adv), 2)})
    return pd.DataFrame(rows)


def trade_grid(sel, names, stops=(0.0075, 0.01, 0.015, 0.02), targets=(0.02, 0.03, 0.04, 9.0), cost=0.0012):
    rows = []
    for name in names:
        s, dirn = sel[name]
        for st in stops:
            for tg in targets:
                for pess in (True, False):
                    pnl = pd.Series(simulate(s, dirn, st, tg, cost, pess), index=s.index)
                    rows.append({"selection": name, "stop%": st * 100, "target%": "close" if tg > 1 else tg * 100,
                                 "fill": "stop first" if pess else "target first", **summarize(pnl, s.Date)})
    return pd.DataFrame(rows)


def yearly(sel, name, stop, target, cost=0.0012):
    s, dirn = sel[name]
    out = {}
    for pess in (True, False):
        pnl = pd.Series(simulate(s, dirn, stop, target, cost, pess), index=s.index)
        out["stop first" if pess else "target first"] = (pnl.groupby(s.Date.dt.year).sum() * 100).round(1)
    fav = pd.Series(np.where(dirn > 0, s.up_move, s.dn_move) >= .03, index=s.index)
    out["hit 3% my way %"] = (fav.groupby(s.Date.dt.year).mean() * 100).round(1)
    return pd.DataFrame(out)


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_rows", 300, "display.max_columns", 30)
    p = pd.read_parquet(D / "picker_oos.parquet")
    print("Out-of-sample:", p.Date.min().date(), "to", p.Date.max().date(), len(p), "stock-days")
    for t in ("up3", "dn3", "up2", "dn2"):
        print(f"  AUC {t}: {roc_auc_score(p[t], p['p_' + t]):.3f}  base rate {p[t].mean():.3f}")
    sel = selections(p)
    ht = hit_table(sel)
    ht.to_csv(D / "picker_hits.csv", index=False)
    print(ht.to_string(index=False))
    names = [n for n in sel if "top1" in n or "top2" in n]
    tg = trade_grid(sel, names)
    tg.to_csv(D / "picker_trades.csv", index=False)
    best = tg[tg.fill == "stop first"].sort_values("sharpe", ascending=False).head(15)
    print("\nBest by Sharpe (pessimistic fills):")
    print(best.to_string(index=False))
