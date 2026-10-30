"""Scalping on the index build-up bars (the Index Build-up page): does a 3-minute bar's option + futures OI build-up
tell us where Nifty / Bank Nifty / Fin Nifty go in the next few minutes?

History: Dhan keeps 1-minute OI only for contracts that have not expired, about a month back. So each past day is
rebuilt from the nearest expiry that is still live today (for days before the last expiry that is the next week's
or next month's contract, a proxy for what the page shows live), with the 5 strikes each side of that day's open,
plus the near-month future. Same arithmetic as apex.buildup.

Tests (3-minute bars, from 9:30 to 15:00, index points before costs):
  1. information: average next 3 / 6 / 15 / 30-minute move after bullish vs bearish bars, by bar strength;
  2. burst: one bar with net build-up >= k x the day's typical bar, entry at its close, in its direction;
  3. streak: 3 bars in a row the same way, entry at the third bar's close;
  4. trade version of 2 and 3: stop S points, target 3S, out after 30 minutes.
Costs for an at-the-money option scalp come to roughly 2-3 Nifty points of index move (spread + charges at delta
0.5), so an edge must clear that.

Usage (Omnipuls folder):  .venv\\Scripts\\python research\\apex_backtest.py
"""
from __future__ import annotations

import pickle
import sys
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dhan as D  # noqa: E402

CACHE = HERE / "cache" / "apex"
CACHE.mkdir(parents=True, exist_ok=True)
OUT = HERE / "results"
INDICES = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27}
STRIKES = 5
DAYS = 40
COST_PTS = {"NIFTY": 2.5, "BANKNIFTY": 6.0, "FINNIFTY": 3.0}  # round-trip cost of an ATM option scalp, index points
STOP_PTS = {"NIFTY": 15, "BANKNIFTY": 40, "FINNIFTY": 18}


def _naive(df):
    if df is None or df.empty:
        return pd.DataFrame()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    df = df.copy()
    df.index = idx
    return df[~df.index.duplicated(keep="last")].sort_index()


def bars1(seg, sid, instrument, days=DAYS) -> pd.DataFrame:
    """1-minute bars, cached for the day."""
    f = CACHE / f"{seg}_{sid}_{date.today():%Y%m%d}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    for attempt in range(3):
        try:
            df = _naive(D.intraday(seg, sid, instrument, 1, days))
            break
        except D.DhanError as e:
            if attempt == 2:
                print("  skip", seg, sid, e)
                df = pd.DataFrame()
            time.sleep(2)
    if not df.empty:
        f.write_bytes(pickle.dumps(df))
    return df


def to3(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = []
    for day, g in df.groupby(df.index.normalize()):
        g = g.between_time("09:15", "15:29")
        if g.empty:
            continue
        agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        if "OI" in g:
            agg["OI"] = "last"
        out.append(g.resample("3min", origin=day + pd.Timedelta(minutes=555), label="left", closed="left")
                   .agg(agg).dropna(subset=["Close"]))
    return pd.concat(out) if out else pd.DataFrame()


def chains(sid: int) -> dict:
    """{expiry: chain} for the live expiries in the next ~45 days (strike -> CE/PE security IDs)."""
    f = CACHE / f"chains_{sid}_{date.today():%Y%m%d}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    out = {}
    for e in D.expiries(sid, "IDX_I"):
        if (pd.Timestamp(e).date() - date.today()).days > 45:
            break
        _, ch = D.option_chain(sid, "IDX_I", e)
        out[e] = ch[["Strike", "CE ID", "PE ID"]].dropna(subset=["Strike"])
        time.sleep(3.1)
    f.write_bytes(pickle.dumps(out))
    return out


def rebuild(name: str, sid: int) -> pd.DataFrame:
    """Build-up bars for every past day that has enough live-contract data."""
    px = to3(bars1("IDX_I", sid, "INDEX"))
    if px.empty:
        raise SystemExit(f"No {name} index bars from Dhan (token or connection).")
    fut = D.nearest_futures("NSE_FNO", "FUTIDX", [name])[name]
    fb = to3(bars1("NSE_FNO", fut["id"], "FUTIDX"))
    lot = float(fut["lot"])
    ch = chains(sid)
    days = sorted(set(px.index.normalize()))
    rows = []
    for day in days:
        p = px[px.index.normalize() == day]
        spot = float(p["Open"].iloc[0])
        for exp, c in ch.items():  # nearest live expiry that has this day's data
            if pd.Timestamp(exp) < day:
                continue
            near = c.assign(d=(c["Strike"] - spot).abs()).nsmallest(2 * STRIKES + 1, "d")
            ce, pe, got = [], [], 0
            for _, r in near.iterrows():
                for side, store in (("CE ID", ce), ("PE ID", pe)):
                    if pd.isna(r[side]):
                        continue
                    b = to3(bars1("NSE_FNO", int(r[side]), "OPTIDX"))
                    b = b[b.index.normalize() == day] if not b.empty else b
                    if not b.empty and "OI" in b and b["OI"].gt(0).any():
                        store.append(b["OI"])
                        got += 1
            if got >= 0.7 * 2 * len(near):
                break
        else:
            continue
        if got < 0.7 * 2 * len(near):
            continue

        def total(cols):
            return pd.concat(cols, axis=1, sort=True).reindex(p.index).ffill().bfill().sum(axis=1)

        d_ce, d_pe = total(ce).diff().fillna(0) / lot, total(pe).diff().fillna(0) / lot
        out = p[["Open", "High", "Low", "Close"]].copy()
        out["bull"] = 0.5 * (d_pe.clip(lower=0) + (-d_ce).clip(lower=0))
        out["bear"] = 0.5 * (d_ce.clip(lower=0) + (-d_pe).clip(lower=0))
        f = fb[fb.index.normalize() == day].reindex(p.index).ffill()
        if not f.empty and "OI" in f:
            d_oi = f["OI"].diff().fillna(0).abs() / lot
            d_px = f["Close"].diff().fillna(0)
            out["bull"] += np.where(d_px > 0, d_oi, 0.0)
            out["bear"] += np.where(d_px < 0, d_oi, 0.0)
        out.iloc[0, out.columns.get_indexer(["bull", "bear"])] = 0.0
        out["net"] = out["bull"] - out["bear"]
        out["expiry"] = exp
        out["index"] = name
        rows.append(out)
        print(f"  {name} {day:%d %b} expiry {exp} contracts {got}")
    return pd.concat(rows) if rows else pd.DataFrame()


def features(b: pd.DataFrame) -> pd.DataFrame:
    """Per day: strength = net / median gross of the day's bars so far (no look-ahead); forward moves."""
    out = []
    for _, g in b.groupby(b.index.normalize()):
        g = g.copy()
        gross = (g["bull"] + g["bear"]).replace(0, np.nan)
        typ = gross.expanding(min_periods=5).median().shift(1)
        g["strength"] = g["net"] / typ
        g["share"] = g["bull"] / gross
        for n in (1, 2, 5, 10):
            g[f"fwd{n * 3}"] = g["Close"].shift(-n) - g["Close"]
        s = np.sign(g["net"])
        g["streak"] = s.groupby((s != s.shift()).cumsum()).cumcount() + 1
        g["streak"] *= s
        g["cum"] = g["net"].cumsum()
        out.append(g)
    return pd.concat(out)


def trade(g: pd.DataFrame, i: int, side: int, stop: float, max_bars: int = 10) -> float:
    """Entry at bar i's close; stop `stop` points, target 3x stop, else out after max_bars (bar highs/lows)."""
    entry = g["Close"].iloc[i]
    for j in range(i + 1, min(i + 1 + max_bars, len(g))):
        hi, lo = g["High"].iloc[j], g["Low"].iloc[j]
        if side > 0:
            if lo <= entry - stop:
                return -stop
            if hi >= entry + 3 * stop:
                return 3 * stop
        else:
            if hi >= entry + stop:
                return -stop
            if lo <= entry - 3 * stop:
                return 3 * stop
    j = min(i + max_bars, len(g) - 1)
    return side * (g["Close"].iloc[j] - entry)


def report(name: str, f: pd.DataFrame):
    win = f[(f.index.time >= pd.Timestamp("09:30").time()) & (f.index.time <= pd.Timestamp("15:00").time())]
    win = win.dropna(subset=["strength", "fwd15"])
    days = win.index.normalize().nunique()
    cost = COST_PTS[name]
    print(f"\n=== {name}: {days} days, {len(win)} bars (9:30-15:00) · cost per scalp ~{cost} pts ===")
    print("1. Next move after a bar, by its strength (net / typical bar), in index points, signed in the bar's way:")
    rows = []
    for lo, hi in ((0, 0.5), (0.5, 1), (1, 2), (2, 4), (4, np.inf)):
        m = win[(win["strength"].abs() >= lo) & (win["strength"].abs() < hi)]
        s = np.sign(m["strength"])
        rows.append({"strength": f"{lo}-{hi}", "bars": len(m),
                     **{f"next {n} min": round((s * m[f"fwd{n}"]).mean(), 2) for n in (3, 6, 15, 30)},
                     "15-min hit %": round(100 * ((s * m["fwd15"]) > 0).mean(), 1)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("2-3. Trades: entry at the signal bar's close, stop/target 1:3, out after 30 min (after cost):")
    stop = STOP_PTS[name]
    res = []
    for label, cond in (("burst k>=2", lambda g: g["strength"].abs() >= 2),
                        ("burst k>=3", lambda g: g["strength"].abs() >= 3),
                        ("streak 3", lambda g: g["streak"].abs() == 3),
                        ("streak 3 + cum same way", lambda g: (g["streak"].abs() == 3)
                         & (np.sign(g["cum"]) == np.sign(g["streak"]))),
                        ("burst k>=2 + cum same way", lambda g: (g["strength"].abs() >= 2)
                         & (np.sign(g["cum"]) == np.sign(g["strength"]))),
                        ("against: fade burst k>=2", lambda g: g["strength"].abs() >= 2)):
        pnl, by_day = [], {}
        for day, g in f.groupby(f.index.normalize()):
            busy_until = -1
            ok = cond(g).fillna(False).to_numpy()
            for i in range(len(g)):
                t = g.index[i].time()
                if not ok[i] or i <= busy_until or t < pd.Timestamp("09:30").time() or t > pd.Timestamp("14:45").time():
                    continue
                side = int(np.sign(g["strength"].iloc[i] if "burst" in label else g["streak"].iloc[i]))
                if label.startswith("against"):
                    side = -side
                r = trade(g, i, side, stop) - cost
                pnl.append(r)
                by_day.setdefault(day, []).append(r)
                busy_until = i + 10
        p = pd.Series(pnl, dtype=float)
        dsum = pd.Series({k: sum(v) for k, v in by_day.items()}, dtype=float)
        half = len(p) // 2
        res.append({"rule": label, "trades": len(p), "per trade pts": round(p.mean(), 2) if len(p) else np.nan,
                    "win %": round(100 * (p > 0).mean(), 1) if len(p) else np.nan,
                    "1st half": round(p.iloc[:half].mean(), 2) if half else np.nan,
                    "2nd half": round(p.iloc[half:].mean(), 2) if half else np.nan,
                    "green days": f"{int((dsum > 0).sum())}/{len(dsum)}",
                    "t-stat": round(p.mean() / (p.std() / np.sqrt(len(p))), 2) if len(p) > 2 and p.std() else np.nan})
    print(pd.DataFrame(res).to_string(index=False))


def main():
    allb = []
    for name, sid in INDICES.items():
        print(f"Rebuilding {name}…")
        b = rebuild(name, sid)
        if b.empty:
            print("  no days")
            continue
        allb.append(b)
        report(name, features(b))
    if allb:  # keep every rebuilt day: Dhan drops a month-old day, this file doesn't, so the sample grows per run
        new = pd.concat(allb)
        f = OUT / "apex_history.csv.gz"
        if f.exists():
            old = pd.read_csv(f, index_col=0, parse_dates=True)
            key = lambda d: d["index"] + d.index.strftime("%Y%m%d")  # noqa: E731
            new = pd.concat([old[~key(old).isin(set(key(new)))], new]).sort_index()
        new.to_csv(f)


if __name__ == "__main__":
    main()
