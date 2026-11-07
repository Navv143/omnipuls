"""Cross-sectional scan: many small, consistent edges from ranking ALL F&O stocks at fixed times (not single-chart
indicators). Grid fixed in advance:
  rank time   10:15, 11:15, 12:15, 13:15
  measure     rs_nifty (move from open minus Nifty's), rs_sector (minus its sector's average), vwap_dist (% from the
              day's VWAP), gap (open vs yesterday's close), conviction (move from open x relative volume so far)
  hold        to 15:15, or 60 minutes
  leg         short the bottom 5, long the top 5, hedged short (bottom 5 short + Nifty long = their underperformance),
              hedged long (top 5 long + Nifty short)
Costs: 0.12% a stock round trip, +0.02% for the Nifty hedge leg. Gross shown too.
Selection on the FIRST half of the days only (train); a rule counts only if it also holds on the second half (test).

Then a portfolio: the test-surviving rules + the Super Bot 3-window plan, day by day: % winning days, worst day,
correlation between them.

Usage: python research/cross_section_scan.py <fno60_new.pkl> <yahoo_idx5m.pkl> <superbot_candidates.pkl>
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import universe as U             # noqa: E402

COST, HEDGE = 0.12, 0.02
TIMES = ["10:15", "11:15", "12:15", "13:15"]
MEASURES = ["rs_nifty", "rs_sector", "vwap_dist", "gap", "conviction"]
N = 5


def naive(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    d = d[(d.index.second == 0) & (d.index.strftime("%H:%M") >= "09:15") & (d.index.strftime("%H:%M") < "15:30")]
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def panel(stocks: dict, nifty: pd.DataFrame) -> pd.DataFrame:
    """One row per (day, stock, rank time): every measure at that time and the forward returns."""
    rows = []
    days = sorted(set(nifty.index.normalize()))
    usual = {}                                    # stock -> {slot: list of cumulative volume}
    prev_close = {}
    for day in days:
        nz = nifty[nifty.index.normalize() == day]
        if len(nz) < 70:
            continue
        n_open = float(nz["Open"].iloc[0])

        def npx(t, after=False):
            z = nz[nz.index >= t] if after else nz[nz.index < t]
            return float(z["Open"].iloc[0]) if after and len(z) else (float(z["Close"].iloc[-1]) if len(z) else np.nan)
        day_rows = []
        for s, b in stocks.items():
            z = b[b.index.normalize() == day]
            if len(z) < 60:
                if len(z):
                    prev_close[s] = float(z["Close"].iloc[-1])
                continue
            o = float(z["Open"].iloc[0])
            tp = (z["High"] + z["Low"] + z["Close"]) / 3
            cv = z["Volume"].cumsum()
            vwap = (tp * z["Volume"]).cumsum() / cv.replace(0, np.nan)
            u = usual.setdefault(s, {})
            for T in TIMES:
                t = day + pd.Timedelta(hours=int(T[:2]), minutes=int(T[3:]))
                m = z[z.index < t]
                a = z[z.index >= t]
                if m.empty or a.empty:
                    continue
                px = float(m["Close"].iloc[-1])
                e = float(a["Open"].iloc[0])
                close_bar = a[a.index < day + pd.Timedelta(hours=15, minutes=15)]
                h60 = a[a.index < t + pd.Timedelta(minutes=60)]
                if close_bar.empty or h60.empty:
                    continue
                vol_now = float(cv.loc[m.index[-1]])
                hist = u.get(T, [])
                rvol = vol_now / np.mean(hist[-20:]) if len(hist) >= 10 and np.mean(hist[-20:]) > 0 else np.nan
                u.setdefault(T, []).append(vol_now)
                n_mv = (npx(t) / n_open - 1) * 100
                mv = (px / o - 1) * 100
                day_rows.append({
                    "day": day, "stock": s, "T": T, "sector": U.FNO_SECTOR_OF.get(s, "Other"),
                    "mv": mv, "rs_nifty": mv - n_mv, "vwap_dist": (px / float(vwap.loc[m.index[-1]]) - 1) * 100,
                    "gap": (o / prev_close[s] - 1) * 100 if s in prev_close else np.nan,
                    "conviction": mv * (rvol if np.isfinite(rvol) else np.nan),
                    "r_close": (float(close_bar["Close"].iloc[-1]) / e - 1) * 100,
                    "r_60": (float(h60["Close"].iloc[-1]) / e - 1) * 100,
                    "n_close": (npx(day + pd.Timedelta(hours=15, minutes=15)) / npx(t, True) - 1) * 100,
                    "n_60": (npx(t + pd.Timedelta(minutes=60)) / npx(t, True) - 1) * 100})
            prev_close[s] = float(z["Close"].iloc[-1])
        if day_rows:
            dr = pd.DataFrame(day_rows)
            dr["rs_sector"] = dr["mv"] - dr.groupby(["T", "sector"])["mv"].transform("mean")
            rows.append(dr)
    return pd.concat(rows, ignore_index=True)


def rule_returns(p: pd.DataFrame, T: str, meas: str, hold: str, leg: str) -> pd.Series:
    """Daily % return of one rule (average over its N stocks, after costs)."""
    z = p[(p["T"] == T)].dropna(subset=[meas])
    rc, rn = ("r_close", "n_close") if hold == "15:15" else ("r_60", "n_60")
    out = {}
    for day, g in z.groupby("day"):
        if len(g) < 50:
            continue
        g = g.sort_values(meas)
        bot, top = g.head(N), g.tail(N)
        nifty = g[rn].iloc[0]
        if leg == "short bottom":
            r = -bot[rc].mean() - COST
        elif leg == "long top":
            r = top[rc].mean() - COST
        elif leg == "hedged short bottom":
            r = (-bot[rc].mean() + nifty) / 2 - (COST + HEDGE) / 2
        else:
            r = (top[rc].mean() - nifty) / 2 - (COST + HEDGE) / 2
        out[day] = r
    return pd.Series(out).sort_index()


def summ(x: pd.Series) -> dict:
    if len(x) < 5:
        return {"days": len(x)}
    pf = x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else np.inf
    return {"days": len(x), "avg %": round(x.mean(), 3), "t": round(x.mean() / x.std() * np.sqrt(len(x)), 2),
            "win days %": round((x > 0).mean() * 100), "PF": round(pf, 2), "worst day": round(x.min(), 2)}


def main(argv):
    st, _ = pickle.load(open(argv[1], "rb"))
    stocks = {s: naive(df) for s, df in st.items() if s in U.FNO_SECTOR_OF and df is not None and len(df)}
    nifty = naive(pd.read_pickle(argv[2])["NIFTY"])
    cache = Path(argv[1]).resolve().parent / "cross_panel.pkl"
    p = pd.read_pickle(cache) if cache.exists() else panel(stocks, nifty)
    p.to_pickle(cache)
    days = sorted(p["day"].unique())
    split = days[len(days) // 2]
    print(f"panel: {len(p)} rows, {len(days)} days, train {days[0].date()}..{(split - pd.Timedelta(days=1)).date()}, "
          f"test {split.date()}..{days[-1].date()}")
    rows, series = [], {}
    for T in TIMES:
        for meas in MEASURES:
            for hold in ("15:15", "60 min"):
                for leg in ("short bottom", "long top", "hedged short bottom", "hedged long top"):
                    x = rule_returns(p, T, meas, hold, leg)
                    tr, te = x[x.index < split], x[x.index >= split]
                    k = f"{T} {meas} {hold} {leg}"
                    series[k] = x
                    rows.append({"rule": k, **{f"train {a}": b for a, b in summ(tr).items() if a in ("avg %", "t", "win days %")},
                                 **{f"test {a}": b for a, b in summ(te).items() if a in ("avg %", "t", "win days %", "PF")},
                                 "gross all %": round(x.mean() + (COST if "hedged" not in leg else (COST + HEDGE) / 2), 3)})
    res = pd.DataFrame(rows)
    res.to_csv(Path(argv[1]).resolve().parent / "cross_section_scan.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    picked = res[(res["train t"] >= 2.0) & (res["train avg %"] > 0)].sort_values("train t", ascending=False)
    print(f"\n{len(res)} rules; picked on TRAIN (t >= 2, after costs): {len(picked)}")
    print(picked.to_string(index=False))
    held = picked[(picked["test avg %"] > 0) & (picked["test t"] >= 1.0)]
    print(f"\n...of which HOLD on the unseen TEST half (avg > 0, t >= 1): {len(held)}")
    print(held.to_string(index=False))
    # expected by luck: share of all rules with train t >= 2 that also pass test
    print(f"\n(for scale: {len(res[(res['test avg %'] > 0) & (res['test t'] >= 1.0)])} of {len(res)} rules pass the test bar "
          "on their own, with no train selection)")
    # portfolio
    import superbot_strict as X
    import superbot_windows as W
    import superbot_backtest as BT
    c = pd.read_pickle(argv[3])
    c = c[c.apply(X.RULES["with the market"], axis=1)].dropna(subset=["entry"])
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in st.items()}
    sb = W.run(c, bars, [("10:00", "10:30", 2), ("11:00", "12:00", 2), ("12:00", "12:30", 2)])
    sbd = sb.groupby("day")["pct"].mean()
    sbd.index = pd.to_datetime(sbd.index)
    port = {"Super Bot 3 windows (avg per trade, per day)": sbd}
    for k in held["rule"].head(4):
        port[k] = series[k]
    P = pd.DataFrame(port).dropna(how="all")
    print("\nPORTFOLIO, day by day (each component = its average trade that day, after costs):")
    for k in P:
        print(f"  {k:60s} {summ(P[k].dropna())}")
    if P.shape[1] > 1:
        comb = P.mean(axis=1)
        print(f"  {'COMBINED (equal weight)':60s} {summ(comb)}")
        print("  correlation of daily results:\n" + P.corr().round(2).to_string())


if __name__ == "__main__":
    main(sys.argv)
