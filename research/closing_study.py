"""Do the last 30 minutes predict the next day? For every F&O stock and day, readings at 15:15 (last 30 min: return,
money-flow share, net money vs usual, volume vs usual; the day: return, close location in the range; sector money in
the last 30 min) -> next day's open (gap) and close, from the 15:15 price, 0.12% costs (delivery / overnight).
Usage: python research/closing_study.py <stocks_5m.pkl>"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import universe as U  # noqa: E402

CUT = "15:15"   # decide on the 15:10 candle's close (known at 15:15), buy at the 15:15 candle's open


def rows_for(sym, df):
    d = df[~df.index.duplicated(keep="last")].sort_index()
    d = d[(d.index.strftime("%H:%M") >= "09:15") & (d.index.strftime("%H:%M") <= "15:25")]
    if d.empty:
        return []
    d = d.assign(day=d.index.normalize(), t=d.index.strftime("%H:%M"))
    turn = d["Volume"] * (d["High"] + d["Low"] + d["Close"]) / 3
    rng = (d["High"] - d["Low"]).replace(0, np.nan)
    press = ((d["Close"] - d["Open"]) / rng).fillna(0)
    d["inf"], d["outf"] = turn * (1 + press) / 2, turn * (1 - press) / 2
    out = []
    days = sorted(d["day"].unique())
    turn_day = d.groupby("day").apply(lambda x: (x["inf"] + x["outf"]).sum())
    vol30 = d[(d["t"] >= "14:45") & (d["t"] < CUT)].groupby("day")["Volume"].sum()
    for i, day in enumerate(days[1:-1], start=1):
        x = d[d["day"] == day]
        pre = x[x["t"] < CUT]
        if len(pre) < 60:
            continue
        last30 = pre[pre["t"] >= "14:45"]
        prev_close = float(d[d["day"] == days[i - 1]]["Close"].iloc[-1])
        entry_bar = x[x["t"] == CUT]
        if entry_bar.empty or last30.empty:
            continue
        entry = float(entry_bar["Open"].iloc[0])
        nxt = d[d["day"] == days[i + 1]]
        if nxt.empty:
            continue
        hi, lo, c = float(pre["High"].max()), float(pre["Low"].min()), float(pre["Close"].iloc[-1])
        inf, outf = float(last30["inf"].sum()), float(last30["outf"].sum())
        usual_turn = turn_day.iloc[max(0, i - 20):i].mean()
        usual_v30 = vol30.reindex(days[max(0, i - 20):i]).mean()
        out.append({"sym": sym, "day": day, "ret_day": (c / prev_close - 1) * 100,
                    "ret_30": (c / float(last30["Open"].iloc[0]) - 1) * 100,
                    "clv": (c - lo) / (hi - lo) if hi > lo else 0.5,
                    "flow_30": inf / (inf + outf) if inf + outf > 0 else 0.5,
                    "net_30_x": (inf - outf) / usual_turn * 100 if usual_turn else np.nan,
                    "vol_30_x": float(last30["Volume"].sum()) / usual_v30 if usual_v30 else np.nan,
                    "net_30": (inf - outf) / 1e7,
                    "gap": (float(nxt["Open"].iloc[0]) / entry - 1) * 100,
                    "next_close": (float(nxt["Close"].iloc[-1]) / entry - 1) * 100})
    return out


if __name__ == "__main__":
    bars = pickle.load(open(sys.argv[1], "rb"))
    T = pd.DataFrame([r for s, df in bars.items() if s in U.FNO_SECTOR_OF for r in rows_for(s, df)])
    T["sector"] = T["sym"].map(U.FNO_SECTOR_OF)
    T["sec_net_30"] = T.groupby(["day", "sector"])["net_30"].transform("sum")
    T["mkt_ret_30"] = T.groupby("day")["ret_30"].transform("mean")
    T.to_parquet(os.path.join(os.path.dirname(sys.argv[1]), "closing_T.parquet"))
    days = np.sort(T["day"].unique())
    mid = days[len(days) // 2]
    print(f"{len(T):,} stock-days, {len(days)} days")

    def rep(m, side, label):
        x = T[m]
        if len(x) < 20:
            print(f"  {label:58s} n {len(x)}")
            return
        g, c = side * x["gap"] - 0.12, side * x["next_close"] - 0.12
        d = c.groupby(x["day"]).mean()
        tt = d.mean() / d.std() * np.sqrt(len(d)) if d.std() > 0 else 0
        print(f"  {label:58s} n {len(x):5d} | sell at next open {g.mean():+.3f}% win {(g > 0).mean() * 100:3.0f}% | "
              f"at next close {c.mean():+.3f}% (t days {tt:+.1f}, halves {d[d.index < mid].mean():+.3f}/{d[d.index >= mid].mean():+.3f})")
    rep(T["ret_day"].notna(), 1, "all (buy every stock at 15:15)")
    rep((T["flow_30"] >= 0.6) & (T["net_30_x"] >= 2), 1, "LONG: last 30 min money 60%+ buying, net >= 2% of a day")
    rep((T["flow_30"] >= 0.6) & (T["net_30_x"] >= 2) & (T["clv"] >= 0.8), 1, "  + closing near the day high (top 20%)")
    rep((T["flow_30"] >= 0.6) & (T["net_30_x"] >= 2) & (T["clv"] >= 0.8) & (T["vol_30_x"] >= 1.3), 1, "  + last 30 min volume 1.3x+")
    rep((T["flow_30"] >= 0.6) & (T["net_30_x"] >= 2) & (T["clv"] >= 0.8) & (T["sec_net_30"] > 0), 1, "  + sector money in (last 30 min)")
    rep((T["clv"] >= 0.9) & (T["ret_day"] >= 2), 1, "LONG: strong day (+2%) closing at the high")
    rep((T["flow_30"] <= 0.4) & (T["net_30_x"] <= -2) & (T["clv"] <= 0.2), -1, "SHORT: last 30 min selling, closing near the low")
    rep((T["clv"] <= 0.1) & (T["ret_day"] <= -2), -1, "SHORT: weak day (-2%) closing at the low")
    rep((T["clv"] <= 0.1) & (T["ret_day"] <= -2), 1, "REVERSAL LONG: buy weak day (-2%) closing at the low")
    rep((T["clv"] >= 0.9) & (T["ret_day"] >= 2), -1, "REVERSAL SHORT: strong day closing at the high")
