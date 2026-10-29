"""Sector money flow, the TradeFinder way: find the sector where big players are buying/selling from the morning,
take its stock with the highest 'R-factor', trade around 10:00, hit and run.

At a checkpoint (9:45 / 10:00 / 10:15 / 10:30), for every F&O stock: move from yesterday's close in ATRs and volume
so far vs the same time on its last 10 sessions (both known at that moment). Sector strength = average move/ATR of
its stocks (at least 4 stocks), breadth = share moving the same way, sector volume = average volume ratio.
Pick the strongest sector (by |average move/ATR|), direction = its sign; inside it the stock with the highest
R-factor proxy (rank of volume ratio + rank of move/ATR in that direction). Entry = next 5-minute candle's open.
Exits compared: 30 minutes; 1% stop then 30 minutes; 1% stop to the last bar; +1% target / -0.5% stop to the last bar.
Controls: the market-wide highest R stock (no sector), and a random stock of the chosen sector.
Option view: an ATM stock option moves roughly 15-20x the stock's % move intraday (delta ~0.5, premium ~2.5-3%).
  .venv\\Scripts\\python research\\sector_flow.py
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
import universe as U  # noqa: E402
from momentum_dhan import OUT, slot, to_grid  # noqa: E402
from movers_study import LAST, daily_features, load  # noqa: E402

warnings.filterwarnings("ignore")
COST = 0.0012
CHECKS = ["09:45", "10:00", "10:15", "10:30"]
RNG = np.random.default_rng(11)


def exits(O, H, L, C, e, side, entry):
    """Returns for the four exit rules from entry slot e."""
    out = {}
    t30 = min(e + 6, LAST)
    out["30min"] = side * (C[t30] / entry - 1) if np.isfinite(C[t30]) else np.nan
    stop = entry * (1 - side * 0.01)
    r_stop30, r_stopday, r_tgt = None, None, None
    tstop, ttgt = entry * (1 - side * 0.005), entry * (1 + side * 0.01)
    for t in range(e, LAST + 1):
        if not np.isfinite(O[t]):
            continue
        hit_stop = (side > 0 and L[t] <= stop) or (side < 0 and H[t] >= stop)
        if hit_stop:
            px = side * ((min(O[t], stop) if side > 0 else max(O[t], stop)) / entry - 1)
            if r_stop30 is None and t <= t30:
                r_stop30 = px
            if r_stopday is None:
                r_stopday = px
        if r_stop30 is None and t == t30:
            r_stop30 = side * (C[t] / entry - 1)
        if r_tgt is None:
            if (side > 0 and L[t] <= tstop) or (side < 0 and H[t] >= tstop):
                r_tgt = -0.005
            elif (side > 0 and H[t] >= ttgt) or (side < 0 and L[t] <= ttgt):
                r_tgt = 0.01
        if r_stopday is not None and r_tgt is not None and r_stop30 is not None:
            break
    lastpx = C[LAST] if np.isfinite(C[LAST]) else C[np.where(np.isfinite(C))[0][-1]]
    out["stop30"] = r_stop30 if r_stop30 is not None else out["30min"]
    out["stopday"] = r_stopday if r_stopday is not None else side * (lastpx / entry - 1)
    out["tgt"] = r_tgt if r_tgt is not None else side * (lastpx / entry - 1)
    return out


if __name__ == "__main__":
    nifty, raw, _ = load()
    days = pd.DatetimeIndex(sorted(set(nifty.index.normalize())))
    full = np.isfinite(to_grid(nifty, days)["C"]).sum(1) >= 60
    days = days[full]
    syms, G, F = [], {}, {}
    for s, df in raw.items():
        g = to_grid(df, days)
        if g is not None:
            G[s], F[s] = g, daily_features(g)
            syms.append(s)
    sector = {s: U.FNO_SECTOR_OF.get(s, "Other") for s in syms}
    print(f"{len(syms)} stocks, {len(days)} sessions to {days[-1]:%d %b %Y}")
    # per stock: move/ATR and volume ratio at each checkpoint
    cks = {ck: slot(ck) for ck in CHECKS}
    feat = {}
    for s in syms:
        g, f = G[s], F[s]
        Cf = pd.DataFrame(g["C"]).ffill(axis=1).values
        V = np.nan_to_num(g["V"])
        cumv = np.cumsum(V, 1)
        avg = pd.DataFrame(np.where(f["ok"].values[:, None], cumv, np.nan)).rolling(10, min_periods=7).mean() \
            .shift(1).values
        for ck, sl in cks.items():
            mv = Cf[:, sl - 1] / f["prev"].values - 1
            feat[(s, ck)] = (mv, mv / f["atr"].values, cumv[:, sl - 1] / avg[:, sl - 1], f["ok"].values)
    rows = []
    for ck, sl in cks.items():
        mv = np.vstack([feat[(s, ck)][0] for s in syms])
        ma = np.vstack([feat[(s, ck)][1] for s in syms])
        rv = np.vstack([feat[(s, ck)][2] for s in syms])
        ok = np.vstack([feat[(s, ck)][3] for s in syms]) & np.isfinite(ma) & np.isfinite(rv)
        secs = np.array([sector[s] for s in syms])
        for d in range(len(days)):
            m = ok[:, d]
            if m.sum() < 100:
                continue
            df = pd.DataFrame({"i": np.where(m)[0], "sec": secs[m], "ma": ma[m, d], "rv": rv[m, d],
                               "mv": mv[m, d]})
            df = df[df["sec"] != "Other"]
            sg = df.groupby("sec").agg(n=("ma", "size"), ma=("ma", "mean"), rv=("rv", "mean"),
                                       up=("ma", lambda x: (x > 0).mean()))
            sg = sg[sg["n"] >= 4]
            if sg.empty:
                continue
            sg["breadth"] = np.where(sg["ma"] > 0, sg["up"], 1 - sg["up"])
            top = sg.reindex(sg["ma"].abs().sort_values(ascending=False).index)
            nifty_dir = np.sign(df["ma"].mean())
            for variant, pick in [("top sector", top.head(1)),
                                  ("top sector, breadth 70%+", top[top["breadth"] >= 0.7].head(1)),
                                  ("top sector, volume 1.3x+", top[top["rv"] >= 1.3].head(1)),
                                  ("top sector, breadth 70%+ & vol 1.3x+",
                                   top[(top["breadth"] >= 0.7) & (top["rv"] >= 1.3)].head(1)),
                                  ("top sector against Nifty", top[np.sign(top["ma"]) != nifty_dir].head(1))]:
                if pick.empty:
                    continue
                sec, side = pick.index[0], int(np.sign(pick["ma"].iloc[0]))
                inside = df[(df["sec"] == sec) & (np.sign(df["ma"]) == side)].copy()
                if inside.empty:
                    continue
                inside["R"] = inside["rv"].rank(pct=True) + (side * inside["ma"]).rank(pct=True)
                choices = {"highest R in sector": inside.sort_values("R", ascending=False).head(1),
                           "top 2 R in sector": inside.sort_values("R", ascending=False).head(2),
                           "random stock in sector": inside.sample(1, random_state=int(RNG.integers(1e9)))}
                if variant == "top sector":
                    allm = df[np.sign(df["ma"]) != 0].copy()
                    allm["side"] = np.sign(allm["ma"])
                    allm["R"] = allm["rv"].rank(pct=True) + allm["ma"].abs().rank(pct=True)
                    choices["market-wide highest R (no sector)"] = allm.sort_values("R", ascending=False).head(1)
                for cname, sel in choices.items():
                    for _, r in sel.iterrows():
                        s = syms[int(r["i"])]
                        sd = side if cname != "market-wide highest R (no sector)" else int(r["side"])
                        g = G[s]
                        e = sl
                        if not np.isfinite(g["O"][d, e]):
                            continue
                        x = exits(g["O"][d], g["H"][d], g["L"][d], g["C"][d], e, sd, g["O"][d, e])
                        rows.append({"date": days[d], "check": ck, "variant": variant, "choice": cname, "sym": s,
                                     "sector": sector[s], "side": sd, "move_so_far": sd * r["mv"],
                                     "rvol": r["rv"], **x})
    T = pd.DataFrame(rows)
    T.to_csv(OUT / "sector_flow_trades.csv.gz", index=False, compression="gzip")
    mid = T["date"].quantile(0.5)
    res = []
    for (ck, v, c), x in T.groupby(["check", "variant", "choice"]):
        r = {"check": ck, "variant": v, "choice": c, "trades": len(x)}
        for ex in ("30min", "stop30", "stopday", "tgt"):
            net = x[ex] - COST
            r[f"{ex} net %"] = 100 * net.mean()
        net = x["stop30"] - COST
        r.update({"win % (stop30)": 100 * (net > 0).mean(), "H1 %": 100 * net[x["date"] < mid].mean(),
                  "H2 %": 100 * net[x["date"] >= mid].mean(),
                  "2025-26 %": 100 * net[x["date"].dt.year >= 2025].mean(),
                  "t": net.mean() / net.std() * np.sqrt(len(net))})
        res.append(r)
    R = pd.DataFrame(res)
    R.to_csv(OUT / "sector_flow_summary.csv", index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 40)
    print("\nNet per trade on the stock after 0.12% costs. stop30 = 1% stop, else exit after 30 minutes "
          "(the 'hit and run'); H1/H2/2025-26 use stop30.")
    print(R[R["variant"] == "top sector"].round(3).to_string(index=False))
    print("\nWith sector filters, highest R in sector only:")
    print(R[(R["variant"] != "top sector") & (R["choice"] == "highest R in sector")].round(3).to_string(index=False))
    good = R[(R["H1 %"] > 0) & (R["H2 %"] > 0) & (R["2025-26 %"] > 0) & (R["t"] >= 2.5)]
    print(f"\n{len(R)} versions; positive in both halves and 2025-26 with t >= 2.5: {len(good)}")
    if len(good):
        print(good.round(3).to_string(index=False))
    last = T[(T["date"] >= days[-22]) & (T["check"] == "10:00") & (T["variant"] == "top sector") &
             (T["choice"] == "highest R in sector")]
    print("\nLast month at 10:00, top sector -> highest R stock (stock move %, 30-min hit and run with 1% stop):")
    print(last[["date", "sector", "sym", "side", "move_so_far", "rvol", "stop30", "stopday"]]
          .assign(move_so_far=lambda d: 100 * d["move_so_far"], stop30=lambda d: 100 * d["stop30"],
                  stopday=lambda d: 100 * d["stopday"]).round(2).to_string(index=False))
    print(f"  average 30-min result {100 * last['stop30'].mean():+.2f}% per trade before costs, "
          f"win {100 * (last['stop30'] > 0).mean():.0f}%")
