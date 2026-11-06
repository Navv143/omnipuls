"""'London Clean Breakout' (gold PDF) on every market and timeframe, as written:
Asian box = high / low of 01:00-07:00 server time (EET/EEST = Europe/Athens). First candle that CLOSES outside the box
in 07:30-10:30 -> trade that way (entry at the next candle's open: a market order right after the close), stop at the box
midpoint, target 1.5R, out at 15:00 server time if neither is hit. One trade a day, weekdays.
Volume filter: the PDF's 800-1500 contracts is broker tick volume; here 'mid volume' = breakout candle volume between the
40th and 80th percentile of the previous 20 days' breakout-window candles (same idea: not quiet, not a news spike).
Also: target 1R / 2R / 3R, and stop at the far side of the box.

Usage: python research/pdf_setups/london_breakout.py <pdf_data.pkl>
"""
import sys

import numpy as np
import pandas as pd

COST = {"NIFTY": 0.03, "BANKNIFTY": 0.03, "BTC": 0.08, "EURUSD": 0.01, "GBPUSD": 0.01, "USDJPY": 0.01, "USDINR": 0.01}
DEF_COST = 0.03     # commodity futures, % a round trip


def trades(df: pd.DataFrame, cost: float, target_r=1.5, stop="mid", vol_filter=False) -> pd.DataFrame:
    d = df.tz_convert("Europe/Athens") if df.index.tz is not None else df.tz_localize("UTC").tz_convert("Europe/Athens")
    d = d[d.index.dayofweek < 5]
    hm = d.index.strftime("%H:%M")
    d = d.assign(hm=hm, day=d.index.normalize())
    win_vol = d[(d.hm >= "07:30") & (d.hm < "10:30")]["Volume"]
    out = []
    for day, g in d.groupby("day"):
        box = g[(g.hm >= "01:00") & (g.hm < "07:00")]
        if len(box) < 3:
            continue
        hi, lo = float(box["High"].max()), float(box["Low"].min())
        mid = (hi + lo) / 2
        sig = g[(g.hm >= "07:30") & (g.hm < "10:30")]
        o, h, l, c, hmv = g["Open"].values, g["High"].values, g["Low"].values, g["Close"].values, g.hm.values
        pos = {ts: i for i, ts in enumerate(g.index)}
        for ts, r in sig.iterrows():
            side = 1 if r["Close"] > hi else -1 if r["Close"] < lo else 0
            if not side:
                continue
            if vol_filter:
                past = win_vol[(win_vol.index < day) & (win_vol.index >= day - pd.Timedelta(days=28))]
                if len(past) < 20 or not (past.quantile(0.4) <= r["Volume"] <= past.quantile(0.8)):
                    break            # the first breakout is the trade; a filtered one means no trade that day
            i = pos[ts] + 1
            if i >= len(g):
                break
            e = float(o[i])
            st = mid if stop == "mid" else (lo if side > 0 else hi)
            risk = side * (e - st)
            if risk <= 0:
                break
            tg = e + side * target_r * risk
            x, why = None, "timeout"
            for j in range(i, len(g)):
                if hmv[j] >= "15:00":
                    x = float(o[j])
                    break
                if (side > 0 and l[j] <= st) or (side < 0 and h[j] >= st):
                    x, why = (min(o[j], st) if side > 0 else max(o[j], st)), "stop"
                    break
                if (side > 0 and h[j] >= tg) or (side < 0 and l[j] <= tg):
                    x, why = (max(o[j], tg) if side > 0 else min(o[j], tg)), "target"
                    break
            if x is None:
                x = float(c[-1])
            gross_r = side * (x - e) / risk
            net_r = gross_r - cost / (risk / e * 100)
            out.append({"day": day, "side": side, "why": why, "r": gross_r, "net_r": net_r,
                        "pct": side * (x / e - 1) * 100 - cost, "risk_pct": risk / e * 100})
            break
    return pd.DataFrame(out)


def summary(t: pd.DataFrame) -> dict:
    if len(t) < 5:
        return {"n": len(t)}
    r = t["net_r"]
    eq = r.cumsum()
    yrs = t["day"].dt.year
    half = t["day"].iloc[len(t) // 2]
    streak = max((len(list(g)) for k, g in __import__("itertools").groupby(r <= 0) if k), default=0)
    return {"n": len(t), "win%": round((t["why"] == "target").mean() * 100), "loss%": round((t["why"] == "stop").mean() * 100),
            "timeout%": round((t["why"] == "timeout").mean() * 100), "net win%": round((r > 0).mean() * 100),
            "avg R": round(t["r"].mean(), 3), "net R": round(r.mean(), 3), "total net R": round(r.sum(), 1),
            "PF": round(r[r > 0].sum() / -r[r < 0].sum(), 2) if (r < 0).any() else np.inf,
            "maxDD R": round((eq - eq.cummax()).min(), 1), "max losses row": streak,
            "h1 R": round(r[t["day"] < half].mean(), 3), "h2 R": round(r[t["day"] >= half].mean(), 3),
            "by year": {int(y): round(z.sum(), 1) for y, z in r.groupby(yrs)} if yrs.nunique() > 1 else "",
            "avg stop %": round(t["risk_pct"].mean(), 3)}


def main(path):
    data = pd.read_pickle(path)
    rows = []
    for (m, tf), df in sorted(data.items()):
        if tf == "2m" or m in ("NIFTY", "BANKNIFTY"):        # no Asian box for Indian indices (closed at night)
            continue
        cost = COST.get(m, DEF_COST)
        for name, kw in (("PDF rule (mid stop, 1.5R)", {}), ("+ mid volume", {"vol_filter": True}),
                         ("1R", {"target_r": 1.0}), ("3R", {"target_r": 3.0}), ("far stop 1.5R", {"stop": "far"})):
            s = summary(trades(df, cost, **kw))
            rows.append({"market": m, "tf": tf, "rule": name, **s})
            if name.startswith("PDF"):
                print(m, tf, s, flush=True)
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    cols = ["market", "tf", "rule", "n", "win%", "loss%", "timeout%", "net R", "total net R", "PF", "maxDD R",
            "max losses row", "h1 R", "h2 R", "by year"]
    print("\n", res[cols].to_string(index=False))
    res.to_csv(path.replace("pdf_data.pkl", "london_breakout_results.csv"), index=False)


if __name__ == "__main__":
    main(sys.argv[1])
