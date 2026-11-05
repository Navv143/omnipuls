"""What separates the Momentum Funnel's winners from its losers? Every signal of research/funnel_backtest.py (first
candle per stock and day where all 5 steps pass, 9:30-14:00) with its readings at entry and the bots' managed exit
(funnel.manage), then each reading split into thirds: average managed R per third, in both halves of the period.
Usage: python research/funnel_winners.py bars.pkl [cutoff YYYY-MM-DD]
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import funnel as FN  # noqa: E402
import funnel_backtest as FB  # noqa: E402
import universe as U  # noqa: E402


def signals_with_features(bars: dict) -> pd.DataFrame:
    c = FN.DEFAULTS
    parts = [FB.readings(s, df) for s, df in bars.items() if s in U.FNO_SECTOR_OF]
    T = pd.concat([p for p in parts if not p.empty])
    T["ts"] = T.index
    T["sector"] = T["sym"].map(U.FNO_SECTOR_OF)
    T["sec_net"] = T.groupby(["ts", "sector"])["net"].transform("sum")
    T["mkt_move"] = T.groupby("ts")["move_pct"].transform("mean")
    s_ = T["side"]
    T["step5"] = ((T["day_x"] >= c["day_x"]) & (T["now_x"] >= c["now_x"]) & (s_ != 0) & (T["range_x"] >= c["range_x"])
                  & (np.sign(T["sec_net"]) == s_) & (np.sign(T["net"]) == s_) & (s_ * (T["net"] - T["net_before"]) > 0)
                  & (np.sign(T["mkt_move"]) == s_) & ~(T["prev_rng_atr"].fillna(1) >= c["wide_yday"]))
    sig = T[T["step5"] & (T["m"] + 5 >= 570) & (T["m"] + 5 <= 840) & T["atr14"].notna()]
    sig = sig.sort_values("ts").groupby(["sym", "day"]).head(1)
    rows = []
    for _, r in sig.iterrows():
        b = bars[r["sym"]]
        day_b = b[b.index.normalize() == r["day"]]
        before, after = day_b[day_b.index <= r["ts"]], day_b[day_b.index > r["ts"]]
        if after.empty or before.empty:
            continue
        side = int(r["side"])
        entry = float(after["Open"].iloc[0])
        p = FN.trade_plan(side, entry, float(r["atr14"]), float(r["swing_low"]), float(r["swing_high"]))
        if not p:
            continue
        mg = FN.manage(side, entry, p["sl"], p["tp1"], p["tp2"], after)
        if not mg or mg.get("exit_r") is None:
            continue
        tp = (before["High"] + before["Low"] + before["Close"]) / 3
        vol = before["Volume"].replace(0, np.nan)
        vwap = float((tp * vol).sum() / vol.sum()) if vol.notna().any() else float(before["Close"].mean())
        day_open = float(before["Open"].iloc[0])
        hist = b[b.index.normalize() < r["day"]]
        prev_close = float(hist["Close"].iloc[-1]) if len(hist) else day_open
        a = float(r["atr14"])
        rows.append({
            "day": r["day"], "time": (r["ts"] + pd.Timedelta(minutes=5)).strftime("%H:%M"), "sym": r["sym"], "side": side,
            "R": float(mg["exit_r"]), "pct": float(mg.get("exit_pct") or 0), "best_R": mg.get("best_r"), "worst_R": mg.get("worst_r"),
            # readings at entry
            "day_x": r["day_x"], "now_x": r["now_x"], "range_x": r["range_x"],
            "net_cr": side * r["net"], "net_growth": side * (r["net"] - r["net_before"]),
            "sec_net": side * r["sec_net"], "mkt_with": side * r["mkt_move"],
            "ran_from_open_atr": side * (entry - day_open) / a,          # how far it had already run
            "gap_atr": side * (day_open - prev_close) / a,
            "vs_vwap_atr": side * (entry - vwap) / a,                    # stretched above VWAP?
            "stop_pct": p["risk_pct"], "prev_rng_atr": r["prev_rng_atr"],
            "minute": int(r["m"]) + 5,
            "last3_body": side * float((before["Close"].iloc[-1] - before["Open"].iloc[-3]) / a) if len(before) >= 3 else np.nan,
        })
    return pd.DataFrame(rows)


def compare(d: pd.DataFrame) -> pd.DataFrame:
    feats = ["minute", "day_x", "now_x", "range_x", "net_cr", "net_growth", "sec_net", "mkt_with", "ran_from_open_atr",
             "gap_atr", "vs_vwap_atr", "stop_pct", "prev_rng_atr", "last3_body"]
    days = np.sort(d["day"].unique())
    mid = days[len(days) // 2]
    out = []
    for f in feats:
        x = d[[f, "R", "day"]].dropna()
        if len(x) < 30:
            continue
        q = pd.qcut(x[f].rank(method="first"), 3, labels=["low", "mid", "high"])
        g = x.groupby(q, observed=True)["R"].mean()
        h1 = x[x.day < mid].groupby(q[x.day < mid], observed=True)["R"].mean()
        h2 = x[x.day >= mid].groupby(q[x.day >= mid], observed=True)["R"].mean()
        cuts = x.groupby(q, observed=True)[f].agg(["min", "max"])
        out.append({"reading": f, "winners median": round(x[x.R > 0][f].median(), 3), "losers median": round(x[x.R <= 0][f].median(), 3),
                    "low third R": round(g.get("low", np.nan), 2), "mid third R": round(g.get("mid", np.nan), 2),
                    "high third R": round(g.get("high", np.nan), 2),
                    "high-low, half 1": round(h1.get("high", np.nan) - h1.get("low", np.nan), 2),
                    "high-low, half 2": round(h2.get("high", np.nan) - h2.get("low", np.nan), 2),
                    "low cut": f"≤{cuts.loc['low', 'max']:.2f}", "high cut": f"≥{cuts.loc['high', 'min']:.2f}"})
    return pd.DataFrame(out)


if __name__ == "__main__":
    bars = pickle.load(open(sys.argv[1], "rb"))
    cut = sys.argv[2] if len(sys.argv) > 2 else None
    if cut:
        bars = {k: v[v.index < cut] for k, v in bars.items()}
    d = signals_with_features(bars)
    d.to_csv(Path(sys.argv[1]).with_name("funnel_winners_trades.csv"), index=False)
    print(f"{len(d)} trades, {d['day'].nunique()} days, win {(d.R > 0).mean() * 100:.0f}%, avg managed R {d.R.mean():+.3f}, "
          f"avg % after costs {d.pct.mean():+.3f}")
    pd.set_option("display.width", 250)
    print(compare(d).to_string(index=False))
