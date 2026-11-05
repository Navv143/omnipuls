"""Momentum ignition: a 5-minute candle that breaks the day's high (low) on a volume burst. Does the move come fast
(within 60-120 minutes) and is a target / stop / time limit trade on it profitable?

Event (checked on candles closing 09:35-14:00, first per stock, day and side): close beyond the day's high (low) so far,
candle volume >= `vx` times the usual volume for that time of day (20 previous days), candle range >= 0.15 ATR, close
in the top (bottom) 30% of the candle. Entry at the next candle's open, stop first, 0.12% costs.
Usage: python research/ignition_study.py fno60.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

COST = 0.12


def events(bars: dict, nifty: pd.DataFrame, min_vx: float = 1.5) -> pd.DataFrame:
    n = nifty[~nifty.index.duplicated()].sort_index()
    n_open = n.groupby(n.index.normalize())["Open"].transform("first")
    n_day = (n["Close"] / n_open - 1) * 100
    rows = []
    for sym, df in bars.items():
        if sym not in U.FNO_SECTOR_OF:
            continue
        x = df[~df.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")]
        dd = x.index.normalize()
        hm = x.index.strftime("%H:%M")
        d = x.groupby(dd).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
        pc = d["c"].shift()
        tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift()
        vt = x["Volume"].groupby([dd, hm]).last().unstack()
        vavg = vt.rolling(20, min_periods=10).mean().shift().stack()
        x = x.assign(day=dd, hm=hm)
        x["vavg"] = vavg.reindex(list(zip(dd, hm))).to_numpy()
        x["hod"] = x.groupby("day")["High"].transform(lambda s: s.cummax().shift())
        x["lod"] = x.groupby("day")["Low"].transform(lambda s: s.cummin().shift())
        x["A"] = atr.reindex(dd).to_numpy()
        x["P"] = pc.reindex(dd).to_numpy()
        x["O"] = d["o"].reindex(dd).to_numpy()
        tp = (x["High"] + x["Low"] + x["Close"]) / 3
        x["vwap"] = (tp * x["Volume"]).groupby(dd).cumsum() / x["Volume"].groupby(dd).cumsum().replace(0, np.nan)
        x["vx"] = x["Volume"] / x["vavg"]
        rng = x["High"] - x["Low"]
        clv = (x["Close"] - x["Low"]) / rng.replace(0, np.nan)
        up = (x["Close"] > x["hod"]) & (clv >= 0.7)
        dn = (x["Close"] < x["lod"]) & (clv <= 0.3)
        ok = (x["hm"] >= "09:30") & (x["hm"] <= "13:55") & (x["vx"] >= min_vx) & (rng >= 0.15 * x["A"]) & (x["A"] > 0)
        for side, m in ((1, up & ok), (-1, dn & ok)):
            ev = x[m].groupby("day").head(1)
            for ts, r in ev.iterrows():
                day = x[x["day"] == r["day"]]
                post = day[day.index > ts]
                if len(post) < 3:
                    continue
                e, A = post["Open"].iloc[0], r["A"]
                fav = ((post["High"] if side > 0 else -post["Low"]) - side * e) / A
                adv = (side * e - (post["Low"] if side > 0 else -post["High"])) / A
                cl = side * (post["Close"] - e) / A
                mins = ((post.index - post.index[0]).total_seconds() / 60 + 5).to_numpy()
                pre = day[day.index <= ts]
                row = {"day": r["day"], "sym": sym, "sector": U.FNO_SECTOR_OF[sym], "t": r["hm"], "side": side,
                       "entry": e, "A": A, "atr_pct": A / r["P"] * 100, "vx": r["vx"],
                       "gap_atr": side * (r["O"] - r["P"]) / A, "day_atr": side * (r["Close"] - r["P"]) / A,
                       "from_open_atr": side * (r["Close"] - r["O"]) / A, "bar_atr": (r["High"] - r["Low"]) / A,
                       "vwap_dist_atr": side * (r["Close"] - r["vwap"]) / A,
                       "nifty_day": side * n_day.get(ts, np.nan),
                       "stop_bar_atr": (e - r["Low"]) / A if side > 0 else (r["High"] - e) / A,
                       "range_sofar_atr": (pre["High"].max() - pre["Low"].min()) / A,
                       "fav": fav.to_numpy(), "adv": adv.to_numpy(), "cl": cl.to_numpy(), "mins": mins,
                       "ret_close": cl.iloc[-1], "mfe_close": fav.max()}
                for w in (30, 60, 120):
                    k = mins <= w
                    row[f"mfe_{w}"], row[f"mae_{w}"], row[f"ret_{w}"] = fav[k].max(), adv[k].max(), cl[k].iloc[-1]
                rows.append(row)
    return pd.DataFrame(rows)


def sim(p: pd.DataFrame, tp: float, sl, limit: int) -> pd.Series:
    """% per trade: target tp ATR, stop sl ATR (or 'bar' = beyond the signal candle), exit at the close of the last
    candle within `limit` minutes of entry (or 15:25)."""
    out = []
    for r in p.itertuples(index=False):
        s = max(r.stop_bar_atr, 0.05) if sl == "bar" else sl
        k = r.mins <= limit
        res = r.cl[k][-1]
        for f, a in zip(r.fav[k], r.adv[k]):
            if a >= s:
                res = -s
                break
            if f >= tp:
                res = tp
                break
        out.append(res * r.A / r.entry * 100 - COST)
    return pd.Series(out, index=p.index)


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    ev = events(bars, ix["NIFTY"])
    pickle.dump(ev, open(Path(sys.argv[1]).with_name("ignition.pkl"), "wb"))
    print(len(ev), "events")
