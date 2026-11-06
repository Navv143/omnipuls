"""Back-test of the six-stage Super Bot (superbot.py) on past candles.

At checkpoints every 15 minutes (09:30-14:30) the bot sees only the candles up to that moment and runs all six stages
exactly as live. A stock arriving at the decision stage (not there at the previous checkpoint) is a TRADE / REJECT /
REPEAT as live (8 trades a day, best scores first); trades enter at the next candle's open and are followed with the
live exit (stop, target, profit lock after +1R, 15:20; momentum_paper.track, cost 0.12%).

Not available in past data: futures OI and the order book. Stage 4 then passes on unusual candles with the move and a
smart score not against (the smart score itself has no OI / book part).

Also measures what each stage adds: for every stock that reached a stage, the move from the checkpoint to the close in
the stage-1 direction, split by passed / rejected at that stage.

Usage: python research/superbot_backtest.py <bars.pkl>     (dict {stock: 5-min OHLCV with history}, naive or IST)
       on the server (6 months of 1-minute candles): python research/superbot_backtest.py --server
"""
from __future__ import annotations

import copy
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import activity as A          # noqa: E402
import momentum_paper as MP   # noqa: E402
import scanners as SC         # noqa: E402
import superbot as SB         # noqa: E402
import universe as U          # noqa: E402

CHECKS = [f"{h:02d}:{m:02d}" for h in range(9, 15) for m in (0, 15, 30, 45) if "09:30" <= f"{h:02d}:{m:02d}" <= "14:30"]


def naive(df):
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    d = df.copy()
    d.index = idx
    return d[~d.index.duplicated(keep="last")].sort_index()


def run_day(bars: dict, day: pd.Timestamp, tf: int) -> tuple[list, list]:
    """All decision-stage arrivals of one day (with trade results) and the per-stage forward-move rows."""
    cut_day = {s: df[df.index < day + pd.Timedelta(days=1)] for s, df in bars.items()}
    cut_day = {s: df for s, df in cut_day.items() if len(df) and df.index[-1].normalize() == day}
    if len(cut_day) < 50:
        return [], []
    S_full = SC.prepare(cut_day, day)                       # day constants (prev close, ATR, history) + today
    R, E, per = A.rank({s: SC.clean(df) for s, df in cut_day.items()}, day, None, None, U.FNO_SECTOR_OF)
    if not per:
        return [], []
    arrivals, stage_rows, prev_final, open_now = [], [], set(), set()
    for chk in CHECKS:
        t = day + pd.Timedelta(hours=int(chk[:2]), minutes=int(chk[3:]))
        S = {}
        for sym, s in S_full.items():
            c = copy.copy(s)
            c.today = s.today[s.today.index + pd.Timedelta(minutes=tf) <= t]     # closed candles only
            if len(c.today) >= 2:
                S[sym] = c
        per_t = {s: c[c.index + pd.Timedelta(minutes=tf) <= t] for s, c in per.items()}
        per_t = {s: c for s, c in per_t.items() if len(c)}
        if E is not None and not E.empty:
            ets = pd.to_datetime(day.strftime("%Y-%m-%d ") + E["Time"].astype(str))
            ev_t = E[(ets + pd.Timedelta(minutes=tf) <= t).values]
        else:
            ev_t = E
        now = datetime(day.year, day.month, day.day, t.hour, t.minute)
        n_tr = sum(1 for a in arrivals if a["decision"] == "TRADE")
        res = SB.run(S, per_t, ev_t, pd.DataFrame(), U.FNO_SECTOR_OF, now, open_now, n_tr)
        # what each stage adds: move from now to the close, in the stage-1 direction
        side_of = {r["stock"]: (1 if r["table"] == "UP" else -1 if r["table"] == "DOWN" else 0)
                   for r in res[1].to_dict("records")} if not res[1].empty else {}
        for k in range(2, 7):
            df = res.get(k)
            if df is None or df.empty:
                continue
            for r in df.to_dict("records"):
                sd = side_of.get(r["stock"], 0)
                s = S_full.get(r["stock"])
                if not sd or s is None:
                    continue
                after = s.today[s.today.index >= t]
                if after.empty:
                    continue
                e = float(after["Open"].iloc[0])
                stage_rows.append({"day": day, "time": chk, "stage": k, "stock": r["stock"], "passed": bool(r["pass"]),
                                   "to_close": sd * (float(after["Close"].iloc[-1]) / e - 1) * 100})
        final = res.get(6)
        now_final = set(final["stock"]) if final is not None and not final.empty else set()
        for r in (final.to_dict("records") if final is not None and not final.empty else []):
            if r["stock"] in prev_final:
                continue
            a = {"day": day, "time": chk, "stock": r["stock"], "side": r["side"], "decision": r["decision"],
                 "reason": r["reason"], "score": r["score"], "rr": r.get("rr"), "risk_pct": r.get("risk_pct")}
            if r["decision"] == "TRADE":
                s = S_full[r["stock"]]
                nxt = s.today[s.today.index >= t]
                if len(nxt):
                    sd = 1 if r["side"] == "UP" else -1
                    e = float(nxt["Open"].iloc[0])
                    shift = e - r["entry_plan"]
                    tr = MP.track(s.today, nxt.index[0], sd, e, r["stop"] + shift, r["target"] + shift,
                                  datetime(day.year, day.month, day.day, 15, 30))
                    a.update(entry=e, result=tr["result"], exit_at=tr["exit_at"], pct=tr["pct"],
                             r=tr["pct"] / (abs(r["stop"] - r["entry_plan"]) / r["entry_plan"] * 100))
                    open_now.add(r["stock"])
            arrivals.append(a)
        prev_final = now_final
    return arrivals, stage_rows


def report(arr: pd.DataFrame, st: pd.DataFrame) -> str:
    out = []
    tr = arr[arr["decision"] == "TRADE"].dropna(subset=["pct"])
    if len(tr):
        mid = tr["day"].sort_values().iloc[len(tr) // 2]
        out.append(f"TRADES: {len(tr)} on {tr['day'].nunique()} days ({len(tr) / max(tr['day'].nunique(), 1):.1f} a day) | "
                   f"win {(tr['pct'] > 0).mean() * 100:.0f}% | avg {tr['pct'].mean():+.3f}% a trade after costs | "
                   f"avg R {tr['r'].mean():+.2f} | h1 {tr.loc[tr['day'] < mid, 'pct'].mean():+.3f}% "
                   f"h2 {tr.loc[tr['day'] >= mid, 'pct'].mean():+.3f}% | total {tr['pct'].sum():+.1f}%")
        out.append("  by exit: " + ", ".join(f"{k} {len(z)} ({z['pct'].mean():+.2f}%)" for k, z in tr.groupby("result")))
        out.append("  by side: " + ", ".join(f"{k} {len(z)} ({z['pct'].mean():+.3f}%, win {(z['pct'] > 0).mean() * 100:.0f}%)"
                                             for k, z in tr.groupby("side")))
        out.append("  by entry time: " + ", ".join(f"{k} {len(z)} ({z['pct'].mean():+.2f}%)"
                                                   for k, z in tr.groupby(tr["time"].str[:2] + "h")))
        out.append("  by score: " + ", ".join(f"{k} {len(z)} ({z['pct'].mean():+.2f}%)"
                                              for k, z in tr.groupby(pd.cut(tr["score"], [0, 8, 10, 12, 99]), observed=True)))
    rj = arr[arr["decision"] != "TRADE"]
    out.append(f"REJECT / REPEAT: {len(rj)} ({rj['decision'].value_counts().to_dict()})")
    if len(st):
        out.append("WHAT EACH STAGE ADDS (move to the close in the stage-1 direction, from the checkpoint, before costs):")
        for k, z in st.groupby("stage"):
            p, f = z[z["passed"]], z[~z["passed"]]
            out.append(f"  stage {k} {SB.STAGES[k]:14s} passed n={len(p):6d} {p['to_close'].mean():+.3f}%  |  "
                       f"rejected n={len(f):6d} {f['to_close'].mean():+.3f}%  |  difference {p['to_close'].mean() - f['to_close'].mean():+.3f}%")
    return "\n".join(out)


def main(argv):
    if "--server" in argv:
        import bot as B
        import candles as C
        cache = B.BOT_DIR / "cache_m1"
        bars = {}
        for s in sorted(U.FNO_SECTOR_OF):
            f = cache / f"{s.replace('&', '_and_')}.parquet"
            if f.exists():
                bars[s] = C.resample(C.naive(pd.read_parquet(f)).astype("float64"), 5)
        out_dir = B.BOT_DIR
    else:
        bars = pickle.load(open(argv[1], "rb"))
        bars = bars[0] if isinstance(bars, tuple) else bars
        out_dir = Path(argv[1]).resolve().parent
    bars = {s: naive(df).dropna(subset=["Close"]) for s, df in bars.items() if s in U.FNO_SECTOR_OF and df is not None and len(df)}
    tf = int(pd.Series(next(iter(bars.values())).index).diff().dt.total_seconds().median() // 60)
    days = sorted(set().union(*[set(df.index.normalize()) for df in bars.values()]))[20:]   # 20 days of history first
    t0, arr, st = time.time(), [], []
    for i, d in enumerate(days):
        a, s_ = run_day(bars, d, tf)
        arr += a
        st += s_
        print(f"{d.date()}: {sum(1 for x in a if x['decision'] == 'TRADE')} trades  ({i + 1}/{len(days)}, "
              f"{time.time() - t0:.0f}s)", flush=True)
    arr, st = pd.DataFrame(arr), pd.DataFrame(st)
    arr.to_pickle(out_dir / "superbot_bt_arrivals.pkl")
    st.to_pickle(out_dir / "superbot_bt_stages.pkl")
    text = report(arr, st)
    print("\n" + text)
    if "--server" in argv:      # the summary for the app / review
        try:
            import json
            import cloudstore
            run_at = datetime.now().isoformat(timespec="seconds")
            cloudstore.upsert_rows("bot_results", [{"run_at": "superbot_bt " + run_at, "result": json.loads(json.dumps(
                {"run_at": run_at, "days": len(days), "report": text}, default=str))}], "run_at")
        except Exception as e:
            print(f"save: {e}")


if __name__ == "__main__":
    main(sys.argv)
