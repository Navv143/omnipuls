"""What the option market promises vs what happens - the edge option sellers live on.

1. Volatility premium: India VIX (implied, annual) vs the move Nifty actually makes next (realized). Short ATM straddle
   proxy: premium = 0.8 * S * sigma * sqrt(T) (Black-Scholes ATM approximation, sigma from VIX), payoff = |move|.
   Held one trading day and one week (5 trading days). Reported overall, by year, and for the recent 6 / 12 months.
2. Expected-move fade: on the hourly candles (3 years), when Nifty is already beyond k x the day's VIX-implied move by
   11:15-14:15, what happens until the close - continuation or snap-back?
3. Expiry pin: on weekly expiry days, does Nifty close nearer a 100-point strike than on other days, and does it move
   towards the nearest strike in the last hours?
Usage: python research/option_edge_study.py daily_idx.pkl yahoo1h.pkl
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd


def vol_premium(d: dict, name: str = "NIFTY"):
    n, v = d[name]["Close"].dropna(), d["VIX"]["Close"].dropna()
    x = pd.DataFrame({"c": n, "vix": v}).dropna()
    x["ret"] = x["c"].pct_change().shift(-1)                      # tomorrow's move (decision at today's close)
    x["sig_d"] = x["vix"] / 100 / np.sqrt(252)                    # implied 1-day SD
    x["prem1"] = 0.8 * x["sig_d"]                                 # 1-day ATM straddle, % of the index
    x["pnl1"] = x["prem1"] - x["ret"].abs()
    x["ret5"] = x["c"].shift(-5) / x["c"] - 1
    x["prem5"] = 0.8 * x["sig_d"] * np.sqrt(5)
    x["pnl5"] = x["prem5"] - x["ret5"].abs()
    x["rv21"] = x["c"].pct_change().rolling(21).std().shift(-21) * np.sqrt(252) * 100   # realized next month
    x = x.dropna()
    wk = x.iloc[::5]                                              # non-overlapping weeks
    print(f"\n== 1. Volatility premium ({name}, {x.index.min():%Y}-{x.index.max():%Y}) ==")
    print(f"VIX above the next month's realized vol on {(x.vix > x.rv21).mean() * 100:.0f}% of days; "
          f"average VIX {x.vix.mean():.1f} vs realized {x.rv21.mean():.1f}")
    print(f"Short 1-day straddle: wins {(x.pnl1 > 0).mean() * 100:.0f}% of days, avg {x.pnl1.mean() * 100:+.3f}% of index, "
          f"worst {x.pnl1.min() * 100:+.2f}% ({x.pnl1.idxmin():%d %b %Y})")
    print(f"Short 1-week straddle: wins {(wk.pnl5 > 0).mean() * 100:.0f}% of weeks, avg {wk.pnl5.mean() * 100:+.3f}%, "
          f"worst {wk.pnl5.min() * 100:+.2f}% ({wk.pnl5.idxmin():%d %b %Y})")
    for y, g in wk.groupby(wk.index.year):
        print(f"  {y}: weekly win {(g.pnl5 > 0).mean() * 100:3.0f}%  avg {g.pnl5.mean() * 100:+.3f}%  worst {g.pnl5.min() * 100:+.2f}%  "
              f"VIX {g.vix.mean():4.1f} realized {g.rv21.mean():4.1f}")
    for m in (6, 12):
        g = wk[wk.index >= wk.index.max() - pd.DateOffset(months=m)]
        print(f"  last {m:2d} months: weekly win {(g.pnl5 > 0).mean() * 100:.0f}% avg {g.pnl5.mean() * 100:+.3f}% worst {g.pnl5.min() * 100:+.2f}%")
    # when is the premium richest? by VIX level and by VIX vs its own 1-month average
    x["vix_rel"] = x["vix"] / x["vix"].rolling(21).mean()
    wk = x.iloc[::5].dropna()
    print("  weekly short straddle by VIX vs its 1-month average:")
    for lo, hi in ((0, 0.9), (0.9, 1.0), (1.0, 1.1), (1.1, 9)):
        g = wk[(wk.vix_rel >= lo) & (wk.vix_rel < hi)]
        print(f"    VIX {lo:.1f}-{hi:.1f}x its average: n={len(g)} win {(g.pnl5 > 0).mean() * 100:.0f}% avg {g.pnl5.mean() * 100:+.3f}%")
    return x


def expected_move_fade(h1: pd.DataFrame, daily: dict):
    x = h1[~h1.index.duplicated()].sort_index()
    if x.index.tz is not None:
        x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None)
    vix = daily["VIX"]["Close"].dropna()
    rows = []
    days = [(dd, g) for dd, g in x.groupby(x.index.normalize()) if len(g) >= 6]
    for k in range(1, len(days)):
        dd, g = days[k]
        pc = days[k - 1][1]["Close"].iloc[-1]
        pv = vix[vix.index < dd]
        if pv.empty:
            continue
        em = pv.iloc[-1] / 100 / np.sqrt(252) * pc                 # VIX-implied 1-day move, points
        close = g["Close"].iloc[-1]
        for i in range(1, len(g) - 1):
            t = g.index[i].strftime("%H:%M")
            if not ("11:15" <= t <= "14:15"):
                continue
            c = g["Close"].iloc[i]
            mv = (c - pc) / em
            if abs(mv) >= 1.0:
                e = g["Open"].iloc[i + 1]
                rows.append({"day": dd, "t": t, "mv": mv, "fade_pct": -np.sign(mv) * (close / e - 1) * 100,
                             "day_hi_lo": abs(e - (g["High"].iloc[: i + 1].max() if mv > 0 else g["Low"].iloc[: i + 1].min())) / e * 100})
                break                                             # first time beyond 1x per day
    z = pd.DataFrame(rows)
    print(f"\n== 2. Beyond the VIX-implied move by midday (hourly, {len(days)} days) ==")
    for lo in (1.0, 1.25, 1.5):
        g = z[z["mv"].abs() >= lo]
        mid = g["day"].quantile(0.5) if len(g) else None
        if len(g):
            print(f"  >= {lo:.2f}x implied: {len(g)} days ({len(g) / len(days) * 100:.0f}%), fade to close avg {g.fade_pct.mean() - 0.03:+.3f}% "
                  f"(halves {g[g.day < mid].fade_pct.mean() - 0.03:+.3f}/{g[g.day >= mid].fade_pct.mean() - 0.03:+.3f}), "
                  f"fade wins {(g.fade_pct > 0.03).mean() * 100:.0f}%")
    for s, nm in ((1, "up days"), (-1, "down days")):
        g = z[np.sign(z["mv"]) == s]
        print(f"  {nm}: n={len(g)} fade avg {g.fade_pct.mean() - 0.03:+.3f}% wins {(g.fade_pct > 0.03).mean() * 100:.0f}%")


def expiry_dates(idx: pd.DatetimeIndex) -> set:
    """Weekly Nifty expiry: Thursday until 28 Aug 2025, Tuesday from 1 Sep 2025; a holiday moves it to the day before."""
    days = pd.DatetimeIndex(sorted(set(idx.normalize())))
    out = set()
    for d in pd.date_range(days.min(), days.max(), freq="D"):
        wd = 1 if d >= pd.Timestamp("2025-09-01") else 3
        if d.weekday() != wd:
            continue
        prior = days[days <= d]
        if len(prior) and (d - prior[-1]).days < 5:
            out.add(prior[-1])
    return out


def expiry_pin(daily: dict, h1: pd.DataFrame):
    c = daily["NIFTY"]["Close"].dropna()
    c = c[c.index >= "2019-01-01"]
    exp = expiry_dates(c.index)
    dist = (c - (c / 100).round() * 100).abs()                    # points from the nearest 100 strike
    is_exp = c.index.isin(list(exp))
    print(f"\n== 3. Expiry pin (daily closes since 2019, {is_exp.sum()} expiry days) ==")
    print(f"  distance of the close to the nearest 100 strike: expiry {dist[is_exp].mean():.1f} pts vs other days "
          f"{dist[~is_exp].mean():.1f} pts (no pin = 25); within 15 pts: {(dist[is_exp] <= 15).mean() * 100:.0f}% vs "
          f"{(dist[~is_exp] <= 15).mean() * 100:.0f}%")
    for y in sorted(set(c.index.year)):
        m = c.index.year == y
        print(f"    {y}: expiry {dist[is_exp & m].mean():5.1f}  other {dist[~is_exp & m].mean():5.1f}")
    x = h1[~h1.index.duplicated()].sort_index()
    if x.index.tz is not None:
        x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None)
    rows = []
    for dd, g in x.groupby(x.index.normalize()):
        a = g[g.index.strftime("%H:%M") == "13:15"]
        if a.empty:
            continue
        p0 = a["Open"].iloc[0]
        k = round(p0 / 100) * 100
        rows.append({"day": dd, "exp": dd in exp, "d0": abs(p0 - k), "d1": abs(g["Close"].iloc[-1] - k)})
    z = pd.DataFrame(rows)
    for e, g in z.groupby("exp"):
        print(f"  {'expiry' if e else 'other '} days (hourly, {len(g)}): 13:15 distance to nearest 100 strike {g.d0.mean():.1f} -> close "
              f"{g.d1.mean():.1f} pts; closer at the close on {(g.d1 < g.d0).mean() * 100:.0f}% of days")


if __name__ == "__main__":
    daily = pickle.load(open(sys.argv[1], "rb"))
    h1 = pickle.load(open(sys.argv[2], "rb"))
    vol_premium(daily, "NIFTY")
    expected_move_fade(h1["NIFTY"], daily)
    expiry_pin(daily, h1["NIFTY"])


def iron_fly(d: dict, wing_sd: float = 2.0, name: str = "NIFTY"):
    """Weekly short ATM straddle with bought wings at +-wing_sd weekly SDs (defined risk), priced with Black-Scholes at
    the VIX level (r = 0; real wings cost more because of skew, so this is optimistic on the wings)."""
    from math import erf, exp, log, pi, sqrt

    def N(z):
        return 0.5 * (1 + erf(z / sqrt(2)))

    def bs(S, K, s, T, call):
        d1 = (log(S / K) + 0.5 * s * s * T) / (s * sqrt(T))
        d2 = d1 - s * sqrt(T)
        return S * N(d1) - K * N(d2) if call else K * N(-d2) - S * N(-d1)

    n, v = d[name]["Close"].dropna(), d["VIX"]["Close"].dropna()
    x = pd.DataFrame({"c": n, "vix": v}).dropna()
    rows = []
    for i in range(0, len(x) - 5, 5):
        S, s = x["c"].iloc[i], x["vix"].iloc[i] / 100
        T = 7 / 365
        w = S * s * sqrt(T) * wing_sd
        prem = bs(S, S, s, T, True) + bs(S, S, s, T, False) - bs(S, S + w, s, T, True) - bs(S, S - w, s, T, False)
        mv = abs(x["c"].iloc[i + 5] - S)
        rows.append({"day": x.index[i], "pnl_pct": (prem - min(mv, w)) / S * 100, "max_loss_pct": (w - prem) / S * 100,
                     "prem_pct": prem / S * 100})
    z = pd.DataFrame(rows).set_index("day")
    print(f"\n== 4. Weekly iron fly (wings at {wing_sd:.1f} SD), {name} {z.index.min():%Y}-{z.index.max():%Y} ==")
    print(f"  wins {(z.pnl_pct > 0).mean() * 100:.0f}% of weeks, avg {z.pnl_pct.mean():+.3f}% of index a week, credit "
          f"{z.prem_pct.mean():.2f}%, max loss {z.max_loss_pct.mean():.2f}%, worst week {z.pnl_pct.min():+.2f}%, "
          f"avg / max loss {z.pnl_pct.mean() / z.max_loss_pct.mean():+.2f}")
    for y, g in z.groupby(z.index.year):
        print(f"    {y}: win {(g.pnl_pct > 0).mean() * 100:3.0f}% avg {g.pnl_pct.mean():+.3f}% worst {g.pnl_pct.min():+.2f}%")
    print(f"  option BUYER of the same (retail side): avg {-z.pnl_pct.mean():+.3f}% a week, wins {(z.pnl_pct < 0).mean() * 100:.0f}%")
