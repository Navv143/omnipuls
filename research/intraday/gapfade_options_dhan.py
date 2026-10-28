"""Gap fade traded with REAL stock-option prices from Dhan (1-minute expired-options data), on your own computer.

Why: on 5-minute stock data the gap fade made about +9.5% per option trade when bought at the opening price, but
about 0% (since 2022) when bought at 9:20. Options can't be bought in the pre-open, so what matters is what an
option buyer actually gets at 9:15-9:17. This script measures it on real option prices.

Rule tested: each day take the 2 F&O stocks with the biggest opening gap of 3%+ (from Dhan daily bars).
Gap-up -> buy ATM PUT, gap-down -> buy ATM CALL. Entry at the option's 1-minute bar open at 9:16 (also 9:15,
9:17, 9:18, 9:20 for comparison). Stop when the stock moves 0.5 x ATR(14) against the trade (checked on 1-minute
spot closes), else exit at the option's 15:20 bar open. The strike is fixed at entry: Dhan's data is "rolling"
(ATM re-centres every minute), so the script downloads ATM-3..ATM+3 and follows the entry strike.

Usage (Omnipuls folder, Dhan connected, data plan active):
  .venv\\Scripts\\python research\\intraday\\gapfade_options_dhan.py --years 5
  .venv\\Scripts\\python research\\intraday\\gapfade_options_dhan.py --years 1 --limit 40     # quick first look
Downloads are cached in research\\cache\\opt; results in research\\results\\gapfade_options_*.csv.
"""
from __future__ import annotations

import argparse
import pickle
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
import dhan as D  # noqa: E402
import universe as U  # noqa: E402

CACHE = ROOT / "research" / "cache" / "opt"
OUT = ROOT / "research" / "results"
CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
STRIKES = ["ATM-3", "ATM-2", "ATM-1", "ATM", "ATM+1", "ATM+2", "ATM+3"]


def cached(name, fn):
    f = CACHE / name
    if f.exists():
        return pickle.loads(f.read_bytes())
    v = fn()
    f.write_bytes(pickle.dumps(v))
    return v


# ---------------------------------------------------------------- candidates from daily bars

def daily_bars(sym, sid, years):
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=int(365.25 * years) + 40)
    return cached(f"daily_{sym}_{start}_{end}.pkl", lambda: D.daily("NSE_EQ", sid, "EQUITY", start, end))


def candidates(years, limit, gap_min, top):
    ids = D.equity_ids()
    syms = [s for s in sorted(U.FNO_SECTOR_OF) if s in ids][:limit]
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            df = daily_bars(s, ids[s], years)
        except Exception as e:
            print(f"  {s}: {e}")
            continue
        if df.empty:
            continue
        pc = df["Close"].shift(1)
        tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift(1)
        gap = df["Open"] / pc - 1
        big = gap.abs() > 0.2  # corporate actions / bad prints
        ok = gap.abs().ge(gap_min) & ~big & atr.notna()
        for d0 in df.index[ok]:
            rows.append({"date": d0.date(), "sym": s, "sid": ids[s], "gap": gap[d0], "atr": atr[d0], "open": df.at[d0, "Open"]})
        if i % 25 == 0:
            print(f"  daily bars {i}/{len(syms)}")
    c = pd.DataFrame(rows)
    if c.empty:
        return c
    c["abs_gap"] = c["gap"].abs()
    c = c.sort_values(["date", "abs_gap"], ascending=[True, False]).groupby("date").head(top).reset_index(drop=True)
    c["side"] = np.where(c["gap"] < 0, 1, -1)  # fade: gap-down -> long (CALL), gap-up -> short (PUT)
    return c


# ---------------------------------------------------------------- option minute data

def rolling(sid, kind, strike, start, end, expiry_code):
    body = {"exchangeSegment": "NSE_FNO", "interval": "1", "securityId": int(sid), "instrument": "OPTSTK",
            "expiryFlag": "MONTH", "expiryCode": expiry_code, "strike": strike, "drvOptionType": kind,
            "requiredData": ["open", "high", "low", "close", "volume", "strike", "spot", "iv"],
            "fromDate": start.isoformat(), "toDate": end.isoformat()}
    res = D.call("POST", "/charts/rollingoption", "data", body)
    sec = (res or {}).get("data", {}).get("ce" if kind == "CALL" else "pe") or {}
    if not sec.get("timestamp"):
        return pd.DataFrame()
    df = pd.DataFrame({k: sec.get(k) for k in ("open", "high", "low", "close", "volume", "strike", "spot", "iv")
                       if sec.get(k) and len(sec.get(k)) == len(sec["timestamp"])})
    df.index = pd.to_datetime(pd.Series(sec["timestamp"]), unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return df


def month_data(sym, sid, kind, day, expiry_code):
    """All seven rolling strikes for the 30-day window containing `day` (cached per stock/type/window)."""
    start = date(day.year, day.month, 1)
    end = (pd.Timestamp(start) + pd.offsets.MonthBegin(1)).date()
    frames = []
    for k in STRIKES:
        df = cached(f"ro_{sym}_{kind}_{k}_{start}_{expiry_code}.pkl", lambda: rolling(sid, kind, k, start, end, expiry_code))
        if not df.empty:
            frames.append(df.assign(rel=k))
    return pd.concat(frames) if frames else pd.DataFrame()


def simulate(c, entry_times, stop_atr, expiry_code, costs):
    out = []
    for i, r in enumerate(c.itertuples(), 1):
        kind = "CALL" if r.side > 0 else "PUT"
        try:
            m = month_data(r.sym, r.sid, kind, r.date, expiry_code)
        except Exception as e:
            print(f"  {r.sym} {r.date}: {e}")
            continue
        if m.empty:
            continue
        day = m[m.index.date == r.date]
        if day.empty or "strike" not in day:
            continue
        for et in entry_times:
            t0 = datetime.combine(r.date, et)
            first = day[(day.index >= t0) & (day.rel == "ATM")].head(1)
            if first.empty:
                continue
            K = first["strike"].iloc[0]
            leg = day[day["strike"] == K].sort_index()
            leg = leg[~leg.index.duplicated()]
            leg = leg[leg.index >= first.index[0]]
            if len(leg) < 5:
                continue
            entry = leg["open"].iloc[0]
            spot0 = leg["spot"].iloc[0] if "spot" in leg else np.nan
            stop_spot = spot0 - r.side * stop_atr * r.atr
            exit_px, how, xt = None, "time", None
            for ts, b in leg.iloc[1:].iterrows():
                if ts.time() >= dtime(15, 20):
                    exit_px, xt = b["open"], ts
                    break
                if np.isfinite(spot0) and ((r.side > 0 and b["spot"] <= stop_spot) or (r.side < 0 and b["spot"] >= stop_spot)):
                    exit_px, how, xt = b["close"], "stop", ts
                    break
            if exit_px is None:  # strike stopped trading in our data (moved beyond ATM+-3): exit at the last price
                exit_px, how, xt = leg["close"].iloc[-1], "data_end", leg.index[-1]
            row = {"date": r.date, "sym": r.sym, "side": "CALL" if r.side > 0 else "PUT", "gap": r.gap, "entry_time": et.strftime("%H:%M"),
                   "strike": K, "spot_entry": spot0, "stock_open": r.open, "entry": entry, "exit": exit_px, "exit_by": how,
                   "exit_time": xt, "iv_entry": leg["iv"].iloc[0] if "iv" in leg else np.nan,
                   "volume_first_min": leg["volume"].iloc[0] if "volume" in leg else np.nan}
            for cst in costs:
                row[f"ret_{cst:.0%}"] = exit_px / entry - 1 - cst
            out.append(row)
        if i % 25 == 0:
            print(f"  options {i}/{len(c)}")
    return pd.DataFrame(out)


def summary(t, costs):
    rows = []
    for et, g in t.groupby("entry_time"):
        for cst in costs:
            r = g[f"ret_{cst:.0%}"]
            yrs = r.groupby(pd.to_datetime(g["date"]).dt.year).mean()
            rows.append({"entry": et, "cost": f"{cst:.0%}", "trades": len(r), "win%": round(100 * (r > 0).mean(), 1),
                         "avg %": round(100 * r.mean(), 2), "median %": round(100 * r.median(), 1),
                         "PF": round(r[r > 0].sum() / -r[r <= 0].sum(), 2) if (r <= 0).any() else np.inf,
                         "t-stat": round(r.mean() / r.std() * np.sqrt(len(r)), 2) if len(r) > 2 else np.nan,
                         "years +": f"{(yrs > 0).sum()}/{len(yrs)}",
                         **{f"{y}": round(100 * v, 1) for y, v in yrs.items()}})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=5)
    ap.add_argument("--limit", type=int, default=None, help="first N F&O stocks only (quick test)")
    ap.add_argument("--gap", type=float, default=0.03)
    ap.add_argument("--top", type=int, default=2)
    ap.add_argument("--stop-atr", type=float, default=0.5)
    ap.add_argument("--expiry-code", type=int, default=1, help="Dhan expiryCode for the monthly contract (1 = nearest in Dhan's example)")
    a = ap.parse_args()
    if not D.configured():
        sys.exit("Connect Dhan first (Dhan Connect page in Omnipuls).")
    costs = (0.01, 0.02, 0.04)
    c = candidates(a.years, a.limit, a.gap, a.top)
    print(f"{len(c)} gap candidates")
    t = simulate(c, [dtime(9, 15), dtime(9, 16), dtime(9, 17), dtime(9, 18), dtime(9, 20)], a.stop_atr, a.expiry_code, costs)
    if t.empty:
        sys.exit("No option data came back. Check the data plan, or try --expiry-code 0.")
    t.to_csv(OUT / "gapfade_options_trades.csv", index=False)
    s = summary(t, costs)
    s.to_csv(OUT / "gapfade_options_summary.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(s.to_string(index=False))
    print("\nHow to read: 'avg %' is the average return on the premium paid. Compare 9:15/9:16 with 9:20.")
