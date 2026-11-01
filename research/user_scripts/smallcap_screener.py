"""
Small-cap momentum screener (NSE cash, Rs 10-30 stocks) for 2-3 month swing trades.

Data:
  - Prices / history : Dhan API v2 (env DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
  - Fundamentals     : optional Screener.in CSV export (--fundamentals file.csv)
  - Exclusions       : optional CSV of ASM/GSM/T2T symbols (--exclude file.csv, column "Symbol")

Usage:
  python smallcap_screener.py scan                       # today's shortlist
  python smallcap_screener.py scan --fundamentals screener_export.csv --exclude asm_gsm.csv
  python smallcap_screener.py backtest --years 3         # test the technical rules on history

Outputs CSVs in ./output/. History is cached in ./cache/ so re-runs are fast.
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ----------------------------------------------------------------------------
# Settings - tweak here
# ----------------------------------------------------------------------------

@dataclass
class Rules:
    min_price: float = 10.0
    max_price: float = 30.0
    min_avg_turnover: float = 1e7      # Rs 1 crore average daily turnover (20d)
    min_vol_ratio: float = 2.0         # today's volume vs 20-day average
    breakout_lookback: int = 20        # close above prior N-day high
    max_circuit_days: int = 3          # days with ~5% moves in last 20 (operator-ish behaviour)
    require_above_sma50: bool = True
    require_above_sma200: bool = True
    top_n: int = 5

    # fundamentals (applied only if a Screener.in file is supplied)
    min_mcap_cr: float = 200
    max_mcap_cr: float = 2000
    min_promoter_pct: float = 50
    max_pledge_pct: float = 1
    min_sales_growth: float = 10       # YoY quarterly sales growth %
    min_profit_growth: float = 10      # YoY quarterly profit growth %


@dataclass
class TradeRules:
    stop_loss: float = 0.12            # 12% below entry
    target1: float = 0.30              # book half at +30%
    max_hold_days: int = 50            # ~2.5 months of trading days
    cost_pct: float = 0.0025           # round-trip charges + slippage


CACHE = Path("cache")
OUT = Path("output")
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
HIST_URL = "https://api.dhan.co/v2/charts/historical"
LTP_URL = "https://api.dhan.co/v2/marketfeed/ltp"


# ----------------------------------------------------------------------------
# Dhan data layer
# ----------------------------------------------------------------------------

class Dhan:
    def __init__(self):
        self.client_id = os.environ.get("DHAN_CLIENT_ID", "")
        self.token = os.environ.get("DHAN_ACCESS_TOKEN", "")
        if not self.token:
            sys.exit("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables.")
        self.s = requests.Session()
        self.s.headers.update({
            "access-token": self.token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def universe(self) -> pd.DataFrame:
        """All NSE EQ-series equities: columns symbol, security_id."""
        CACHE.mkdir(exist_ok=True)
        f = CACHE / "scrip_master.csv"
        if not f.exists() or time.time() - f.stat().st_mtime > 86400:
            r = requests.get(SCRIP_MASTER_URL, timeout=60)
            r.raise_for_status()
            f.write_bytes(r.content)
        m = pd.read_csv(f, low_memory=False)
        m = m[(m["SEM_EXM_EXCH_ID"] == "NSE")
              & (m["SEM_INSTRUMENT_NAME"] == "EQUITY")
              & (m["SEM_SERIES"].astype(str).str.strip() == "EQ")]
        return (m.rename(columns={"SEM_TRADING_SYMBOL": "symbol",
                                  "SEM_SMST_SECURITY_ID": "security_id"})
                [["symbol", "security_id"]].drop_duplicates("security_id")
                .reset_index(drop=True))

    def ltp(self, ids: list) -> dict:
        """Last price for many ids (1000 per call, ~1 call/sec)."""
        out = {}
        for i in range(0, len(ids), 1000):
            chunk = [int(x) for x in ids[i:i + 1000]]
            r = self.s.post(LTP_URL, json={"NSE_EQ": chunk}, timeout=30)
            r.raise_for_status()
            data = r.json().get("data", {}).get("NSE_EQ", {})
            for k, v in data.items():
                out[int(k)] = float(v.get("last_price", np.nan))
            time.sleep(1.1)
        return out

    def history(self, security_id: int, start: date, end: date) -> pd.DataFrame:
        """Daily OHLCV, cached per security."""
        CACHE.mkdir(exist_ok=True)
        f = CACHE / f"{security_id}.csv"
        cached = None
        if f.exists():
            cached = pd.read_csv(f, parse_dates=["date"])
            if len(cached) and cached["date"].min().date() <= start + timedelta(days=7) \
                    and cached["date"].max().date() >= end - timedelta(days=4):
                return cached
        body = {
            "securityId": str(security_id), "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY", "expiryCode": 0, "oi": False,
            "fromDate": start.isoformat(), "toDate": end.isoformat(),
        }
        for attempt in range(3):
            r = self.s.post(HIST_URL, json=body, timeout=30)
            if r.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            break
        time.sleep(0.25)  # stay under rate limits
        if r.status_code != 200:
            return cached if cached is not None else pd.DataFrame()
        j = r.json()
        if not j.get("close"):
            return pd.DataFrame()
        df = pd.DataFrame({
            "date": pd.to_datetime(j["timestamp"], unit="s").normalize(),
            "open": j["open"], "high": j["high"], "low": j["low"],
            "close": j["close"], "volume": j["volume"],
        }).drop_duplicates("date").sort_values("date").reset_index(drop=True)
        df.to_csv(f, index=False)
        return df


# ----------------------------------------------------------------------------
# Indicators and signal logic (pure functions - easy to reuse in the app)
# ----------------------------------------------------------------------------

def add_indicators(df: pd.DataFrame, rules: Rules) -> pd.DataFrame:
    d = df.copy()
    c, v = d["close"], d["volume"]
    d["sma50"] = c.rolling(50).mean()
    d["sma200"] = c.rolling(200).mean()
    d["turnover"] = c * v
    d["avg_turnover20"] = d["turnover"].rolling(20).mean()
    d["vol20"] = v.shift(1).rolling(20).mean()
    d["vol_ratio"] = v / d["vol20"]
    d["prior_high"] = d["high"].shift(1).rolling(rules.breakout_lookback).max()
    d["breakout"] = c > d["prior_high"]
    chg = c.pct_change().abs()
    d["circuit_days20"] = (chg >= 0.048).rolling(20).sum()
    d["ret20"] = c / c.shift(20) - 1
    d["high252"] = d["high"].rolling(252, min_periods=120).max()
    d["pct_of_52wh"] = c / d["high252"]
    return d


def signal_mask(d: pd.DataFrame, rules: Rules) -> pd.Series:
    m = (
        d["close"].between(rules.min_price, rules.max_price)
        & (d["avg_turnover20"] >= rules.min_avg_turnover)
        & (d["vol_ratio"] >= rules.min_vol_ratio)
        & d["breakout"]
        & (d["circuit_days20"] <= rules.max_circuit_days)
    )
    if rules.require_above_sma50:
        m &= d["close"] > d["sma50"]
    if rules.require_above_sma200:
        m &= d["close"] > d["sma200"]
    return m.fillna(False)


def score_row(r) -> float:
    """0-100. Rewards volume surge, 20-day momentum, nearness to 52-week high."""
    vol = min(r["vol_ratio"], 5) / 5
    mom = float(np.clip(r["ret20"], 0, 0.5)) / 0.5
    near = float(np.clip(r["pct_of_52wh"], 0, 1))
    return round(100 * (0.4 * vol + 0.3 * mom + 0.3 * near), 1)


# ----------------------------------------------------------------------------
# Fundamentals (Screener.in export)
# ----------------------------------------------------------------------------

FUND_COLS = {  # Screener.in column name -> internal name
    "NSE Code": "symbol",
    "Market Capitalization": "mcap_cr",
    "Promoter holding": "promoter_pct",
    "Pledged percentage": "pledge_pct",
    "YOY Quarterly sales growth": "sales_growth",
    "YOY Quarterly profit growth": "profit_growth",
}


def load_fundamentals(path: str, rules: Rules) -> pd.DataFrame:
    f = pd.read_csv(path)
    f.columns = [c.strip() for c in f.columns]
    missing = [c for c in FUND_COLS if c not in f.columns]
    if missing:
        sys.exit(f"Fundamentals file missing columns: {missing}. "
                 f"Add them to your Screener.in screen before exporting.")
    f = f.rename(columns=FUND_COLS)[list(FUND_COLS.values())]
    for c in FUND_COLS.values():
        if c != "symbol":
            f[c] = pd.to_numeric(f[c], errors="coerce")
    ok = (
        f["mcap_cr"].between(rules.min_mcap_cr, rules.max_mcap_cr)
        & (f["promoter_pct"] >= rules.min_promoter_pct)
        & (f["pledge_pct"].fillna(0) <= rules.max_pledge_pct)
        & (f["sales_growth"] >= rules.min_sales_growth)
        & (f["profit_growth"] >= rules.min_profit_growth)
    )
    return f[ok]


def load_excludes(path: str) -> set:
    e = pd.read_csv(path)
    col = next((c for c in e.columns if c.strip().lower() == "symbol"), e.columns[0])
    return set(e[col].astype(str).str.strip().str.upper())


# ----------------------------------------------------------------------------
# Scan
# ----------------------------------------------------------------------------

def scan(api: Dhan, rules: Rules, fundamentals=None, excludes=None) -> pd.DataFrame:
    uni = api.universe()
    print(f"Universe: {len(uni)} NSE EQ stocks")

    if fundamentals is not None:
        uni = uni[uni["symbol"].isin(fundamentals["symbol"])]
        print(f"After fundamentals filter: {len(uni)}")
    if excludes:
        uni = uni[~uni["symbol"].str.upper().isin(excludes)]
        print(f"After ASM/GSM exclusion: {len(uni)}")

    # Cheap price pre-filter (slightly wider band so breakouts at edges are caught)
    prices = api.ltp(uni["security_id"].tolist())
    uni["ltp"] = uni["security_id"].map(prices)
    uni = uni[uni["ltp"].between(rules.min_price * 0.9, rules.max_price * 1.1)]
    print(f"In price band: {len(uni)} - fetching history...")

    end = date.today()
    start = end - timedelta(days=420)
    rows = []
    for i, r in enumerate(uni.itertuples(), 1):
        h = api.history(r.security_id, start, end)
        if len(h) < 210:
            continue
        d = add_indicators(h, rules)
        last = d.iloc[-1]
        if signal_mask(d.tail(1), rules).iloc[0]:
            rows.append({
                "symbol": r.symbol, "date": last["date"].date(),
                "close": round(last["close"], 2),
                "vol_ratio": round(last["vol_ratio"], 2),
                "ret20_pct": round(100 * last["ret20"], 1),
                "pct_of_52wh": round(100 * last["pct_of_52wh"], 1),
                "avg_turnover_cr": round(last["avg_turnover20"] / 1e7, 2),
                "stop_loss": round(last["close"] * 0.88, 2),
                "target1": round(last["close"] * 1.30, 2),
                "score": score_row(last),
            })
        if i % 50 == 0:
            print(f"  {i}/{len(uni)} checked, {len(rows)} signals")

    res = pd.DataFrame(rows)
    if res.empty:
        print("No stocks passed today. That is normal in a weak market - don't force trades.")
        return res
    if fundamentals is not None:
        res = res.merge(fundamentals, on="symbol", how="left")
    res = res.sort_values("score", ascending=False).head(rules.top_n)
    OUT.mkdir(exist_ok=True)
    f = OUT / f"scan_{date.today().isoformat()}.csv"
    res.to_csv(f, index=False)
    print(f"\nTop {len(res)} saved to {f}\n")
    print(res.to_string(index=False))
    return res


# ----------------------------------------------------------------------------
# Backtest (technical rules only - fundamentals are not point-in-time)
# ----------------------------------------------------------------------------

def simulate(d: pd.DataFrame, sig: pd.Series, tr: TradeRules, symbol: str) -> list:
    """Enter next day's open after a signal. One open trade per stock at a time.
    Stop 12%; at +30% sell half and move stop to entry; exit rest at max hold."""
    trades = []
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    dates = d["date"].to_numpy()
    idx = np.flatnonzero(sig.to_numpy())
    busy_until = -1
    for s in idx:
        e = s + 1
        if e >= len(d) or s <= busy_until:
            continue
        entry = o[e]
        stop = entry * (1 - tr.stop_loss)
        tgt = entry * (1 + tr.target1)
        half_booked = False
        realised = 0.0  # weighted return
        exit_i, reason = None, None
        for j in range(e, min(e + tr.max_hold_days, len(d))):
            # gap through stop
            if o[j] <= stop and j > e:
                px = o[j]
            elif l[j] <= stop:
                px = stop
            else:
                px = None
            if px is not None:  # stop checked first (conservative)
                w = 0.5 if half_booked else 1.0
                realised += w * (px / entry - 1)
                exit_i, reason = j, "breakeven" if half_booked else "stop"
                break
            if not half_booked and h[j] >= tgt:
                realised += 0.5 * tr.target1
                half_booked = True
                stop = entry
        if exit_i is None:
            exit_i = min(e + tr.max_hold_days, len(d)) - 1
            w = 0.5 if half_booked else 1.0
            realised += w * (c[exit_i] / entry - 1)
            reason = "time"
        trades.append({
            "symbol": symbol, "signal_date": pd.Timestamp(dates[s]).date(),
            "entry_date": pd.Timestamp(dates[e]).date(), "entry": round(entry, 2),
            "exit_date": pd.Timestamp(dates[exit_i]).date(),
            "days": exit_i - e + 1, "half_booked": half_booked, "exit_reason": reason,
            "return_pct": round(100 * (realised - tr.cost_pct), 2),
        })
        busy_until = exit_i
    return trades


def summarise(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0}
    r = t["return_pct"].astype(float)
    wins, losses = r[r > 0], r[r <= 0]
    out = {
        "trades": len(t),
        "win_rate_pct": round(100 * len(wins) / len(t), 1),
        "avg_return_pct": round(r.mean(), 2),
        "median_return_pct": round(r.median(), 2),
        "avg_win_pct": round(wins.mean(), 2) if len(wins) else 0,
        "avg_loss_pct": round(losses.mean(), 2) if len(losses) else 0,
        "profit_factor": round(wins.sum() / abs(losses.sum()), 2) if losses.sum() else np.inf,
        "hit_target1_pct": round(100 * t["half_booked"].mean(), 1),
        "worst_trade_pct": round(r.min(), 2),
        "avg_days_held": round(t["days"].mean(), 1),
    }
    return {k: (float(v) if isinstance(v, (np.floating, np.integer)) else v) for k, v in out.items()}


def backtest(api: Dhan, rules: Rules, tr: TradeRules, years: int, excludes=None):
    uni = api.universe()
    if excludes:
        uni = uni[~uni["symbol"].str.upper().isin(excludes)]
    end = date.today()
    start = end - timedelta(days=int(365 * years) + 320)
    print(f"Backtesting {len(uni)} stocks from {start} (first ~300 days are indicator warm-up).")
    print("This fetches full history once; later runs use the cache.")
    all_trades = []
    for i, r in enumerate(uni.itertuples(), 1):
        h = api.history(r.security_id, start, end)
        if len(h) < 260:
            continue
        # skip stocks never in the price band - saves time
        if not h["close"].between(rules.min_price, rules.max_price).any():
            continue
        d = add_indicators(h, rules)
        all_trades += simulate(d, signal_mask(d, rules), tr, r.symbol)
        if i % 100 == 0:
            print(f"  {i}/{len(uni)} done, {len(all_trades)} trades")
    t = pd.DataFrame(all_trades)
    OUT.mkdir(exist_ok=True)
    t.to_csv(OUT / "backtest_trades.csv", index=False)
    s = summarise(t)
    print("\n=== Backtest summary ===")
    for k, v in s.items():
        print(f"{k:>20}: {v}")
    if not t.empty:
        t["year"] = pd.to_datetime(t["entry_date"]).dt.year
        by_year = t.groupby("year")["return_pct"].agg(["count", "mean", lambda x: (x > 0).mean() * 100])
        by_year.columns = ["trades", "avg_ret_pct", "win_rate_pct"]
        print("\nBy year:\n", by_year.round(2).to_string())
    print("\nCaveats: uses today's listed stocks only (delisted names missing -> results "
          "look better than reality); fundamentals and ASM/GSM not applied historically.")
    pd.DataFrame([s | asdict(rules) | asdict(tr)]).to_csv(OUT / "backtest_summary.csv", index=False)
    return t, s


# ----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["scan", "backtest"])
    p.add_argument("--fundamentals", help="Screener.in CSV export")
    p.add_argument("--exclude", help="CSV of ASM/GSM symbols to skip")
    p.add_argument("--years", type=float, default=3)
    p.add_argument("--top", type=int, default=5)
    a = p.parse_args()

    rules = Rules(top_n=a.top)
    api = Dhan()
    ex = load_excludes(a.exclude) if a.exclude else None
    if a.mode == "scan":
        fund = load_fundamentals(a.fundamentals, rules) if a.fundamentals else None
        scan(api, rules, fund, ex)
    else:
        backtest(api, rules, TradeRules(), a.years, ex)


if __name__ == "__main__":
    main()
