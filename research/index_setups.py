"""Index intraday setups for option buyers: Nifty and Bank Nifty, Dhan 5-minute bars, Nov 2021 - Oct 2026.

Each rule decides with bars already closed; entry at the next bar's open; stop checked on bar highs/lows (stop
assumed first inside a bar); exit at 15:15 unless the rule says otherwise.

Two scores per trade:
  idx %   = index move in the trade's way minus 0.03% (futures round trip);
  opt %   = what an at-the-money option buyer keeps, in % of the index: 0.5 x move - 0.017% cost - theta.
            Theta of a weekly ATM option is about 0.05% of the index per trading hour, 0.025% for monthly-style
            (Bank Nifty since late 2024); held time counts.
A rule is worth trading only if opt % is positive in most years and in both halves.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\index_setups.py
"""
from __future__ import annotations

import glob
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
FUT_COST, OPT_COST = 0.03, 0.017
T915, T1515 = pd.Timestamp("09:15").time(), pd.Timestamp("15:15").time()


def load(sid: int) -> pd.DataFrame:
    f = sorted(glob.glob(str(HERE / "cache" / f"IDX_I_{sid}_5_1800_*.pkl")))[-1]
    df = pickle.loads(Path(f).read_bytes())
    idx = pd.DatetimeIndex(df.index)
    df.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    df = df[~df.index.duplicated()].sort_index().between_time("09:15", "15:25")
    return df


def theta_per_hour(name: str, day) -> float:
    if name == "BANKNIFTY" and day >= pd.Timestamp("2024-11-20"):
        return 0.025  # Bank Nifty weeklies ended: monthly options decay slower intraday
    return 0.05


def sim(day: pd.DataFrame, i: int, side: int, stop: float | None, target: float | None = None,
        exit_t=T1515) -> tuple[float, float, float]:
    """Entry at bar i's open. Returns (move % in trade's way, hours held, exit price)."""
    entry = day["Open"].iloc[i]
    for j in range(i, len(day)):
        b = day.iloc[j]
        if day.index[j].time() > exit_t:
            px = day["Open"].iloc[j]
            break
        if stop is not None and ((side > 0 and b["Low"] <= stop) or (side < 0 and b["High"] >= stop)):
            px = stop if not ((side > 0 and b["Open"] < stop) or (side < 0 and b["Open"] > stop)) else b["Open"]
            break
        if target is not None and ((side > 0 and b["High"] >= target) or (side < 0 and b["Low"] <= target)):
            px = target
            break
    else:
        j, px = len(day) - 1, day["Close"].iloc[-1]
    hours = (day.index[min(j, len(day) - 1)] - day.index[i]).seconds / 3600 + 5 / 60
    return side * (px / entry - 1) * 100, hours, px


def first_at(day: pd.DataFrame, t: str) -> int | None:
    k = np.searchsorted(day.index.time, pd.Timestamp(t).time())
    return int(k) if k < len(day) else None


def rules(name: str, df: pd.DataFrame):
    """Yield (rule, date, side, move %, hours)."""
    days = {d: g for d, g in df.groupby(df.index.normalize())}
    keys = sorted(days)
    daily = pd.DataFrame({d: {"o": g["Open"].iloc[0], "h": g["High"].max(), "l": g["Low"].min(),
                              "c": g["Close"].iloc[-1]} for d, g in days.items()}).T.sort_index()
    pc = daily["c"].shift(1)
    tr = pd.concat([daily["h"] - daily["l"], (daily["h"] - pc).abs(), (daily["l"] - pc).abs()], axis=1).max(axis=1)
    atr = (tr.rolling(14).mean() / daily["c"]).shift(1) * 100  # % ATR known before the day
    rng7 = (daily["h"] - daily["l"]).rolling(7)
    nr7 = ((daily["h"] - daily["l"]) <= rng7.min()).shift(1)
    for n, d in enumerate(keys[1:], 1):
        g = days[d]
        if len(g) < 60 or pd.isna(atr.get(d)):
            continue
        prev = daily.loc[keys[n - 1]]
        a = atr[d]
        o = g["Open"].iloc[0]
        gap = (o / prev["c"] - 1) * 100
        cl = g["Close"]
        vw = ((g["High"] + g["Low"] + g["Close"]) / 3).expanding().mean()  # index has no volume: typical-price mean
        # 1. opening drive: 9:15-9:45 move > k ATR, follow it at 9:45, stop at the 9:15-9:45 extreme against
        i = first_at(g, "09:45")
        mv = (cl.iloc[i - 1] / o - 1) * 100
        for k in (0.25, 0.4):
            if abs(mv) >= k * a:
                s = int(np.sign(mv))
                first = g.iloc[:i]
                stop = first["Low"].min() if s > 0 else first["High"].max()
                yield (f"opening drive >{k} ATR, follow", d, s, *sim(g, i, s, stop)[:2])
                yield (f"opening drive >{k} ATR, fade", d, -s, *sim(g, i, -s, cl.iloc[i - 1] * (1 + s * a / 200))[:2])
        # 2. gap fade toward yesterday's close
        for gmin in (0.4, 0.7):
            if abs(gap) >= gmin:
                s = -int(np.sign(gap))
                i = first_at(g, "09:20")
                first = g.iloc[:i]
                stop = first["Low"].min() if s > 0 else first["High"].max()
                stop = (stop * (1 - 0.0005 * s))
                yield (f"gap {gmin}%+ fade at 9:20, target prev close", d, s,
                       *sim(g, i, s, stop, target=prev["c"])[:2])
                yield (f"gap {gmin}%+ follow at 9:20", d, -s, *sim(g, i, -s, first["High"].max() if -s < 0
                                                                   else first["Low"].min())[:2])
        # 3. 15/30/60-min opening range breakout, stop other side, plus NR7-day variant
        for m, t in ((15, "09:30"), (30, "09:45"), (60, "10:15")):
            i0 = first_at(g, t)
            hi, lo = g["High"].iloc[:i0].max(), g["Low"].iloc[:i0].min()
            later = g.iloc[i0:]
            up = later.index[later["Close"] > hi]
            dn = later.index[later["Close"] < lo]
            if len(up) or len(dn):
                tu = up[0] if len(up) else pd.Timestamp.max
                td = dn[0] if len(dn) else pd.Timestamp.max
                s, t_sig = (1, tu) if tu < td else (-1, td)
                if t_sig.time() <= pd.Timestamp("13:30").time():
                    j = g.index.get_loc(t_sig) + 1
                    if j < len(g):
                        r = sim(g, j, s, lo if s > 0 else hi)
                        yield (f"{m}-min ORB, stop other side", d, s, *r[:2])
                        if nr7.get(d) is True:
                            yield (f"{m}-min ORB on NR7 day", d, s, *r[:2])
        # 4. VWAP trend at 11:00 / 12:00: above VWAP and above open -> long to close (below/below -> short)
        for t in ("11:00", "12:00", "13:30"):
            i = first_at(g, t)
            c, v = cl.iloc[i - 1], vw.iloc[i - 1]
            if (c > v and c > o) or (c < v and c < o):
                s = 1 if c > v else -1
                yield (f"trend at {t} (VWAP + open same way), hold to 15:15", d, s,
                       *sim(g, i, s, v * (1 - s * 0.001))[:2])
        # 5. yesterday's high/low break by a 5-min close (9:20-13:00), stop 0.25 ATR back inside
        brk_up = g.index[(cl > prev["h"]) & (g.index.time >= pd.Timestamp("09:20").time())]
        brk_dn = g.index[(cl < prev["l"]) & (g.index.time >= pd.Timestamp("09:20").time())]
        if o < prev["h"] and len(brk_up) and brk_up[0].time() <= pd.Timestamp("13:00").time():
            j = g.index.get_loc(brk_up[0]) + 1
            yield ("yday high break (opened below)", d, 1, *sim(g, j, 1, prev["h"] * (1 - a / 400))[:2])
        if o > prev["l"] and len(brk_dn) and brk_dn[0].time() <= pd.Timestamp("13:00").time():
            j = g.index.get_loc(brk_dn[0]) + 1
            yield ("yday low break (opened above)", d, -1, *sim(g, j, -1, prev["l"] * (1 + a / 400))[:2])
        # 6. big first candle (9:15-9:20 range > 0.3 ATR... body > 0.15%): follow vs fade, 30-min hold
        b0 = g.iloc[0]
        body = (b0["Close"] / b0["Open"] - 1) * 100
        if abs(body) >= 0.2:
            s = int(np.sign(body))
            yield ("first 5-min candle 0.2%+, follow 1 hour", d, s,
                   *sim(g, 1, s, b0["Low"] if s > 0 else b0["High"], exit_t=pd.Timestamp("10:20").time())[:2])
            yield ("first 5-min candle 0.2%+, fade 1 hour", d, -s,
                   *sim(g, 1, -s, b0["Close"] * (1 + s * a / 300), exit_t=pd.Timestamp("10:20").time())[:2])
        # 7. afternoon: day's direction at 14:00 continues to 15:15 / reverses
        i = first_at(g, "14:00")
        mv = (cl.iloc[i - 1] / o - 1) * 100
        if abs(mv) >= 0.5 * a:
            s = int(np.sign(mv))
            yield ("strong day at 14:00 (>0.5 ATR), follow to close", d, s, *sim(g, i, s, None)[:2])
            yield ("strong day at 14:00 (>0.5 ATR), fade to close", d, -s, *sim(g, i, -s, None)[:2])


def summarise(name: str, tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rule, t in tr.groupby("rule"):
        t = t.sort_values("date")
        yr = t.groupby(t["date"].dt.year)["opt"].mean()
        half = len(t) // 2
        rows.append({"index": name, "rule": rule, "trades": len(t), "per yr": round(len(t) / 4.9),
                     "win %": round(100 * (t["move"] > 0).mean(), 1), "idx %": round(t["idx"].mean(), 3),
                     "opt %": round(t["opt"].mean(), 3),
                     "opt t": round(t["opt"].mean() / (t["opt"].std() / np.sqrt(len(t))), 2) if len(t) > 2 else np.nan,
                     "opt 1st half": round(t["opt"].iloc[:half].mean(), 3), "opt 2nd half": round(t["opt"].iloc[half:].mean(), 3),
                     "yrs opt +": f"{int((yr > 0).sum())}/{len(yr)}", "2026 opt %": round(yr.get(2026, np.nan), 3),
                     "hrs": round(t["hours"].mean(), 1)})
    return pd.DataFrame(rows).sort_values("opt %", ascending=False)


def main():
    out = []
    for name, sid in (("NIFTY", 13), ("BANKNIFTY", 25)):
        df = load(sid)
        tr = pd.DataFrame(list(rules(name, df)), columns=["rule", "date", "side", "move", "hours"])
        tr["idx"] = tr["move"] - FUT_COST
        tr["opt"] = [0.5 * m - OPT_COST - theta_per_hour(name, d) * h
                     for m, d, h in zip(tr["move"], tr["date"], tr["hours"])]
        s = summarise(name, tr)
        print(f"\n=== {name}: {df.index.normalize().nunique()} days {df.index.min():%b %Y} - {df.index.max():%b %Y} ===")
        print(s.drop(columns="index").to_string(index=False))
        out.append(s)
    pd.concat(out).to_csv(OUT / "index_setups.csv", index=False)


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
