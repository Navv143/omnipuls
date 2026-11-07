"""Candle-breakout map: for every candle of the day on 5 / 15 / 30 / 60-minute charts, what happens when price later
breaks its HIGH (long) or its LOW (short)?

Entry = at the candle's high / low the first time a later 5-minute candle trades through it (a stop order; a gap
through fills at that candle's open); if one 5-minute candle trades through both sides, the break is skipped as
ambiguous. Measured from the entry, until the exit time (Indian indices 15:15; gold / BTC 4 hours):
  pts_end   points at the exit time (no stop)
  MFE / MAE best / worst points along the way
  trade     stop at the other side of the reference candle, target 1x / 2x the candle's range, else the exit time
Per (timeframe, candle time, direction): how often it breaks, average points, % reaching 1x / 2x range, false-break %
(stop hit), trade result in points and in R (R = candle range) gross and after costs, both halves of the period.

Usage: python research/candle_breakouts.py <scratchpad dir>
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


def prep(df, tz=None):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx if idx.tz is None else idx.tz_convert(tz or "UTC").tz_localize(None)
    d = d[d.index.second == 0]
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def breaks(m5: pd.DataFrame, tf: int, session_start: str, exit_after: str | int, cost_pct: float,
           window: tuple[str, str] | None = None) -> pd.DataFrame:
    """m5: 5-minute bars (one market). tf: reference candle minutes. exit_after: 'HH:MM' same day, or hours (int)."""
    rows = []
    off = pd.Timedelta(hours=int(session_start[:2]), minutes=int(session_start[3:]))
    for day, z in m5.groupby(m5.index.normalize()):
        if len(z) < 5:
            continue
        ref = z.resample(f"{tf}min", origin=day + off).agg(AGG).dropna(subset=["Close"])
        ref = ref[ref.index >= day + off]
        o, h, l, c = (z[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
        ts = z.index
        for t0, r in ref.iterrows():
            hm = t0.strftime("%H:%M")
            if window and not (window[0] <= hm <= window[1]):
                continue
            t_close = t0 + pd.Timedelta(minutes=tf)
            end = day + pd.Timedelta(hours=int(exit_after[:2]), minutes=int(exit_after[3:])) if isinstance(exit_after, str) \
                else t_close + pd.Timedelta(hours=exit_after)
            if t_close >= end:
                continue
            hi, lo = float(r["High"]), float(r["Low"])
            rng = hi - lo
            if rng <= 0:
                continue
            i0 = np.searchsorted(ts.values, np.datetime64(t_close))
            i1 = np.searchsorted(ts.values, np.datetime64(end))
            if i0 >= i1:
                continue
            side, e, k = 0, None, None
            for j in range(i0, i1):
                up, dn = h[j] >= hi + 1e-9 * hi, l[j] <= lo - 1e-9 * lo
                if up and dn:
                    side = 9
                    break
                if up:
                    side, e, k = 1, max(o[j], hi), j
                    break
                if dn:
                    side, e, k = -1, min(o[j], lo), j
                    break
            if side in (0, 9):
                continue
            stop = lo if side > 0 else hi
            seg_h, seg_l = h[k:i1], l[k:i1]
            mfe = (seg_h.max() - e) if side > 0 else (e - seg_l.min())
            mae = (e - seg_l.min()) if side > 0 else (seg_h.max() - e)
            ex_end = o[i1] if i1 < len(o) and ts[i1] == end else c[i1 - 1]
            pts_end = side * (ex_end - e)
            res = {}
            for mult in (1, 2):
                tg = e + side * mult * rng
                x = None
                for j in range(k, i1):
                    # entry candle: the stop can be hit inside it too (conservative: stop first)
                    if (l[j] <= stop) if side > 0 else (h[j] >= stop):
                        x = stop if j > k or True else stop
                        break
                    if (h[j] >= tg) if side > 0 else (l[j] <= tg):
                        x = tg
                        break
                if x is None:
                    x = ex_end
                res[mult] = side * (x - e)
            rows.append({"day": day, "tf": tf, "time": hm, "side": side, "range": rng, "entry": e,
                         "pts_end": pts_end, "mfe": mfe, "mae": mae, "hit1": mfe >= rng, "hit2": mfe >= 2 * rng,
                         "false": mae >= rng + (e - hi if side > 0 else lo - e),
                         "t1": res[1], "t2": res[2], "cost_pts": e * cost_pct / 100})
    return pd.DataFrame(rows)


def table(b: pd.DataFrame, days: int) -> pd.DataFrame:
    if b.empty:
        return pd.DataFrame()
    mid = sorted(b["day"].unique())[b["day"].nunique() // 2]
    out = []
    for (tf, tm, sd), g in b.groupby(["tf", "time", "side"]):
        if len(g) < 15:
            continue
        r1 = (g["t1"] - g["cost_pts"]) / g["range"]
        r2 = (g["t2"] - g["cost_pts"]) / g["range"]
        h1, h2 = r2[g["day"] < mid], r2[g["day"] >= mid]
        out.append({"tf": tf, "candle": tm, "break": "HIGH (long)" if sd > 0 else "LOW (short)", "breaks": len(g),
                    "of days %": round(len(g) / days * 100), "avg range pts": round(g["range"].mean(), 1),
                    "pts at exit": round(g["pts_end"].mean(), 1), "median MFE pts": round(g["mfe"].median(), 1),
                    "reach 1x %": round(g["hit1"].mean() * 100), "reach 2x %": round(g["hit2"].mean() * 100),
                    "false %": round(g["false"].mean() * 100),
                    "trade 1x pts": round(g["t1"].mean(), 1), "trade 2x pts": round(g["t2"].mean(), 1),
                    "net R 1x": round(r1.mean(), 3), "net R 2x": round(r2.mean(), 3),
                    "t 2x": round(r2.mean() / r2.std() * np.sqrt(len(r2)), 2) if r2.std() > 0 else np.nan,
                    "h1 / h2 (2x)": f"{h1.mean():+.2f} / {h2.mean():+.2f}",
                    "both +": bool(h1.mean() > 0 and h2.mean() > 0 and len(g) >= 25)})
    return pd.DataFrame(out)


def main(argv):
    S = Path(argv[1])
    idx5 = pd.read_pickle(S / "yahoo_idx5m.pkl")
    y1h = pd.read_pickle(S / "yahoo1h.pkl")
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 600)
    allres = []
    say("CANDLE-BREAKOUT MAP. Indian indices: exit 15:15, cost 0.02%. Points = index points. R = the candle's range.")
    for k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"):
        m5 = prep(idx5[k])
        m5 = m5[(m5.index.strftime("%H:%M") >= "09:15") & (m5.index.strftime("%H:%M") < "15:30")]
        days = m5.index.normalize().nunique()
        for tf in (5, 15, 30, 60):
            b = breaks(m5, tf, "09:15", "15:15", 0.02, window=("09:15", "14:15"))
            t = table(b, days)
            if not t.empty:
                t.insert(0, "market", f"{k} ({days}d)")
                allres.append(t)
        print(k, "done", flush=True)
    # 3-year check: hourly candles, the next hours' bars as the 'fine' series
    for k in ("NIFTY", "BANKNIFTY"):
        h = prep(y1h[k])
        days = h.index.normalize().nunique()
        b = breaks(h, 60, "09:15", "15:15", 0.02, window=("09:15", "13:15"))
        t = table(b, days)
        if not t.empty:
            t.insert(0, "market", f"{k} 1h-on-1h ({days}d, 3y)")
            allres.append(t)
    say("(3-year rows use hourly candles to detect the break, so entries / exits are coarser)")
    # night: gold and BTC, IST evening candles, 4-hour hold
    for name, f, cost in (("Gold (PAXG)", "paxg5m.pkl", 0.03), ("BTC", "btc5m.pkl", 0.08)):
        m5 = prep(pd.read_pickle(S / f))
        m5.index = m5.index + pd.Timedelta(hours=5, minutes=30)          # UTC -> IST
        m5 = m5[m5.index.dayofweek < 5] if name.startswith("Gold") else m5
        days = m5.index.normalize().nunique()
        for tf in (15, 30, 60):
            b = breaks(m5, tf, "00:00", 4, cost, window=("17:00", "23:00"))
            t = table(b, days)
            if not t.empty:
                t.insert(0, "market", f"{name} night IST ({days}d, 3.5y)")
                allres.append(t)
        print(name, "done", flush=True)
    R = pd.concat(allres, ignore_index=True)
    R.to_csv(S / "candle_breakouts.csv", index=False)
    cols = ["market", "tf", "candle", "break", "breaks", "avg range pts", "pts at exit", "median MFE pts", "reach 1x %",
            "reach 2x %", "false %", "trade 2x pts", "net R 2x", "t 2x", "h1 / h2 (2x)"]
    for mk in R["market"].unique():
        z = R[R["market"] == mk]
        say(f"\n=== {mk}: top 8 candle breaks by net R (2x target) ===")
        say(z.sort_values("net R 2x", ascending=False)[cols].head(8).to_string(index=False))
    good = R[(R["both +"]) & (R["t 2x"] >= 2.0)]
    say(f"\nSTRONG: positive after costs in both halves, t >= 2 (of {len(R)} cells): {len(good)}")
    if len(good):
        say(good.sort_values("t 2x", ascending=False)[cols].to_string(index=False))
    say("\nAVERAGE over all candles, by timeframe and side (net R, 2x target):")
    say(R.groupby(["market", "tf", "break"])["net R 2x"].mean().round(3).unstack().to_string())
    (S / "candle_breakouts.txt").write_text("\n".join(OUT))


if __name__ == "__main__":
    main(sys.argv)
