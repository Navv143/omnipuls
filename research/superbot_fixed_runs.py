"""Super Bot as fixed runs: at set times (e.g. 9:45 top 3, 11:00 top 3, 13:30 top 2) the bot sees every stock that passes
all six stages at that moment (not only new arrivals), ranks by score and takes the top N, skipping stocks and sectors
already taken that day. With the market (Nifty direction), next-candle entry, live exits (stop, 3R, lock after +1R,
15:20), cost 0.12%. The live entry window is switched off so any time can be tested.

Usage: python research/superbot_fixed_runs.py <bars.pkl with (stocks, {"NIFTY": bars})>
"""
from __future__ import annotations

import copy
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import activity as A           # noqa: E402
import momentum_paper as MP    # noqa: E402
import scanners as SC          # noqa: E402
import superbot as SB          # noqa: E402
import superbot_backtest as BT  # noqa: E402
import universe as U           # noqa: E402

RUN_TIMES = ["09:45", "10:00", "10:30", "11:00", "12:00", "13:00", "13:30"]   # recorded; plans pick from these


def collect(bars: dict, nifty: pd.DataFrame, day: pd.Timestamp, tf: int = 5) -> list:
    """Every stock the bot would trade at each run time (no daily limit), with its result if taken there."""
    cut = {s: df[df.index < day + pd.Timedelta(days=1)] for s, df in bars.items()}
    cut = {s: df for s, df in cut.items() if len(df) and df.index[-1].normalize() == day}
    if len(cut) < 50:
        return []
    S_full = SC.prepare(cut, day)
    R, E, per = A.rank({s: SC.clean(df) for s, df in cut.items()}, day, None, None, U.FNO_SECTOR_OF)
    nt = nifty[nifty.index.normalize() == day]
    npc = nifty[nifty.index.normalize() < day]["Close"]
    if nt.empty or npc.empty or not per:
        return []
    npc = float(npc.iloc[-1])
    rows = []
    for chk in RUN_TIMES:
        t = day + pd.Timedelta(hours=int(chk[:2]), minutes=int(chk[3:]))
        S = {}
        for sym, s in S_full.items():
            c = copy.copy(s)
            c.today = s.today[s.today.index + pd.Timedelta(minutes=tf) <= t]
            if len(c.today) >= 2:
                S[sym] = c
        pt = {s: c[c.index + pd.Timedelta(minutes=tf) <= t] for s, c in per.items()}
        pt = {s: c for s, c in pt.items() if len(c)}
        ets = pd.to_datetime(day.strftime("%Y-%m-%d ") + E["Time"].astype(str)) if E is not None and not E.empty else None
        ev = E[(ets + pd.Timedelta(minutes=tf) <= t).values] if ets is not None else E
        nz = nt[nt.index + pd.Timedelta(minutes=tf) <= t]
        nchg = (float(nz["Close"].iloc[-1]) / npc - 1) * 100 if len(nz) else None
        now = datetime(day.year, day.month, day.day, t.hour, t.minute)
        fin = SB.run(S, pt, ev, pd.DataFrame(), U.FNO_SECTOR_OF, now, set(), -10 ** 6, nifty_chg=nchg).get(6)
        if fin is None or fin.empty:
            continue
        for r in fin[fin["decision"] == "TRADE"].to_dict("records"):
            s, sd = S_full[r["stock"]], (1 if r["side"] == "UP" else -1)
            nxt = s.today[s.today.index >= t]
            if nxt.empty:
                continue
            e = float(nxt["Open"].iloc[0])
            shift = e - r["entry_plan"]
            tr = MP.track(s.today, nxt.index[0], sd, e, r["stop"] + shift, r["target"] + shift,
                          datetime(day.year, day.month, day.day, 15, 30))
            rows.append({"day": day, "run": chk, "stock": r["stock"], "sector": U.FNO_SECTOR_OF.get(r["stock"], "Other"),
                         "side": sd, "score": r["score"], "nifty_chg": nchg, "entry_at": nxt.index[0].strftime("%H:%M"),
                         "entry": e, "exit_at": tr["exit_at"], "result": tr["result"], "pct": tr["pct"]})
    return rows


def plan(c: pd.DataFrame, runs: list) -> pd.DataFrame:
    """runs: [(time, top_n)]. Best scores first at each run, no stock or sector twice in a day."""
    out = []
    for day, g in c.groupby("day"):
        stocks, secs = set(), set()
        for tm, n in runs:
            k = 0
            for _, r in g[g["run"] == tm].sort_values("score", ascending=False).iterrows():
                if k >= n:
                    break
                if r["stock"] in stocks or r["sector"] in secs:
                    continue
                out.append(r)
                stocks.add(r["stock"])
                secs.add(r["sector"])
                k += 1
    return pd.DataFrame(out)


def show(name: str, t: pd.DataFrame, nd: int):
    if t.empty:
        print(f"{name:34s} no trades")
        return
    d = t.groupby("day")["pct"].sum()
    mid = sorted(t["day"].unique())[t["day"].nunique() // 2]
    mon = t.groupby(t["day"].dt.strftime("%b"))["pct"].sum().round(1).to_dict()
    tt = t["pct"].mean() / t["pct"].std() * np.sqrt(len(t))
    print(f"{name:34s} {len(t):3d} tr ({len(t) / nd:.1f}/d) win {(t['pct'] > 0).mean() * 100:3.0f}% avg {t['pct'].mean():+.3f}% "
          f"t {tt:+.2f} h1 {t.loc[t['day'] < mid, 'pct'].mean():+.2f} h2 {t.loc[t['day'] >= mid, 'pct'].mean():+.2f} | "
          f"days+ {(d > 0).sum()}/{nd} worst day {d.min():+.1f}% total {t['pct'].sum():+5.1f}% | {mon}")
    print(" " * 36 + "by run: " + ", ".join(f"{k} {len(z)} ({z.mean():+.2f}%, win {(z > 0).mean() * 100:.0f}%)"
                                              for k, z in t.groupby("run")["pct"]))


def main(argv):
    stocks, idx = pickle.load(open(argv[1], "rb"))
    nifty = idx["NIFTY"]
    nifty = nifty.droplevel(1, axis=1) if isinstance(nifty.columns, pd.MultiIndex) else nifty
    nifty = BT.naive(nifty).dropna(subset=["Close"])
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items() if s in U.FNO_SECTOR_OF and len(df)}
    SB.RULES.update(first_entry="09:15", last_entry="15:00")      # any run time can be tested
    cache = Path(argv[1]).resolve().parent / "superbot_fixed_runs.pkl"
    if cache.exists() and "--fresh" not in argv:
        c = pd.read_pickle(cache)
    else:
        days = sorted(set().union(*[set(df.index.normalize()) for df in bars.values()]))[20:]
        t0, rows = time.time(), []
        for i, d in enumerate(days):
            rows += collect(bars, nifty, d)
            print(f"{d.date()} ({i + 1}/{len(days)}, {time.time() - t0:.0f}s, {len(rows)} rows)", flush=True)
        c = pd.DataFrame(rows)
        c.to_pickle(cache)
    nd = c["day"].nunique()
    print(f"\n{len(c)} tradeable rows on {nd} days; per run: {c.groupby('run').size().to_dict()}")
    for name, runs in (("9:45 x3 + 11:00 x3 + 13:30 x2", [("09:45", 3), ("11:00", 3), ("13:30", 2)]),
                       ("9:45 x3 + 11:00 x3", [("09:45", 3), ("11:00", 3)]),
                       ("9:45 x2 + 11:00 x2 + 13:30 x2", [("09:45", 2), ("11:00", 2), ("13:30", 2)]),
                       ("only 9:45 x3", [("09:45", 3)]), ("only 11:00 x3", [("11:00", 3)]),
                       ("only 13:30 x2", [("13:30", 2)])):
        show(name, plan(c, runs), nd)
    print("\nnearby times (is the slot steady?), top 3 alone:")
    for tm in RUN_TIMES:
        show(f"only {tm} x3", plan(c, [(tm, 3)]), nd)


if __name__ == "__main__":
    main(sys.argv)
