"""Dr. Devendra's 7 setups (Red Bar PDF) on Indian indices, F&O stocks and MCX commodities, on several timeframes.
Rules written down before testing (the PDF leaves some details open; choices noted):
  S1 Opening mean: first candle's 0.44 / 0.56 levels. After a close beyond the first candle (breakout), wait for the retest:
     a candle that touches the 0.56 (long) / 0.44 (short) level and closes back on the breakout side -> enter; stop at the
     other level (0.44 / 0.56). A close through the far level first cancels. Entries until 11:30.
  S2 Red Bar POB: the first red candle after the first candle (until 10:15); POB = its midpoint. Close below the red bar's
     low -> short; close above its high -> long; stop at POB. Entries until 11:30.
  S3 30 EMA pullback: price stretched >= 1.5 ATR(14) from the 30 EMA in the last 12 candles, then a candle touches the EMA
     and closes on the trend side -> enter with the trend; stop 1 ATR beyond the EMA. 9:45-14:30.
  S3f 30 EMA fade: close >= 2.5 ATR away from the 30 EMA -> fade, target the EMA, stop 1 ATR beyond the candle. 9:45-14:30.
  S4 Channel 11:30-12:00: close beyond its high / low in 12:00-12:15 -> enter; stop at the channel middle.
  S5 Afternoon range 12:00-12:45: close beyond the range in 12:45-14:30 -> enter; stop at the 50% line; after a stop-out
     the opposite break may be taken (the PDF's 'flip on a fake breakout').
  S6 CPR filter (previous session's pivot range): longs only above the CPR, shorts only below.
  S7 previous session's last 15 minutes (the 3:15 PM candle) box: longs only above it, shorts only below.
Entry at the next candle's open after the signal close, stop checked first, target 3R (the PDF's 1:3; also 1.5R), out at
15:20 (MCX: 23:20). Costs a round trip: index 0.03%, stocks 0.12%, commodities 0.03%. One trade per setup per direction
a day (S1-S4: one a day). Results in R after costs, and in % of the underlying.

Usage: python research/pdf_setups/redbar.py <pdf_data.pkl> <fno60_new.pkl> <yahoo1h.pkl>
"""
import pickle
import sys

import numpy as np
import pandas as pd

SESS = {"IN": ("09:15", "15:20", "15:15"), "MCX": ("09:00", "23:20", "23:15")}   # open, exit, last-15-min candle


def ist(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    return d[~d.index.duplicated(keep="last")].sort_index()


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def atr(d, n=14):
    pc = d["Close"].shift()
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def run_market(df, kind, cost, targets=(3.0, 1.5)):
    """All setup trades for one market/timeframe: rows with setup, day, side, filters, R per target."""
    op, ex, last = SESS[kind]
    d = ist(df)
    if kind == "MCX":
        d = d[(d.index.strftime("%H:%M") >= op) & (d.index.strftime("%H:%M") <= "23:30") & (d.index.dayofweek < 5)]
    else:
        d = d[(d.index.strftime("%H:%M") >= op) & (d.index.strftime("%H:%M") < "15:30")]
    if len(d) < 50:
        return []
    d = d.assign(e30=ema(d["Close"], 30), atr=atr(d))
    days = sorted(set(d.index.normalize()))
    out, prev = [], None
    for day in days:
        g = d[d.index.normalize() == day]
        if len(g) < 6:
            prev = g
            continue
        hm = g.index.strftime("%H:%M").values
        o, h, l, c = (g[k].values for k in ("Open", "High", "Low", "Close"))
        e30, at = g["e30"].values, g["atr"].values
        n = len(g)
        # S6 / S7 levels from the previous session
        cpr = box = None
        if prev is not None and len(prev):
            H, L, C = prev["High"].max(), prev["Low"].min(), prev["Close"].iloc[-1]
            P, BC = (H + L + C) / 3, (H + L) / 2
            cpr = (min(BC, 2 * P - BC), max(BC, 2 * P - BC))
            lb = prev[prev.index.strftime("%H:%M") >= last]
            if len(lb):
                box = (lb["Low"].min(), lb["High"].max())
        prev = g

        def take(setup, i_sig, side, stop, target_px=None):
            i = i_sig + 1
            if i >= n or hm[i] >= ex:
                return
            e = float(o[i])
            risk = side * (e - stop)
            if risk <= 0:
                return
            rec = {"setup": setup, "day": day, "time": hm[i_sig], "side": side, "risk_pct": risk / e * 100,
                   "cpr_ok": cpr is None or (e > cpr[1] if side > 0 else e < cpr[0]),
                   "box_ok": box is None or (e > box[1] if side > 0 else e < box[0])}
            for tr in (targets if target_px is None else ("ema",)):
                tg = target_px if target_px is not None else e + side * tr * risk
                x = None
                for j in range(i, n):
                    if hm[j] >= ex:
                        x = float(o[j])
                        break
                    if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
                        x = min(o[j], stop) if side > 0 else max(o[j], stop)
                        break
                    if (side > 0 and h[j] >= tg) or (side < 0 and l[j] <= tg):
                        x = max(o[j], tg) if side > 0 else min(o[j], tg)
                        break
                if x is None:
                    x = float(c[-1])
                k = "ema" if target_px is not None else tr
                rec[f"R_{k}"] = side * (x - e) / risk - cost / (risk / e * 100)
                rec[f"pct_{k}"] = side * (x / e - 1) * 100 - cost
            out.append(rec)
            return True

        # S1 opening mean
        H1, L1 = h[0], l[0]
        a, b = L1 + 0.44 * (H1 - L1), L1 + 0.56 * (H1 - L1)
        brk = 0
        for i in range(1, n):
            if hm[i] > "11:30":
                break
            if brk == 0:
                brk = 1 if c[i] > H1 else -1 if c[i] < L1 else 0
                continue
            if (brk > 0 and c[i] < a) or (brk < 0 and c[i] > b):
                break
            if brk > 0 and l[i] <= b and c[i] > b:
                take("S1 opening mean", i, 1, a)
                break
            if brk < 0 and h[i] >= a and c[i] < a:
                take("S1 opening mean", i, -1, b)
                break
        # S2 red bar POB
        rb = next((i for i in range(1, n) if hm[i] <= "10:15" and c[i] < o[i]), None)
        if rb is not None:
            pob = (h[rb] + l[rb]) / 2
            for i in range(rb + 1, n):
                if hm[i] > "11:30":
                    break
                if c[i] < l[rb]:
                    take("S2 red bar POB", i, -1, pob)
                    break
                if c[i] > h[rb]:
                    take("S2 red bar POB", i, 1, pob)
                    break
        # S3 / S3f 30 EMA (needs the EMA / ATR history, carried over days)
        done3 = done3f = False
        for i in range(1, n):
            if hm[i] < "09:45" or hm[i] > "14:30" or np.isnan(at[i]) or at[i] <= 0:
                continue
            lo_i = max(0, i - 12)
            dist = (c[lo_i:i] - e30[lo_i:i]) / at[i]
            if not done3 and len(dist):
                if dist.max() >= 1.5 and l[i] <= e30[i] < c[i] and c[i] > e30[i]:
                    done3 = take("S3 30EMA pullback", i, 1, e30[i] - at[i]) or True
                elif dist.min() <= -1.5 and h[i] >= e30[i] > c[i]:
                    done3 = take("S3 30EMA pullback", i, -1, e30[i] + at[i]) or True
            if not done3f:
                z = (c[i] - e30[i]) / at[i]
                if z >= 2.5:
                    done3f = take("S3f 30EMA fade", i, -1, h[i] + at[i], target_px=e30[i]) or True
                elif z <= -2.5:
                    done3f = take("S3f 30EMA fade", i, 1, l[i] - at[i], target_px=e30[i]) or True
        # S4 channel 11:30-12:00
        ch = [i for i in range(n) if "11:30" <= hm[i] < "12:00"]
        if ch:
            chh, chl = h[ch].max(), l[ch].min()
            for i in range(ch[-1] + 1, n):
                if hm[i] > "12:15":
                    break
                if c[i] > chh:
                    take("S4 channel 12:00", i, 1, (chh + chl) / 2)
                    break
                if c[i] < chl:
                    take("S4 channel 12:00", i, -1, (chh + chl) / 2)
                    break
        # S5 afternoon range 12:00-12:45, 50% stop, flip allowed (one per direction)
        rg = [i for i in range(n) if "12:00" <= hm[i] < "12:45"]
        if rg:
            rh, rl = h[rg].max(), l[rg].min()
            mid = (rh + rl) / 2
            used = set()
            for i in range(rg[-1] + 1, n):
                if hm[i] > "14:30" or len(used) == 2:
                    break
                if c[i] > rh and 1 not in used:
                    take("S5 afternoon 50%", i, 1, mid)
                    used.add(1)
                elif c[i] < rl and -1 not in used:
                    take("S5 afternoon 50%", i, -1, mid)
                    used.add(-1)
    return out


def stat(t, col):
    r = t[col].dropna()
    if len(r) < 8:
        return None
    half = t["day"].sort_values().iloc[len(t) // 2]
    h1, h2 = r[t["day"] < half].mean(), r[t["day"] >= half].mean()
    eq = r.cumsum()
    return {"n": len(r), "win%": round((r > 0).mean() * 100), "net R": round(r.mean(), 3),
            "t": round(r.mean() / r.std() * np.sqrt(len(r)), 2) if r.std() else np.nan, "total R": round(r.sum(), 1),
            "h1": round(h1, 3), "h2": round(h2, 3), "maxDD R": round((eq - eq.cummax()).min(), 1),
            "avg %": round(t[col.replace("R_", "pct_")].mean(), 3), "stop %": round(t["risk_pct"].mean(), 3)}


def main(argv):
    data = pd.read_pickle(argv[1])
    stocks, _ = pickle.load(open(argv[2], "rb"))
    y1h = pd.read_pickle(argv[3])
    jobs = []      # (group, tf, kind, cost, {name: df})
    for tf in ("2m", "5m", "15m", "1h"):
        jobs.append(("NIFTY", tf, "IN", 0.03, {"NIFTY": data[("NIFTY", tf)]}))
        jobs.append(("BANKNIFTY", tf, "IN", 0.03, {"BANKNIFTY": data[("BANKNIFTY", tf)]}))
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    st5 = {s: ist(df).dropna(subset=["Close"]) for s, df in stocks.items() if df is not None and len(df)}
    jobs.append(("F&O STOCKS", "5m", "IN", 0.12, st5))
    jobs.append(("F&O STOCKS", "15m", "IN", 0.12, {s: df.resample("15min", offset="15min").agg(agg).dropna(subset=["Close"])
                                                   for s, df in st5.items()}))
    jobs.append(("F&O STOCKS", "1h", "IN", 0.12, {s: df for s, df in y1h.items()
                                                  if s not in ("NIFTY", "BANKNIFTY") and len(df)}))
    for tf in ("5m", "15m", "1h"):
        jobs.append(("MCX (COMEX/NYMEX)", tf, "MCX", 0.03, {m: data[(m, tf)] for m in ("GOLD", "SILVER", "CRUDE", "NATGAS")}))
    rows, alltr = [], []
    for grp, tf, kind, cost, dfs in jobs:
        tr = []
        for name, df in dfs.items():
            for r in run_market(df, kind, cost):
                r["market"] = name
                tr.append(r)
        t = pd.DataFrame(tr)
        if t.empty:
            continue
        t["group"], t["tf"] = grp, tf
        alltr.append(t)
        for s, z in t.groupby("setup"):
            for filt, m in (("none", slice(None)), ("CPR", z["cpr_ok"]), ("3:15 box", z["box_ok"]),
                            ("CPR + box", z["cpr_ok"] & z["box_ok"])):
                zz = z[m] if filt != "none" else z
                for col in ([c for c in ("R_3.0", "R_1.5") if c in zz] if "fade" not in s else ["R_ema"]):
                    st = stat(zz, col)
                    if st:
                        rows.append({"group": grp, "tf": tf, "setup": s, "filter": filt,
                                     "target": col.replace("R_", "").replace("3.0", "3R").replace("1.5", "1.5R"), **st})
        print(grp, tf, len(t), "trades", flush=True)
    res = pd.DataFrame(rows)
    out = argv[1].replace("pdf_data.pkl", "redbar_results.csv")
    res.to_csv(out, index=False)
    pd.concat(alltr).to_pickle(argv[1].replace("pdf_data.pkl", "redbar_trades.pkl"))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 1000)
    print(res[(res["filter"] == "none") & (res["target"].isin(["3R", "ema"]))].to_string(index=False))


if __name__ == "__main__":
    main(sys.argv)
