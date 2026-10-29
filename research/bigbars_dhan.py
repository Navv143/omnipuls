"""Big-money bars on real 5-minute bars from Dhan (run after momentum_dhan.py, which downloads the data).

A big-money bar = a 5-minute candle with volume K x (3, 4 or 5) the average for that same 5-minute slot on the last
10 sessions, whose candle moves the same way as the stock's move from yesterday's close. (The live radar also wants
OI added in that bar; there is no OI history, so that part can't be tested.)

Question: at 10:00 / 10:30 / 11:00, for stocks 1%+ from yesterday's close, does the number of big-money bars so far
tell us the move will keep going? Trade the same way at the next candle's open, 1% stop, exit at the last bar before
15:20 (Dhan's stock bars end at 15:10), 0.12% costs. Checked on the first and second half of the dates and by year.

Usage (in the Omnipuls folder, after momentum_dhan.py has cached the data today or earlier):
  .venv\\Scripts\\python research\\bigbars_dhan.py
"""
from __future__ import annotations

import glob
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import universe as U  # noqa: E402
from momentum_dhan import COST, NSLOT, OUT, STOP, day_basics, slot, to_grid  # noqa: E402

warnings.filterwarnings("ignore", message="All-NaN slice encountered")
warnings.filterwarnings("ignore", message="Mean of empty slice")
CHECKS = ["10:00", "10:30", "11:00"]
KS = [3, 4, 5]
EXIT = "15:20"


def load_cache() -> tuple[pd.DataFrame, dict]:
    """Newest cached 5-minute download per security from research/cache, mapped back to NSE symbols."""
    import dhan as D
    files = sorted(glob.glob(str(HERE / "cache" / "*_5_1800_*.pkl")))
    newest = {}
    for f in files:
        p = Path(f).name.split("_")
        newest[(p[0] + "_" + p[1], int(p[2]))] = f  # sorted, so the last date wins
    nifty = pickle.loads(Path(newest[("IDX_I", 13)]).read_bytes())
    ids = {v: k for k, v in D.equity_ids().items() if k in U.FNO_SECTOR_OF}
    raw = {ids[sid]: pickle.loads(Path(f).read_bytes()) for (seg, sid), f in newest.items()
           if seg == "NSE_EQ" and sid in ids}
    return nifty, raw


def events(sym: str, g: dict, days: pd.DatetimeIndex) -> pd.DataFrame:
    b = day_basics(g)
    O, H, L, C, V = g["O"], g["H"], g["L"], b["C"], g["V"]
    Vs = np.where(np.isfinite(V), V, np.nan)
    # same-slot average volume over the previous 10 valid sessions
    vv = pd.DataFrame(np.where(b["ok"][:, None], Vs, np.nan))
    avg = vv.rolling(10, min_periods=7).mean().shift(1).values
    candle = np.sign(g["C"] - O)
    ex = slot(EXIT)
    exit_px = np.where(np.isfinite(O[:, ex]), O[:, ex], C[:, ex - 1])
    rows = []
    for ck in CHECKS:
        s = slot(ck)
        px = C[:, s - 1]
        chg = px / b["prev"] - 1
        side = np.sign(chg)
        entry = np.where(np.isfinite(O[:, s]), O[:, s], px)
        keep = b["ok"] & (np.abs(chg) >= 0.01) & np.isfinite(entry) & (np.isfinite(avg[:, :s]).sum(1) >= 0.8 * s)
        k = np.where(keep)[0]
        if not len(k):
            continue
        sd, en = side[k], entry[k]
        ratio = Vs[k, :s] / avg[k, :s]
        same = candle[k, :s] == sd[:, None]
        counts = {f"big{m}": ((ratio >= m) & same).sum(1) for m in KS}
        recent = ((ratio[:, -6:] >= 4) & same[:, -6:]).sum(1)  # big-money bars in the last 30 minutes
        opp = ((ratio >= 4) & (candle[k, :s] == -sd[:, None])).sum(1)  # big bars against the move
        stop_px = en * (1 - sd * STOP)
        Lw, Hw, Ow = L[k, s:ex], H[k, s:ex], O[k, s:ex]
        hit = np.where(sd[:, None] > 0, Lw <= stop_px[:, None], Hw >= stop_px[:, None]) & np.isfinite(Lw)
        first = np.where(hit.any(1), hit.argmax(1), -1)
        o_hit = Ow[np.arange(len(k)), np.maximum(first, 0)]
        fill = np.where(sd > 0, np.fmin(o_hit, stop_px), np.fmax(o_hit, stop_px))
        rows.append(pd.DataFrame({
            "date": days[k], "sym": sym, "check": ck, "side": sd.astype(int), "chg": chg[k], "atr": b["atr"][k],
            "rvol": np.nansum(Vs[k, :s], 1) / np.nansum(avg[k, :s], 1), **counts, "big4_last30": recent,
            "big4_against": opp, "stop1": sd * (np.where(first >= 0, fill, exit_px[k]) / en - 1),
            "hold": sd * (exit_px[k] / en - 1)}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def summ(x: pd.DataFrame, label: dict) -> dict:
    net = x["stop1"] - COST
    h = x["date"] < MID
    return {**label, "n": len(x), "per day": round(len(x) / NDAYS, 2), "net %": round(100 * net.mean(), 3),
            "hold net %": round(100 * (x["hold"] - COST).mean(), 3), "win %": round(100 * (net > 0).mean(), 1),
            "H1 %": round(100 * net[h].mean(), 3), "H2 %": round(100 * net[~h].mean(), 3),
            "2025-26 %": round(100 * net[x["date"].dt.year >= 2025].mean(), 3),
            "t": round(net.mean() / net.std() * np.sqrt(len(net)), 2) if len(net) > 2 else np.nan}


if __name__ == "__main__":
    nifty, raw = load_cache()
    idx = nifty.index.tz_localize(None) if nifty.index.tz is not None else nifty.index
    days = pd.DatetimeIndex(sorted(set(idx.normalize())))
    full = np.isfinite(to_grid(nifty, days)["C"]).sum(1) >= 60
    ev = []
    for i, (s, df) in enumerate(raw.items(), 1):
        g = to_grid(df, days)
        if g is not None:
            ev.append(events(s, g, days))
        if i % 50 == 0:
            print(f"  {i}/{len(raw)} stocks", flush=True)
    E = pd.concat(ev, ignore_index=True)
    E = E[E["date"].isin(days[full])]
    NDAYS = E["date"].nunique()
    MID = E["date"].quantile(0.5)
    pd.set_option("display.width", 220)
    print(f"\n{E['sym'].nunique()} stocks, {NDAYS} sessions, {E['date'].min():%b %Y} - {E['date'].max():%b %Y}; "
          f"{len(E)} stock-checkpoints 1%+ from yesterday's close. Net = 1% stop, after {COST * 100:.2f}% costs.")

    print("\n1. By number of big-money bars (4x volume, candle with the move) so far")
    E["n4"] = E["big4"].clip(upper=5)
    t1 = pd.DataFrame([summ(x, {"check": c, "big bars (4x)": f"{n}+" if n == 5 else n})
                       for (c, n), x in E.groupby(["check", "n4"])])
    print(t1.to_string(index=False))

    print("\n2. 3+ big-money bars: by volume threshold, move size, direction and recent bars")
    rows = []
    for c, x in E.groupby("check"):
        for m in KS:
            rows.append(summ(x[x[f"big{m}"] >= 3], {"check": c, "filter": f"3+ bars at {m}x"}))
        y = x[x["big4"] >= 3]
        rows.append(summ(y[y["chg"].abs() >= 0.02], {"check": c, "filter": "3+ at 4x & move 2%+"}))
        rows.append(summ(y[y["side"] > 0], {"check": c, "filter": "3+ at 4x, up (buy)"}))
        rows.append(summ(y[y["side"] < 0], {"check": c, "filter": "3+ at 4x, down (short)"}))
        rows.append(summ(y[y["big4_last30"] >= 1], {"check": c, "filter": "3+ at 4x & 1+ in last 30 min"}))
        rows.append(summ(y[y["big4_against"] == 0], {"check": c, "filter": "3+ at 4x & none against"}))
        top = x[x["big4"] >= 3].sort_values("big4", ascending=False).groupby("date").head(2)
        rows.append(summ(top, {"check": c, "filter": "3+ at 4x, 2 most per day"}))
    t2 = pd.DataFrame(rows)
    print(t2.to_string(index=False))

    print("\n3. By year, 10:30, 3+ big-money bars at 4x")
    y = E[(E["check"] == "10:30") & (E["big4"] >= 3)]
    print(pd.DataFrame([summ(z, {"year": yr}) for yr, z in y.groupby(y["date"].dt.year)]).to_string(index=False))
    print("\nSlippage on top of costs, 10:30, 3+ at 4x:")
    for extra in (0, 0.0005, 0.001):
        print(f"  +{extra * 100:.2f}%: {100 * (y['stop1'] - COST - extra).mean():+.3f}% per trade")
    t1.to_csv(OUT / "bigbars_counts.csv", index=False)
    t2.to_csv(OUT / "bigbars_filters.csv", index=False)
    E.to_csv(OUT / "bigbars_events.csv.gz", index=False, compression="gzip")
    print(f"\nCSV files in {OUT}: bigbars_counts.csv, bigbars_filters.csv, bigbars_events.csv.gz")
