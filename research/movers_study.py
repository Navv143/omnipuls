"""What do the day's big movers look like before and while they move, and do NR5/NR7, box, ATR-squeeze or OBV
setups catch them? Dhan 5-minute bars (research/cache, topped up by fetch_recent.py) and near + next futures OI.

Part A (last month): each session's top 10 gainers and losers (close vs previous close). For every stock-day that
reached +-1% from yesterday's close, measured at the moment it first did: volume vs the same time on the last 10
sessions, net volume (up-candle minus down-candle volume, as a share), futures OI change, ATR, and the daily set-ups
known before the open. Big movers are compared with stocks that reached 1% and then stalled.

Part B (5 years): daily set-ups + an intraday breakout trigger, traded the way an option buyer would need:
entry at the next 5-minute candle's open, stop 1% from entry, exit at the last bar (Dhan stock bars end at 15:10).
Reported: net per trade on shares after 0.12% costs, and the share of trades that reach +2% before the stop
(about +40% on an ATM option) and +3%.
  .venv\\Scripts\\python research\\movers_study.py
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
from momentum_dhan import NSLOT, OUT, slot, to_grid  # noqa: E402

warnings.filterwarnings("ignore")
COST = 0.0012
CACHE = HERE / "cache"
LAST = slot("15:10")  # last 5-minute bar in Dhan's stock data


# ---------------------------------------------------------------- data

def load():
    import dhan as D
    newest = {}
    for f in sorted(glob.glob(str(CACHE / "*_5_1800_*.pkl"))):
        p = Path(f).name.split("_")
        newest[(p[0] + "_" + p[1], int(p[2]))] = f
    ids = {v: k for k, v in D.equity_ids().items() if k in U.FNO_SECTOR_OF}

    def merged(f, sid):
        df = pickle.loads(Path(f).read_bytes())
        r = CACHE / f"recent_{sid}.pkl"
        if r.exists():
            df = pd.concat([df, pickle.loads(r.read_bytes())])
        df.index = pd.DatetimeIndex(df.index).tz_convert("Asia/Kolkata").tz_localize(None) \
            if pd.DatetimeIndex(df.index).tz is not None else df.index
        return df[~df.index.duplicated(keep="last")].sort_index()

    nifty = merged(newest[("IDX_I", 13)], "IDX_13")
    raw = {ids[sid]: merged(f, sid) for (seg, sid), f in newest.items() if seg == "NSE_EQ" and sid in ids}
    oi = {}
    for s in raw:
        f = CACHE / f"oi_{s.replace('&', '_and_')}.pkl"
        if f.exists():
            oi[s] = pickle.loads(f.read_bytes())
    return nifty, raw, oi


def daily_features(g: dict) -> dict:
    """Per day: OHLCV from the 5-minute grid and set-ups known before the open (all shifted by one day)."""
    O, H, L, C, V = g["O"], g["H"], g["L"], g["C"], g["V"]
    Cf = pd.DataFrame(C).ffill(axis=1).values
    has = np.isfinite(C).sum(1) >= 60
    op = O[:, 0]
    hi, lo = np.nanmax(H, 1), np.nanmin(L, 1)
    cl = Cf[:, LAST]
    vol = np.nansum(V, 1)
    d = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": cl, "vol": vol, "has": has})
    d.loc[~d["has"], ["open", "high", "low", "close", "vol"]] = np.nan
    pc = d["close"].shift(1)
    rng = (d["high"] - d["low"])
    tr = pd.concat([rng, (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1) / pc
    f = pd.DataFrame(index=d.index)
    f["prev"] = pc
    f["gap"] = d["open"] / pc - 1
    f["chg"] = d["close"] / pc - 1
    f["atr"] = tr.rolling(14, min_periods=10).mean().shift(1)
    f["atr_ratio"] = (tr.rolling(5).mean() / tr.rolling(20).mean()).shift(1)
    r1 = rng.shift(1)
    f["nr5"] = (r1 <= rng.rolling(5).min().shift(1)) & r1.notna()
    f["nr7"] = (r1 <= rng.rolling(7).min().shift(1)) & r1.notna()
    f["inside"] = (d["high"].shift(1) <= d["high"].shift(2)) & (d["low"].shift(1) >= d["low"].shift(2))
    for n in (10, 20):
        bh, bl = d["high"].rolling(n).max().shift(1), d["low"].rolling(n).min().shift(1)
        f[f"box{n}_hi"], f[f"box{n}_lo"] = bh, bl
        f[f"box{n}_atr"] = (bh - bl) / pc / f["atr"]  # box height in ATRs; random walk ~ sqrt(n)
    sgn = np.sign(d["close"].diff()).fillna(0)
    obv = (sgn * d["vol"].fillna(0)).cumsum()
    f["obv_hi20"] = obv.shift(1) >= obv.rolling(20).max().shift(1)
    f["obv_lo20"] = obv.shift(1) <= obv.rolling(20).min().shift(1)
    f["px_hi20"] = d["close"].shift(1) >= d["close"].rolling(20).max().shift(1)
    f["px_lo20"] = d["close"].shift(1) <= d["close"].rolling(20).min().shift(1)
    f["yhi"], f["ylo"] = d["high"].shift(1), d["low"].shift(1)
    f["ok"] = d["has"] & f["prev"].notna() & f["atr"].notna() & (f["gap"].abs() < 0.2)
    return f


# ---------------------------------------------------------------- part A: last month's movers

def part_a(days, grids, feats, oi, ndays=22):
    rows = []
    for s, g in grids.items():
        f = feats[s]
        C = pd.DataFrame(g["C"]).ffill(axis=1).values
        O, V = g["O"], np.nan_to_num(g["V"])
        cumv = np.cumsum(V, 1)
        avg_cum = pd.DataFrame(np.where(f["ok"].values[:, None], cumv, np.nan)).rolling(10, min_periods=7).mean() \
            .shift(1).values
        updown = np.sign(np.nan_to_num(g["C"] - O))
        netv = np.cumsum(updown * V, 1)
        o = oi.get(s)
        for di in range(len(days) - ndays, len(days)):
            if not f["ok"].iat[di]:
                continue
            prev = f["prev"].iat[di]
            mv = C[di] / prev - 1
            hit = np.where(np.abs(mv) >= 0.01)[0]
            if not len(hit):
                continue
            t1 = hit[0]
            side = np.sign(mv[t1])
            t2 = next((t for t in range(t1, NSLOT) if side * mv[t] >= 0.02), None)
            t3 = next((t for t in range(t1, NSLOT) if side * mv[t] >= 0.03), None)
            r = {"date": days[di], "sym": s, "side": int(side), "chg": f["chg"].iat[di],
                 "t1": t1, "t2": t2, "t3": t3, "gap": f["gap"].iat[di], "atr": f["atr"].iat[di],
                 "atr_ratio": f["atr_ratio"].iat[di],
                 "rvol_t1": cumv[di, t1] / avg_cum[di, t1] if avg_cum[di, t1] > 0 else np.nan,
                 "netvol_t1": side * netv[di, t1] / cumv[di, t1] if cumv[di, t1] > 0 else np.nan,
                 "left_after_t1": side * (C[di, LAST] / C[di, t1] - 1),
                 "nr5": f["nr5"].iat[di], "nr7": f["nr7"].iat[di], "inside": f["inside"].iat[di],
                 "box10_atr": f["box10_atr"].iat[di],
                 "obv_lead": (f["obv_hi20"].iat[di] and not f["px_hi20"].iat[di]) if side > 0 else
                             (f["obv_lo20"].iat[di] and not f["px_lo20"].iat[di]),
                 "broke_yday": (C[di, t1] > f["yhi"].iat[di]) if side > 0 else (C[di, t1] < f["ylo"].iat[di]),
                 "oi_t1": np.nan}
            if o is not None and not o.empty:
                day = days[di]
                ts = day + pd.Timedelta(minutes=555 + 5 * int(t1))
                before = o[o.index < day]
                now = o[(o.index >= day) & (o.index <= ts)]
                if len(before) and len(now) and before["OI"].iloc[-1] > 0:
                    r["oi_t1"] = now["OI"].iloc[-1] / before["OI"].iloc[-1] - 1
            rows.append(r)
    A = pd.DataFrame(rows)
    A["rank_up"] = A.groupby("date")["chg"].rank(ascending=False)
    A["rank_dn"] = A.groupby("date")["chg"].rank(ascending=True)
    A["mover"] = ((A["side"] > 0) & (A["rank_up"] <= 10) & (A["chg"] > 0)) | \
                 ((A["side"] < 0) & (A["rank_dn"] <= 10) & (A["chg"] < 0))
    A["big3"] = A["side"] * A["chg"] >= 0.03
    A["oi_with"] = np.where(A["oi_t1"].notna(), A["oi_t1"] > 0, np.nan)  # positions added while moving = buildup
    return A


def hhmm(t):
    return "" if t is None or pd.isna(t) else f"{(555 + 5 * int(t)) // 60:02d}:{(555 + 5 * int(t)) % 60:02d}"


def report_a(A):
    print(f"\nPART A: {A['date'].nunique()} sessions ({A['date'].min():%d %b} - {A['date'].max():%d %b %Y}); "
          f"{len(A)} stock-days reached +-1% from yesterday's close; {int(A['mover'].sum())} were the day's top-10 "
          f"gainers/losers.")
    m, rest = A[A["mover"]], A[~A["mover"]]
    print("\nWhen did the top-10 movers start? (time first +-1% / +-2% / +-3% from yesterday's close)")
    for col in ("t1", "t2", "t3"):
        x = m[col].dropna()
        q = x.quantile([0.25, 0.5, 0.75]).map(hhmm)
        print(f"  {col[1]}%: reached by {100 * len(x) / len(m):.0f}%; 25% by {q.iloc[0]}, half by {q.iloc[1]}, "
              f"75% by {q.iloc[2]}")
    print(f"  move left after the first 1%: movers {100 * m['left_after_t1'].median():+.2f}% (median), "
          f"stalled {100 * rest['left_after_t1'].median():+.2f}%")
    print("\nMovers vs stocks that reached 1% and stalled (at the moment of the first 1%):")
    rows = []
    for name, fn in [
        ("volume vs usual (median)", lambda x: x["rvol_t1"].median()),
        ("volume 2x+ usual (share)", lambda x: (x["rvol_t1"] >= 2).mean()),
        ("net volume with move (median)", lambda x: x["netvol_t1"].median()),
        ("futures OI added (share, buildup)", lambda x: x["oi_with"].mean()),
        ("OI change % (median)", lambda x: 100 * x["oi_t1"].median()),
        ("ATR % (median)", lambda x: 100 * x["atr"].median()),
        ("ATR5/ATR20 < 0.8 (squeeze, share)", lambda x: (x["atr_ratio"] < 0.8).mean()),
        ("yesterday NR5 (share)", lambda x: x["nr5"].mean()),
        ("yesterday NR7 (share)", lambda x: x["nr7"].mean()),
        ("yesterday inside day (share)", lambda x: x["inside"].mean()),
        ("10-day box <= 3 ATR (tight, share)", lambda x: (x["box10_atr"] <= 3).mean()),
        ("OBV at 20-day extreme before price (share)", lambda x: x["obv_lead"].mean()),
        ("gap same way 1%+ (share)", lambda x: (x["side"] * x["gap"] >= 0.01).mean()),
        ("first 1% before 9:30 (share)", lambda x: (x["t1"] < 3).mean()),
        ("first 1% already beyond yesterday's high/low (share)", lambda x: x["broke_yday"].mean()),
    ]:
        rows.append({"feature": name, "top-10 movers": fn(m), "stalled": fn(rest), "all 1% stocks": fn(A)})
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    print("\nHow often a stock that reached 1% became a top-10 mover, by feature (base "
          f"{100 * A['mover'].mean():.1f}%):")
    rows = []
    for name, mask in [("volume 3x+ usual", A["rvol_t1"] >= 3), ("volume 2-3x", A["rvol_t1"].between(2, 3)),
                       ("volume under 1x", A["rvol_t1"] < 1), ("net volume >= 0.3", A["netvol_t1"] >= 0.3),
                       ("OI added (buildup)", A["oi_with"] == 1), ("OI reduced", A["oi_with"] == 0),
                       ("NR5 yesterday", A["nr5"]), ("NR7 yesterday", A["nr7"]), ("inside day", A["inside"]),
                       ("tight 10-day box", A["box10_atr"] <= 3), ("ATR squeeze", A["atr_ratio"] < 0.8),
                       ("OBV leading", A["obv_lead"] == True),  # noqa: E712
                       ("volume 3x+ & OI added", (A["rvol_t1"] >= 3) & (A["oi_with"] == 1))]:
        x = A[mask.fillna(False).astype(bool)]
        rows.append({"feature": name, "stocks": len(x), "became top-10 %": 100 * x["mover"].mean(),
                     "finished 3%+ %": 100 * x["big3"].mean(),
                     "move left after 1% (median)": 100 * x["left_after_t1"].median()})
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    print("\nToday's (latest session) top movers:")
    d = A["date"].max()
    t = A[(A["date"] == d) & A["mover"]].sort_values("chg", ascending=False)
    t = t.assign(**{"first 1%": t["t1"].map(hhmm), "first 2%": t["t2"].map(hhmm), "first 3%": t["t3"].map(hhmm)})
    print(t[["sym", "chg", "first 1%", "first 2%", "first 3%", "rvol_t1", "netvol_t1", "oi_t1", "nr5", "nr7",
             "box10_atr", "obv_lead"]].round(3).to_string(index=False))


# ---------------------------------------------------------------- part B: set-ups over 5 years

def walk(O, H, L, C, e, side, entry, stop_pct=0.01, last=LAST):
    """Exit at stop or the last bar; also whether +2% / +3% from entry came before the stop."""
    stop = entry * (1 - side * stop_pct)
    t2 = t3 = False
    for t in range(e, last + 1):
        if not np.isfinite(O[t]):
            continue
        if (side > 0 and L[t] <= stop) or (side < 0 and H[t] >= stop):
            px = min(O[t], stop) if side > 0 else max(O[t], stop)
            return side * (px / entry - 1), t2, t3
        fav = (H[t] / entry - 1) if side > 0 else (1 - L[t] / entry)
        t2, t3 = t2 or fav >= 0.02, t3 or fav >= 0.03
    last_px = C[last] if np.isfinite(C[last]) else C[np.where(np.isfinite(C))[0][-1]]
    return side * (last_px / entry - 1), t2, t3


def part_b(days, grids, feats):
    rows = []
    s_from, s_to = slot("09:20"), slot("13:00")
    for s, g in grids.items():
        f = feats[s]
        O, H, L, C, V = g["O"], g["H"], g["L"], g["C"], np.nan_to_num(g["V"])
        cumv = np.cumsum(V, 1)
        avg_cum = pd.DataFrame(np.where(f["ok"].values[:, None], cumv, np.nan)).rolling(10, min_periods=7).mean() \
            .shift(1).values
        for di in np.where(f["ok"].values)[0]:
            base = {k: f[k].iat[di] for k in ("nr5", "nr7", "inside", "box10_atr", "box20_atr", "atr_ratio")}
            base["obv_hi"], base["obv_lo"] = f["obv_hi20"].iat[di], f["obv_lo20"].iat[di]
            base["px_hi"], base["px_lo"] = f["px_hi20"].iat[di], f["px_lo20"].iat[di]
            # triggers: break of yesterday's high/low, and of the 10-day box, by a 5-minute close
            for trig, hi_lvl, lo_lvl in (("yday", f["yhi"].iat[di], f["ylo"].iat[di]),
                                         ("box10", f["box10_hi"].iat[di], f["box10_lo"].iat[di])):
                if not (np.isfinite(hi_lvl) and np.isfinite(lo_lvl)):
                    continue
                op = O[di, 0]
                for side, lvl in ((1, hi_lvl), (-1, lo_lvl)):
                    if not np.isfinite(op) or side * (op - lvl) >= 0:  # opened beyond the level: no breakout
                        continue
                    cl = C[di, s_from:s_to]
                    cross = np.where(side * (cl - lvl) > 0)[0]
                    if not len(cross):
                        continue
                    tb = s_from + cross[0]
                    e = tb + 1
                    if e > LAST or not np.isfinite(O[di, e]):
                        continue
                    entry = O[di, e]
                    net, r2, r3 = walk(O[di], H[di], L[di], C[di], e, side, entry)
                    rows.append({"date": days[di], "sym": s, "trigger": trig, "side": side, "time": tb,
                                 "rvol": cumv[di, tb] / avg_cum[di, tb] if avg_cum[di, tb] > 0 else np.nan,
                                 "net": net - COST, "r2": r2, "r3": r3, **base})
    return pd.DataFrame(rows)


def report_b(B):
    mid = B["date"].quantile(0.5)

    def summ(x, label):
        return {"setup": label, "trades": len(x), "per day": round(len(x) / B["date"].nunique(), 2),
                "net %": 100 * x["net"].mean(), "+2% first %": 100 * x["r2"].mean(),
                "+3% first %": 100 * x["r3"].mean(), "win %": 100 * (x["net"] > 0).mean(),
                "H1 %": 100 * x.loc[x["date"] < mid, "net"].mean(),
                "H2 %": 100 * x.loc[x["date"] >= mid, "net"].mean(),
                "2025-26 %": 100 * x.loc[x["date"].dt.year >= 2025, "net"].mean(),
                "t": x["net"].mean() / x["net"].std() * np.sqrt(len(x)) if len(x) > 2 else np.nan}

    print(f"\nPART B: {B['sym'].nunique()} stocks, {B['date'].nunique()} sessions; breakout by a 5-minute close "
          "between 9:20 and 13:00, entry next candle, 1% stop, exit at the last bar, 0.12% costs.")
    rows = []
    for trig, x in B.groupby("trigger"):
        nm = {"yday": "yesterday's high/low break", "box10": "10-day box break"}[trig]
        sq = x["atr_ratio"] < 0.8
        tight = x["box10_atr"] <= 3
        obv = ((x["side"] > 0) & x["obv_hi"] & ~x["px_hi"]) | ((x["side"] < 0) & x["obv_lo"] & ~x["px_lo"])
        v2 = x["rvol"] >= 2
        for label, mask in [("all", None), ("NR5 yesterday", x["nr5"]), ("NR7 yesterday", x["nr7"]),
                            ("inside day", x["inside"]), ("tight 10-day box (<=3 ATR)", tight),
                            ("ATR squeeze (5/20 < 0.8)", sq), ("OBV leading price", obv),
                            ("volume 2x+ at break", v2), ("NR7 & volume 2x+", x["nr7"] & v2),
                            ("tight box & volume 2x+", tight & v2), ("squeeze & volume 2x+", sq & v2),
                            ("tight box & squeeze & vol 2x+", tight & sq & v2),
                            ("OBV leading & volume 2x+", obv & v2),
                            ("break before 10:30 & vol 2x+", (x["time"] < slot("10:30")) & v2)]:
            y = x if mask is None else x[mask.fillna(False).astype(bool)]
            for side_name, z in (("both", y), ("buy", y[y["side"] > 0]), ("short", y[y["side"] < 0])):
                if len(z) >= 100:
                    rows.append(summ(z, f"{nm} | {label} | {side_name}"))
    T = pd.DataFrame(rows)
    T.to_csv(OUT / "setups_breakouts.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 70)
    print(T[T["setup"].str.endswith("| both")].round(3).to_string(index=False))
    good = T[(T["H1 %"] > 0) & (T["H2 %"] > 0) & (T["2025-26 %"] > 0) & (T["t"] >= 2.5)]
    print(f"\n{len(T)} versions; positive in both halves and in 2025-26 with t >= 2.5: {len(good)}")
    if len(good):
        print(good.sort_values("2025-26 %", ascending=False).round(3).to_string(index=False))


if __name__ == "__main__":
    nifty, raw, oi = load()
    idx = nifty.index
    days = pd.DatetimeIndex(sorted(set(idx.normalize())))
    full = np.isfinite(to_grid(nifty, days)["C"]).sum(1) >= 60
    days = days[full]
    grids, feats = {}, {}
    for s, df in raw.items():
        g = to_grid(df, days)
        if g is not None:
            grids[s], feats[s] = g, daily_features(g)
    print(f"{len(grids)} stocks, {len(days)} sessions to {days[-1]:%d %b %Y}; OI for {len(oi)} stocks")
    A = part_a(days, grids, feats, oi)
    A.to_csv(OUT / "movers_last_month.csv", index=False)
    report_a(A)
    B = part_b(days, grids, feats)
    B.to_csv(OUT / "setups_trades.csv.gz", index=False, compression="gzip")
    report_b(B)
