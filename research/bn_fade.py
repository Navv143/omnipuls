"""Bank Nifty previous-day high / low break FADE, as a full trading rule, 5 years of 5-minute data.

The 1-year study found Bank Nifty breaks of the previous day's high (PDH) / low (PDL) tend to fail. Here that idea
gets entries, stops and exits, on Nov 2021 - Oct 2026 (Nifty run the same way as a check).

Event: the day did not open beyond the level; the first 5-minute candle (9:20-14:30) that CLOSES beyond it.
Entries (against the break):
  A  at the break candle's close
  B  only if it fails: the first candle within 30 minutes that closes back inside the level, at that close
Stops:
  S1 just past the furthest point since the break (break-side extreme + 10 pts)
  S2 a fixed 0.4 x daily ATR(14) from the entry
Exits: E1 at 15:10's close (out by 15:15); E2 target 1 x risk; E3 target 2 x risk (else out at 15:10).
Inside a candle the stop is checked before the target. Costs 5 pts a round trip for Bank Nifty, 2 for Nifty
(futures; the index is used as the price, so basis is ignored). One trade per level per day.
12 versions are tried; a version counts only if it is positive after costs in both halves and in most years.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\bn_fade.py
"""
from __future__ import annotations

import glob
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intraday_study import features, slot_of, slot_time, to_grid  # noqa: E402

COST = {"BANKNIFTY": 5.0, "NIFTY": 2.0}
FIRST, LAST_ENTRY, OUT = slot_of("09:20", 5), slot_of("14:30", 5), slot_of("15:10", 5)
pd.set_option("display.width", 250)


def load(sid: int) -> pd.DataFrame:
    d = pickle.loads(open(sorted(glob.glob(str(HERE / "cache" / f"IDX_I_{sid}_5_1800_*.pkl")))[-1], "rb").read())
    d.index = d.index.tz_convert("Asia/Kolkata").tz_localize(None)
    return d


def run(name: str, df: pd.DataFrame) -> pd.DataFrame:
    days, G = to_grid(df, 5)
    F = features(G, days)
    H, L, C = G["H"], G["L"], G["C"]
    rows = []
    for d in range(1, len(days)):
        atr = F["atr"][d]
        if not np.isfinite(atr) or not np.isfinite(F["pH"][d]):
            continue
        for brk, lvl in ((1, F["pH"][d]), (-1, F["pL"][d])):
            if brk * (F["dO"][d] - lvl) > 0:  # opened beyond: not a break during the day
                continue
            cl = C[d, :LAST_ENTRY + 1]
            hit = np.flatnonzero((brk * (cl - lvl) > 0) & (np.arange(len(cl)) >= FIRST))
            if not len(hit):
                continue
            kb = int(hit[0])
            side = -brk  # the fade
            for entry in ("A", "B"):
                if entry == "A":
                    k = kb
                else:
                    back = [j for j in range(kb + 1, min(kb + 7, OUT)) if np.isfinite(C[d, j]) and brk * (C[d, j] - lvl) <= 0]
                    if not back:
                        continue
                    k = back[0]
                e = C[d, k]
                ext = np.nanmax(H[d, kb:k + 1]) if brk > 0 else np.nanmin(L[d, kb:k + 1])
                for stop_rule in ("S1", "S2"):
                    stop = ext + brk * 10 if stop_rule == "S1" else e - side * 0.4 * atr
                    risk = side * (e - stop)
                    if risk <= 0:
                        continue
                    for ex in ("E1", "E2", "E3"):
                        tgt = None if ex == "E1" else e + side * risk * (1 if ex == "E2" else 2)
                        pts, how, kk = None, "close", OUT
                        for j in range(k + 1, OUT + 1):
                            h, l = H[d, j], L[d, j]
                            if not np.isfinite(h):
                                continue
                            if (side > 0 and l <= stop) or (side < 0 and h >= stop):
                                pts, how, kk = -risk, "stop", j
                                break
                            if tgt is not None and ((side > 0 and h >= tgt) or (side < 0 and l <= tgt)):
                                pts, how, kk = side * (tgt - e), "target", j
                                break
                        if pts is None:
                            last = C[d, k + 1:OUT + 1]
                            last = last[np.isfinite(last)]
                            pts = side * ((last[-1] if len(last) else e) - e)
                        rows.append({"index": name, "date": days[d], "year": days[d].year, "broke": "PDH" if brk > 0 else "PDL",
                                     "version": f"{entry} {stop_rule} {ex}", "time": slot_time(k, 5), "entry": e,
                                     "risk": risk, "how": how, "pts": pts - COST[name], "R": (pts - COST[name]) / risk})
    return pd.DataFrame(rows)


def report(T: pd.DataFrame):
    for name, X in T.groupby("index"):
        print(f"\n######## {name} fade of previous-day high/low breaks, {X['date'].min():%b %Y} - {X['date'].max():%b %Y}, "
              f"points after {COST[name]:.0f} pts cost")
        mid = X["date"].sort_values().iloc[len(X) // 2]
        rows = []
        for v, g in X.groupby("version"):
            y = g.groupby("year")["pts"].mean()
            eq = g.sort_values("date")["pts"].cumsum()
            rows.append({"version": v, "trades": len(g), "per year": round(len(g) / g["date"].dt.year.nunique(), 0),
                         "avg pts": g["pts"].mean(), "win %": 100 * (g["pts"] > 0).mean(), "avg risk": g["risk"].mean(),
                         "avg R": g["R"].mean(), "total": g["pts"].sum(), "worst run": (eq - eq.cummax()).min(),
                         "1st half": g[g["date"] < mid]["pts"].mean(), "2nd half": g[g["date"] >= mid]["pts"].mean(),
                         "years +": f"{int((y > 0).sum())}/{len(y)}",
                         "PDH short": g[g.broke == "PDH"]["pts"].mean(), "PDL long": g[g.broke == "PDL"]["pts"].mean()})
        R = pd.DataFrame(rows).round(1)
        print(R.to_string(index=False))
        print("\nBy year (avg pts a trade):")
        print(X.pivot_table(index="version", columns="year", values="pts", aggfunc="mean").round(1).to_string())


def main():
    T = pd.concat([run("BANKNIFTY", load(25)), run("NIFTY", load(13))])
    T.to_csv(HERE / "results" / "bn_fade.csv", index=False)
    report(T)


if __name__ == "__main__":
    main()
