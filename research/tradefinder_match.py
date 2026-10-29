"""What did TradeFinder's verified picks look like in our data, versus every other F&O stock the same day?

Input: research/tradefinder_trades.txt (their Sensibull verified P&L: date, stock, CE/PE strike, P&L).
For each trade day and every F&O stock (Dhan 5-minute bars, research/cache): move from yesterday's close at 9:30 /
10:00 / 10:30 / 11:00 in the option's direction (CE = up, PE = down), move in ATRs, volume so far vs the same time on
the last 20 sessions (their R-factor window), whether it crossed yesterday's high (CE) / low (PE) and when, its
sector's average move, and how it finished. Their pick is then ranked against the other stocks on each measure.
  .venv\\Scripts\\python research\\tradefinder_match.py
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
CHECKS = ["09:30", "10:00", "10:30", "11:00"]
ALIAS = {"ZOMATO": "ETERNAL", "LTIM": "LTM"}


def trades() -> pd.DataFrame:
    rows = []
    for line in (HERE / "tradefinder_trades.txt").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        for rec in line.split(";"):
            p = rec.split()
            if len(p) < 6 or p[1] == "UNTRACKED":
                continue
            rows.append({"date": pd.Timestamp("20" + p[0]), "sym": ALIAS.get(p[1], p[1]), "side": 1 if p[2][0] == "C" else -1,
                         "strike": float(p[2][1:]), "pnl": float(p[4]), "lot": float(p[5])})
    return pd.DataFrame(rows).drop_duplicates()


if __name__ == "__main__":
    T = trades()
    nifty, raw, _ = load()
    days = pd.DatetimeIndex(sorted(set(nifty.index.normalize())))
    full = np.isfinite(to_grid(nifty, days)["C"]).sum(1) >= 60
    days = days[full]
    dpos = {d: i for i, d in enumerate(days)}
    want = sorted(set(T["date"]) & set(days))
    syms = list(raw)
    # per stock, per trade day: features
    feats = []
    for s in syms:
        g = to_grid(raw[s], days)
        if g is None:
            continue
        f = daily_features(g)
        Cf = pd.DataFrame(g["C"]).ffill(axis=1).values
        V = np.nan_to_num(g["V"])
        cumv = np.cumsum(V, 1)
        avg20 = pd.DataFrame(np.where(f["ok"].values[:, None], cumv, np.nan)).rolling(20, min_periods=12).mean() \
            .shift(1).values
        for d in want:
            i = dpos[d]
            if not f["ok"].iat[i]:
                continue
            prev, atr = f["prev"].iat[i], f["atr"].iat[i]
            r = {"date": d, "sym": s, "sector": U.FNO_SECTOR_OF.get(s, "Other"), "atr": atr, "gap": f["gap"].iat[i],
                 "chg": f["chg"].iat[i], "open": g["O"][i, 0], "yhi": f["yhi"].iat[i], "ylo": f["ylo"].iat[i]}
            for ck in CHECKS:
                sl = slot(ck)
                r[f"mv_{ck}"] = Cf[i, sl - 1] / prev - 1
                r[f"rv_{ck}"] = cumv[i, sl - 1] / avg20[i, sl - 1] if avg20[i, sl - 1] > 0 else np.nan
            c = Cf[i, :LAST + 1]
            up = np.where(c > r["yhi"])[0]
            dn = np.where(c < r["ylo"])[0]
            r["t_pdh"] = up[0] if len(up) else np.nan  # first 5-minute close above yesterday's high
            r["t_pdl"] = dn[0] if len(dn) else np.nan
            r["hi_after10"] = np.nanmax(g["H"][i, slot("10:00"):LAST + 1]) / Cf[i, slot("10:00") - 1] - 1
            r["lo_after10"] = np.nanmin(g["L"][i, slot("10:00"):LAST + 1]) / Cf[i, slot("10:00") - 1] - 1
            feats.append(r)
    F = pd.DataFrame(feats)
    print(f"{len(T)} verified trades, {T['date'].nunique()} days; matched to our data: "
          f"{T.merge(F, on=['date', 'sym']).shape[0]} (stocks missing from our F&O list or dates outside data skipped)")

    # direction-aligned measures for every stock, ranked within the day, for BOTH directions
    out = []
    for side in (1, -1):
        X = F.copy()
        X["side"] = side
        for ck in CHECKS:
            X[f"smv_{ck}"] = side * X[f"mv_{ck}"]
            X[f"satr_{ck}"] = X[f"smv_{ck}"] / X["atr"]
        X["schg"] = side * X["chg"]
        X["sgap"] = side * X["gap"]
        X["t_break"] = X["t_pdh"] if side > 0 else X["t_pdl"]
        X["fav_after10"] = X["hi_after10"] if side > 0 else -X["lo_after10"]
        sec = X.groupby(["date", "sector"])["smv_10:00"].transform("mean")
        X["sector_mv10"] = sec
        out.append(X)
    A = pd.concat(out, ignore_index=True)
    g = A.groupby(["date", "side"])
    for c in ["smv_09:30", "smv_10:00", "smv_10:30", "satr_10:00", "rv_10:00", "rv_10:30", "schg", "sector_mv10",
              "sgap"]:
        A[f"rk_{c}"] = g[c].rank(ascending=False, pct=True)
    # radar-like score at 10:30: volume vs usual + move/ATR + move size, among stocks moving that way
    A["R"] = g["rv_10:30"].rank(pct=True) + g["satr_10:00"].rank(pct=True) + g["smv_10:30"].rank(pct=True)
    A["rk_R"] = A.groupby(["date", "side"])["R"].rank(ascending=False)
    A["secrank"] = A.groupby(["date", "side"])["sector_mv10"].rank(ascending=False, method="dense")
    M = T.merge(A, on=["date", "sym", "side"], how="inner")
    base = A[A["date"].isin(M["date"])]
    M.to_csv(OUT / "tradefinder_matched.csv", index=False)

    def hhmm(t):
        return "" if pd.isna(t) else f"{(555 + 5 * int(t)) // 60:02d}:{(555 + 5 * int(t)) % 60:02d}"

    pd.set_option("display.width", 220)
    print(f"\nTHEIR PICKS ({len(M)}) vs ALL F&O STOCKS THE SAME DAYS (same direction as their option)")
    rows = []
    for name, col, fn in [
        ("move by 9:30 (median %)", "smv_09:30", lambda x: 100 * x.median()),
        ("move by 10:00 (median %)", "smv_10:00", lambda x: 100 * x.median()),
        ("move by 10:30 (median %)", "smv_10:30", lambda x: 100 * x.median()),
        ("move by 10:00 in ATRs (median)", "satr_10:00", lambda x: x.median()),
        ("volume vs 20-day same time at 10:00 (median)", "rv_10:00", lambda x: x.median()),
        ("volume vs 20-day same time at 10:30 (median)", "rv_10:30", lambda x: x.median()),
        ("gap in the option's direction (median %)", "sgap", lambda x: 100 * x.median()),
        ("day's change in the option's direction (median %)", "schg", lambda x: 100 * x.median()),
        ("best move after 10:00 (median %)", "fav_after10", lambda x: 100 * x.median()),
        ("crossed yesterday's high (CE) / low (PE) by 10:30 (share)", "t_break",
         lambda x: (x < slot("10:30")).mean()),
        ("crossed it at all (share)", "t_break", lambda x: x.notna().mean()),
        ("sector moving the same way at 10:00 (share)", "sector_mv10", lambda x: (x > 0).mean()),
    ]:
        rows.append({"measure": name, "their picks": fn(M[col]), "all stocks": fn(base[col])})
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    print("\nWhere their pick ranked among ~200 F&O stocks that day (1 = strongest that way; percentile 0 = top):")
    for c, lab in [("rk_smv_10:00", "move by 10:00"), ("rk_rv_10:30", "volume vs usual at 10:30"),
                   ("rk_satr_10:00", "move in ATRs at 10:00"), ("rk_sector_mv10", "its sector's move at 10:00"),
                   ("rk_schg", "day's final change")]:
        x = M[c]
        print(f"  {lab:30s} median top {100 * x.median():.0f}%; in top 10%: {100 * (x <= 0.1).mean():.0f}%; "
              f"top 25%: {100 * (x <= 0.25).mean():.0f}%")
    print(f"  radar-style score at 10:30: median rank {M['rk_R'].median():.0f}; #1: {100 * (M['rk_R'] == 1).mean():.0f}%; "
          f"top 5: {100 * (M['rk_R'] <= 5).mean():.0f}%; top 20: {100 * (M['rk_R'] <= 20).mean():.0f}%")
    print(f"  its sector's rank (by average move at 10:00, that direction): #1 {100 * (M['secrank'] == 1).mean():.0f}%, "
          f"top 3 {100 * (M['secrank'] <= 3).mean():.0f}%")
    print(f"\n  time it crossed yesterday's high/low (their picks, median): {hhmm(M['t_break'].median())}; "
          f"before 10:00: {100 * (M['t_break'] < slot('10:00')).mean():.0f}%, before 11:00: "
          f"{100 * (M['t_break'] < slot('11:00')).mean():.0f}%, never: {100 * M['t_break'].isna().mean():.0f}%")
    print(f"  CE {100 * (M['side'] > 0).mean():.0f}% / PE {100 * (M['side'] < 0).mean():.0f}%; "
          f"strike vs open (in the option's direction) median {100 * ((M['strike'] / M['open'] - 1) * M['side']).median():+.1f}%")
    print(f"  lot value at open (median): Rs {(M['open'] * M['lot']).median():,.0f}")
    # losing trades vs winners
    print("\nTheir 30 losing days vs winners:")
    for c in ["smv_10:00", "rv_10:30", "schg", "fav_after10"]:
        print(f"  {c:12s} winners {M.loc[M['pnl'] > 0, c].median():+.4f}  losers {M.loc[M['pnl'] < 0, c].median():+.4f}")
