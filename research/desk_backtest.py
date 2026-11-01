"""Test the Trading Desk's readings on history: do the CE / PE focus lists and the market verdict make money?

Dhan 5-minute bars, 206 F&O stocks + Nifty, Nov 2021 - Oct 2026 (cached by momentum_dhan.py). Futures OI has no
history (expired contracts), so the OI parts of the desk (buildup, sector futures money, smart-money pick) are left
out; everything else is rebuilt as the desk computes it, with information known at the check time only.

Per stock at 10:00 / 10:30 / 11:00 (signed: + bullish, - bearish):
  activity  volume since the open vs the same time on the last 20 sessions: 1.5x+ -> 1 point, 3x+ -> 2 points,
            in the direction of the move from yesterday's close (needs a 1%+ move)
  flow      share of turnover buying (each candle's turnover split by where it closed in its range): 55%+ / 45%-
  breakout  yesterday's high (up) / low (down) broken by a 5-minute close
  sector    the stock's F&O sector average move the same way, 0.5%+
  radar     breakout + sector + volume 1.5x (the TradeFinder-pattern shortlist)
Focus = 3+ points agreeing with the move. Trade: next candle's open, 1% stop, exit 15:20, 0.12% costs; also an
at-the-money option proxy (0.5 x move - 1% of premium-equivalent cost, theta ignored: an upper bound for buyers).
Baselines: every 1%+ mover at that time, and movers with 0-2 points.

Verdict at 10:15 / 11:00 from the parts with history (breadth, market buy share, Nifty from its open), as the desk
weighs them; outcome = Nifty from the check time to 15:20, in index %, and a Nifty futures trade in the verdict's way.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\desk_backtest.py
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
from bigbars_dhan import load_cache  # noqa: E402
from momentum_dhan import NSLOT, day_basics, ffill_rows, slot, to_grid  # noqa: E402

warnings.filterwarnings("ignore")
COST = 0.0012
STOP = 0.01
EXIT = slot("15:20")
CHECKS = ["10:00", "10:30", "11:00"]


def naive(df):
    i = pd.DatetimeIndex(df.index)
    df = df.copy()
    df.index = i.tz_convert("Asia/Kolkata").tz_localize(None) if i.tz is not None else i
    return df


def main():
    nifty, raw = load_cache()
    nifty = naive(nifty)
    days = pd.DatetimeIndex(sorted(set(nifty.index.normalize())))
    NG = to_grid(nifty, days)
    NC = ffill_rows(NG["C"])
    syms, G, B = [], {}, {}
    for s, df in raw.items():
        g = to_grid(naive(df), days)
        if g is None:
            continue
        b = day_basics(g)
        syms.append(s)
        G[s], B[s] = g, b
    n_d = len(days)
    sec_of = pd.Series(U.FNO_SECTOR_OF).reindex(syms).fillna("Other").to_numpy()
    # per stock arrays: change from yesterday at each slot, cumulative volume, buy share, yesterday high/low
    CHG, CUMV, AVGV, BUY, PDH, PDL, C = {}, {}, {}, {}, {}, {}, {}
    for s in syms:
        g, b = G[s], B[s]
        c = ffill_rows(g["C"])
        C[s] = c
        CHG[s] = c / b["prev"][:, None] - 1
        v = np.nan_to_num(g["V"])
        cv = np.cumsum(v, 1)
        CUMV[s] = cv
        AVGV[s] = pd.DataFrame(np.where(b["ok"][:, None], cv, np.nan)).rolling(20, min_periods=12).mean().shift(1).values
        rng = g["H"] - g["L"]
        press = np.where(rng > 0, (g["C"] - g["O"]) / np.where(rng > 0, rng, 1), 0.0)
        turn = v * np.nan_to_num(g["C"])
        inflow = np.cumsum(turn * (1 + np.nan_to_num(press)) / 2, 1)
        tot = np.cumsum(turn, 1)
        BUY[s] = np.where(tot > 0, inflow / np.where(tot > 0, tot, 1), np.nan)
        hi, lo = np.nanmax(g["H"], 1), np.nanmin(g["L"], 1)
        PDH[s], PDL[s] = np.r_[np.nan, hi[:-1]], np.r_[np.nan, lo[:-1]]
    rows, vrows = [], []
    for ck in CHECKS + ["10:15"]:
        k = slot(ck)  # bars before slot k are known; entry at slot k's open
        chg = np.column_stack([CHG[s][:, k - 1] for s in syms])  # days x stocks
        sec_mv = pd.DataFrame(chg.T).groupby(sec_of).transform("mean").to_numpy().T
        if ck == "10:15":
            pass
        else:
            for j, s in enumerate(syms):
                g, b = G[s], B[s]
                ok = b["ok"]
                for di in np.where(ok & (np.abs(chg[:, j]) >= 0.01))[0]:
                    side = 1 if chg[di, j] > 0 else -1
                    e = g["O"][di, k]
                    if not np.isfinite(e):
                        continue
                    pts, why = 0, []
                    rv = CUMV[s][di, k - 1] / AVGV[s][di, k - 1] if AVGV[s][di, k - 1] > 0 else np.nan
                    if np.isfinite(rv) and rv >= 1.5:
                        pts += 2 if rv >= 3 else 1
                        why.append("vol")
                    bs = BUY[s][di, k - 1]
                    if np.isfinite(bs) and (bs >= 0.55 if side > 0 else bs <= 0.45):
                        pts += 1
                        why.append("flow")
                    closes = g["C"][di, :k]
                    brk = np.nanmax(closes) > PDH[s][di] if side > 0 else np.nanmin(closes) < PDL[s][di]
                    if brk:
                        pts += 1
                        why.append("break")
                    sec_ok = sec_of[j] != "Other" and side * sec_mv[di, j] >= 0.005
                    if sec_ok:
                        pts += 1
                        why.append("sector")
                    if brk and sec_ok and np.isfinite(rv) and rv >= 1.5:
                        pts += 1
                        why.append("radar")
                    # 1% stop then 15:20
                    sp = e * (1 - side * STOP)
                    out = side * ((g["O"][di, EXIT] if np.isfinite(g["O"][di, EXIT]) else C[s][di, EXIT - 1]) / e - 1)
                    for t in range(k, EXIT):
                        lo_, hi_ = g["L"][di, t], g["H"][di, t]
                        if (side > 0 and lo_ <= sp) or (side < 0 and hi_ >= sp):
                            o_ = g["O"][di, t]
                            f = o_ if ((side > 0 and o_ < sp) or (side < 0 and o_ > sp)) else sp
                            out = side * (f / e - 1)
                            break
                    rows.append((days[di], s, ck, side, pts, "+".join(why), out))
        # verdict pieces at this time (market level)
        ok_all = np.column_stack([B[s]["ok"] for s in syms])
        up = ((chg > 0) & ok_all).sum(1)
        dn = ((chg < 0) & ok_all).sum(1)
        tin = sum(np.nan_to_num(BUY[s][:, k - 1]) * np.nan_to_num(CUMV[s][:, k - 1]) for s in syms)
        ttot = sum(np.nan_to_num(CUMV[s][:, k - 1]) for s in syms)
        nfo = NC[:, k - 1] / NG["O"][:, 0] - 1
        nifty_exit = (NG["O"][:, EXIT] if True else None)
        n_out = np.where(np.isfinite(NG["O"][:, EXIT]), NG["O"][:, EXIT], NC[:, EXIT - 1]) / NG["O"][:, k] - 1
        for di in range(n_d):
            if up[di] + dn[di] < 100 or not np.isfinite(n_out[di]) or not np.isfinite(nfo[di]):
                continue
            br = (up[di] - dn[di]) / (up[di] + dn[di])
            bshare = tin[di] / ttot[di] if ttot[di] > 0 else np.nan
            parts = [(0.20, np.clip(br / 0.5, -1, 1)), (0.15, np.clip((bshare * 100 - 50) / 5, -1, 1)),
                     (0.15, np.clip(nfo[di] / 0.006, -1, 1))]
            score = 100 * sum(w * x for w, x in parts) / sum(w for w, _ in parts)
            vrows.append((days[di], ck, score, n_out[di]))
    T = pd.DataFrame(rows, columns=["date", "sym", "check", "side", "pts", "why", "ret"])
    V = pd.DataFrame(vrows, columns=["date", "check", "score", "nifty_rest"])
    T["net"] = T["ret"] - COST
    T["opt"] = 0.5 * T["ret"] - 0.01 * 0.5  # premium-equivalent cost ~1% of an ATM premium at delta 0.5 (no theta)
    T.to_csv(HERE / "results" / "desk_trades.csv.gz", index=False)
    mid = T["date"].sort_values().iloc[len(T) // 2]
    print(f"{len(T)} stock signals (1%+ movers at {', '.join(CHECKS)}), {T['date'].nunique()} days, split {mid:%d %b %Y}")

    def summ(x, label):
        yr = x.groupby(x["date"].dt.year)["net"].mean()
        d = x.groupby("date")["net"].mean()
        return {"set": label, "trades": len(x), "per day": round(len(x) / max(x['date'].nunique(), 1), 1),
                "net %": round(100 * x["net"].mean(), 3), "win %": round(100 * (x["net"] > 0).mean(), 1),
                "1st half": round(100 * x.loc[x["date"] < mid, "net"].mean(), 3),
                "2nd half": round(100 * x.loc[x["date"] >= mid, "net"].mean(), 3),
                "2025-26": round(100 * x.loc[x["date"] >= "2025-01-01", "net"].mean(), 3),
                "yrs +": f"{int((yr > 0).sum())}/{len(yr)}",
                "day-book t": round(d.mean() / (d.std() / np.sqrt(len(d))), 2) if len(d) > 2 else np.nan}

    res = []
    for ck in CHECKS:
        x = T[T["check"] == ck]
        res.append(summ(x, f"{ck} all 1%+ movers (baseline)"))
        res.append(summ(x[x["pts"] <= 2], f"{ck} 0-2 points"))
        res.append(summ(x[x["pts"] >= 3], f"{ck} FOCUS 3+ points"))
        res.append(summ(x[x["pts"] >= 4], f"{ck} 4+ points"))
        res.append(summ(x[(x["pts"] >= 3) & (x["side"] > 0)], f"{ck} FOCUS CE side"))
        res.append(summ(x[(x["pts"] >= 3) & (x["side"] < 0)], f"{ck} FOCUS PE side"))
        top = x[x["pts"] >= 3].sort_values(["date", "pts"], ascending=[True, False]).groupby("date").head(3)
        res.append(summ(top, f"{ck} FOCUS top 3 a day"))
    R = pd.DataFrame(res)
    pd.set_option("display.width", 250)
    print("\nStock focus lists (shares, 1% stop, exit 15:20, after 0.12% costs; % per trade):")
    print(R.to_string(index=False))
    for ck in CHECKS:
        x = T[(T["check"] == ck) & (T["pts"] >= 3)]
        print(f"  {ck} focus as ATM option proxy (no time decay, so an upper bound): "
              f"{100 * x['opt'].mean():+.3f}% of the index-equivalent per trade")
    print("\nEach reading alone (10:30, among 1%+ movers):")
    x = T[T["check"] == "10:30"]
    for w in ("vol", "flow", "break", "sector", "radar"):
        has = x["why"].str.contains(w)
        print(f"  {w:7s} with: {100 * x.loc[has, 'net'].mean():+.3f}% ({has.sum()})   without: "
              f"{100 * x.loc[~has, 'net'].mean():+.3f}% ({(~has).sum()})")
    print("\nMarket verdict (breadth + buy share + Nifty from open) vs Nifty for the rest of the day:")
    vr = []
    for ck in ("10:15", "11:00"):
        v = V[V["check"] == ck]
        for lo, hi, lab in ((-101, -20, "Bearish (<= -20)"), (-20, 20, "Neutral"), (20, 101, "Bullish (>= 20)"),
                            (-101, -55, "Strong bearish"), (55, 101, "Strong bullish")):
            m = v[(v["score"] > lo) & (v["score"] <= hi)] if lo > -101 else v[v["score"] <= hi]
            if hi == 101:
                m = v[v["score"] > lo]
            sgn = 1 if lo >= 20 else (-1 if hi <= -20 else 0)
            trade = sgn * m["nifty_rest"] - 0.0003 if sgn else pd.Series(dtype=float)
            vr.append({"check": ck, "verdict": lab, "days": len(m),
                       "Nifty rest of day %": round(100 * m["nifty_rest"].mean(), 3),
                       "same way %": round(100 * ((np.sign(m["nifty_rest"]) == sgn).mean()), 1) if sgn else np.nan,
                       "futures trade net %": round(100 * trade.mean(), 3) if sgn else np.nan,
                       "2025-26 net %": round(100 * trade[m["date"] >= "2025-01-01"].mean(), 3) if sgn else np.nan})
    print(pd.DataFrame(vr).to_string(index=False))


if __name__ == "__main__":
    main()
