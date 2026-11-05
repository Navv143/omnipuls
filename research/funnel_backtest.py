"""Backtest of the Momentum Funnel (5 steps) with its trade plan (funnel.trade_plan / funnel.simulate).

Every F&O stock, every 5-minute candle 9:30-14:00: the first candle of the day where all 5 steps pass is the signal;
entry at the next candle's open, stop / targets from the plan, exit by 15:15, 0.12% costs.
Usage: python research/funnel_backtest.py [bars.pkl]   (bars = {symbol: 5-minute OHLCV}; default: Setup Finder cache)
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import funnel as FN  # noqa: E402
import index_funnel as IF  # noqa: E402
import universe as U  # noqa: E402


def readings(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    t = IF.index_table(df, {sym: df}, {sym: 100}, None)
    if t.empty:
        return t
    d = t.groupby("day").agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    pc = d["c"].shift(1)
    tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean().shift(1)
    t["atr14"] = t["day"].map(atr14)
    t["prev_rng_atr"] = t["day"].map(((d["h"] - d["l"]).shift(1)) / atr14)
    g = t.groupby("day")
    t["swing_low"] = g["Low"].transform(lambda x: x.rolling(6, min_periods=1).min())
    t["swing_high"] = g["High"].transform(lambda x: x.rolling(6, min_periods=1).max())
    t["sym"] = sym
    return t


def run(bars: dict, cfg: dict | None = None) -> pd.DataFrame:
    c = {**FN.DEFAULTS, **(cfg or {})}
    parts = [readings(s, df) for s, df in bars.items() if s in U.FNO_SECTOR_OF]
    T = pd.concat([p for p in parts if not p.empty])
    T["ts"] = T.index
    T["sector"] = T["sym"].map(U.FNO_SECTOR_OF)
    T["sec_net"] = T.groupby(["ts", "sector"])["net"].transform("sum")
    T["mkt_move"] = T.groupby("ts")["move_pct"].transform("mean")
    s_ = T["side"]
    T["step1"] = (T["day_x"] >= c["day_x"]) & (T["now_x"] >= c["now_x"]) & (s_ != 0)
    T["step2"] = T["step1"] & (T["range_x"] >= c["range_x"])
    T["step3"] = T["step2"] & (np.sign(T["sec_net"]) == s_)
    T["step4"] = T["step3"] & (np.sign(T["net"]) == s_) & (s_ * (T["net"] - T["net_before"]) > 0)
    T["step5"] = T["step4"] & (np.sign(T["mkt_move"]) == s_) & ~(T["prev_rng_atr"].fillna(1) >= c["wide_yday"])
    sig = T[T["step5"] & (T["m"] + 5 >= 570) & (T["m"] + 5 <= 840) & T["atr14"].notna()]
    sig = sig.sort_values("ts").groupby(["sym", "day"]).head(1)
    rows = []
    for _, r in sig.iterrows():
        b = bars[r["sym"]]
        day_b = b[b.index.normalize() == r["day"]]
        after = day_b[day_b.index > r["ts"]]
        if after.empty:
            continue
        entry = float(after["Open"].iloc[0])
        p = FN.trade_plan(int(r["side"]), entry, float(r["atr14"]), float(r["swing_low"]), float(r["swing_high"]))
        if not p:
            continue
        res = FN.simulate(int(r["side"]), entry, p["sl"], p["tp1"], p["tp2"], after)
        if res:
            rows.append({"day": r["day"], "time": (r["ts"] + pd.Timedelta(minutes=5)).strftime("%H:%M"), "sym": r["sym"],
                         "side": p["side"], "entry": entry, "sl": p["sl"], "tp1": p["tp1"], "tp2": p["tp2"],
                         "risk_pct": p["risk_pct"], "day_x": r["day_x"], "range_x": r["range_x"], **res})
    return pd.DataFrame(rows)


def report(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0}
    d = tr.groupby("day")["pct"].mean()
    days = np.sort(tr["day"].unique())
    mid = days[len(days) // 2]
    f = lambda x: {"n": int(len(x)), "pct": round(float(x.mean()), 3), "t": round(float(x.mean() / x.std() * np.sqrt(len(x))), 2) if len(x) > 2 and x.std() > 0 else 0}  # noqa: E731
    return {"trades": int(len(tr)), "days": int(len(days)), "per_day": round(len(tr) / len(days), 1),
            "avg_pct": round(float(tr["pct"].mean()), 3), "avg_r": round(float(tr["r"].mean()), 3),
            "win": round(float((tr["pct"] > 0).mean() * 100), 1), "by_day": f(d), "first_half": f(d[d.index < mid]),
            "second_half": f(d[d.index >= mid]), "outcomes": tr["outcome"].value_counts().to_dict(),
            "first3": f(tr.sort_values("time").groupby("day").head(3).groupby("day")["pct"].mean())}


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if src:
        bars = pickle.load(open(src, "rb"))
    else:
        import bot as B
        bars = {f.stem.replace("_and_", "&"): pd.read_parquet(f) for f in B.CACHE.glob("*.parquet")}
    tr = run(bars)
    print(report(tr))
