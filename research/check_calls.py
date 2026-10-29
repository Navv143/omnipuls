"""Check TradeFinder community calls (28-29 Oct 2026) and their 'Breakout Beacon' list on Dhan 1-minute data, and
test the beacon idea as a rule: stock 2%+ from yesterday's close at 9:25-9:31 with heavy volume, traded that way.
  .venv\\Scripts\\python research\\check_calls.py
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import universe as U  # noqa: E402
from volume_spikes import CACHE, naive  # noqa: E402

COST = 0.0012


def bars(sym, ids):
    return naive(pickle.loads((CACHE / f"m1_{ids[sym]}.pkl").read_bytes()))


def path(df, day, t_entry, side, t_exit=None):
    """Stock path from a time: entry price, best move, move at exit time / close, time of the day's extreme."""
    d = df[df.index.normalize() == pd.Timestamp(day)]
    prev = df[df.index.normalize() < pd.Timestamp(day)]["Close"].iloc[-1]
    after = d[d.index >= pd.Timestamp(f"{day} {t_entry}")]
    e = after["Open"].iloc[0]
    ext = after["High"].max() if side > 0 else after["Low"].min()
    t_ext = (after["High"].idxmax() if side > 0 else after["Low"].idxmin()).strftime("%H:%M")
    adverse = side * ((after["Low"].min() if side > 0 else after["High"].max()) / e - 1)
    r = {"prev close": prev, "chg at entry %": 100 * (e / prev - 1), "entry": e,
         "best % after entry": 100 * side * (ext / e - 1), "best at": t_ext,
         "worst % after entry": 100 * adverse, "close %": 100 * side * (d["Close"].iloc[-1] / e - 1),
         "day chg %": 100 * (d["Close"].iloc[-1] / prev - 1)}
    if t_exit:
        x = d[d.index <= pd.Timestamp(f"{day} {t_exit}")]["Close"].iloc[-1]
        r["at exit time %"] = 100 * side * (x / e - 1)
    return r


if __name__ == "__main__":
    import dhan as D
    ids = {k: v for k, v in D.equity_ids().items() if k in U.FNO_SECTOR_OF}
    pd.set_option("display.width", 250)
    posted = [("2026-10-28", "VOLTAS", 1, "09:26", "09:48", "Ganesh 960 CE +9,037 (post 09:48)"),
              ("2026-10-28", "VOLTAS", 1, "09:26", "09:55", "LM9865 980 CE +14,924 (screen 09:55)"),
              ("2026-10-28", "KAYNES", -1, "09:32", "10:43", "user 3200 PE +8,420 (post 10:43)"),
              ("2026-10-29", "HINDUNILVR", 1, "10:00", "10:23", "Deval 1880/1900 CE +4,215 (screen 10:23)"),
              ("2026-10-29", "JSWENERGY", 1, "09:16", None, "your chart: box breakout above 476.7")]
    rows = []
    for day, s, side, te, tx, note in posted:
        rows.append({"trade": note, "stock": s, "side": "CE" if side > 0 else "PE", **path(bars(s, ids), day, te, side, tx)})
    print("POSTED TRADES (stock moves from the likely entry; entry = first beacon minute after the signal):")
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    # the 28 Oct Breakout Beacon list (signal times from the screenshot)
    beacon = [("VOLTAS", 1, "09:25"), ("KAYNES", -1, "09:31"), ("UPL", 1, "09:25"), ("APOLLOHOSP", 1, "09:31"),
              ("FORTIS", 1, "09:31"), ("MAZDOCK", 1, "09:25"), ("AMBER", 1, "09:30"), ("POLYCAB", 1, "09:25")]
    rows = []
    for s, side, t in beacon:
        if s not in ids:
            continue
        t1 = (pd.Timestamp(f"2026-10-28 {t}") + pd.Timedelta(minutes=1)).strftime("%H:%M")
        r = path(bars(s, ids), "2026-10-28", t1, side, (pd.Timestamp(f"2026-10-28 {t1}") + pd.Timedelta(minutes=30))
                 .strftime("%H:%M"))
        rows.append({"stock": s, "signal": t, "side": "CE" if side > 0 else "PE", **r})
    B = pd.DataFrame(rows)
    print("\n28 OCT BREAKOUT BEACON LIST, every stock (entry next minute; '30 min' = hit and run):")
    print(B.rename(columns={"at exit time %": "after 30 min %"}).round(2).to_string(index=False))

    # beacon as a rule, last month: 2%+ from prev close at 9:25 (or 9:31), volume so far 2x+ usual for that time
    rows = []
    for s, sid in ids.items():
        f = CACHE / f"m1_{sid}.pkl"
        if not f.exists():
            continue
        df = naive(pickle.loads(f.read_bytes()))
        dd = df.index.normalize()
        days = sorted(set(dd))
        cumv_at = {}
        for i, day in enumerate(days):
            d = df[dd == day]
            if len(d) < 300:
                continue
            for tsig in ("09:25", "09:31"):
                upto = d[d.index <= pd.Timestamp(f"{day:%Y-%m-%d} {tsig}")]
                cumv_at.setdefault(tsig, {})[day] = upto["Volume"].sum()
            if i < 11:
                continue
            prev = df[dd == days[i - 1]]["Close"].iloc[-1]
            for tsig in ("09:25", "09:31"):
                hist = [cumv_at[tsig].get(x) for x in days[i - 10:i] if cumv_at[tsig].get(x)]
                if len(hist) < 7:
                    continue
                upto = d[d.index <= pd.Timestamp(f"{day:%Y-%m-%d} {tsig}")]
                mv = upto["Close"].iloc[-1] / prev - 1
                rv = upto["Volume"].sum() / np.mean(hist)
                if abs(mv) < 0.02 or rv < 2:
                    continue
                side = 1 if mv > 0 else -1
                after = d[d.index > upto.index[-1]]
                e = after["Open"].iloc[0]
                stop = e * (1 - side * 0.01)
                res30 = None
                for ts, b in after.iterrows():
                    if (side > 0 and b["Low"] <= stop) or (side < 0 and b["High"] >= stop):
                        res30 = -0.01
                        break
                    if ts >= after.index[0] + pd.Timedelta(minutes=30):
                        res30 = side * (b["Close"] / e - 1)
                        break
                best = side * ((after["High"].max() if side > 0 else after["Low"].min()) / e - 1)
                rows.append({"date": day, "sym": s, "signal": tsig, "side": side, "move": mv, "rvol": rv,
                             "30min_stop1": res30, "best": best, "close": side * (after["Close"].iloc[-1] / e - 1)})
    R = pd.DataFrame(rows)
    R.to_csv(HERE / "results" / "beacon_rule_last_month.csv", index=False)
    print(f"\nBEACON AS A RULE, last month ({R['date'].nunique()} sessions): stock 2%+ from yesterday's close at the "
          "signal time with volume 2x+ usual; trade that way next minute; 1% stop else exit after 30 minutes")
    for sig, x in R.groupby("signal"):
        net = x["30min_stop1"] - COST
        print(f"  signal {sig}: {len(x)} trades ({len(x) / x['date'].nunique():.1f}/day), win {100 * (net > 0).mean():.0f}%, "
              f"avg {100 * net.mean():+.2f}% after costs, stopped {100 * (x['30min_stop1'] == -0.01).mean():.0f}%, "
              f"best move after entry median {100 * x['best'].median():.2f}%, reached +2% "
              f"{100 * (x['best'] >= 0.02).mean():.0f}%")
    d28 = R[(R["date"] == pd.Timestamp("2026-10-28")) & (R["signal"] == "09:25")].sort_values("30min_stop1")
    print("\n  28 Oct, 9:25 rule signals:")
    print(d28[["sym", "side", "move", "rvol", "30min_stop1", "best", "close"]].assign(
        move=lambda x: 100 * x["move"], **{"30min_stop1": lambda x: 100 * x["30min_stop1"]},
        best=lambda x: 100 * x["best"], close=lambda x: 100 * x["close"]).round(2).to_string(index=False))
