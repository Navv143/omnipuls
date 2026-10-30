"""Positional (multi-day) setups on F&O stocks, daily bars 2013 - Oct 2026 (eod2_data, research/fetch_daily_nse.py).

Every portfolio is decided on day t's close and traded at day t+1's open (no look-ahead), equal weight, costs 0.12%
per round trip on the part of the book that changes. Benchmark = all F&O stocks equal weight (the same survivorship
bias: today's F&O list), so each rule is judged on what it adds over simply holding the universe.

Rules
  momentum 12-1 / 6-1 / 3-1: top 10% by return over the last 12/6/3 months skipping the last month, monthly
  52-week high: top 10% closest to their 52-week high, monthly
  low volatility: lowest 10% 60-day volatility, monthly
  short-term reversal: bottom 10% of last week's return, weekly
  pullback in uptrend: above 200-day average, RSI(2) < 10, hold 5 days (each signal its own trade)
  sector momentum: stocks of the 2 F&O sectors with the best 3-month return, monthly
  + long-short versions (top minus bottom 10%) for momentum and 52-week high

Usage (Omnipuls folder): .venv\\Scripts\\python research\\swing_daily.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import universe as U  # noqa: E402

DATA = HERE / "data" / "nse"
OUT = HERE / "results"
COST = 0.0012
START = "2013-01-01"


def load():
    o, c = {}, {}
    for sym in sorted(U.FNO_SECTOR_OF):
        f = DATA / f"{sym.replace(' ', '_').replace('&', 'and')}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Date"]).drop_duplicates("Date").set_index("Date").sort_index()
        df = df[df.index >= "2011-06-01"]
        if len(df) < 300:
            continue
        o[sym], c[sym] = df["Open"], df["Close"]
    O, C = pd.DataFrame(o), pd.DataFrame(c)
    # corporate actions / bad prints: a 25%+ overnight jump blocks the stock for 20 sessions around it
    jump = (O / C.shift(1) - 1).abs() > 0.25
    bad = jump.rolling(20, min_periods=1).max().shift(-10).fillna(0).astype(bool) | jump
    C, O = C.mask(bad), O.mask(bad)
    return O, C


def book_returns(weights: pd.DataFrame, O: pd.DataFrame) -> pd.Series:
    """weights decided at close t -> held from open t+1 to open t+2 ... daily open-to-open returns, minus costs."""
    r = (O.shift(-1) / O - 1)  # open t -> open t+1
    w = weights.shift(1).fillna(0)  # decided at close t-1, in from open t
    gross = (w * r.fillna(0)).sum(axis=1)
    turnover = w.diff().abs().sum(axis=1).fillna(0)
    return gross - turnover * COST / 2


def rebalance_dates(idx: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(s.groupby(idx.to_period(freq)).max().values)


def top_weights(score: pd.DataFrame, dates, q=0.1, bottom=False, ls=False) -> pd.DataFrame:
    W = pd.DataFrame(np.nan, index=score.index, columns=score.columns)
    for d in dates:
        s = score.loc[d].dropna()
        if len(s) < 30:
            continue
        n = max(int(len(s) * q), 5)
        hi = s.nlargest(n).index if not bottom else s.nsmallest(n).index
        row = pd.Series(0.0, index=score.columns)
        row[hi] = 1 / n
        if ls:
            lo = s.nsmallest(n).index if not bottom else s.nlargest(n).index
            row[lo] = -1 / n
        W.loc[d] = row
    return W.ffill().fillna(0)


def stats(r: pd.Series, bench: pd.Series | None = None) -> dict:
    r = r[r.index >= START]
    eq = (1 + r).cumprod()
    yrs = len(r) / 248
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
    out = {"CAGR %": round(100 * cagr, 1), "Sharpe": round(r.mean() / r.std() * np.sqrt(248), 2),
           "max DD %": round(100 * dd, 1), "yrs +": f"{int((yr > 0).sum())}/{len(yr)}",
           "2013-19 %/yr": round(100 * ((1 + r[r.index < "2020"]).prod() ** (248 / max(len(r[r.index < '2020']), 1)) - 1), 1),
           "2020-26 %/yr": round(100 * ((1 + r[r.index >= "2020"]).prod() ** (248 / max(len(r[r.index >= '2020']), 1)) - 1), 1),
           "2025 %": round(100 * yr.get(2025, np.nan), 1), "2026 %": round(100 * yr.get(2026, np.nan), 1)}
    if bench is not None:
        b = bench[bench.index >= START]
        ex = r - b.reindex(r.index).fillna(0)
        exy = ex.groupby(ex.index.year).sum()
        out["beats bench yrs"] = f"{int((exy > 0).sum())}/{len(exy)}"
        out["excess %/yr"] = round(100 * ex.mean() * 248, 1)
    return out


def rsi2(C: pd.DataFrame) -> pd.DataFrame:
    d = C.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def main():
    O, C = load()
    print(f"{C.shape[1]} stocks, {C.index.min():%Y-%m-%d} - {C.index.max():%Y-%m-%d}")
    idx = C.index
    month_ends, week_ends = rebalance_dates(idx, "M"), rebalance_dates(idx, "W")
    alive = C.notna() & O.notna()
    ew = alive.div(alive.sum(axis=1), axis=0).fillna(0)
    bench = book_returns(ew, O)
    res = {"Benchmark: all F&O stocks equal weight": stats(bench)}
    ret_d = C.pct_change(fill_method=None)
    for months in (12, 6, 3):
        score = C.shift(21) / C.shift(21 * (months + 1) - 21 * 0 if months else 21) - 1
        score = C.shift(21) / C.shift(21 * months) - 1
        W = top_weights(score.where(alive), month_ends)
        res[f"Momentum {months}-1 top 10%, monthly"] = stats(book_returns(W, O), bench)
        if months == 12:
            Wls = top_weights(score.where(alive), month_ends, ls=True)
            res["Momentum 12-1 long-short 10%"] = stats(book_returns(Wls, O))
    hi52 = C / C.rolling(250, min_periods=200).max()
    res["52-week high top 10%, monthly"] = stats(book_returns(top_weights(hi52.where(alive), month_ends), O), bench)
    res["52-week high long-short 10%"] = stats(book_returns(top_weights(hi52.where(alive), month_ends, ls=True), O))
    vol = ret_d.rolling(60).std()
    res["Low volatility 10%, monthly"] = stats(book_returns(top_weights((-vol).where(alive), month_ends), O), bench)
    wk = C / C.shift(5) - 1
    res["Short-term reversal: last week's worst 10%"] = stats(
        book_returns(top_weights(wk.where(alive), week_ends, bottom=True), O), bench)
    res["Last week's best 10% (continuation check)"] = stats(
        book_returns(top_weights(wk.where(alive), week_ends), O), bench)
    # pullback in uptrend: each signal held 5 days, book = average of open signals
    ma200 = C.rolling(200).mean()
    sig = (C > ma200) & (rsi2(C) < 10) & alive
    held = sig.astype(float).rolling(5, min_periods=1).sum().clip(upper=1)
    W = held.div(held.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    res["Pullback: above 200DMA, RSI(2)<10, hold 5 days"] = stats(book_returns(W, O), bench)
    # sector momentum
    sec_of = pd.Series(U.FNO_SECTOR_OF).reindex(C.columns)
    sec_ret = (C.shift(1) / C.shift(63) - 1).T.groupby(sec_of).mean().T
    W = pd.DataFrame(0.0, index=idx, columns=C.columns)
    Wm = pd.DataFrame(np.nan, index=idx, columns=C.columns)
    for d in month_ends:
        s = sec_ret.loc[d].drop("Other", errors="ignore").dropna()
        if len(s) < 4:
            continue
        top = s.nlargest(2).index
        members = [x for x in C.columns if sec_of[x] in top and alive.loc[d, x]]
        row = pd.Series(0.0, index=C.columns)
        if members:
            row[members] = 1 / len(members)
        Wm.loc[d] = row
    W = Wm.ffill().fillna(0)
    res["Sector momentum: best 2 sectors (3 months), monthly"] = stats(book_returns(W, O), bench)
    # momentum inside an index uptrend only (cash when Nifty is under its 200-day average)
    nifty = pd.read_csv(DATA / "nifty_50.csv", parse_dates=["Date"]).set_index("Date")["Close"].reindex(idx).ffill()
    up = (nifty > nifty.rolling(200).mean())
    score = C.shift(21) / C.shift(21 * 12) - 1
    W = top_weights(score.where(alive), month_ends).mul(up.astype(float), axis=0)
    res["Momentum 12-1 top 10%, only when Nifty > 200DMA"] = stats(book_returns(W, O), bench)
    t = pd.DataFrame(res).T
    pd.set_option("display.width", 250)
    print(t.to_string())
    t.to_csv(OUT / "swing_daily.csv")


if __name__ == "__main__":
    main()
