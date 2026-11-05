"""Sniper setups for BTC and gold (XAUUSD): one or two trades a day, small stop, honest test.

Data: BTC Binance spot 5-minute klines (data.binance.vision), gold Dukascopy XAUUSD 1-minute bid candles resampled to
5 minutes. Times are converted to London / New York local time (daylight saving handled). Entry at the next candle's
open after the signal candle; stop and target in the same candle counts as the stop; costs in % of price per round
trip (BTC 0.05, gold 0.02) taken off every trade in R. Tune on 2023-2024, confirm on 2025-2026.

python research/sniper_study.py <scratch dir>
"""
from __future__ import annotations

import glob
import io
import lzma
import os
import struct
import sys
import zipfile

import numpy as np
import pandas as pd

COST = {"BTC": 0.05, "XAU": 0.02}


def load_btc(d: str) -> pd.DataFrame:
    out = []
    for f in sorted(glob.glob(f"{d}/btc/*.zip")):
        with zipfile.ZipFile(f) as z:
            x = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=range(6))
        x.columns = ["t", "Open", "High", "Low", "Close", "Volume"]
        unit = "us" if x["t"].iloc[0] > 1e14 else "ms"   # Binance spot switched to microseconds in 2025
        x.index = pd.to_datetime(x["t"], unit=unit, utc=True)
        out.append(x.drop(columns="t"))
    return pd.concat(out).sort_index()


def load_paxg(d: str) -> pd.DataFrame:
    return load_btc(d.replace("/btc", "")) if False else _load_zip_dir(f"{d}/paxg")


def _load_zip_dir(p: str) -> pd.DataFrame:
    out = []
    for f in sorted(glob.glob(f"{p}/*.zip")):
        with zipfile.ZipFile(f) as z:
            x = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=range(6))
        x.columns = ["t", "Open", "High", "Low", "Close", "Volume"]
        x.index = pd.to_datetime(x["t"], unit="us" if x["t"].iloc[0] > 1e14 else "ms", utc=True)
        out.append(x.drop(columns="t"))
    return pd.concat(out).sort_index()


def load_xau(d: str) -> pd.DataFrame:
    """Dukascopy BID_candles_min_1.bi5: LZMA, records of (sec from day start, open, close, low, high: int /1000, vol)."""
    rows = []
    for f in sorted(glob.glob(f"{d}/xau/d/*.bi5")):
        day = pd.Timestamp(os.path.basename(f)[:10], tz="UTC")
        try:
            raw = lzma.decompress(open(f, "rb").read())
        except Exception:
            continue
        a = np.frombuffer(raw, dtype=">i4").reshape(-1, 6)
        if not len(a):
            continue
        vol = np.frombuffer(raw, dtype=">f4").reshape(-1, 6)[:, 5]
        df = pd.DataFrame({"Open": a[:, 1] / 1000, "Close": a[:, 2] / 1000, "Low": a[:, 3] / 1000, "High": a[:, 4] / 1000,
                           "Volume": vol}, index=day + pd.to_timedelta(a[:, 0], unit="s"))
        rows.append(df[df["Volume"] > 0])
    m1 = pd.concat(rows).sort_index()
    return m1.resample("5min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()


# ---------------------------------------------------------------- trade simulation

def run_trade(o, h, l, c, i, side, stop, target, last):
    """Enter at o[i]; walk to bar `last` (inclusive). Returns (exit price, how, bars held)."""
    e = o[i]
    for j in range(i, last + 1):
        if side > 0:
            if l[j] <= stop:
                return stop, "stop", j - i
            if h[j] >= target:
                return target, "target", j - i
        else:
            if h[j] >= stop:
                return stop, "stop", j - i
            if l[j] <= target:
                return target, "target", j - i
    return c[last], "time", last - i


def result(side, e, stop, x, cost_pct):
    risk = abs(e - stop)
    return (side * (x - e) - e * cost_pct / 100) / risk if risk > 0 else np.nan


# ---------------------------------------------------------------- setups (one trade per day per setup at most)

def prep(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    x = df.copy()
    lt = x.index.tz_convert(tz)
    x["day"] = lt.normalize().tz_localize(None)
    x["hm"] = lt.hour * 60 + lt.minute
    return x


def days_iter(x: pd.DataFrame):
    o, h, l, c = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx = np.arange(len(x))
    for day, g in x.groupby("day", sort=True):
        yield day, idx[x["day"].to_numpy() == day] if False else g.index, g
    return


def by_day(x: pd.DataFrame) -> dict:
    pos = pd.Series(np.arange(len(x)), index=x.index)
    return {d: pos.loc[g.index].to_numpy() for d, g in x.groupby("day", sort=True)}


def orb(x, D, cost, or_start, or_mins, end_hm, stop_mode="opp", rr=1.5, max_or_atr=None, atr=None, confirm="close"):
    """Opening range breakout: range of [or_start, or_start+or_mins); first 5-min close beyond it → trade the break;
    stop at the other side (opp) or the middle (mid); target rr x risk; exit at end_hm."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    out = []
    for day, ix in D.items():
        m = hm[ix]
        r_ix = ix[(m >= or_start) & (m < or_start + or_mins)]
        a_ix = ix[(m >= or_start + or_mins) & (m < end_hm)]
        if len(r_ix) < or_mins // 5 or len(a_ix) < 3:
            continue
        hi, lo = h[r_ix].max(), l[r_ix].min()
        if max_or_atr and atr is not None and day in atr.index and (hi - lo) > max_or_atr * atr.loc[day]:
            continue
        last = a_ix[-1]
        for k in a_ix[:-1]:
            side = 1 if c[k] > hi else -1 if c[k] < lo else 0
            if not side:
                continue
            i = k + 1
            e = o[i]
            stop = (lo if side > 0 else hi) if stop_mode == "opp" else (hi + lo) / 2
            if side * (e - stop) <= 0:
                break
            tgt = e + side * rr * abs(e - stop)
            xp, how, _ = run_trade(o, h, l, c, i, side, stop, tgt, last)
            out.append({"day": day, "side": side, "r": result(side, e, stop, xp, cost), "how": how,
                        "stop_pct": abs(e - stop) / e * 100})
            break
    return pd.DataFrame(out)


def sweep(x, D, cost, rng_start, rng_end, win_start, win_end, end_hm, rr=2.0, target="rr", buf=0.0, atr=None,
          min_rng_atr=0.0, max_rng_atr=9.0):
    """Liquidity sweep reversal: range of [rng_start, rng_end) (e.g. Asia); in the window a candle trades beyond the
    range high (low) and CLOSES back inside → fade it: stop beyond the sweep extreme (+buf x ATR), target rr x risk or
    the range middle / other side. One trade a day."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    out = []
    for day, ix in D.items():
        m = hm[ix]
        if rng_start > rng_end:   # range across midnight (previous evening) not used here
            continue
        r_ix = ix[(m >= rng_start) & (m < rng_end)]
        w_ix = ix[(m >= win_start) & (m < win_end)]
        e_ix = ix[(m >= win_start) & (m < end_hm)]
        if len(r_ix) < 6 or len(w_ix) < 2 or len(e_ix) < 3:
            continue
        hi, lo = h[r_ix].max(), l[r_ix].min()
        a = atr.loc[day] if atr is not None and day in atr.index else np.nan
        if a == a and not (min_rng_atr * a <= hi - lo <= max_rng_atr * a):
            continue
        last = e_ix[-1]
        ext_hi, ext_lo = hi, lo
        for k in w_ix[:-1]:
            ext_hi, ext_lo = max(ext_hi, h[k]), min(ext_lo, l[k])
            side = 0
            if h[k] > hi and c[k] < hi and c[k] > lo:
                side, stop = -1, ext_hi + buf * (a if a == a else 0)
            elif l[k] < lo and c[k] > lo and c[k] < hi:
                side, stop = 1, ext_lo - buf * (a if a == a else 0)
            if not side:
                continue
            i = k + 1
            e = o[i]
            if side * (e - stop) <= 0:
                break
            tgt = {"rr": e + side * rr * abs(e - stop), "mid": (hi + lo) / 2, "other": lo if side < 0 else hi}[target]
            if side * (tgt - e) <= 0:
                break
            xp, how, _ = run_trade(o, h, l, c, i, side, stop, tgt, last)
            out.append({"day": day, "side": side, "r": result(side, e, stop, xp, cost), "how": how,
                        "stop_pct": abs(e - stop) / e * 100})
            break
    return pd.DataFrame(out)


def pdhl_sweep(x, D, cost, win_start, win_end, end_hm, rr=2.0, buf=0.0, atr=None):
    """Previous day's high / low swept and closed back inside in the window → fade; stop beyond the sweep extreme."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    out, prev = [], None
    for day, ix in D.items():
        if prev is None:
            prev = (h[ix].max(), l[ix].min())
            continue
        phi, plo = prev
        prev = (h[ix].max(), l[ix].min())
        m = hm[ix]
        w_ix = ix[(m >= win_start) & (m < win_end)]
        e_ix = ix[(m >= win_start) & (m < end_hm)]
        if len(w_ix) < 2:
            continue
        a = atr.loc[day] if atr is not None and day in atr.index else 0
        pre = ix[m < win_start]
        if len(pre) and (h[pre].max() > phi or l[pre].min() < plo):
            continue   # already swept before the window
        last = e_ix[-1]
        ext_hi, ext_lo = -np.inf, np.inf
        for k in w_ix[:-1]:
            ext_hi, ext_lo = max(ext_hi, h[k]), min(ext_lo, l[k])
            side = 0
            if h[k] > phi and c[k] < phi:
                side, stop = -1, ext_hi + buf * a
            elif l[k] < plo and c[k] > plo:
                side, stop = 1, ext_lo - buf * a
            if not side:
                continue
            i = k + 1
            e = o[i]
            if side * (e - stop) <= 0:
                break
            tgt = e + side * rr * abs(e - stop)
            xp, how, _ = run_trade(o, h, l, c, i, side, stop, tgt, last)
            out.append({"day": day, "side": side, "r": result(side, e, stop, xp, cost), "how": how,
                        "stop_pct": abs(e - stop) / e * 100})
            break
    return pd.DataFrame(out)


def daily_atr(x: pd.DataFrame, n: int = 14) -> pd.Series:
    d = x.groupby("day").agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    tr = pd.concat([d["h"] - d["l"], (d["h"] - d["c"].shift()).abs(), (d["l"] - d["c"].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean().shift(1)


def summary(t: pd.DataFrame, split: str = "2025-01-01") -> dict:
    if t is None or t.empty:
        return {"n": 0}
    t = t.dropna(subset=["r"])
    a, b = t[t["day"] < split], t[t["day"] >= split]

    def s(z):
        if len(z) < 5:
            return {"n": len(z)}
        return {"n": len(z), "win": round((z["r"] > 0).mean() * 100), "avgR": round(z["r"].mean(), 3),
                "t": round(z["r"].mean() / z["r"].std(ddof=1) * np.sqrt(len(z)), 2), "sumR": round(z["r"].sum(), 1)}
    return {"all": s(t), "tune": s(a), "test": s(b), "stop%": round(t["stop_pct"].median(), 3)}


if __name__ == "__main__":
    print("see the research notes; functions are driven from a runner")


def add_ind(x: pd.DataFrame) -> pd.DataFrame:
    """Session VWAP (from the local day start), its deviation band, and the 1-hour EMA trend mapped onto 5-min bars."""
    x = x.copy()
    tp = (x["High"] + x["Low"] + x["Close"]) / 3
    v = x["Volume"].replace(0, np.nan).fillna(1e-9)
    g = x.groupby("day")
    x["vwap"] = (tp * v).groupby(x["day"]).cumsum() / v.groupby(x["day"]).cumsum()
    dev = (x["Close"] - x["vwap"])
    x["vsd"] = dev.groupby(x["day"]).transform(lambda s: s.expanding(12).std())
    h1 = x["Close"].resample("1h").last().dropna()
    e50, e20 = h1.ewm(span=50).mean(), h1.ewm(span=20).mean()
    tr = pd.Series(np.where((h1 > e50) & (e20 > e20.shift(3)), 1, np.where((h1 < e50) & (e20 < e20.shift(3)), -1, 0)),
                   index=h1.index)
    x["trend"] = tr.shift(1).reindex(x.index, method="ffill").fillna(0)   # last finished hour only
    return x


def pullback(x, D, cost, win_start, win_end, end_hm, rr=2.0, min_stop=0.3, max_stop=0.8, swing=3):
    """With the 1-hour trend: price dips to the session VWAP, then a 5-min candle closes beyond the previous candle's
    high (low) on the trend side → enter; stop beyond the last `swing` candles' extreme; target rr x risk."""
    o, h, l, c, hm, vw, tr = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm", "vwap", "trend"))
    out = []
    for day, ix in D.items():
        m = hm[ix]
        w_ix = ix[(m >= win_start) & (m < win_end)]
        e_ix = ix[(m >= win_start) & (m < end_hm)]
        if len(w_ix) < 4:
            continue
        last = e_ix[-1]
        touched = 0
        for k in w_ix[1:-1]:
            sd = int(tr[k])
            if not sd:
                continue
            if (sd > 0 and l[k] <= vw[k] and c[k] > vw[k] * 0.998) or (sd < 0 and h[k] >= vw[k] and c[k] < vw[k] * 1.002):
                touched = sd
                continue
            if touched == sd and ((sd > 0 and c[k] > h[k - 1]) or (sd < 0 and c[k] < l[k - 1])):
                i = k + 1
                e = o[i]
                lo_, hi_ = l[k - swing + 1:k + 1].min(), h[k - swing + 1:k + 1].max()
                stop = lo_ if sd > 0 else hi_
                sp = abs(e - stop) / e * 100
                if not (min_stop <= sp <= max_stop) or sd * (e - stop) <= 0:
                    touched = 0
                    continue
                xp, how, _ = run_trade(o, h, l, c, i, sd, stop, e + sd * rr * abs(e - stop), last)
                out.append({"day": day, "side": sd, "r": result(sd, e, stop, xp, cost), "how": how, "stop_pct": sp})
                break
    return pd.DataFrame(out)


def vwap_snap(x, D, cost, win_start, win_end, end_hm, k_sd=2.5, min_stop=0.2, max_stop=1.0, with_trend=False):
    """A 5-min candle closes beyond VWAP ± k·σ, the next closes back inside → fade to VWAP; stop beyond the extreme."""
    o, h, l, c, hm, vw, sdv, tr = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm", "vwap", "vsd", "trend"))
    out = []
    for day, ix in D.items():
        m = hm[ix]
        w_ix = ix[(m >= win_start) & (m < win_end)]
        e_ix = ix[(m >= win_start) & (m < end_hm)]
        if len(w_ix) < 4:
            continue
        last = e_ix[-1]
        for k in w_ix[1:-1]:
            if not sdv[k] == sdv[k]:
                continue
            up, dn = vw[k - 1] + k_sd * sdv[k - 1], vw[k - 1] - k_sd * sdv[k - 1]
            side = -1 if (c[k - 1] > up and c[k] < up) else 1 if (c[k - 1] < dn and c[k] > dn) else 0
            if not side or (with_trend and tr[k] == -side):
                continue
            i = k + 1
            e = o[i]
            stop = max(h[k - 1], h[k]) if side < 0 else min(l[k - 1], l[k])
            sp = abs(e - stop) / e * 100
            tgt = vw[k]
            if not (min_stop <= sp <= max_stop) or side * (tgt - e) <= abs(e - stop) * 0.8:
                continue
            xp, how, _ = run_trade(o, h, l, c, i, side, stop, tgt, last)
            out.append({"day": day, "side": side, "r": result(side, e, stop, xp, cost), "how": how, "stop_pct": sp})
            break
    return pd.DataFrame(out)


def halfhour_mom(x, D, cost, a_start, a_end, b_start, b_end, min_move=0.0):
    """Return from a_start to a_end predicts b_start to b_end (same sign); time exit, result in % (net)."""
    o, c, hm = x["Open"].to_numpy(), x["Close"].to_numpy(), x["hm"].to_numpy()
    out = []
    for day, ix in D.items():
        m = hm[ix]
        a = ix[(m >= a_start) & (m < a_end)]
        b = ix[(m >= b_start) & (m < b_end)]
        if len(a) < 2 or len(b) < 2:
            continue
        ra = c[a[-1]] / o[a[0]] - 1
        if abs(ra) * 100 < min_move:
            continue
        sd = 1 if ra > 0 else -1
        rb = sd * (c[b[-1]] / o[b[0]] - 1) * 100 - cost
        out.append({"day": day, "side": sd, "r": rb, "how": "time", "stop_pct": np.nan})
    return pd.DataFrame(out)


def orb_trend(x, D, cost, or_start, or_mins, end_hm, rr=2.0, stop_mode="opp", vol_x=0.0):
    """ORB taken only in the 1-hour trend's direction (and optionally with a breakout candle volume ≥ vol_x × the
    opening range's average candle volume)."""
    o, h, l, c, v, hm, tr = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "Volume", "hm", "trend"))
    out = []
    for day, ix in D.items():
        m = hm[ix]
        r_ix = ix[(m >= or_start) & (m < or_start + or_mins)]
        a_ix = ix[(m >= or_start + or_mins) & (m < end_hm)]
        if len(r_ix) < or_mins // 5 or len(a_ix) < 3:
            continue
        hi, lo, av = h[r_ix].max(), l[r_ix].min(), v[r_ix].mean()
        last = a_ix[-1]
        for k in a_ix[:-1]:
            side = 1 if c[k] > hi else -1 if c[k] < lo else 0
            if not side:
                continue
            if tr[k] != side or (vol_x and v[k] < vol_x * av):
                break
            i = k + 1
            e = o[i]
            stop = (lo if side > 0 else hi) if stop_mode == "opp" else (hi + lo) / 2
            if side * (e - stop) <= 0:
                break
            xp, how, _ = run_trade(o, h, l, c, i, side, stop, e + side * rr * abs(e - stop), last)
            out.append({"day": day, "side": side, "r": result(side, e, stop, xp, cost), "how": how,
                        "stop_pct": abs(e - stop) / e * 100})
            break
    return pd.DataFrame(out)


def daily_trend(x: pd.DataFrame, span: int = 20) -> pd.Series:
    """+1 / -1 / 0 per day from the days before it: yesterday's close vs its 20-day EMA, and the EMA's slope."""
    d = x.groupby("day")["Close"].last()
    e = d.ewm(span=span).mean()
    t = pd.Series(np.where((d > e) & (e > e.shift(3)), 1, np.where((d < e) & (e < e.shift(3)), -1, 0)), index=d.index)
    return t.shift(1).fillna(0)


def orb_daily(x, D, cost, or_start, or_mins, end_hm, dtr, rr=2.0, stop_mode="opp"):
    """ORB taken only in the daily trend's direction; one trade a day."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    out = []
    for day, ix in D.items():
        sd_day = int(dtr.get(day, 0))
        if not sd_day:
            continue
        m = hm[ix]
        r_ix = ix[(m >= or_start) & (m < or_start + or_mins)]
        a_ix = ix[(m >= or_start + or_mins) & (m < end_hm)]
        if len(r_ix) < or_mins // 5 or len(a_ix) < 3:
            continue
        hi, lo = h[r_ix].max(), l[r_ix].min()
        last = a_ix[-1]
        for k in a_ix[:-1]:
            side = 1 if c[k] > hi else -1 if c[k] < lo else 0
            if not side:
                continue
            if side != sd_day:
                break
            i = k + 1
            e = o[i]
            stop = (lo if side > 0 else hi) if stop_mode == "opp" else (hi + lo) / 2
            if side * (e - stop) <= 0:
                break
            xp, how, _ = run_trade(o, h, l, c, i, side, stop, e + side * rr * abs(e - stop), last)
            out.append({"day": day, "side": side, "r": result(side, e, stop, xp, cost), "how": how,
                        "stop_pct": abs(e - stop) / e * 100})
            break
    return pd.DataFrame(out)
