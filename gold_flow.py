"""Gold Order Flow, live: the user's TradingView strategy "Order Flow + Structure + Order Blocks" on gold 15-minute
candles, ported line by line (research/my_scripts.py) and cross-checked against TradingView's Strategy Tester (the
same trades, Aug-Oct 2026). Backtest on 2 years of gold: 176 trades, +0.31% a trade after costs, 7 of 9 quarters
positive (PAXG on Binance, a gold-backed token that tracks XAU).

Rules:
- Order flow: up closes x (volume / its 20-candle average), and down closes the same way, each smoothed by EMA 7 then
  EMA 5. BUY when buy flow crosses above sell flow, SELL on the opposite cross.
- Structure (10-candle pivots): a buy needs bullish structure (last pivot high / low not lower than the one before),
  a sell bearish. "FULL" when price is also inside the latest order block (marked on the chart, not required).
- Stop 1.5%, target 3% from the signal candle's close; entry at the next candle's open; one trade at a time; a
  trade can run for days.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SL_PCT, TP_PCT = 1.5, 3.0
COST_PCT = 0.013  # ~0.5 $ a round trip on XAUUSD
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def _pivots(X, n, high):
    out = np.full(len(X), np.nan)
    for c in range(n, len(X) - n):
        win = X[c - n:c + n + 1]
        if high and X[c] == win.max() and X[c] > X[c - n:c].max():
            out[c + n] = X[c]
        if not high and X[c] == win.min() and X[c] < X[c - n:c].min():
            out[c + n] = X[c]
    return out


def to_15m(df5: pd.DataFrame) -> pd.DataFrame:
    return df5.resample("15min").agg(AGG).dropna(subset=["Close"])


def run(df: pd.DataFrame, length=10, ob_len=10) -> dict:
    """All trades on 15-minute candles (UTC index), the open one included, and the current state."""
    df = df.sort_index()
    O, H, L, C, V = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close", "Volume"))
    n = len(C)
    vb = V / _sma(V, 20)
    ch = np.diff(C, prepend=np.nan)
    bs = _ema(_ema(np.nan_to_num(np.where(ch > 0, ch * vb, 0)), 7), 5)
    ss = _ema(_ema(np.nan_to_num(np.where(ch < 0, -ch * vb, 0)), 7), 5)
    fb = (bs > ss) & np.r_[False, bs[:-1] <= ss[:-1]]
    fs = (ss > bs) & np.r_[False, ss[:-1] <= bs[:-1]]
    ph, pl = _pivots(H, length, True), _pivots(L, length, False)
    oph, opl = _pivots(H, ob_len, True), _pivots(L, ob_len, False)
    avgc, avgv = _sma(H - L, 20), _sma(V, 20)
    lastPH = prevPH = lastPL = prevPL = np.nan
    bull = bear = False
    bt = bb = brt = brb = np.nan
    trades, busy_until = [], -1
    for t in range(n):
        if np.isfinite(ph[t]):
            prevPH, lastPH = lastPH, ph[t]
        if np.isfinite(pl[t]):
            prevPL, lastPL = lastPL, pl[t]
        if lastPH > prevPH or lastPL > prevPL:
            bull, bear = True, False
        if lastPH < prevPH or lastPL < prevPL:
            bear, bull = True, False
        for piv, want_red, is_bull in ((opl[t], True, True), (oph[t], False, False)):
            if np.isfinite(piv):
                for i in range(1, ob_len + 1):
                    j = t - (ob_len + i)
                    if j < 1:
                        break
                    if (C[j] < O[j]) if want_red else (C[j] > O[j]):
                        imp = j + 1
                        if (H[imp] - L[imp]) >= avgc[imp] * 1.5 and V[imp] >= avgv[imp] * 1.2:
                            if is_bull:
                                bt, bb = H[j], L[j]
                            else:
                                brt, brb = H[j], L[j]
                        break
        if t <= busy_until:
            continue
        in_bull = np.isfinite(bt) and bb <= C[t] <= bt
        in_bear = np.isfinite(brt) and brb <= C[t] <= brt
        for side, sig, full in ((1, fb[t] and bull, in_bull), (-1, fs[t] and bear, in_bear)):
            if not sig:
                continue
            ref = C[t]
            stop, tgt = ref * (1 - side * SL_PCT / 100), ref * (1 + side * TP_PCT / 100)
            tr = {"signal_time": df.index[t], "side": side, "kind": "FULL" if full else "base", "ref": ref,
                  "stop": stop, "target": tgt, "entry": None, "entry_time": None, "exit": None, "exit_time": None,
                  "state": "waiting for next candle", "pct": None}
            if t + 1 < n:
                tr["entry"], tr["entry_time"] = O[t + 1], df.index[t + 1]
                tr["state"] = "open"
                for j in range(t + 1, n):
                    if (side > 0 and L[j] <= stop) or (side < 0 and H[j] >= stop):
                        tr.update(exit=stop, exit_time=df.index[j], state="stopped")
                        break
                    if (side > 0 and H[j] >= tgt) or (side < 0 and L[j] <= tgt):
                        tr.update(exit=tgt, exit_time=df.index[j], state="target hit")
                        break
                px = tr["exit"] if tr["exit"] is not None else C[-1]
                tr["pct"] = side * (px / tr["entry"] - 1) * 100
                busy_until = next((j for j in range(t + 1, n) if df.index[j] == tr["exit_time"]), n)
            else:
                busy_until = n
            trades.append(tr)
            break
    state = {"flow": "Buy dominant" if bs[-1] > ss[-1] else "Sell dominant",
             "structure": "Bullish (HH+HL)" if bull else "Bearish (LH+LL)" if bear else "Ranging",
             "in_ob": "In bull OB" if np.isfinite(bt) and bb <= C[-1] <= bt else
                      "In bear OB" if np.isfinite(brt) and brb <= C[-1] <= brt else "Outside OB",
             "last": C[-1], "time": df.index[-1]}
    return {"trades": trades, "state": state}
