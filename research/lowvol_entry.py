"""'World's smallest stop loss' intraday setup (YouTube b0D4mvFZa5k, Kushal Varshney), on Dhan 5-minute bars of 206
F&O stocks, Nov 2021 - Oct 2026.

Rules as described in the video:
  1. 9:25: Nifty 50 advances vs declines -> today's side (more decliners: shorts only; more advancers: longs only).
     Here: the Nifty 100 stocks we have, change at the 9:25 candle's close vs yesterday's close.
  2. The sector moving most that way at 9:25 (F&O sector = average of its F&O stocks, 3+ stocks).
  3. Its F&O stocks moving that way, skipping any already 5%+ (or at a circuit); top 1 or 2 by move.
  4. 5-minute chart, the first 3 candles (9:15-9:30) only set the volume bar. Wait for an opposite-colour candle
     (green when shorting, red when buying) whose volume is the lowest of the day so far. Sell-stop 1 tick below its
     low (buy-stop above its high), stop loss at its other end. If a newer such candle appears before the order
     fills, move the order to it. New orders until 14:30.
  5. Exits tested: (a) half at 1:2, rest stop to cost, hold to the close (the video's default); (b) all at 1:2;
     (c) hold all to the close with the stop; (d) 10-EMA trail (exit when a candle closes back across the 10-EMA).
Fills: stop assumed before target inside a bar; an entry bar that also reaches the stop counts as stopped.
Costs 0.12% round trip on the stock (cash/futures). Results in % of price and in R (risk = entry to stop).

Usage (Omnipuls folder, after momentum_dhan.py cached the 5-minute data):
  .venv\\Scripts\\python research\\lowvol_entry.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import scanners as SC  # noqa: E402
import universe as U  # noqa: E402
from bigbars_dhan import load_cache  # noqa: E402

warnings.filterwarnings("ignore")
COST = 0.0012
TICK = 0.05
LAST_SETUP = pd.Timestamp("14:30").time()


def prep(df: pd.DataFrame) -> pd.DataFrame:
    idx = pd.DatetimeIndex(df.index)
    df = df.copy()
    df.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    df = df[~df.index.duplicated()].sort_index().between_time("09:15", "15:25")
    return df[df["Volume"] > 0]


def ema(x: np.ndarray, n=10) -> np.ndarray:
    a, out = 2 / (n + 1), np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def simulate(g: pd.DataFrame, s: int) -> dict | None:
    """One stock-day, side s (+1 long, -1 short). Returns the trade under each exit, or None if no fill."""
    O, H, L, C, V = (g[c].to_numpy(float) for c in ("Open", "High", "Low", "Close", "Volume"))
    t = g.index.time
    n = len(g)
    if n < 10:
        return None
    minvol = V[:3].min()
    pend = None
    for k in range(3, n):
        if pend is not None:
            e, stp = pend
            hit = (L[k] <= e) if s < 0 else (H[k] >= e)
            if hit:
                fill = min(O[k], e) if s < 0 else max(O[k], e)
                return manage(O, H, L, C, t, k, fill, stp, s)
        if t[k] <= LAST_SETUP:
            opp = (C[k] > O[k]) if s < 0 else (C[k] < O[k])
            if opp and V[k] <= minvol:
                pend = (L[k] - TICK, H[k] + TICK) if s < 0 else (H[k] + TICK, L[k] - TICK)
        elif pend is None:
            return None
        minvol = min(minvol, V[k])
    return None


def manage(O, H, L, C, t, k, e, stp, s) -> dict:
    risk = abs(e - stp)
    if risk <= 0:
        return None
    n = len(C)
    em = ema(C)
    res = {"entry_t": t[k], "risk %": risk / e * 100}

    def run(mode):
        half_done, stop = False, stp
        realised = 0.0  # in price points, per 1 unit, weighted by position share
        size = 1.0
        for j in range(k, n):
            # stop first (conservative), including the entry bar
            if (s < 0 and H[j] >= stop) or (s > 0 and L[j] <= stop):
                px = stop if not ((s < 0 and O[j] > stop and j > k) or (s > 0 and O[j] < stop and j > k)) else O[j]
                return realised + size * s * (px - e)
            tgt = e + s * 2 * risk
            if mode in ("half", "target") and not half_done and ((s > 0 and H[j] >= tgt) or (s < 0 and L[j] <= tgt)):
                if mode == "target":
                    return s * (tgt - e)
                realised += 0.5 * s * (tgt - e)
                size, half_done, stop = 0.5, True, e
            if mode == "ema" and j > k and ((s < 0 and C[j] > em[j]) or (s > 0 and C[j] < em[j])):
                px = O[j + 1] if j + 1 < n else C[j]
                return realised + size * s * (px - e)
        return realised + size * s * (C[-1] - e)

    for mode in ("half", "target", "close", "ema"):
        pts = run(mode)
        res[mode + " %"] = (pts / e - COST) * 100
        res[mode + " R"] = (pts - COST * e) / risk
    return res


def main():
    nifty, raw = load_cache()
    data = {s: prep(df) for s, df in raw.items()}
    data = {s: d for s, d in data.items() if not d.empty}
    print(f"{len(data)} stocks")
    # per stock per day: prev close, 9:25 candle close
    day_groups, c925, closes = {}, {}, {}
    for s, d in data.items():
        g = {k: v for k, v in d.groupby(d.index.normalize())}
        day_groups[s] = g
        closes[s] = pd.Series({k: v["Close"].iloc[-1] for k, v in g.items()})
        c925[s] = pd.Series({k: v.loc[v.index.time == pd.Timestamp("09:25").time(), "Close"].iloc[0]
                             for k, v in g.items() if (v.index.time == pd.Timestamp("09:25").time()).any()})
    CL, P = pd.DataFrame(closes).sort_index(), pd.DataFrame(c925).sort_index()
    chg = P / CL.shift(1) - 1
    big = (CL / CL.shift(1) - 1).abs() > 0.25  # corporate actions
    chg = chg.mask(big | big.shift(1, fill_value=False))
    n100 = [s for s in SC.NIFTY100 if s in chg.columns]
    sec_of = pd.Series(U.FNO_SECTOR_OF).reindex(chg.columns).fillna("Other")
    rows = []
    for day, row in chg.iterrows():
        r = row.dropna()
        if len(r) < 100:
            continue
        a = r.reindex(n100).dropna()
        adv, dec = (a > 0).sum(), (a < 0).sum()
        if adv == dec:
            continue
        side = 1 if adv > dec else -1
        sec = r.groupby(sec_of.reindex(r.index)).agg(["mean", "size"])
        sec = sec[(sec["size"] >= 3) & (sec.index != "Other")]
        if sec.empty:
            continue
        best = (side * sec["mean"]).idxmax()
        if side * sec.loc[best, "mean"] <= 0:
            continue
        members = r[(sec_of.reindex(r.index) == best) & (side * r > 0) & (r.abs() < 0.05)]
        cands = (side * members).sort_values(ascending=False).index[:2]
        for rank, sym in enumerate(cands, 1):
            g = day_groups[sym].get(day)
            if g is None:
                continue
            tr = simulate(g, side)
            if tr:
                rows.append({"date": day, "sym": sym, "rank": rank, "side": side, "sector": best,
                             "adv": adv, "dec": dec, "move 9:25 %": r[sym] * 100, **tr})
    T = pd.DataFrame(rows)
    T.to_csv(HERE / "results" / "lowvol_entry_trades.csv.gz", index=False)
    days = chg.index.size
    print(f"{len(T)} trades on {T['date'].nunique()} of {days} days; median risk {T['risk %'].median():.2f}% of price; "
          f"entry median {pd.Series([x.hour * 60 + x.minute for x in T['entry_t']]).median() // 60:.0f}:"
          f"{pd.Series([x.hour * 60 + x.minute for x in T['entry_t']]).median() % 60:02.0f}")

    def summ(x: pd.DataFrame, label: str):
        out = {"set": label, "trades": len(x)}
        for m in ("half", "target", "close", "ema"):
            p = x[m + " %"]
            out[m + " %"] = round(p.mean(), 3)
            out[m + " R"] = round(x[m + " R"].mean(), 2)
        p = x["half %"]
        out["half win %"] = round(100 * (p > 0).mean(), 1)
        out["half t"] = round(p.mean() / (p.std() / np.sqrt(len(p))), 2)
        yr = x.groupby(x["date"].dt.year)["half %"].mean()
        out["yrs + (half)"] = f"{int((yr > 0).sum())}/{len(yr)}"
        out["2025"] = round(yr.get(2025, np.nan), 3)
        out["2026"] = round(yr.get(2026, np.nan), 3)
        return out

    S = [summ(T, "all (top 2 per day)"), summ(T[T["rank"] == 1], "top 1 only"),
         summ(T[T["side"] < 0], "shorts"), summ(T[T["side"] > 0], "longs"),
         summ(T[T["risk %"] >= 0.4], "risk >= 0.4% of price"), summ(T[T["risk %"] < 0.4], "risk < 0.4%"),
         summ(T[T["date"] < "2024-05-01"], "first half"), summ(T[T["date"] >= "2024-05-01"], "second half")]
    pd.set_option("display.width", 250)
    print("Per trade after 0.12% costs. half = half at 1:2 + rest to cost, hold to close (the video's way);"
          " target = all at 1:2; close = hold to close; ema = 10-EMA trail.")
    print(pd.DataFrame(S).to_string(index=False))
    # gross, before costs: is there any edge to start with?
    g = T.copy()
    for m in ("half", "close"):
        g[m + " %"] = g[m + " %"] + COST * 100
    print(f"\nBefore costs: half {g['half %'].mean():+.3f}%, close {g['close %'].mean():+.3f}% per trade")
    yr = T.groupby(T["date"].dt.year).agg(trades=("half %", "size"), half=("half %", "mean"),
                                          close=("close %", "mean"), R_half=("half R", "mean"))
    print(yr.round(3).to_string())


if __name__ == "__main__":
    main()
