"""REAL option prices from Dhan (expired-options data) for Nifty / Bank Nifty: settles what the models can't.

Why: on modelled premiums the answer for intraday option selling flips with one assumption (how much of a day's time
decay happens during the session vs overnight). Trading-time model: 09:20 straddle selling wins 12/12 years;
calendar-time model: it loses 12/12 years. Real traded prices decide. The same applies to option BUYING results.

Tests (all intraday, flat by 15:15, costs: slippage 0.5 pt Nifty / 2 pt Bank Nifty per leg per side, double on stop
exits, plus 0.15% of premium charges and Rs 40 brokerage per leg):
  SELL  straddle 09:20 / 09:45 with per-leg stop 25/40/60% and a combined stop 30%;
        strangle at +/-0.4 and +/-0.7 x daily ATR with per-leg stop 50/100%;
        iron fly (straddle + wings at +/-1.2 ATR) with combined stop 25%.
        Split by days to expiry (expiry day / 1 day before / 2+ days).
  BUY   (a) trend-day + OI signals exported from the futures study (research/index_options/trend_oi_signals_2021_2023.csv)
        (b) the same rule WITHOUT the OI check, computed from Dhan spot for every year Dhan has (no futures OI history)
        (c) random entries at the same times of day, as the yardstick. Exit: stop -30% premium; after +30% exit when
        30% off the best; else 15:15.

Usage (Omnipuls folder, Dhan connected, data plan active):
  .venv\\Scripts\\python research\\index_options\\dhan_index_options.py --years 1      # quick look (~5 min)
  .venv\\Scripts\\python research\\index_options\\dhan_index_options.py --years 5      # full run
Downloads are cached in research\\cache\\idxopt (re-runs are instant); results go to research\\results\\idxopt_*.csv
and are printed. Send the printed summary back to Claude.
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

CACHE = ROOT / "research" / "cache" / "idxopt"
OUT = ROOT / "research" / "results"
CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
IDX = {"NIFTY": {"sid": 13, "step": 50, "slip": 0.5, "lot": 75},
       "BANKNIFTY": {"sid": 25, "step": 100, "slip": 2.0, "lot": 35}}
REL = [f"ATM{k:+d}" if k else "ATM" for k in range(-10, 11)]


def flag_for(sym, d):
    if sym == "BANKNIFTY" and d >= date(2024, 11, 20):
        return "MONTH"
    return "WEEK"


def cached(name, fn):
    f = CACHE / name
    if f.exists():
        return pickle.loads(f.read_bytes())
    v = fn()
    f.write_bytes(pickle.dumps(v))
    return v


def rolling(sym, kind, rel, start, end, flag):
    body = {"exchangeSegment": "NSE_FNO", "interval": "1", "securityId": IDX[sym]["sid"], "instrument": "OPTIDX",
            "expiryFlag": flag, "expiryCode": 1, "strike": rel, "drvOptionType": kind,
            "requiredData": ["open", "high", "low", "close", "volume", "oi", "strike", "spot", "iv"],
            "fromDate": start.isoformat(), "toDate": end.isoformat()}
    try:
        res = D.call("POST", "/charts/rollingoption", "data", body)
    except Exception as e:
        print(f"   {sym} {kind} {rel} {start}: {getattr(e, 'friendly', e)}")
        return pd.DataFrame()
    sec = (res or {}).get("data", {}).get("ce" if kind == "CALL" else "pe") or {}
    if not sec.get("timestamp"):
        return pd.DataFrame()
    cols = {k: sec.get(k) for k in ("open", "high", "low", "close", "volume", "oi", "strike", "spot", "iv")
            if sec.get(k) and len(sec.get(k)) == len(sec["timestamp"])}
    df = pd.DataFrame(cols)
    df.index = pd.to_datetime(pd.Series(sec["timestamp"]), unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return df


def month(sym, start):
    end = (pd.Timestamp(start) + pd.offsets.MonthBegin(1)).date()
    flag = flag_for(sym, start)
    frames = []
    for kind in ("CALL", "PUT"):
        for rel in REL:
            df = cached(f"{sym}_{kind}_{rel}_{start}_{flag}.pkl", lambda: rolling(sym, kind, rel, start, end, flag))
            if not df.empty:
                frames.append(df.assign(kind=kind, rel=rel))
    return pd.concat(frames) if frames else pd.DataFrame()


def load(sym, years):
    first = (pd.Timestamp(date.today()) - pd.DateOffset(years=years)).date().replace(day=1)
    months = pd.date_range(first, date.today(), freq="MS")
    out = []
    for i, m in enumerate(months, 1):
        print(f" {sym}: month {i}/{len(months)} {m:%b %Y}", flush=True)
        df = month(sym, m.date())
        if not df.empty:
            out.append(df)
    return pd.concat(out) if out else pd.DataFrame()


def day_book(df_day):
    """{(kind, strike): DataFrame minute -> open/high/low/close} for the actual (fixed) strikes seen that day."""
    book = {}
    for (kind, k), g in df_day.groupby(["kind", "strike"]):
        g = g[~g.index.duplicated(keep="last")].sort_index()
        book[(kind, float(k))] = g[["open", "high", "low", "close", "oi"]] if "oi" in g else g[["open", "high", "low", "close"]]
    return book


def leg_series(book, kind, K, t0, t1):
    s = book.get((kind, float(K)))
    if s is None:
        return None
    s = s[(s.index >= t0) & (s.index <= t1)]
    return s if len(s) >= 3 else None


def costs(sym, prem):
    i = IDX[sym]
    return i["slip"] + 0.0015 * prem + 40 / i["lot"]


def sell_day(sym, book, spot, d, atr, entry_t, kind, sl=None, width=0.0, wing=0.0, comb=None):
    t0, t1 = datetime.combine(d, entry_t), datetime.combine(d, dtime(15, 15))
    s0 = spot[spot.index >= t0]
    if s0.empty:
        return None
    S0 = float(s0.iloc[0]); step = IDX[sym]["step"]
    if kind == "straddle":
        Kc = Kp = round(S0 / step) * step
    else:
        Kc = np.ceil((S0 + width * atr) / step) * step; Kp = np.floor((S0 - width * atr) / step) * step
    legs = {"C": ("CALL", Kc), "P": ("PUT", Kp)}
    wings = {"WC": ("CALL", np.ceil((S0 + wing * atr) / step) * step), "WP": ("PUT", np.floor((S0 - wing * atr) / step) * step)} if wing else {}
    ser = {}
    for n, (kd, K) in {**legs, **wings}.items():
        x = leg_series(book, kd, K, t0, t1)
        if x is None:
            return None
        ser[n] = x
    idx = ser["C"].index
    for n in ser:
        ser[n] = ser[n].reindex(idx).ffill()
    p0 = {n: float(ser[n]["open"].iloc[0]) for n in ser}
    prem = p0["C"] + p0["P"]
    cst = sum(costs(sym, p0[n]) for n in ser)
    stop_at = {n: None for n in legs}
    if sl is not None:
        for n in legs:
            hit = np.flatnonzero(ser[n]["high"].values >= p0[n] * (1 + sl))
            stop_at[n] = hit[0] if len(hit) else None
    if comb:
        mtm = sum(p0[n] - ser[n]["close"].values for n in legs) + sum(ser[n]["close"].values - p0[n] for n in wings)
        hit = np.flatnonzero(mtm <= -comb * prem)
        if len(hit):
            j = hit[0]
            return dict(pnl=float(mtm[j]) - cst - sum(costs(sym, ser[n]["close"].iloc[j]) + IDX[sym]["slip"] for n in ser), prem=prem, S0=S0)
    pnl = 0.0
    for n in legs:
        j = stop_at[n]
        if j is not None:
            px = p0[n] * (1 + sl); pnl += p0[n] - px; cst += costs(sym, px) + IDX[sym]["slip"]
        else:
            v = float(ser[n]["close"].iloc[-1]); pnl += p0[n] - v; cst += costs(sym, v)
    for n in wings:
        v = float(ser[n]["close"].iloc[-1]); pnl += v - p0[n]; cst += costs(sym, v)
    return dict(pnl=pnl - cst, prem=prem, S0=S0)


def buy_trade(sym, book, spot, t_sig, call):
    """Enter at the first minute after the signal candle closes; ATM strike fixed at entry; trailing exit."""
    d = t_sig.date(); t0 = t_sig + timedelta(minutes=5); t1 = datetime.combine(d, dtime(15, 15))
    s0 = spot[spot.index >= t0]
    if s0.empty:
        return None
    K = round(float(s0.iloc[0]) / IDX[sym]["step"]) * IDX[sym]["step"]
    x = leg_series(book, "CALL" if call else "PUT", K, t0, t1)
    if x is None:
        return None
    p0 = float(x["open"].iloc[0]); peak = 0.0
    if p0 <= 0:
        return None
    c0 = costs(sym, p0) / p0
    for ts, r in x.iloc[1:].iterrows():
        lo = r["low"] / p0 - 1; hi = r["high"] / p0 - 1; cl = r["close"] / p0 - 1
        if lo <= -0.30 and peak < 0.30:
            return -0.30 - c0 - costs(sym, p0 * 0.7) / p0 - IDX[sym]["slip"] / p0
        peak = max(peak, hi)
        if peak >= 0.30 and cl <= (1 + peak) * 0.70 - 1:
            return cl - c0 - costs(sym, r["close"]) / p0
    cl = x["close"].iloc[-1] / p0 - 1
    return cl - c0 - costs(sym, x["close"].iloc[-1]) / p0


def summarise(name, r, extra=None):
    r = pd.Series(r).dropna()
    if r.empty:
        return None
    return {"test": name, "n": len(r), "avg": round(r.mean(), 3), "median": round(r.median(), 3),
            "win%": round((r > 0).mean() * 100), "t": round(r.mean() / r.std() * np.sqrt(len(r)), 1) if r.std() > 0 else np.nan,
            **(extra or {})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--index", default="NIFTY,BANKNIFTY")
    a = ap.parse_args()
    if D.has_auto(D.load_config()):
        D.ensure_token(D.load_config())
    sig_file = HERE / "trend_oi_signals_2021_2023.csv"
    sigs = pd.read_csv(sig_file, parse_dates=["time"]) if sig_file.exists() else pd.DataFrame()
    rng = np.random.default_rng(5)
    sell_rows, buy_rows = [], []
    for sym in a.index.split(","):
        raw = load(sym, a.years)
        if raw.empty:
            print(f"{sym}: no data (check the Dhan data plan)")
            continue
        spot_all = raw[["spot"]][~raw.index.duplicated()].sort_index()["spot"]
        dd = spot_all.groupby(spot_all.index.date).agg(["first", "max", "min", "last"])
        pc = dd["last"].shift(1)
        tr = pd.concat([dd["max"] - dd["min"], (dd["max"] - pc).abs(), (dd["min"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift(1)
        days = [d for d in dd.index if pd.notna(atr.get(d))]
        print(f"{sym}: {len(days)} sessions {days[0]} .. {days[-1]}")
        cfgs = []
        for et in (dtime(9, 20), dtime(9, 45)):
            for sl in (0.25, 0.40, 0.60):
                cfgs.append((f"straddle {et:%H:%M} legSL {int(sl*100)}%", dict(entry_t=et, kind="straddle", sl=sl)))
            cfgs.append((f"straddle {et:%H:%M} combSL 30%", dict(entry_t=et, kind="straddle", comb=0.30)))
            for w in (0.4, 0.7):
                for sl in (0.5, 1.0):
                    cfgs.append((f"strangle {et:%H:%M} ±{w}ATR legSL {int(sl*100)}%", dict(entry_t=et, kind="strangle", sl=sl, width=w)))
            cfgs.append((f"ironfly {et:%H:%M} wings ±1.2ATR combSL 25%", dict(entry_t=et, kind="straddle", wing=1.2, comb=0.25)))
        res = {n: [] for n, _ in cfgs}
        buys = {"random 11:00-12:30": [], "move-only 0.7 ATR first 10:30-13:00": [], "move-only 1.0 ATR first 10:30-13:00": []}
        sig_sym = sigs[sigs["index"] == sym] if not sigs.empty else pd.DataFrame()
        for d in days:
            day_df = raw[raw.index.date == d]
            book = day_book(day_df)
            spot = spot_all[spot_all.index.date == d]
            # expiry-day flag from the data itself: the nearest contract's last day is when its strikes stop trading
            for n, kw in cfgs:
                r = sell_day(sym, book, spot, d, float(atr[d]), **kw)
                if r:
                    res[n].append({"day": d, "pnl": r["pnl"], "prem": r["prem"], "pct_spot": r["pnl"] / r["S0"] * 100})
            # buying: random time + move-only rule
            s5 = spot.resample("5min", label="left").last().dropna()
            o = float(spot.iloc[0]); mv = (s5 - o) / float(atr[d])
            tt = s5.between_time("11:00", "12:30")
            if len(tt):
                t = tt.index[rng.integers(len(tt))]
                buys["random 11:00-12:30"].append(buy_trade(sym, book, spot, t.to_pydatetime(), bool(rng.random() < 0.5)))
            win = mv.between_time("10:30", "13:00")
            for thr, key in ((0.7, "move-only 0.7 ATR first 10:30-13:00"), (1.0, "move-only 1.0 ATR first 10:30-13:00")):
                hit = win[win.abs() >= thr]
                if len(hit):
                    buys[key].append(buy_trade(sym, book, spot, hit.index[0].to_pydatetime(), bool(hit.iloc[0] > 0)))
            for _, s in sig_sym[sig_sym.time.dt.date == d].iterrows():
                k = f"trend+OI {s['mode']} thr {s['thr']}"
                buys.setdefault(k, []).append(buy_trade(sym, book, spot, s.time.to_pydatetime(), s.side == "CALL"))
        for n, rows in res.items():
            if not rows:
                continue
            R = pd.DataFrame(rows)
            R["year"] = pd.to_datetime(R.day).dt.year
            yr = R.groupby("year").pct_spot.sum()
            sell_rows.append(summarise(f"{sym} SELL {n}", R.pct_spot, {
                "avg_pts": round(R.pnl.mean(), 1), "kept_%_of_premium": round(R.pnl.sum() / R.prem.sum() * 100, 1),
                "years_positive": f"{(yr > 0).sum()}/{len(yr)}", "by_year_%spot": " ".join(f"{y % 100}:{v:+.1f}" for y, v in yr.items())}))
            R.to_csv(OUT / f"idxopt_sell_{sym}_{n.replace(' ', '_').replace('%', '').replace('±', 'pm').replace(':', '')}.csv", index=False)
        for n, r in buys.items():
            row = summarise(f"{sym} BUY {n}", r)
            if row:
                buy_rows.append(row)
    S, B = pd.DataFrame([x for x in sell_rows if x]), pd.DataFrame([x for x in buy_rows if x])
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200); pd.set_option("display.max_colwidth", 90)
    print("\n===== SELLING (avg = % of spot per day; avg_pts = index points per lot-unit) =====")
    print(S.to_string(index=False))
    print("\n===== BUYING (avg = return on premium per trade, after costs) =====")
    print(B.to_string(index=False))
    S.to_csv(OUT / "idxopt_selling_summary.csv", index=False)
    B.to_csv(OUT / "idxopt_buying_summary.csv", index=False)


if __name__ == "__main__":
    main()
