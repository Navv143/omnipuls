"""Time-of-day volume: is a 3-minute bar with unusual volume (vs the same 3 minutes on the stock's last 10 sessions)
followed by a move in the bar's direction? Last month on 3-minute bars (built from Dhan 1-minute data,
research/fetch_1min.py), then the same test on 5 years of 5-minute bars (research/cache).

For every bar: volume ratio R = volume / average volume of the same time slot on the previous 10 sessions.
A spike is R >= 3 with a green or red candle. Entry = next bar's open, in the candle's direction. Measured:
move after 3/6/15/30/60 minutes and to the last bar, and whether +1% comes before -0.5% (an option buyer's 2:1).
Control = ordinary bars (R < 1.5) of the same direction. Costs 0.12% on trades held to the close.
  .venv\\Scripts\\python research\\volume_spikes.py
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
from momentum_dhan import OUT  # noqa: E402

warnings.filterwarnings("ignore")
CACHE = HERE / "cache"
COST = 0.0012


def naive(df):
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    df = df.copy()
    df.index = idx
    return df[~df.index.duplicated(keep="last")].sort_index()


def grid(df: pd.DataFrame, days: pd.DatetimeIndex, minutes: int) -> dict:
    """Bars -> {O,H,L,C,V: [day, slot]} on a `minutes` grid from 9:15 (aggregating finer bars)."""
    df = naive(df)
    mins = df.index.hour * 60 + df.index.minute - (9 * 60 + 15)
    nslot = 375 // minutes
    ok = (mins >= 0) & (mins < nslot * minutes)
    df, mins = df[ok], mins[ok]
    g = df.groupby([df.index.normalize(), np.asarray(mins // minutes)]).agg(O=("Open", "first"), H=("High", "max"), L=("Low", "min"), C=("Close", "last"),
                            V=("Volume", "sum"))
    pos = pd.Series(np.arange(len(days)), index=days)
    di = pos.reindex(g.index.get_level_values(0)).values
    keep = ~np.isnan(di)
    di, si = di[keep].astype(int), g.index.get_level_values(1)[keep].astype(int)
    out = {}
    for k in "OHLCV":
        a = np.full((len(days), nslot), np.nan)
        a[di, si] = g[k].values[keep]
        out[k] = a
    return out


def ids_map():
    import dhan as D
    return {v: k for k, v in D.equity_ids().items() if k in U.FNO_SECTOR_OF}


def study(g: dict, days, sym: str, minutes: int, last_entry_min: int = 315) -> pd.DataFrame:
    """Events (R >= 3) and controls (R < 1.5) with forward moves, for one stock."""
    O, H, L, C, V = g["O"], g["H"], g["L"], g["C"], np.nan_to_num(g["V"])
    T = C.shape[1]
    okday = np.isfinite(C).sum(1) >= 0.8 * T
    Cf = pd.DataFrame(C).ffill(axis=1).values
    lastc = np.array([row[np.where(np.isfinite(row))[0][-1]] if np.isfinite(row).any() else np.nan for row in C])
    lasti = np.array([np.where(np.isfinite(row))[0][-1] if np.isfinite(row).any() else -1 for row in C])
    prev = pd.Series(np.where(okday, lastc, np.nan)).shift(1).values
    base = pd.DataFrame(np.where(okday[:, None], V, np.nan)).rolling(10, min_periods=7).mean().shift(1).values
    R = V / base
    dirn = np.sign(C - O)
    hz = {m: max(1, m // minutes) for m in (3, 6, 15, 30, 60) if m >= minutes}
    smax = last_entry_min // minutes
    rows = []
    for d in np.where(okday & np.isfinite(prev))[0]:
        for s in range(0, min(smax, T - 1)):
            r = R[d, s]
            if not np.isfinite(r) or not np.isfinite(dirn[d, s]) or dirn[d, s] == 0 or not (r >= 3 or r < 1.5):
                continue
            e = s + 1
            entry = O[d, e]
            if not np.isfinite(entry):
                continue
            sd = dirn[d, s]
            row = {"date": days[d], "sym": sym, "slot": s, "R": r, "side": int(sd),
                   "so_far": sd * (Cf[d, s] / prev[d] - 1), "bar": abs(C[d, s] / O[d, s] - 1),
                   "close": sd * (lastc[d] / entry - 1)}
            for m, j in hz.items():
                t = min(s + j, lasti[d])
                row[f"m{m}"] = sd * (Cf[d, t] / entry - 1)
            # +1% before -0.5% (checked bar by bar; stop assumed first if both inside one bar)
            hit = 0
            for t in range(e, lasti[d] + 1):
                if (sd > 0 and L[d, t] <= entry * 0.995) or (sd < 0 and H[d, t] >= entry * 1.005):
                    hit = -1
                    break
                if (sd > 0 and H[d, t] >= entry * 1.01) or (sd < 0 and L[d, t] <= entry * 0.99):
                    hit = 1
                    break
            row["tgt"] = hit
            rows.append(row)
    return pd.DataFrame(rows)


def hhmm(s, minutes):
    m = 555 + minutes * int(s)
    return f"{m // 60:02d}:{m % 60:02d}"


def table(E, minutes, label):
    E = E.copy()
    E["bucket"] = pd.cut(E["R"], [0, 1.5, 3, 5, 10, np.inf], labels=["<1.5 (normal)", "1.5-3", "3-5x", "5-10x",
                                                                    "10x+"], right=False)
    cols = [c for c in ("m3", "m6", "m15", "m30", "m60") if c in E]
    rows = []
    for b, x in E.groupby("bucket", observed=True):
        r = {"volume vs usual": b, "bars": len(x)}
        for c in cols:
            r[f"after {c[1:]} min %"] = 100 * x[c].mean()
        r["to close, net %"] = 100 * (x["close"] - COST).mean()
        r["+1% before -0.5% %"] = 100 * (x["tgt"] == 1).mean()
        r["-0.5% first %"] = 100 * (x["tgt"] == -1).mean()
        rows.append(r)
    print(f"\n{label}: average move after the bar, in the bar's direction (entry = next bar's open)")
    print(pd.DataFrame(rows).round(3).to_string(index=False))


def split(E, label):
    S = E[E["R"] >= 5].copy()
    mid = S["date"].quantile(0.5)
    rows = []
    for name, m in [("all 5x+ spikes", S.index == S.index),
                    ("first 5x+ spike of the day per stock", ~S.duplicated(["date", "sym"])),
                    ("stock already 2%+ that way", S["so_far"] >= 0.02),
                    ("stock less than 1% so far", S["so_far"].abs() < 0.01),
                    ("against the day's move (so far <= -1%)", S["so_far"] <= -0.01),
                    ("big candle (bar >= 0.5%)", S["bar"] >= 0.005),
                    ("before 10:00", S["slot"] * MIN < 45), ("10:00-12:00", (S["slot"] * MIN).between(45, 164)),
                    ("after 12:00", S["slot"] * MIN >= 165), ("buy side", S["side"] > 0),
                    ("short side", S["side"] < 0)]:
        x = S[m]
        if len(x) < 30:
            continue
        net = x["close"] - COST
        rows.append({"5x+ spikes": name, "n": len(x), "to close net %": 100 * net.mean(),
                     "after 15 min %": 100 * x["m15"].mean(), "+1% before -0.5% %": 100 * (x["tgt"] == 1).mean(),
                     "H1 %": 100 * net[x["date"] < mid].mean(), "H2 %": 100 * net[x["date"] >= mid].mean(),
                     "t": net.mean() / net.std() * np.sqrt(len(net))})
    print(f"\n{label}: 5x+ spikes split")
    print(pd.DataFrame(rows).round(3).to_string(index=False))


if __name__ == "__main__":
    ids = ids_map()
    pd.set_option("display.width", 250)
    # ------------------------------------------------ last month, 3-minute bars
    MIN = 3
    nifty = naive(pickle.loads((CACHE / "m1_IDX_13.pkl").read_bytes()))
    days = pd.DatetimeIndex(sorted(set(nifty.index.normalize())))
    ev, prof = [], []
    for f in glob.glob(str(CACHE / "m1_*.pkl")):
        sid = Path(f).stem[3:]
        if not sid.isdigit() or int(sid) not in ids:
            continue
        sym = ids[int(sid)]
        g = grid(pickle.loads(Path(f).read_bytes()), days, MIN)
        v = g["V"]
        share = v / np.nansum(v, 1, keepdims=True)
        prof.append(np.nanmean(share, 0))
        ev.append(study(g, days, sym, MIN))
    E3 = pd.concat(ev, ignore_index=True)
    E3 = E3[E3["date"] >= days[10]]  # need 10 earlier sessions for the baseline
    E3.to_csv(OUT / "volume_spikes_3min.csv.gz", index=False, compression="gzip")
    P = np.nanmean(np.vstack(prof), 0)
    print(f"LAST MONTH, 3-minute bars: {E3['sym'].nunique()} stocks, {E3['date'].nunique()} sessions "
          f"({E3['date'].min():%d %b} - {E3['date'].max():%d %b %Y})")
    print("\nAverage share of the day's volume by time (3-minute bars):")
    marks = [0, 1, 2, 5, 10, 15, 20, 30, 40, 60, 80, 100, 110, 115, 120, 124]
    print("  " + "  ".join(f"{hhmm(s, MIN)} {100 * P[s]:.1f}%" for s in marks if s < len(P)))
    print(f"  first 3 minutes = {100 * P[0]:.1f}% of the day; first 15 min = {100 * P[:5].sum():.1f}%; "
          f"last 15 min = {100 * P[-5:].sum():.1f}%")
    spk = E3[E3["R"] >= 5]
    print(f"\n5x+ spikes: {len(spk)} in {E3['date'].nunique()} sessions ({len(spk) / E3['date'].nunique():.0f} a day); "
          f"10x+: {(E3['R'] >= 10).sum()}")
    table(E3, MIN, "LAST MONTH, 3-minute")
    split(E3, "LAST MONTH, 3-minute")

    # spikes vs the day's top-10 movers
    mv = pd.read_csv(OUT / "movers_last_month.csv", parse_dates=["date"])
    top = mv[mv["mover"]][["date", "sym", "side", "t1"]]
    first5 = spk.sort_values("slot").drop_duplicates(["date", "sym"])[["date", "sym", "slot", "side"]]
    j = top.merge(first5, on=["date", "sym"], how="left", suffixes=("", "_spk"))
    j["t1_min"] = j["t1"] * 5
    j["spk_min"] = j["slot"] * MIN
    had = j["spk_min"].notna()
    before = had & (j["spk_min"] < j["t1_min"]) & (j["side_spk"] == j["side"])
    print(f"\nTop-10 movers last month: {len(j)}. Had a 5x+ 3-minute spike that day: {100 * had.mean():.0f}%; "
          f"spike in the move's direction BEFORE the stock was 1% up/down: {100 * before.mean():.0f}% "
          f"(median {j.loc[before, 't1_min'].sub(j.loc[before, 'spk_min']).median():.0f} min earlier)")
    allfirst = first5.merge(top.assign(is_mover=True), on=["date", "sym"], how="left", suffixes=("", "_m"))
    print(f"Precision: of {len(allfirst)} stock-days with a 5x+ spike, {100 * allfirst['is_mover'].notna().mean():.1f}% "
          f"were top-10 movers (base: {100 * len(top) / (E3['date'].nunique() * len(ids)):.1f}% of stock-days)")

    # ------------------------------------------------ 5 years, 5-minute bars
    from movers_study import load
    MIN = 5
    nifty5, raw, _ = load()
    days5 = pd.DatetimeIndex(sorted(set(nifty5.index.normalize())))
    ev = []
    for i, (sym, df) in enumerate(raw.items(), 1):
        ev.append(study(grid(df, days5, MIN), days5, sym, MIN))
        if i % 50 == 0:
            print(f"  5-year: {i}/{len(raw)} stocks", flush=True)
    E5 = pd.concat(ev, ignore_index=True)
    E5 = E5[E5["date"] >= days5[10]]
    print(f"\n5 YEARS, 5-minute bars: {E5['sym'].nunique()} stocks, {E5['date'].nunique()} sessions")
    table(E5, MIN, "5 YEARS, 5-minute")
    split(E5, "5 YEARS, 5-minute")
    yr = E5[E5["R"] >= 5].copy()
    print("\n5x+ spikes by year: to close net %, +1% before -0.5% %")
    print(yr.groupby(yr["date"].dt.year).apply(lambda x: pd.Series({
        "n": len(x), "net %": 100 * (x["close"] - COST).mean(), "after 15 min %": 100 * x["m15"].mean(),
        "+1% first %": 100 * (x["tgt"] == 1).mean()})).round(3).to_string())
