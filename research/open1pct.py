"""Stocks that open quietly (gap under 1%) and then move 1% from the open: what happens next, and is there an edge
right at that moment? Dhan 5-minute bars, 206 F&O stocks, Nov 2021 - Oct 2026 (cached by momentum_dhan.py).

Event: |gap| < 1%, the first 5-minute close 1%+ above (or below) the day's open. Entry at the next candle's open,
in the move's way (follow) or against it (fade). Outcomes after 15 / 30 / 60 minutes and at 15:20, plus 0.5% and 1%
stops held to 15:20; 0.12% round-trip costs.
Context at the trigger: time, gap the same way or not, volume so far vs the same time on the last 10 days, the
trigger candle's volume vs its slot, Nifty since its open, the stock's sector since the open (other F&O stocks),
yesterday's high/low already broken, ATR %, distance travelled vs ATR.
Every 1- and 2-filter combination is checked on the first and second half of the dates and on 2025-26; with
hundreds of combinations some pass by chance, so the count tried is printed.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\open1pct.py
"""
from __future__ import annotations

import itertools
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import universe as U  # noqa: E402
from bigbars_dhan import load_cache  # noqa: E402
from momentum_dhan import NSLOT, day_basics, slot, to_grid  # noqa: E402

warnings.filterwarnings("ignore")
COST = 0.0012
EXIT = slot("15:20")


def nifty_grid(nifty: pd.DataFrame, days) -> np.ndarray:
    g = to_grid(nifty, days)
    from momentum_dhan import ffill_rows
    C = ffill_rows(g["C"])
    return C / g["O"][:, [0]] - 1  # Nifty change since its open, per slot


def main():
    nifty, raw = load_cache()
    idx = pd.DatetimeIndex(nifty.index)
    nifty.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    days = pd.DatetimeIndex(sorted(set(nifty.index.normalize())))
    NF = nifty_grid(nifty, days)
    grids, FO = {}, {}
    from momentum_dhan import ffill_rows
    for s, df in raw.items():
        d = df.copy()
        i2 = pd.DatetimeIndex(d.index)
        d.index = i2.tz_convert("Asia/Kolkata").tz_localize(None) if i2.tz is not None else i2
        g = to_grid(d, days)
        if g is None:
            continue
        b = day_basics(g)
        grids[s] = (g, b)
        FO[s] = ffill_rows(g["C"]) / b["open"][:, None] - 1
    syms = list(grids)
    sec_of = pd.Series(U.FNO_SECTOR_OF)
    # sector average change since open per day/slot (all its F&O stocks)
    sec_mean = {}
    for sec, members in pd.Series(syms).groupby(sec_of.reindex(syms).values):
        arr = np.stack([FO[m] for m in members])
        with np.errstate(all="ignore"):
            sec_mean[sec] = (np.nansum(arr, 0), np.isfinite(arr).sum(0))
    rows = []
    for s in syms:
        g, b = grids[s]
        O, H, L, C, V = g["O"], g["H"], g["L"], g["C"], g["V"]
        fo = FO[s]
        cumv = np.nancumsum(np.nan_to_num(V), 1)
        avg_cum = pd.DataFrame(np.where(b["ok"][:, None], cumv, np.nan)).rolling(10, min_periods=7).mean().shift(1).values
        avg_bar = pd.DataFrame(np.where(b["ok"][:, None], V, np.nan)).rolling(10, min_periods=7).mean().shift(1).values
        pdh = pd.Series(np.nanmax(H, 1)).shift(1).values
        pdl = pd.Series(np.nanmin(L, 1)).shift(1).values
        ssum, scnt = sec_mean.get(sec_of.get(s, "Other"), (None, None))
        for di in np.where(b["ok"] & (np.abs(b["gap"]) < 0.01))[0]:
            row = fo[di, :EXIT - 1]
            hit = np.where(np.abs(row) >= 0.01)[0]
            if not len(hit):
                continue
            k = hit[0]
            if k + 1 >= EXIT or not np.isfinite(O[di, k + 1]):
                continue
            side = int(np.sign(row[k]))
            e = O[di, k + 1]
            path_c = ffill_rows(C[di:di + 1])[0]

            def at(n):
                j = min(k + 1 + n, EXIT)
                px = O[di, j] if np.isfinite(O[di, j]) else path_c[j - 1]
                return side * (px / e - 1)

            out = {"date": days[di], "sym": s, "side": side, "slot": k, "t": f"{9 + (15 + 5 * k) // 60}:{(15 + 5 * k) % 60:02d}",
                   "gap_same": side * b["gap"][di], "atr": b["atr"][di],
                   "rvol": cumv[di, k] / avg_cum[di, k] if avg_cum[di, k] > 0 else np.nan,
                   "bar_rvol": V[di, k] / avg_bar[di, k] if avg_bar[di, k] > 0 else np.nan,
                   "nifty_same": side * NF[di, k], "move_atr": 0.01 / b["atr"][di],
                   "yday_broken": (C[di, k] > pdh[di]) if side > 0 else (C[di, k] < pdl[di]),
                   "r15": at(3), "r30": at(6), "r60": at(12), "close": at(EXIT - k - 1)}
            if ssum is not None and scnt[di, k] > 3:
                out["sector_same"] = side * (ssum[di, k] - fo[di, k]) / (scnt[di, k] - 1)
            else:
                out["sector_same"] = np.nan
            for stp in (0.005, 0.01):
                sp = e * (1 - side * stp)
                res = out["close"]
                for j in range(k + 1, EXIT):
                    if (side > 0 and L[di, j] <= sp) or (side < 0 and H[di, j] >= sp):
                        f = O[di, j] if ((side > 0 and O[di, j] < sp) or (side < 0 and O[di, j] > sp)) else sp
                        res = side * (f / e - 1)
                        break
                out[f"stop{int(stp * 1000)}"] = res
                # fade with the same stop distance
                spf = e * (1 + side * stp)
                resf = -out["close"]
                for j in range(k + 1, EXIT):
                    if (side > 0 and H[di, j] >= spf) or (side < 0 and L[di, j] <= spf):
                        f = O[di, j] if ((side > 0 and O[di, j] > spf) or (side < 0 and O[di, j] < spf)) else spf
                        resf = -side * (f / e - 1)
                        break
                out[f"fade{int(stp * 1000)}"] = resf
            rows.append(out)
    E = pd.DataFrame(rows)
    E.to_csv(HERE / "results" / "open1pct_events.csv.gz", index=False)
    mid = E["date"].sort_values().iloc[len(E) // 2]
    print(f"{len(E)} events, {E['date'].nunique()} days, {E['sym'].nunique()} stocks; median trigger {E['t'].median() if False else E.sort_values('slot')['t'].iloc[len(E)//2]}; split at {mid:%d %b %Y}")
    outs = ["r15", "r30", "r60", "close", "stop5", "stop10", "fade5", "fade10"]

    def score(x):
        r = {"n": len(x)}
        for o in outs:
            r[o] = round(100 * (x[o].mean() - (COST if o not in ("r15", "r30", "r60") else 0)), 3)
        return r

    print("\nAll events (r15/r30/r60 before costs, the rest after 0.12%), % per trade in the move's way:")
    print(pd.DataFrame([score(E)]).to_string(index=False))
    tb = pd.cut(E["slot"], [-1, 2, 5, 11, 23, 200], labels=["9:15-9:25", "9:30-9:40", "9:45-10:10", "10:15-11:10", "11:15+"])
    print("\nBy time the 1% was reached:")
    print(pd.DataFrame({k: score(v) for k, v in E.groupby(tb)}).T.to_string())

    filters = {
        "gap same way": E["gap_same"] > 0.002, "gap against": E["gap_same"] < -0.002,
        "early (by 9:40)": E["slot"] <= 5, "late (10:15+)": E["slot"] >= 12,
        "vol 2x+": E["rvol"] >= 2, "vol <1x": E["rvol"] < 1, "trigger bar 3x+": E["bar_rvol"] >= 3,
        "Nifty same way 0.2%+": E["nifty_same"] > 0.002, "Nifty against": E["nifty_same"] < -0.002,
        "sector same 0.5%+": E["sector_same"] > 0.005, "sector against": E["sector_same"] < 0,
        "yday H/L broken": E["yday_broken"], "yday not broken": ~E["yday_broken"],
        "low ATR (<2%)": E["atr"] < 0.02, "high ATR (3%+)": E["atr"] >= 0.03,
        "long": E["side"] > 0, "short": E["side"] < 0,
    }
    tried, keep = 0, []
    H1, H2 = E["date"] < mid, E["date"] >= mid
    recent = E["date"] >= "2025-01-01"
    names = list(filters)
    combos = [(a,) for a in names] + list(itertools.combinations(names, 2))
    for c in combos:
        m = np.logical_and.reduce([filters[x].fillna(False).values for x in c])
        if m.sum() < 150:
            continue
        for o in ("stop5", "stop10", "close", "fade5", "fade10"):
            tried += 1
            x = E.loc[m, o] - COST
            a, b, r = x[H1[m]].mean(), x[H2[m]].mean(), x[recent[m]].mean()
            if a > 0 and b > 0 and r > 0:
                t = x.mean() / (x.std() / np.sqrt(len(x)))
                keep.append({"filters": " + ".join(c), "exit": o, "n": int(m.sum()), "per trade %": round(100 * x.mean(), 3),
                             "1st half": round(100 * a, 3), "2nd half": round(100 * b, 3), "2025-26": round(100 * r, 3),
                             "t": round(t, 2)})
    K = pd.DataFrame(keep).sort_values("t", ascending=False) if keep else pd.DataFrame()
    print(f"\n{tried} filter/exit combinations tried (150+ trades each); {len(K)} positive in both halves and 2025-26 "
          f"after costs (about {tried // 20} would pass by luck at 5% each... and halves are not independent):")
    if not K.empty:
        print(K.head(25).to_string(index=False))
        K.to_csv(HERE / "results" / "open1pct_combos.csv", index=False)


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
