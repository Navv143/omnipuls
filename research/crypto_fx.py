"""BTC (Bitstamp 1-minute) intraday and daily edges; FX, INR and commodity trend tests on daily closes.

Pre-specified, textbook rules; each checked in two separate periods. Costs included per trade.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).parent / "data"
BTC_COST = 0.0010   # round trip: ~0.04% taker per side on perpetuals + slippage
FX_COST = 0.0002    # round trip on majors
CMD_COST = 0.0010   # round trip on crude / gas futures incl. roll slippage


def load_btc() -> pd.DataFrame:
    cache = D / "btc_1h.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    a = pd.read_csv(D / "btc_1min_hist.csv.gz")
    b = pd.read_csv(D / "btc_1min_latest.csv")
    m = pd.concat([a, b]).drop_duplicates("timestamp").sort_values("timestamp")
    m.index = pd.to_datetime(m["timestamp"], unit="s", utc=True)
    m = m[m.index >= "2015-01-01"]
    h = m.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    h.to_parquet(cache)
    return h


def stats(r: pd.Series, per_year: int) -> dict:
    r = r.dropna()
    t = r[r != 0]
    eq = (1 + r).cumprod()
    yrs = len(r) / per_year
    return {"trades/days": len(t), "win%": round(100 * (t > 0).mean(), 1) if len(t) else np.nan,
            "avg%": round(100 * t.mean(), 3) if len(t) else np.nan,
            "CAGR%": round(100 * (eq.iloc[-1] ** (1 / yrs) - 1), 1) if yrs > 0 and eq.iloc[-1] > 0 else np.nan,
            "sharpe": round(r.mean() / r.std() * np.sqrt(per_year), 2) if r.std() > 0 else np.nan,
            "maxDD%": round(100 * (eq / eq.cummax() - 1).min(), 1), "exposure%": round(100 * (r != 0).mean())}


def btc_hour_of_day(h: pd.DataFrame) -> pd.DataFrame:
    r = h["close"].pct_change()
    df = pd.DataFrame({"r": r, "hour": h.index.hour, "year": h.index.year})
    by = df.groupby(["year", "hour"])["r"].mean().unstack() * 1e4  # basis points per hour
    return by


def btc_rules(h: pd.DataFrame) -> dict[str, pd.Series]:
    d = h.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    c = d["close"]
    cc = c.pct_change()
    out = {"Buy & hold": cc}
    for n in (20, 50, 100, 200):
        pos = (c > c.rolling(n).mean()).shift(1).astype(float)
        out[f"Long above MA{n}"] = pos * cc - pos.diff().abs().fillna(0) * BTC_COST / 2
    for n in (20, 55):
        hi, lo = d["high"].rolling(n).max().shift(1), d["low"].rolling(n).min().shift(1)
        pos = pd.Series(np.nan, index=c.index)
        pos[c > hi] = 1
        pos[c < lo] = -1
        pos = pos.ffill().fillna(0).shift(1)
        out[f"Donchian {n} long/short"] = pos * cc - pos.diff().abs().fillna(0) * BTC_COST / 2
        posl = pos.clip(lower=0)
        out[f"Donchian {n} long only"] = posl * cc - posl.diff().abs().fillna(0) * BTC_COST / 2
    mom = c.pct_change(30).shift(1)
    pos = np.sign(mom).fillna(0)
    out["30-day momentum long/short"] = pos * cc - pos.diff().abs().fillna(0) * BTC_COST / 2
    # Weekend vs weekday
    out["Weekend only (Fri close to Sun close)"] = np.where(c.index.dayofweek.isin([5, 6]), cc, 0) - \
        np.where(c.index.dayofweek == 5, BTC_COST, 0)
    return {k: pd.Series(v, index=c.index) for k, v in out.items()}


def btc_session_rules(h: pd.DataFrame) -> dict[str, pd.Series]:
    """Intraday session trades on hourly bars, one per day, decided by the clock only."""
    r = h["close"].pct_change()
    out = {}
    windows = {"US session 13-21 UTC": (13, 21), "Asia session 0-8 UTC": (0, 8), "Europe 7-13 UTC": (7, 13),
               "Overnight-US 21-24 UTC": (21, 24)}
    for name, (a, b) in windows.items():
        m = (h.index.hour >= a) & (h.index.hour < b)
        day = pd.Series(np.where(m, r, 0.0), index=h.index).resample("1D").sum()
        out[f"Long {name}"] = day - BTC_COST
    return out


def load_fx() -> pd.DataFrame:
    fx = pd.read_csv(D / "fx_daily.csv", parse_dates=["Date"])
    w = fx.pivot_table(index="Date", columns="Country", values=fx.columns[-1])
    # FRED quotes USD per unit for these; others are units per USD. Express all as "price of foreign currency in USD".
    usd_per = {"Euro", "United Kingdom", "Australia", "New Zealand"}
    px = pd.DataFrame(index=w.index)
    for col in w.columns:
        s = w[col].replace(0, np.nan)
        px[col] = s if col in usd_per else 1 / s
    names = {"Euro": "EURUSD", "United Kingdom": "GBPUSD", "Japan": "JPYUSD (=1/USDJPY)", "Australia": "AUDUSD",
             "Canada": "CADUSD", "Switzerland": "CHFUSD", "New Zealand": "NZDUSD", "India": "INRUSD (=1/USDINR)",
             "China": "CNYUSD", "Singapore": "SGDUSD", "Mexico": "MXNUSD", "South Africa": "ZARUSD"}
    return px[[c for c in names if c in px]].rename(columns=names)


def load_cmd() -> pd.DataFrame:
    out = {}
    for f, nm in (("wti_daily.csv", "WTI crude"), ("brent_daily.csv", "Brent crude"), ("natgas_daily.csv", "Natural gas")):
        x = pd.read_csv(D / f)
        x.columns = ["Date", "Price"]
        x["Date"] = pd.to_datetime(x["Date"])
        out[nm] = x.set_index("Date")["Price"].where(lambda s: s > 0)
    return pd.DataFrame(out)


def trend_rules(px: pd.Series, cost: float) -> dict[str, pd.Series]:
    px = px.dropna()
    r = px.pct_change().clip(-0.5, 0.5)
    vol = r.rolling(60).std() * np.sqrt(250)
    out = {"Buy & hold": r}
    for n in (50, 200):
        pos = np.sign(px - px.rolling(n).mean()).shift(1).fillna(0)
        out[f"MA{n} long/short"] = pos * r - pos.diff().abs().fillna(0) * cost / 2
    # Time-series momentum (Moskowitz, Ooi, Pedersen 2012): sign of 12-month return, rebalanced monthly
    sig = np.sign(px.pct_change(250)).shift(1)
    sig = sig.where(sig.index.to_series().dt.month != sig.index.to_series().shift(1).dt.month).ffill().fillna(0)
    out["12m momentum long/short"] = sig * r - sig.diff().abs().fillna(0) * cost / 2
    # Same, scaled to 10% annual volatility
    lev = (0.10 / vol).clip(upper=3).shift(1).fillna(0)
    out["12m momentum, vol-targeted 10%"] = sig * lev * r - (sig * lev).diff().abs().fillna(0) * cost / 2
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_rows", 200)
    h = load_btc()
    print("BTC hourly bars:", len(h), h.index.min(), h.index.max())
    rows = []
    rules = {**btc_rules(h), **btc_session_rules(h)}
    for k, r in rules.items():
        per_year = 365
        for per, (a, b) in {"2015-20": ("2015", "2020-12-31"), "2021-26": ("2021", "2026-12-31")}.items():
            rows.append({"market": "BTC", "rule": k, "period": per, **stats(r[a:b], per_year)})
    hod = btc_hour_of_day(h)
    hod.to_csv(D / "btc_hour_of_day_bps.csv")
    fx = load_fx()
    cmd = load_cmd()
    for name in fx.columns:
        for k, r in trend_rules(fx[name], FX_COST).items():
            for per, (a, b) in {"2000-12": ("2000", "2012-12-31"), "2013-26": ("2013", "2026-12-31")}.items():
                rows.append({"market": name, "rule": k, "period": per, **stats(r[a:b], 250)})
    for name in cmd.columns:
        for k, r in trend_rules(cmd[name], CMD_COST).items():
            for per, (a, b) in {"2000-12": ("2000", "2012-12-31"), "2013-26": ("2013", "2026-12-31")}.items():
                rows.append({"market": name, "rule": k, "period": per, **stats(r[a:b], 250)})
    t = pd.DataFrame(rows)
    t.to_csv(D / "crypto_fx_results.csv", index=False)
    print(t[t.market == "BTC"].pivot_table(index="rule", columns="period", values=["sharpe", "CAGR%", "maxDD%"]).round(2).to_string())
    print()
    print(t[t.market != "BTC"].pivot_table(index=["rule"], columns=["market", "period"], values="sharpe").round(2).T.to_string())
    print("\nBTC mean return by UTC hour (basis points), by year:")
    print(hod.round(1).to_string())
