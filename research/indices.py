"""NSE index edges: classic, pre-specified rules tested in two separate periods (2012-2019 and 2020-2026).

Rules use textbook parameters (not tuned here), so the second period is a genuine out-of-sample check.
Costs: 0.05% per round trip for index futures (brokerage, STT, charges, slippage).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nse_data import load, rsi

COST = 0.0005
INDICES = {"NIFTY": "nifty 50", "BANKNIFTY": "nifty bank", "FINNIFTY": "nifty financial services",
           "NIFTY IT": "nifty it", "NIFTY METAL": "nifty metal", "NIFTY PHARMA": "nifty pharma",
           "NIFTY AUTO": "nifty auto", "MIDCAP 100": "nifty midcap 100"}
PERIODS = {"2012-19": ("2012-01-01", "2019-12-31"), "2020-26": ("2020-01-01", "2026-12-31")}


def stats(r: pd.Series, in_mkt: pd.Series | None = None) -> dict:
    """r: daily strategy returns (0 when flat)."""
    r = r.dropna()
    trades = r[r != 0]
    yrs = len(r) / 250
    eq = (1 + r).cumprod()
    return {"days_in": len(trades), "win%": round(100 * (trades > 0).mean(), 1) if len(trades) else np.nan,
            "avg_trade%": round(100 * trades.mean(), 3) if len(trades) else np.nan,
            "CAGR%": round(100 * (eq.iloc[-1] ** (1 / yrs) - 1), 1) if yrs > 0 else np.nan,
            "sharpe": round(r.mean() / r.std() * np.sqrt(250), 2) if r.std() > 0 else np.nan,
            "maxDD%": round(100 * (eq / eq.cummax() - 1).min(), 1),
            "exposure%": round(100 * (r != 0).mean(), 0)}


def rules(d: pd.DataFrame, vix: pd.Series | None) -> dict[str, pd.Series]:
    """Each rule returns the strategy's daily return series."""
    o, h, l, c = d["Open"], d["High"], d["Low"], d["Close"]
    cc = c.pct_change()                  # close -> close
    on = o / c.shift(1) - 1              # overnight: close -> next open
    oc = c / o - 1                       # intraday: open -> close
    ibs = (c - l) / (h - l).replace(0, np.nan)
    ma200, ma50 = c.rolling(200).mean(), c.rolling(50).mean()
    r2 = rsi(c, 2)
    out = {}
    out["Buy & hold"] = cc
    out["Overnight only (buy close, sell open)"] = on - COST
    out["Intraday only (buy open, sell close)"] = oc - COST
    # Mean reversion, enter at today's close, exit next close
    sig = (ibs < 0.2).shift(1, fill_value=False)
    out["IBS<0.2 long next day"] = np.where(sig, cc - COST, 0.0)
    sig = (ibs > 0.8).shift(1, fill_value=False)
    out["IBS>0.8 short next day"] = np.where(sig, -cc - COST, 0.0)
    sig = ((r2 < 10) & (c > ma200)).shift(1, fill_value=False)
    out["RSI(2)<10 above MA200, long 1 day"] = np.where(sig, cc - COST, 0.0)
    # Hold until RSI(2) > 70 (Connors)
    pos = pd.Series(0.0, index=c.index)
    inpos = False
    for i in range(1, len(c)):
        if inpos and r2.iloc[i - 1] > 70:
            inpos = False
        if not inpos and r2.iloc[i - 1] < 10 and c.iloc[i - 1] > ma200.iloc[i - 1]:
            inpos = True
        pos.iloc[i] = 1.0 if inpos else 0.0
    turns = pos.diff().abs().fillna(0)
    out["RSI(2)<10 above MA200, hold to RSI>70"] = pos * cc - turns * COST / 2
    # Trend following
    pos = (c > ma200).shift(1).astype(float)
    out["Long when above MA200"] = pos * cc - pos.diff().abs().fillna(0) * COST / 2
    pos = (ma50 > ma200).shift(1).astype(float)
    out["Long when MA50>MA200"] = pos * cc - pos.diff().abs().fillna(0) * COST / 2
    # Turn of month: last trading day + first 3 of next month
    dom = c.groupby([c.index.year, c.index.month]).cumcount()
    from_end = c.groupby([c.index.year, c.index.month]).cumcount(ascending=False)
    tom = ((dom <= 2) | (from_end == 0)).astype(float)
    out["Turn of month (last day + first 3)"] = tom * cc - COST * tom
    # Gap behaviour (decided at 9:15)
    big_up, big_dn = on > 0.005, on < -0.005
    out["Gap up >0.5%: fade (short open->close)"] = np.where(big_up, -oc - COST, 0.0)
    out["Gap down >0.5%: buy (long open->close)"] = np.where(big_dn, oc - COST, 0.0)
    # Volatility regime
    if vix is not None:
        v = vix.reindex(c.index).ffill()
        vz = (v - v.rolling(60).mean()) / v.rolling(60).std()
        sig = (vz > 2).shift(1, fill_value=False)
        out["VIX spike (z>2): long next day"] = np.where(sig, cc - COST, 0.0)
    # Day of week (open->close)
    for i, nm in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"]):
        out[f"{nm} intraday long"] = np.where(c.index.dayofweek == i, oc - COST, 0.0)
    return {k: pd.Series(v, index=c.index) for k, v in out.items()}


def run() -> pd.DataFrame:
    vix = load("india vix")
    vixc = vix["Close"] if vix is not None else None
    rows = []
    for nm, f in INDICES.items():
        d = load(f)
        if d is None:
            continue
        for rule, r in rules(d, vixc).items():
            for per, (a, b) in PERIODS.items():
                s = stats(r[(r.index >= a) & (r.index <= b)])
                rows.append({"index": nm, "rule": rule, "period": per, **s})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_rows", 400, "display.max_columns", 20)
    t = run()
    t.to_csv("data/indices_results.csv", index=False)
    piv = t.pivot_table(index=["rule"], columns=["index", "period"], values="sharpe")
    print(piv.round(2).to_string())
