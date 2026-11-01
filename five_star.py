"""Bank Nifty 5-STAR Momentum, live (research/FINAL_SETUPS.md, Setup 1), on 5-minute bars.

BUY at a candle's close when all six are true (SELL is the mirror), on candles from 09:30 to 15:00, one trade a day:
  1. Trend: close above EMA 21, VWAP, VWMA 20 and Supertrend (10, 3)
  2. Volume: market turnover on this candle >= 1.5x its 20-day average for the same time of day
  3. Net volume: buying minus selling pressure of the stocks points the trade's way on this candle
  4. RSI(14) >= 65 (SELL <= 35)
  5. Momentum candle: range >= 1.5x the average of the last 20 candles, body >= 50% of the range, green (SELL red)
  6. Breadth: 60%+ of Nifty 50 stocks above their own VWAP (SELL 40% or fewer)
Entry at the signal close; stop = Supertrend; trail with the Supertrend; exit when price breaks it, or at 15:15.
As in the research, the index has no volume: VWAP / VWMA weights, market volume and net volume come from the
Nifty 100 stocks' turnover (price x volume) on each candle.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NIFTY50 = ("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL CIPLA "
           "COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR ICICIBANK INDIGO "
           "INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI MAXHEALTH NESTLEIND NTPC ONGC POWERGRID RELIANCE SBILIFE "
           "SHRIRAMFIN SBIN SUNPHARMA TCS TATACONSUM TMPV TATASTEEL TECHM TITAN TRENT ULTRACEMCO WIPRO").split()
BANK_HEAVY = ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"]
FIRST, LAST, SQUARE = "09:30", "15:00", "15:15"
CHECK_NAMES = ["Trend (EMA, VWAP, VWMA, Supertrend)", "Volume 1.5x usual", "Net volume with the move",
               "RSI 65+ / 35-", "Momentum candle", "Breadth 60%+ / 40%-"]


def _naive(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    i = pd.DatetimeIndex(df.index)
    df = df.copy()
    df.index = i.tz_convert("Asia/Kolkata").tz_localize(None) if i.tz is not None else i
    return df[~df.index.duplicated(keep="last")].sort_index().between_time("09:15", "15:25")


def supertrend(h, l, c, n=10, factor=3.0):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    mid = (h + l) / 2
    up, lo = mid + factor * atr, mid - factor * atr
    st = np.empty_like(c)
    st[0] = lo[0] if c[0] > up[0] else up[0]
    for i in range(1, len(c)):
        st[i] = max(lo[i], st[i - 1]) if c[i] > st[i - 1] else min(up[i], st[i - 1])
    return st


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    g = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    ls = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + g / ls.replace(0, np.nan))).to_numpy()


def market_internals(stocks: dict) -> pd.DataFrame:
    """Per 5-minute candle: market turnover, net (buy - sell) turnover, the 20-day same-slot averages, and the share
    of Nifty 50 stocks above their own VWAP."""
    turn, net, above, n50 = {}, {}, {}, {}
    for sym, df in stocks.items():
        d = _naive(df)
        if d.empty:
            continue
        rng = (d["High"] - d["Low"]).replace(0, np.nan)
        press = ((d["Close"] - d["Open"]) / rng).fillna(0)
        t = d["Close"] * d["Volume"]
        turn[sym], net[sym] = t, t * press
        if sym in NIFTY50:
            tp = (d["High"] + d["Low"] + d["Close"]) / 3
            day = d.index.normalize()
            vw = (tp * d["Volume"]).groupby(day).cumsum() / d["Volume"].groupby(day).cumsum().replace(0, np.nan)
            above[sym] = (d["Close"] > vw).astype(float).where(vw.notna())
            n50[sym] = vw.notna().astype(float)
    if not turn:
        return pd.DataFrame()
    T = pd.DataFrame(turn).sum(axis=1)
    N = pd.DataFrame(net).sum(axis=1)
    out = pd.DataFrame({"turnover": T, "net": N})
    out["slot"] = out.index.strftime("%H:%M")
    out["day"] = out.index.normalize()
    piv_t = out.pivot_table(index="day", columns="slot", values="turnover")
    piv_n = out.pivot_table(index="day", columns="slot", values="net").abs()
    avg_t = piv_t.rolling(20, min_periods=10).mean().shift(1).stack().rename("avg_turnover")
    avg_n = piv_n.rolling(20, min_periods=10).mean().shift(1).stack().rename("avg_abs_net")
    out = out.join(avg_t, on=["day", "slot"]).join(avg_n, on=["day", "slot"])
    out["vol_x"] = out["turnover"] / out["avg_turnover"]
    out["net_z"] = out["net"] / out["avg_abs_net"]
    if above:
        A = pd.DataFrame(above)
        out["breadth"] = A.mean(axis=1, skipna=True).reindex(out.index)
        out["breadth_n"] = A.notna().sum(axis=1).reindex(out.index)
    else:
        out["breadth"], out["breadth_n"] = np.nan, 0
    return out


def evaluate(bn: pd.DataFrame, internals: pd.DataFrame, st_n=10, st_f=3.0) -> dict:
    """Latest session: the six checks on every candle, today's signal (first all-six candle) and how it is going."""
    b = _naive(bn)
    if b.empty or internals is None or internals.empty:
        return {"status": "no data"}
    b = b.join(internals[["turnover", "net_z", "vol_x", "breadth"]], how="left")
    h, l, c, o = (b[x].to_numpy(float) for x in ("High", "Low", "Close", "Open"))
    w = b["turnover"].fillna(0).to_numpy()
    b["st"] = supertrend(h, l, c, st_n, st_f)
    b["ema"] = pd.Series(c, index=b.index).ewm(span=21, adjust=False).mean()
    b["vwma"] = (pd.Series(c * w, index=b.index).rolling(20).sum() / pd.Series(w, index=b.index).rolling(20).sum())
    day = b.index.normalize()
    tp = (b["High"] + b["Low"] + b["Close"]) / 3
    b["vwap"] = (tp * b["turnover"].fillna(0)).groupby(day).cumsum() / b["turnover"].fillna(0).groupby(day).cumsum().replace(0, np.nan)
    b["rsi"] = rsi(c)
    rng = b["High"] - b["Low"]
    b["rng_x"] = rng / rng.rolling(20).mean().shift(1)
    b["body"] = ((b["Close"] - b["Open"]) / rng.replace(0, np.nan))
    today = b[day == day.max()].copy()
    if len(today) < 3 or len(set(day)) < 12:
        return {"status": "need 12 earlier sessions", "session": day.max()}
    rows, signal = [], None
    for ts, r in today.iterrows():
        t = ts.strftime("%H:%M")
        up = all(r["Close"] > r[k] for k in ("ema", "vwap", "vwma", "st"))
        dn = all(r["Close"] < r[k] for k in ("ema", "vwap", "vwma", "st"))
        side = 1 if up else (-1 if dn else 0)
        s = side if side else (1 if r["Close"] >= r["st"] else -1)  # lean shown when the trend check fails
        checks = [bool(side),
                  bool(r["vol_x"] >= 1.5) if pd.notna(r["vol_x"]) else False,
                  bool(s * r["net_z"] >= 0) if pd.notna(r["net_z"]) else False,
                  bool(r["rsi"] >= 65 if s > 0 else r["rsi"] <= 35) if pd.notna(r["rsi"]) else False,
                  bool(r["rng_x"] >= 1.5 and (r["body"] >= 0.5 if s > 0 else r["body"] <= -0.5))
                  if pd.notna(r["rng_x"]) and pd.notna(r["body"]) else False,
                  bool(r["breadth"] >= 0.6 if s > 0 else r["breadth"] <= 0.4) if pd.notna(r["breadth"]) else False]
        rows.append({"Time": t, "Close": r["Close"], "Lean": "BUY" if s > 0 else "SELL", "Checks": sum(checks),
                     **{n: c_ for n, c_ in zip(CHECK_NAMES, checks)}, "Supertrend": r["st"], "RSI": r["rsi"],
                     "Volume x": r["vol_x"], "Breadth %": 100 * r["breadth"] if pd.notna(r["breadth"]) else np.nan})
        if signal is None and all(checks) and FIRST <= t <= LAST:
            signal = {"time": t, "side": side, "entry": float(r["Close"]), "stop0": float(r["st"]), "ts": ts}
    out = {"status": "signal" if signal else "waiting", "session": day.max(), "rows": pd.DataFrame(rows)}
    last = today.iloc[-1]
    out["last"] = {"time": today.index[-1].strftime("%H:%M"), "close": float(last["Close"]), "st": float(last["st"]),
                   "checks": rows[-1]["Checks"], "lean": rows[-1]["Lean"]}
    if signal:
        side, e = signal["side"], signal["entry"]
        stop, state, exit_px, exit_t = signal["stop0"], "open", None, None
        for ts, r in today[today.index > signal["ts"]].iterrows():
            if ts.strftime("%H:%M") >= SQUARE:
                state, exit_px, exit_t = "squared off 15:15", float(r["Open"]), ts.strftime("%H:%M")
                break
            if (side > 0 and r["Low"] <= stop) or (side < 0 and r["High"] >= stop):
                px = min(r["Open"], stop) if side > 0 else max(r["Open"], stop)
                state, exit_px, exit_t = "stopped (trail)", float(px), ts.strftime("%H:%M")
                break
            stop = max(stop, r["st"]) if side > 0 else min(stop, r["st"])
        now_px = exit_px if exit_px is not None else float(last["Close"])
        signal.update({"stop": float(stop), "state": state, "exit": exit_px, "exit_time": exit_t,
                       "pts": side * (now_px - e), "risk": side * (e - signal["stop0"])})
        signal.pop("ts")
        out["signal"] = signal
    return out


def internals_now(internals: pd.DataFrame, stocks: dict) -> dict:
    """Latest-candle market internals for the panel."""
    if internals is None or internals.empty:
        return {}
    day = internals.index.normalize().max()
    t = internals[internals.index.normalize() == day]
    if t.empty:
        return {}
    r = t.iloc[-1]
    heavy = {}
    for s in BANK_HEAVY:
        d = _naive(stocks.get(s))
        if d.empty:
            continue
        dd = d[d.index.normalize() == day]
        prev = d[d.index.normalize() < day]
        if dd.empty or prev.empty:
            continue
        tp = (dd["High"] + dd["Low"] + dd["Close"]) / 3
        vw = (tp * dd["Volume"]).sum() / max(dd["Volume"].sum(), 1)
        heavy[s] = {"chg": (dd["Close"].iloc[-1] / prev["Close"].iloc[-1] - 1) * 100,
                    "above_vwap": bool(dd["Close"].iloc[-1] > vw)}
    return {"time": t.index[-1].strftime("%H:%M"), "breadth": r.get("breadth"), "breadth_n": int(r.get("breadth_n") or 0),
            "vol_x": r.get("vol_x"), "net_z": r.get("net_z"), "cum_net_cr": float(t["net"].sum() / 1e7),
            "turnover_cr": float(t["turnover"].sum() / 1e7),
            "turnover_x": float(t["turnover"].sum() / t["avg_turnover"].sum()) if t["avg_turnover"].sum() > 0 else np.nan,
            "heavy": heavy}
