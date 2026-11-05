"""Move finder: what do the moments just before a fast, big move have in common?

Every F&O stock, every 5-minute candle from 09:30 to 14:20, both directions (short side mirrored, so one model learns
"the move my way"). Label = from the next candle's open, price reaches +0.75 ATR within 60 minutes before it falls
0.3 ATR (stop first when both fall in one candle). Features use only data known at the candle's close.
A gradient-boosted model is trained on the earlier days and judged on the later days it never saw.
Usage: python research/move_finder.py fno60.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

TP, SL, HORIZON = 0.75, 0.3, 12          # ATR, ATR, candles (60 minutes)
FIRST, LAST = "09:30", "14:20"


def _labels(o, h, l, c, A, side):
    """Per candle i: 1 if from open[i+1] the target comes before the stop within HORIZON candles; also the % result of
    that trade (target, stop or the close of the last candle in the window)."""
    n = len(o)
    win = np.zeros(n, dtype=np.int8)
    res = np.full(n, np.nan)
    for i in range(n - 1):
        e = o[i + 1]
        tp, sl = e + side * TP * A, e - side * SL * A
        out = None
        j_end = min(n, i + 1 + HORIZON)
        for j in range(i + 1, j_end):
            if (side > 0 and l[j] <= sl) or (side < 0 and h[j] >= sl):
                out = -SL * A
                break
            if (side > 0 and h[j] >= tp) or (side < 0 and l[j] <= tp):
                out, win[i] = TP * A, 1
                break
        if out is None:
            out = side * (c[j_end - 1] - e)
        res[i] = out / e * 100
    return win, res


def panel(bars: dict, nifty: pd.DataFrame) -> pd.DataFrame:
    n = nifty[~nifty.index.duplicated()].sort_index()
    nd = n.index.normalize()
    n_open = n.groupby(nd)["Open"].transform("first")
    nf = pd.DataFrame({"n_day": (n["Close"] / n_open - 1) * 100,
                       "n_r3": n.groupby(nd)["Close"].transform(lambda s: (s / s.shift(3) - 1) * 100)})
    parts = []
    for sym, df in bars.items():
        if sym not in U.FNO_SECTOR_OF:
            continue
        x = df[~df.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")].copy()
        if len(x) < 500:
            continue
        dd = x.index.normalize()
        hm = x.index.strftime("%H:%M")
        d = x.groupby(dd).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
        pc = d["c"].shift()
        tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift()
        rng = d["h"] - d["l"]
        daily = pd.DataFrame({
            "A": atr, "P": pc, "O": d["o"], "pdh": d["h"].shift(), "pdl": d["l"].shift(),
            "hi20": d["h"].rolling(20).max().shift(), "lo20": d["l"].rolling(20).min().shift(),
            "yday_rng": rng.shift() / atr, "nr7": (rng.shift() <= rng.shift().rolling(7).min()).astype(float),
            "yday_ret": (pc - d["c"].shift(2)) / atr})
        x = x.join(daily.reindex(dd).set_index(x.index))
        g = x.groupby(dd)
        A, C = x["A"], x["Close"]
        hod, lod = g["High"].cummax(), g["Low"].cummin()
        tp_ = (x["High"] + x["Low"] + C) / 3
        vwap = (tp_ * x["Volume"]).groupby(dd).cumsum() / x["Volume"].groupby(dd).cumsum().replace(0, np.nan)
        vt = x["Volume"].groupby([dd, hm]).last().unstack()
        slot_avg = vt.rolling(20, min_periods=10).mean().shift()
        cum_avg = vt.reindex(sorted(vt.columns), axis=1).fillna(0).cumsum(axis=1).rolling(20, min_periods=10).mean().shift()
        key = list(zip(dd, hm))
        sa = slot_avg.stack().reindex(key).to_numpy()
        ca = cum_avg.stack().reindex(key).to_numpy()
        cumv = x["Volume"].groupby(dd).cumsum()
        bar_i = g.cumcount()
        f = pd.DataFrame(index=x.index)
        f["sym"], f["day"], f["hm"] = sym, dd, hm
        f["sector"] = U.FNO_SECTOR_OF[sym]
        f["t_min"] = bar_i * 5
        f["day_atr"] = (C - x["P"]) / A
        f["open_atr"] = (C - x["O"]) / A
        f["gap_atr"] = (x["O"] - x["P"]) / A
        f["hod_dist"] = (hod - C) / A
        f["lod_dist"] = (C - lod) / A
        f["range_atr"] = (hod - lod) / A
        f["vwap_dist"] = (C - vwap) / A
        f["vwap_above"] = (C > vwap).astype(float).groupby(dd).transform(lambda s: s.expanding().mean())
        for k in (1, 3, 6, 12):
            f[f"r{k}"] = ((C - g["Close"].shift(k)) / A).fillna((C - x["O"]) / A)
        f["vx1"] = x["Volume"].to_numpy() / sa
        f["vx3"] = x["Volume"].groupby(dd).transform(lambda s: s.rolling(3, min_periods=1).sum()).to_numpy() / (
            pd.Series(sa, index=x.index).groupby(dd).transform(lambda s: s.rolling(3, min_periods=1).sum()).to_numpy())
        f["rvol"] = cumv.to_numpy() / ca
        f["tight6"] = (g["High"].transform(lambda s: s.rolling(6, min_periods=1).max())
                       - g["Low"].transform(lambda s: s.rolling(6, min_periods=1).min())) / A
        f["bar_atr"] = (x["High"] - x["Low"]) / A
        f["clv"] = ((C - x["Low"]) / (x["High"] - x["Low"]).replace(0, np.nan)).fillna(0.5)
        is_hod = (x["High"] >= hod).astype(int)
        is_lod = (x["Low"] <= lod).astype(int)
        f["since_hod"] = bar_i - bar_i.where(is_hod == 1).groupby(dd).ffill()
        f["since_lod"] = bar_i - bar_i.where(is_lod == 1).groupby(dd).ffill()
        f["pdh_dist"] = (C - x["pdh"]) / A
        f["pdl_dist"] = (C - x["pdl"]) / A
        f["hi20_dist"] = (C - x["hi20"]) / A
        f["lo20_dist"] = (C - x["lo20"]) / A
        f["atr_pct"] = A / x["P"] * 100
        for k in ("yday_rng", "nr7", "yday_ret"):
            f[k] = x[k]
        f = f.join(nf, how="left")
        f["rel"] = (C / x["O"] - 1) * 100 - f["n_day"]
        o_, h_, l_, c_ = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
        for side, tag in ((1, "L"), (-1, "S")):
            w = np.zeros(len(x), dtype=np.int8)
            r = np.full(len(x), np.nan)
            for day, idx in g.indices.items():
                a = float(A.iloc[idx[0]])
                if not np.isfinite(a) or a <= 0:
                    continue
                w[idx], r[idx] = _labels(o_[idx], h_[idx], l_[idx], c_[idx], a, side)
            f[f"win_{tag}"], f[f"res_{tag}"] = w, r
        f = f[(f["hm"] >= FIRST) & (f["hm"] <= LAST) & np.isfinite(A) & (A > 0)]
        parts.append(f)
    t = pd.concat(parts)
    t["sec_day"] = t.groupby(["day", "hm", "sector"])["day_atr"].transform("mean")
    t["sec_r3"] = t.groupby(["day", "hm", "sector"])["r3"].transform("mean")
    t["breadth"] = t.groupby(["day", "hm"])["day_atr"].transform(lambda s: (s > 0).mean())
    return t


SIGNED = ["day_atr", "open_atr", "gap_atr", "vwap_dist", "r1", "r3", "r6", "r12", "pdh_dist", "yday_ret", "n_day", "n_r3",
          "rel", "sec_day", "sec_r3"]
SWAP = [("hod_dist", "lod_dist"), ("since_hod", "since_lod"), ("pdh_dist", "pdl_dist"), ("hi20_dist", "lo20_dist")]
FEATS = ["t_min", "day_atr", "open_atr", "gap_atr", "hod_dist", "lod_dist", "range_atr", "vwap_dist", "vwap_above",
         "r1", "r3", "r6", "r12", "vx1", "vx3", "rvol", "tight6", "bar_atr", "clv", "since_hod", "since_lod", "pdh_dist",
         "pdl_dist", "hi20_dist", "lo20_dist", "atr_pct", "yday_rng", "nr7", "yday_ret", "n_day", "n_r3", "rel",
         "sec_day", "sec_r3", "breadth"]


def mirrored(t: pd.DataFrame) -> pd.DataFrame:
    """Long rows as they are; short rows with every directional reading flipped, so 'up' always means 'my way'."""
    L = t.assign(side=1, win=t["win_L"], res=t["res_L"])
    S = t.assign(side=-1, win=t["win_S"], res=t["res_S"])
    for k in SIGNED:
        S[k] = -S[k]
    for a, b in SWAP:
        S[a], S[b] = t[b] if a not in SIGNED else -t[b], t[a] if b not in SIGNED else -t[a]
    S["pdh_dist"], S["pdl_dist"] = -t["pdl_dist"], -t["pdh_dist"]
    S["hi20_dist"], S["lo20_dist"] = -t["lo20_dist"], -t["hi20_dist"]
    S["vwap_above"] = 1 - t["vwap_above"]
    S["clv"] = 1 - t["clv"]
    S["breadth"] = 1 - t["breadth"]
    return pd.concat([L, S], ignore_index=True)


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    t = panel(bars, ix["NIFTY"])
    t.to_parquet(Path(sys.argv[1]).with_name("move_panel.parquet"))
    print(len(t), "stock-candles", t["day"].nunique(), "days; base rate long", round(t["win_L"].mean(), 4),
          "short", round(t["win_S"].mean(), 4))
