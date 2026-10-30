"""Robustness of the 12-1 momentum result (research/swing_daily.py): survivorship, costs, size of book, timing.

Survivorship: the stock list is today's F&O list, so early years include stocks that only became big later by
rising. Fixes tried: (a) only stocks in the top 100 by 60-day traded value on the decision date; (b) only stocks
with 3+ years of history on the decision date; (c) start the test in 2018 / 2021 when the list is closer to the
tradable one. Plus costs 0.3%, top 20 / top 30 names, 2-month rebalance, a 1-week delay.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import swing_daily as S  # noqa: E402


def load_vol():
    v = {}
    for sym in S.U.FNO_SECTOR_OF:
        f = S.DATA / f"{sym.replace(' ', '_').replace('&', 'and')}.csv"
        if f.exists():
            df = pd.read_csv(f, parse_dates=["Date"]).drop_duplicates("Date").set_index("Date").sort_index()
            v[sym] = df["Volume"]
    return pd.DataFrame(v)


def topn_weights(score, dates, n):
    W = pd.DataFrame(np.nan, index=score.index, columns=score.columns)
    for d in dates:
        s = score.loc[d].dropna()
        if len(s) < n * 2:
            continue
        row = pd.Series(0.0, index=score.columns)
        row[s.nlargest(n).index] = 1 / n
        W.loc[d] = row
    return W.ffill().fillna(0)


def main():
    O, C = S.load()
    V = load_vol().reindex(index=C.index, columns=C.columns)
    alive = C.notna() & O.notna()
    tv = (C * V).rolling(60, min_periods=40).mean()
    liquid = tv.rank(axis=1, ascending=False) <= 100
    seasoned = C.notna().cumsum() >= 750
    me = S.rebalance_dates(C.index, "M")
    mom = C.shift(21) / C.shift(252) - 1
    bench_all = S.book_returns(alive.div(alive.sum(axis=1), axis=0).fillna(0), O)
    rows = {}

    def run(label, universe, n=20, dates=me, cost=S.COST, start=S.START, lag=0):
        S.COST = cost
        sc = mom.where(alive & universe)
        W = topn_weights(sc, dates, n)
        if lag:
            W = W.shift(lag).fillna(0)
        ub = (alive & universe)
        bench = S.book_returns(ub.div(ub.sum(axis=1), axis=0).fillna(0), O)
        S.START = start
        st = S.stats(S.book_returns(W, O), bench)
        st["bench CAGR %"] = S.stats(bench)["CAGR %"]
        rows[label] = st
        S.COST, S.START = 0.0012, "2013-01-01"

    run("All F&O list, top 20", alive)
    run("Top 100 by traded value, top 20", liquid)
    run("Top 100 by value + 3 yrs history, top 20", liquid & seasoned)
    run("Top 100 by value, top 10", liquid, n=10)
    run("Top 100 by value, top 30", liquid, n=30)
    run("Top 100 by value, cost 0.3%", liquid, cost=0.003)
    run("Top 100 by value, rebalance every 2 months", liquid, dates=me[::2])
    run("Top 100 by value, 5-day delay", liquid, lag=5)
    run("Top 100 by value, from 2018", liquid, start="2018-01-01")
    run("Top 100 by value, from 2021", liquid, start="2021-01-01")
    t = pd.DataFrame(rows).T
    pd.set_option("display.width", 260)
    print(t.to_string())
    t.to_csv(S.OUT / "momentum_robust.csv")


if __name__ == "__main__":
    main()
