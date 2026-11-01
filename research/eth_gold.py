"""ETH and gold (XAU) trend rules, tested the same way as the BTC trend filter (research/crypto_fx.py).

Data: ETH/USDT and BTC/USDT daily from Binance's public market-data API (Aug 2017 on); gold from Yahoo's chart API
(GC=F COMEX futures, 2000 on). Every rule decides on day t's close and holds from day t+1 (no look-ahead);
costs on each change of position: 0.10% crypto, 0.05% gold. Long-only rules sit in cash otherwise (no interest).
Periods are split in two halves; a rule must beat buy-and-hold on risk (Sharpe, drawdown) in both to count.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\eth_gold.py
"""
from __future__ import annotations

import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import truststore

truststore.inject_into_ssl()
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)


def binance_daily(symbol: str) -> pd.Series:
    f = CACHE / f"binance_{symbol}_1d.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        return pickle.loads(f.read_bytes())
    rows, start = [], 1500000000000
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": symbol, "interval": "1d", "startTime": start, "limit": 1000}, timeout=30)
        r.raise_for_status()
        k = r.json()
        if not k:
            break
        rows += k
        start = k[-1][0] + 86400000
        if len(k) < 1000:
            break
        time.sleep(0.3)
    s = pd.Series([float(x[4]) for x in rows], index=pd.to_datetime([x[0] for x in rows], unit="ms")).sort_index()
    f.write_bytes(pickle.dumps(s))
    return s


def yahoo_daily(symbol: str) -> pd.Series:
    f = CACHE / f"yahoo_{symbol.replace('=', '_')}_1d.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        return pickle.loads(f.read_bytes())
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                     params={"period1": 946684800, "period2": int(time.time()), "interval": "1d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    s = pd.Series(res["indicators"]["quote"][0]["close"], index=pd.to_datetime(res["timestamp"], unit="s")).dropna()
    s.index = s.index.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    f.write_bytes(pickle.dumps(s))
    return s


def stats(r: pd.Series, per_year: int) -> dict:
    r = r.dropna()
    if len(r) < 50:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / per_year
    yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
    return {"CAGR %": round(100 * (eq.iloc[-1] ** (1 / yrs) - 1), 1),
            "Sharpe": round(r.mean() / r.std() * np.sqrt(per_year), 2) if r.std() > 0 else np.nan,
            "max DD %": round(100 * (eq / eq.cummax() - 1).min(), 1),
            "yrs +": f"{int((yr > 0).sum())}/{len(yr)}",
            "2024 %": round(100 * yr.get(2024, np.nan), 1), "2025 %": round(100 * yr.get(2025, np.nan), 1),
            "2026 %": round(100 * yr.get(2026, np.nan), 1)}


def rules(px: pd.Series, cost: float) -> dict[str, pd.Series]:
    ret = px.pct_change()
    pos = {"Buy & hold": pd.Series(1.0, index=px.index)}
    for n in (20, 50, 100, 200):
        pos[f"Long above {n}-day average"] = (px > px.rolling(n).mean()).astype(float)
    for n in (20, 55):
        hi, lo = px.rolling(n).max(), px.rolling(n // 2).min()
        p = pd.Series(np.nan, index=px.index)
        p[px >= hi] = 1.0
        p[px <= lo] = 0.0
        pos[f"Donchian {n} breakout, exit {n // 2}-day low"] = p.ffill().fillna(0)
    pos["30-day momentum > 0"] = (px / px.shift(30) - 1 > 0).astype(float)
    pos["50 > 200 average (golden cross)"] = (px.rolling(50).mean() > px.rolling(200).mean()).astype(float)
    out = {}
    for k, p in pos.items():
        held = p.shift(1).fillna(0)
        out[k] = held * ret - held.diff().abs().fillna(0) * cost
    return out


def report(name: str, px: pd.Series, cost: float, per_year: int):
    mid = px.index[len(px) // 2]
    rows = []
    for k, r in rules(px, cost).items():
        a, b = stats(r[r.index < mid], per_year), stats(r[r.index >= mid], per_year)
        full = stats(r, per_year)
        rows.append({"rule": k, **full, "1st half Sharpe": a.get("Sharpe"), "2nd half Sharpe": b.get("Sharpe"),
                     "2nd half CAGR %": b.get("CAGR %"), "2nd half DD %": b.get("max DD %")})
    t = pd.DataFrame(rows)
    print(f"\n=== {name}: {px.index.min():%b %Y} - {px.index.max():%b %Y}, halves split {mid:%b %Y}, cost {cost:.2%} ===")
    print(t.to_string(index=False))
    return t.assign(market=name)


def main():
    pd.set_option("display.width", 260)
    out = [report("ETH", binance_daily("ETHUSDT"), 0.001, 365), report("BTC", binance_daily("BTCUSDT"), 0.001, 365)]
    try:
        out.append(report("Gold (COMEX GC=F)", yahoo_daily("GC=F"), 0.0005, 252))
    except Exception as e:
        print("gold download failed:", e)
    pd.concat(out).to_csv(HERE / "results" / "eth_gold.csv", index=False)


if __name__ == "__main__":
    main()
