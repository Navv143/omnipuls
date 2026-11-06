"""Super Bot -> 2-3 picks a day: which extra rules pick the best of the ~20 decision-stage candidates?

1. Replays the Super Bot (as research/superbot_backtest.py, checkpoints every 15 min) with no trade limit and records
   every new decision-stage arrival that the live rules would take (time and reward:risk ok), with its features at that
   moment and the result of trading it (next-candle entry, live exits, cost 0.12%).
2. Applies the strict rules, chosen in advance from the earlier findings (MOMENTUM_STUDY.md), all together and each one
   left out, with at most 3 trades a day and 1 per sector (best score first), both halves of the period.

Usage: python research/superbot_strict.py <bars.pkl with (stocks, {"NIFTY": bars})>
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

RULES = {
    "with the market": lambda f: (f["side"] > 0 and f["nifty_chg"] >= 0) or (f["side"] < 0 and f["nifty_chg"] <= 0),
    "not overextended": lambda f: f["move_atr"] <= 2.5,
    "sector leader": lambda f: f["sector_side_ok"] and f["sector_rank"] <= 2,
    "stronger than Nifty": lambda f: f["rel_nifty"] >= 1.0,
    "volume 2x": lambda f: f["vol_x"] >= 2.0,
    "money last 30 min": lambda f: f["side"] * f["money_30m"] > 0,
    "unusual with the move": lambda f: f["unusual_with"] >= 1 and f["unusual_against"] == 0,
}


def collect(bars: dict, nifty: pd.DataFrame, day: pd.Timestamp, tf: int) -> list:
    cut = {s: df[df.index < day + pd.Timedelta(days=1)] for s, df in bars.items()}
    cut = {s: df for s, df in cut.items() if len(df) and df.index[-1].normalize() == day}
    if len(cut) < 50:
        return []
    S_full = SC.prepare(cut, day)
    R, E, per = A.rank({s: SC.clean(df) for s, df in cut.items()}, day, None, None, U.FNO_SECTOR_OF)
    nt = nifty[nifty.index.normalize() == day]
    npc = nifty[nifty.index.normalize() < day]["Close"]
    if nt.empty or npc.empty:
        return []
    npc = float(npc.iloc[-1])
    rows, prev_final = [], set()
    for chk in BT.CHECKS:
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
        now = datetime(day.year, day.month, day.day, t.hour, t.minute)
        res = SB.run(S, pt, ev, pd.DataFrame(), U.FNO_SECTOR_OF, now, set(), -10 ** 6)   # no trade limit
        fin = res.get(6)
        if fin is None or fin.empty:
            prev_final = set()
            continue
        nz = nt[nt.index + pd.Timedelta(minutes=tf) <= t]
        nchg = (float(nz["Close"].iloc[-1]) / npc - 1) * 100 if len(nz) else 0.0
        moves = {sym: (float(s.today["Close"].iloc[-1]) / s.prev_close - 1) * 100 for sym, s in S.items() if s.prev_close}
        sec_moves = pd.Series(moves).groupby(pd.Series({k: U.FNO_SECTOR_OF.get(k, "Other") for k in moves}))
        tab = {k: (v.set_index("stock") if v is not None and not v.empty else pd.DataFrame()) for k, v in res.items()}
        for r in fin.to_dict("records"):
            if r["stock"] in prev_final or r["decision"] != "TRADE":
                continue
            sym, sd = r["stock"], (1 if r["side"] == "UP" else -1)
            sec = U.FNO_SECTOR_OF.get(sym, "Other")
            peers = sec_moves.get_group(sec) if sec in sec_moves.groups else pd.Series(dtype=float)
            ranked = (peers * sd).sort_values(ascending=False)
            f = {"day": day, "time": chk, "stock": sym, "sector": sec, "side": sd, "score": r["score"],
                 "nifty_chg": nchg, "move_atr": tab[2].loc[sym, "move_atr"] if sym in tab[2].index else np.nan,
                 "vol_x": tab[2].loc[sym, "vol_x"] if sym in tab[2].index else np.nan,
                 "money_30m": tab[3].loc[sym, "stock_money_30m_cr"] if sym in tab[3].index else 0.0,
                 "unusual_with": tab[4].loc[sym, "unusual_with"] if sym in tab[4].index else 0,
                 "unusual_against": tab[4].loc[sym, "unusual_against"] if sym in tab[4].index else 0,
                 "rel_nifty": sd * (moves.get(sym, 0) - nchg),
                 "sector_side_ok": bool(len(peers) >= 3 and sd * peers.mean() > 0),
                 "sector_rank": (list(ranked.index).index(sym) + 1) if sym in ranked.index else 99}
            s = S_full[sym]
            nxt = s.today[s.today.index >= t]
            if nxt.empty:
                continue
            e = float(nxt["Open"].iloc[0])
            shift = e - r["entry_plan"]
            tr = MP.track(s.today, nxt.index[0], sd, e, r["stop"] + shift, r["target"] + shift,
                          datetime(day.year, day.month, day.day, 15, 30))
            f.update(result=tr["result"], pct=tr["pct"])
            rows.append(f)
        prev_final = set(fin["stock"])
    return rows


def pick(c: pd.DataFrame, rules: list, max_day=3, per_sector=1) -> pd.DataFrame:
    """Apply the rules, then take trades in time order, best score first at each checkpoint, at most `max_day` a day
    and `per_sector` per sector, one trade per stock a day."""
    ok = c.apply(lambda f: all(RULES[k](f) for k in rules), axis=1) if rules else pd.Series(True, index=c.index)
    z = c[ok].sort_values(["day", "time", "score"], ascending=[True, True, False])
    out = []
    for d, g in z.groupby("day"):
        took, secs, stocks = 0, {}, set()
        for _, r in g.iterrows():
            if took >= max_day or r["stock"] in stocks or secs.get(r["sector"], 0) >= per_sector:
                continue
            out.append(r)
            took += 1
            stocks.add(r["stock"])
            secs[r["sector"]] = secs.get(r["sector"], 0) + 1
    return pd.DataFrame(out)


def stats(t: pd.DataFrame, days: int) -> str:
    if t.empty:
        return "no trades"
    mid = sorted(t["day"].unique())[len(t["day"].unique()) // 2]
    h1, h2 = t[t["day"] < mid]["pct"], t[t["day"] >= mid]["pct"]
    tt = t["pct"].mean() / t["pct"].std() * np.sqrt(len(t)) if len(t) > 2 else np.nan
    return (f"{len(t):4d} trades ({len(t) / days:.1f}/day) win {(t['pct'] > 0).mean() * 100:3.0f}%  avg {t['pct'].mean():+.3f}%  "
            f"t {tt:+.2f}  h1 {h1.mean():+.3f}%  h2 {h2.mean():+.3f}%  total {t['pct'].sum():+6.1f}%")


def main(argv):
    stocks, idx = pickle.load(open(argv[1], "rb"))
    nifty = idx["NIFTY"]
    nifty = nifty.droplevel(1, axis=1) if isinstance(nifty.columns, pd.MultiIndex) else nifty
    nifty = BT.naive(nifty).dropna(subset=["Close"])
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items() if s in U.FNO_SECTOR_OF and len(df)}
    tf = 5
    days = sorted(set().union(*[set(df.index.normalize()) for df in bars.values()]))[20:]
    cache = Path(argv[1]).resolve().parent / "superbot_candidates.pkl"
    if cache.exists() and "--fresh" not in argv:
        c = pd.read_pickle(cache)
    else:
        t0, rows = time.time(), []
        for i, d in enumerate(days):
            rows += collect(bars, nifty, d, tf)
            print(f"{d.date()} ({i + 1}/{len(days)}, {time.time() - t0:.0f}s, {len(rows)} candidates)", flush=True)
        c = pd.DataFrame(rows)
        c.to_pickle(cache)
    n = c["day"].nunique()
    print(f"\n{len(c)} candidates on {n} days ({len(c) / n:.0f} a day)")
    print("ALL candidates, no limit       ", stats(c, n))
    print("current: 8/day, no new rules   ", stats(pick(c, [], 8, 99), n))
    print("3/day, 1 per sector, no rules  ", stats(pick(c, [], 3, 1), n))
    allr = list(RULES)
    print("ALL 7 RULES, 3/day, 1/sector   ", stats(pick(c, allr), n))
    print("\neach rule alone (3/day, 1/sector):")
    for k in allr:
        print(f"  only {k:24s}", stats(pick(c, [k]), n))
    print("\nall rules but one (what each rule adds):")
    for k in allr:
        print(f"  without {k:21s}", stats(pick(c, [x for x in allr if x != k]), n))


if __name__ == "__main__":
    main(sys.argv)
