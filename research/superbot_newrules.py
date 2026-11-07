"""The proposed Super Bot rules vs the live ones, step by step, on the server's 6 months (or a local bars file).

1. Collects every decision-stage arrival the bot would trade (research/superbot_strict.collect, entry window opened to
   09:15-15:00 so every time can be tested; the market rule is applied afterwards).
2. Plans (first arrivals, 1 per sector / stock a day, with Nifty):
   live 11:00-12:00 max 3  ->  3 windows (10:00-10:30 x2, 11:00-12:00 x2, 12:00-12:30 x2)  ->  + skip moved > 1.0
   day-ATR  ->  + entry beyond the 15-min opening range  ->  + profit lock (after a +1.2% move, stop to +0.6%; no
   target; 0.05% slippage on stops)  ->  + day loss cap 1.5% (no new trades).
3. Prints and (server) saves the report to bot_results as 'superbot_newrules <time>'.

Usage: python research/superbot_newrules.py --server
       python research/superbot_newrules.py <bars.pkl (stocks, {"NIFTY": ...})> [<candidates.pkl>]
"""
import json
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import superbot as SB            # noqa: E402
import superbot_backtest as BT   # noqa: E402
import superbot_strict as X      # noqa: E402
import superbot_windows as W     # noqa: E402
import universe as U             # noqa: E402

COST, SLIP = 0.12, 0.05
WINDOWS = [("10:00", "10:30", 2), ("11:00", "12:00", 2), ("12:00", "12:30", 2)]
LIVE = [("11:00", "12:00", 3)]


def load_server():
    import bot as B
    import candles as C
    cache = B.BOT_DIR / "cache_m1"
    bars = {}
    for s in sorted(U.FNO_SECTOR_OF):
        f = cache / f"{s.replace('&', '_and_')}.parquet"
        if f.exists():
            bars[s] = C.resample(C.naive(pd.read_parquet(f)).astype("float64"), 5)
    nf = next((f for f in (cache / "NIFTY.parquet", cache / "NIFTY 50.parquet") if f.exists()), None)
    if nf is None:
        raise SystemExit("no NIFTY candles in cache_m1")
    nifty = C.resample(C.naive(pd.read_parquet(nf)).astype("float64"), 5)
    return bars, nifty, B.BOT_DIR


def load_local(path):
    stocks, idx = pickle.load(open(path, "rb"))
    nifty = idx["NIFTY"]
    nifty = nifty.droplevel(1, axis=1) if isinstance(nifty.columns, pd.MultiIndex) else nifty
    return stocks, nifty, Path(path).resolve().parent


def collect_all(bars, nifty):
    SB.RULES.update(first_entry="09:15", last_entry="15:00")
    days = sorted(set().union(*[set(df.index.normalize()) for df in bars.values()]))[20:]
    rows, t0 = [], time.time()
    for i, d in enumerate(days):
        try:
            rows += X.collect(bars, nifty, d, 5)
        except Exception as e:
            print(f"{d.date()}: {e}")
        print(f"{d.date()} ({i + 1}/{len(days)}, {time.time() - t0:.0f}s, {len(rows)} candidates)", flush=True)
    return pd.DataFrame(rows)


def add_orb15(c, bars):
    ok = []
    for _, r in c.iterrows():
        df = bars[r["stock"]]
        o = df[(df.index.normalize() == r["day"]) & (df.index < r["day"] + pd.Timedelta(hours=9, minutes=30))]
        ok.append(bool(len(o)) and (r["entry"] > o["High"].max() if r["side"] > 0 else r["entry"] < o["Low"].min()))
    return c.assign(orb15=ok)


def lock_exit(t, bars, move=1.2, lock=0.6):
    """Re-simulate the exit: live stop, after a +move% favourable move the stop goes to +lock%; no target; out at
    15:20; 0.05% slippage on stop fills."""
    out = []
    for _, r in t.iterrows():
        df = bars[r["stock"]]
        et = r["day"] + pd.Timedelta(hours=int(r["entry_at"][:2]), minutes=int(r["entry_at"][3:]))
        a = df[(df.index.normalize() == r["day"]) & (df.index >= et)]
        sd, e, stop = int(r["side"]), float(r["entry"]), float(r["stop"])
        best, x, locked = e, None, False
        for (_, b), h in zip(a.iterrows(), a.index.strftime("%H:%M")):
            o, hi, lo = float(b["Open"]), float(b["High"]), float(b["Low"])
            if h >= "15:20":
                x = o
                break
            if (sd > 0 and lo <= stop) or (sd < 0 and hi >= stop):
                x = (min(o, stop) if sd > 0 else max(o, stop)) - sd * e * SLIP / 100
                break
            best = max(best, hi) if sd > 0 else min(best, lo)
            if not locked and sd * (best - e) / e * 100 >= move:
                ns = e * (1 + sd * lock / 100)
                stop = max(stop, ns) if sd > 0 else min(stop, ns)
                locked = True
        if x is None:
            x = float(a["Close"].iloc[-1]) if len(a) else e
        out.append(sd * (x / e - 1) * 100 - COST)
    return t.assign(pct=out)


def day_cap(t, cap=1.5):
    """Drop trades entered after the day's realised + open P&L is <= -cap% (approximation on the final results:
    a trade counts against the cap once it has exited before the next entry)."""
    keep = []
    for _, g in t.sort_values(["day", "entry_at"]).groupby("day"):
        done = []
        for i, r in g.iterrows():
            closed = sum(x["pct"] for x in done if str(x["exit_at"]) <= r["entry_at"])
            if closed <= -cap:
                continue
            keep.append(i)
            done.append(r)
    return t.loc[keep]


def pf(p):
    return p[p > 0].sum() / -p[p < 0].sum() if (p < 0).any() else float("inf")


def summary(name, t, nd):
    if t.empty:
        return f"{name}: no trades"
    p = t["pct"]
    mid = sorted(t["day"].unique())[t["day"].nunique() // 2]
    d = t.groupby("day")["pct"].sum()
    mon = t.groupby(t["day"].dt.strftime("%Y-%m"))["pct"].sum().round(1)
    return (f"{name}\n  {len(p)} trades ({len(p) / nd:.1f}/day) | win {(p > 0).mean() * 100:.0f}% | PF {pf(p):.2f} | "
            f"avg {p.mean():+.3f}% | t {p.mean() / p.std() * np.sqrt(len(p)):+.2f} | halves {p[t['day'] < mid].mean():+.3f} / "
            f"{p[t['day'] >= mid].mean():+.3f} | total {p.sum():+.1f}% | worst day {d.min():+.1f}% | losing days "
            f"{(d < 0).sum()}/{nd} | losing months {(mon < 0).sum()}/{len(mon)}\n  months: "
            + ", ".join(f"{k} {v:+.1f}%" for k, v in mon.items()))


def main(argv):
    server = "--server" in argv
    if server:
        raw, nifty, out_dir = load_server()
    else:
        raw, nifty, out_dir = load_local(argv[1])
    nifty = BT.naive(nifty).dropna(subset=["Close"])
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in raw.items()
            if s in U.FNO_SECTOR_OF and df is not None and len(df)}
    if not server and len(argv) > 2 and not argv[2].startswith("--"):
        c = pd.read_pickle(argv[2])
    else:
        c = collect_all(bars, nifty)
        c.to_pickle(out_dir / "superbot_newrules_candidates.pkl")
    c = c.dropna(subset=["entry"])
    c = c[c.apply(X.RULES["with the market"], axis=1)]
    c = add_orb15(c, bars)
    nd = c["day"].nunique()
    f1 = c[c["move_atr"] <= 1.0]
    f2 = f1[f1["orb15"]]
    steps = [("1. LIVE: 11:00-12:00, max 3", W.run(c, bars, LIVE)),
             ("2. 3 windows (10:00 x2, 11-12 x2, 12:00 x2)", W.run(c, bars, WINDOWS)),
             ("3. + skip moved > 1.0 day-ATR", W.run(f1, bars, WINDOWS)),
             ("4. + entry beyond the 15-min opening range", W.run(f2, bars, WINDOWS))]
    t5 = lock_exit(steps[-1][1], bars)
    steps.append(("5. + profit lock (after +1.2% stop to +0.6%, no target, 0.05% slippage)", t5))
    steps.append(("6. + day loss cap 1.5%", day_cap(t5)))
    steps.append(("(live rule with the profit lock only)", lock_exit(steps[0][1], bars)))
    head = (f"SUPER BOT NEW RULES vs LIVE | {nd} days ({c['day'].min().date()} to {c['day'].max().date()}) | "
            f"{len(c)} market-aligned candidates | cost 0.12% a round trip")
    text = head + "\n\n" + "\n\n".join(summary(n, t, nd) for n, t in steps)
    print("\n" + text)
    if server:
        try:
            import cloudstore
            run_at = datetime.now().isoformat(timespec="seconds")
            cloudstore.upsert_rows("bot_results", [{"run_at": "superbot_newrules " + run_at, "result": json.loads(json.dumps(
                {"run_at": run_at, "days": nd, "report": text}, default=str))}], "run_at")
        except Exception as e:
            print(f"save: {e}")


if __name__ == "__main__":
    main(sys.argv)
