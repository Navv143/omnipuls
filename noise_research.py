"""Nightly on the server: the Noise Area strategy (Zarattini et al. 2024) on the Dhan year of 5-minute index candles,
and the noise band as a filter on the index momentum bot's bursts. -> <data>/bot/noise_band.json + Supabase
bot_results ('noise_band <run_at>').

A. Strategy: bands = max/min(open, previous close) x (1 ± band x average |move from the open| at that time of day
   over `lookback` sessions); checks every 30 minutes from the open (9:45, 10:15, ...); close above the upper band →
   long, below the lower → short; trailing stop = band or VWAP (TWAP when the index has no volume); fills at the next
   candle's open; flat at 15:15. Grid of lookback x band, at 0.02% and 0.04% round-trip cost.
B. Filter: every confirmed momentum burst of index_funnel.momentum_table (first per day and direction, 9:30-14:30):
   the result in its direction to 15:15 and over the next 6 candles (30 min), after 0.04% cost, split by whether the
   burst's close was outside the noise band (beyond the upper band for an up burst / the lower for a down burst).
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

INDEXES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
GRID_LB, GRID_BAND = (3, 5, 10, 14), (0.5, 0.75, 1.0, 1.25)
FLAT = "15:15"


def _session(df: pd.DataFrame) -> pd.DataFrame:
    x = df[~df.index.duplicated(keep="last")].sort_index()
    t = x.index.strftime("%H:%M")
    x = x[(t >= "09:15") & (t < "15:30")].copy()
    x["day"] = x.index.normalize()
    x["tod"] = x.index.strftime("%H:%M")
    if "Volume" not in x:
        x["Volume"] = 0.0
    return x


def bands(x: pd.DataFrame, lookback: int, band: float) -> pd.DataFrame:
    x = x.copy()
    first = x.groupby("day")["Open"].transform("first")
    x["move"] = (x["Close"] / first - 1).abs()
    piv = x.pivot_table(index="day", columns="tod", values="move")
    sig = piv.rolling(lookback, min_periods=lookback).mean().shift()
    s = sig.stack()
    x["sigma"] = pd.Series(s.to_numpy(), index=pd.MultiIndex.from_tuples(s.index)).reindex(
        pd.MultiIndex.from_arrays([x["day"], x["tod"]])).to_numpy()
    pc = x["day"].map(x.groupby("day")["Close"].last().shift())
    x["ub"] = np.maximum(first, pc) * (1 + band * x["sigma"])
    x["lb"] = np.minimum(first, pc) * (1 - band * x["sigma"])
    tp = (x["High"] + x["Low"] + x["Close"]) / 3
    v = x["Volume"].replace(0, np.nan).fillna(1.0)
    x["vwap"] = (tp * v).groupby(x["day"]).cumsum() / v.groupby(x["day"]).cumsum()
    return x


def strategy(x: pd.DataFrame, cost_rt: float, checks: set) -> tuple[pd.DataFrame, pd.Series]:
    trades, daily = [], {}
    for d, g in x.groupby("day", sort=True):
        if g["sigma"].isna().all():
            continue
        o, c, ub, lb, vw, tod = (g[k].to_numpy() for k in ("Open", "Close", "ub", "lb", "vwap", "tod"))
        pos, entry, dr = 0, None, 0.0
        n = len(g)
        last_i = n - 1
        for i in range(n - 1):
            if tod[i + 1] >= FLAT:          # the next open is at / after 15:15: no new decisions
                last_i = i + 1
                break
            if tod[i] not in checks or not np.isfinite(ub[i]):
                continue
            want = pos
            if pos == 0:
                want = 1 if c[i] > ub[i] else -1 if c[i] < lb[i] else 0
            elif pos > 0 and c[i] < max(ub[i], vw[i]):
                want = -1 if c[i] < lb[i] else 0
            elif pos < 0 and c[i] > min(lb[i], vw[i]):
                want = 1 if c[i] > ub[i] else 0
            if want != pos:
                px = o[i + 1]
                if pos:
                    r = pos * (px / entry - 1) * 100 - cost_rt
                    trades.append({"day": d, "side": pos, "pct": r})
                    dr += r
                pos, entry = want, (px if want else None)
        if pos:
            px = o[last_i] if last_i < n else c[-1]
            r = pos * (px / entry - 1) * 100 - cost_rt
            trades.append({"day": d, "side": pos, "pct": r})
            dr += r
        daily[d] = dr
    return pd.DataFrame(trades), pd.Series(daily, dtype=float)


def _st(t: pd.DataFrame, d: pd.Series) -> dict:
    if t.empty or d.empty:
        return {"trades": 0}
    dd = d / 100
    h = len(d) // 2
    eq = (1 + dd).cumprod()
    return {"days": int(len(d)), "trades": int(len(t)), "win": round(float((t.pct > 0).mean() * 100)),
            "avg_pct": round(float(t.pct.mean()), 4), "total_pct": round(float(d.sum()), 2),
            "sharpe": round(float(dd.mean() / dd.std() * np.sqrt(248)), 2) if dd.std() > 0 else None,
            "max_dd": round(float((eq / eq.cummax() - 1).min() * 100), 2),
            "h1": round(float(d.iloc[:h].sum()), 2), "h2": round(float(d.iloc[h:].sum()), 2)}


def filter_test(ix: pd.DataFrame, stocks: dict, weights: dict, lookback=14, band=1.0, cost_rt=0.04) -> dict:
    """Momentum bursts inside vs outside the noise band."""
    import index_funnel as IF
    t = IF.momentum_table(ix, stocks, weights, today_only=False)
    if t.empty:
        return {}
    x = bands(_session(ix), lookback, band)
    t = t.join(x[["ub", "lb"]], how="left")
    t["hm"] = t.index.strftime("%H:%M")
    b = t[t["momentum"] & (t["hm"] >= "09:30") & (t["hm"] <= "14:30")].copy()
    b = b[~b.duplicated(["day", "msd"])]                      # first burst per day and direction
    close = t["Close"]
    rows = []
    for ts, r in b.iterrows():
        day = t[t["day"] == r["day"]]
        after = day[day.index > ts]
        if len(after) < 2:
            continue
        e = after["Open"].iloc[0]
        flat = after[after["hm"] >= FLAT]
        ex_close = flat["Open"].iloc[0] if len(flat) else after["Close"].iloc[-1]
        ex_6 = after["Close"].iloc[min(5, len(after) - 1)]
        out = (r["Close"] > r["ub"]) if r["msd"] > 0 else (r["Close"] < r["lb"])
        if not np.isfinite(r["ub"]):
            continue
        rows.append({"outside": bool(out), "to_close": r["msd"] * (ex_close / e - 1) * 100 - cost_rt,
                     "next6": r["msd"] * (ex_6 / e - 1) * 100 - cost_rt, "trend_day": bool(r["trend_day"])})
    if not rows:
        return {}
    d = pd.DataFrame(rows)

    def g(z):
        return {"n": int(len(z)), "to_close": round(float(z.to_close.mean()), 4) if len(z) else None,
                "next6": round(float(z.next6.mean()), 4) if len(z) else None,
                "win": round(float((z.to_close > 0).mean() * 100)) if len(z) else None}
    return {"all": g(d), "outside": g(d[d.outside]), "inside": g(d[~d.outside]),
            "outside_normal_day": g(d[d.outside & ~d.trend_day]), "inside_normal_day": g(d[~d.outside & ~d.trend_day])}


def research(ix_bars: dict, stocks: dict, weights: dict) -> dict:
    res = {"run_at": datetime.now().isoformat(timespec="seconds"), "indices": {}}
    for k in INDEXES:
        df = ix_bars.get(k)
        if df is None or df.empty:
            continue
        x0 = _session(df)
        opn = pd.Timestamp("09:15")
        checks = {(opn + pd.Timedelta(minutes=30 * i)).strftime("%H:%M") for i in range(1, 13)}   # 9:45 ... 15:15
        grid = []
        for lb in GRID_LB:
            for bd in GRID_BAND:
                x = bands(x0, lb, bd)
                for cost in (0.02, 0.04):
                    t, d = strategy(x, cost, checks)
                    d = d.iloc[20:]
                    t = t[t.day.isin(d.index)] if not t.empty else t
                    grid.append({"lookback": lb, "band": bd, "cost": cost, **_st(t, d)})
        out = {"grid": grid, "days": int(x0["day"].nunique()),
               "from": str(x0.index.min())[:10], "to": str(x0.index.max())[:10]}
        try:
            out["filter"] = filter_test(df, stocks, weights.get(k, {}))
        except Exception as e:
            out["filter_error"] = str(e)[:200]
        res["indices"][k] = out
    return res


def run_server() -> dict | None:
    import bot as B
    import indices as IX
    import paths
    bars = {f.stem.replace("_and_", "&"): pd.read_parquet(f) for f in B.CACHE.glob("*.parquet")}
    ix = {k: bars[k] for k in INDEXES if k in bars}
    if not ix:
        return None
    try:
        weights = {k: d.get("w", {}) for k, d in IX.load().items()}
    except Exception:
        weights = {k: IX._norm(v) for k, v in IX.BUILTIN.items()}
    res = research(ix, bars, weights)
    res["source"] = "Dhan 5-minute (Setup Finder cache)"
    out = paths.DATA / "bot"
    out.mkdir(parents=True, exist_ok=True)
    (out / "noise_band.json").write_text(json.dumps(res, default=str))
    try:
        import cloudstore
        if not cloudstore.enabled():
            try:
                import streamlit as st
                sb = dict(st.secrets.get("supabase") or {})
                cloudstore.configure(sb.get("url"), sb.get("key"))
            except Exception:
                pass
        cloudstore.upsert_rows("bot_results", [{"run_at": "noise_band " + res["run_at"],
                                                "result": json.loads(json.dumps(res, default=str))}], "run_at")
        import time as _t
        _t.sleep(3)
    except Exception:
        pass
    return res


if __name__ == "__main__":
    r = run_server()
    print("noise band:", {k: (v.get("filter") or {}).get("outside") for k, v in ((r or {}).get("indices") or {}).items()})
