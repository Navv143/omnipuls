"""Algo lab: every level / sweep / volume-profile / EMA / HTF-bias family as exact rules, on 5-minute candles, run with
strategy_lab.simulate (entry next open, stop first if stop and target share a candle, costs, max trades a day).

Levels are mapped onto each 5-min candle without look-ahead: the previous day's / session's / 1H / 4H candle values are
known only after that period has closed. Sessions in London time: Asia 00:00-07:00, London 07:00-12:00, NY 13:30-20:00.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import strategy_lab as L


def prep(raw: pd.DataFrame) -> pd.DataFrame:
    x = raw[~raw.index.duplicated(keep="last")].sort_index().copy()
    lt = x.index.tz_convert("Europe/London")
    x["day"] = lt.normalize().tz_localize(None)
    x["hm"] = lt.hour * 60 + lt.minute
    x["atr5"] = L.atr(x, 14)
    d = x.groupby("day").agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    tr = pd.concat([d["h"] - d["l"], (d["h"] - d["c"].shift()).abs(), (d["l"] - d["c"].shift()).abs()], axis=1).max(axis=1)
    x["datr"] = x["day"].map(tr.rolling(14).mean().shift())
    x["pdh"], x["pdl"] = x["day"].map(d["h"].shift()), x["day"].map(d["l"].shift())
    # session ranges of the same day (known after the session closes)
    for nm, a, b in (("asia", 0, 420), ("ldn", 420, 720)):
        s = x[(x["hm"] >= a) & (x["hm"] < b)].groupby("day").agg(h=("High", "max"), l=("Low", "min"))
        x[f"{nm}_h"], x[f"{nm}_l"] = x["day"].map(s["h"]), x["day"].map(s["l"])
        x.loc[x["hm"] < b, [f"{nm}_h", f"{nm}_l"]] = np.nan
    # previous 1H / 4H candle (UTC-aligned) high / low
    for rule, nm in (("1h", "h1"), ("4h", "h4")):
        g = x.resample(rule).agg({"High": "max", "Low": "min", "Open": "first", "Close": "last"}).dropna()
        prev = g.shift()
        key = x.index.floor(rule)
        x[f"{nm}_ph"], x[f"{nm}_pl"] = prev["High"].reindex(key).to_numpy(), prev["Low"].reindex(key).to_numpy()
        x[f"{nm}_key"] = key
    # HTF bias: 4H EMA20 vs EMA50 and 1H close vs EMA50, from finished candles
    h4 = x["Close"].resample("4h").last().dropna()
    b4 = np.sign(L.ema(h4, 20) - L.ema(h4, 50)).shift()
    x["bias4h"] = b4.reindex(x.index, method="ffill").fillna(0).to_numpy()
    h1 = x["Close"].resample("1h").last().dropna()
    b1 = np.sign(h1 - L.ema(h1, 50)).shift()
    x["bias1h"] = b1.reindex(x.index, method="ffill").fillna(0).to_numpy()
    tp = (x["High"] + x["Low"] + x["Close"]) / 3
    v = x["Volume"].replace(0, np.nan).fillna(1e-9)
    x["vwap"] = (tp * v).groupby(x["day"]).cumsum() / v.groupby(x["day"]).cumsum()
    return x


def volume_profile(h, l, v, bins=80, va=0.70):
    """POC / VAH / VAL of candles (volume spread evenly over each candle's range)."""
    lo, hi = np.nanmin(l), np.nanmax(h)
    if not np.isfinite(lo) or hi <= lo:
        return np.nan, np.nan, np.nan
    edges = np.linspace(lo, hi, bins + 1)
    prof = np.zeros(bins)
    for a, b, vol in zip(l, h, v):
        i0, i1 = np.searchsorted(edges, a, "right") - 1, np.searchsorted(edges, b, "right") - 1
        i0, i1 = max(i0, 0), min(i1, bins - 1)
        prof[i0:i1 + 1] += vol / (i1 - i0 + 1)
    p = int(prof.argmax())
    tot, lo_i, hi_i, acc = prof.sum(), p, p, prof[p]
    while acc < va * tot and (lo_i > 0 or hi_i < bins - 1):
        up = prof[hi_i + 1] if hi_i < bins - 1 else -1
        dn = prof[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1
            acc += up
        else:
            lo_i -= 1
            acc += dn
    mid = (edges[:-1] + edges[1:]) / 2
    return mid[p], edges[hi_i + 1], edges[lo_i]


def add_profiles(x: pd.DataFrame) -> pd.DataFrame:
    """Previous day's profile (POC / VAH / VAL) and today's Asia-session profile (known from 07:00 London)."""
    rows, rows_a = {}, {}
    for d, g in x.groupby("day"):
        rows[d] = volume_profile(g["High"].to_numpy(), g["Low"].to_numpy(), g["Volume"].to_numpy())
        a = g[g["hm"] < 420]
        if len(a) > 20:
            rows_a[d] = volume_profile(a["High"].to_numpy(), a["Low"].to_numpy(), a["Volume"].to_numpy())
    P = pd.DataFrame(rows, index=["poc", "vah", "val"]).T.shift()          # previous day
    A = pd.DataFrame(rows_a, index=["apoc", "avah", "aval"]).T
    for c_ in P:
        x[f"p{c_}"] = x["day"].map(P[c_])
    for c_ in A:
        x[c_] = x["day"].map(A[c_])
        x.loc[x["hm"] < 420, c_] = np.nan
    return x


# ---------------------------------------------------------------- signal families (side, stop, target arrays)

def _arr(n):
    return np.zeros(n), np.full(n, np.nan), np.full(n, np.nan)


def sweep_levels(x, hi_col, lo_col, win, mode="fade", rr=2.0, target="rr", bias=None, once_key="day", buf=0.05):
    """mode 'fade': a candle trades beyond the level and closes back inside → opposite side, stop beyond the candle's
    extreme (+buf x daily ATR x 0.1), target rr x risk or the other level ('other') / middle ('mid').
    mode 'break': a candle closes beyond the level → with the break, stop at the level -/+ buf x daily ATR, target rr.
    bias: optional column (+1 / -1) that the trade must agree with. One trade per level per `once_key` period."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    H, Lo, datr = x[hi_col].to_numpy(), x[lo_col].to_numpy(), x["datr"].to_numpy()
    key = x[once_key].to_numpy()
    bz = x[bias].to_numpy() if bias else None
    n = len(x)
    side, stop, tgt = _arr(n)
    used = set()
    for k in range(1, n):
        if not (win[0] <= hm[k] < win[1]) or not np.isfinite(H[k]) or not np.isfinite(Lo[k]) or not np.isfinite(datr[k]):
            continue
        b = buf * datr[k]
        for lvl, up in ((H[k], True), (Lo[k], False)):
            tag = (key[k], up)
            if tag in used:
                continue
            if mode == "fade":
                hit = (h[k] > lvl and c[k] < lvl) if up else (l[k] < lvl and c[k] > lvl)
                if not hit:
                    continue
                s = -1 if up else 1
                st = (h[k] + 0.1 * b) if up else (l[k] - 0.1 * b)
            else:
                hit = (c[k] > lvl and c[k - 1] <= lvl) if up else (c[k] < lvl and c[k - 1] >= lvl)
                if not hit:
                    continue
                s = 1 if up else -1
                st = (lvl - b) if up else (lvl + b)
            if bz is not None and bz[k] != s:
                used.add(tag)
                continue
            used.add(tag)
            risk = abs(c[k] - st)
            if risk <= 0:
                continue
            if target == "rr":
                tg = c[k] + s * rr * risk
            elif target == "other":
                tg = Lo[k] if up else H[k]
            else:
                tg = (H[k] + Lo[k]) / 2
            side[k], stop[k], tgt[k] = s, st, tg
            break
    return side, stop, tgt


def vp_fade(x, poc="ppoc", vah="pvah", val="pval", win=(420, 1200), bias=None):
    """Rejection at the value-area edge: a candle trades through VAH (VAL) and closes back inside value → fade toward
    the POC; stop beyond the candle's extreme. One per edge per day."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    P, H, Lo, day = x[poc].to_numpy(), x[vah].to_numpy(), x[val].to_numpy(), x["day"].to_numpy()
    bz = x[bias].to_numpy() if bias else None
    n = len(x)
    side, stop, tgt = _arr(n)
    used = set()
    for k in range(n):
        if not (win[0] <= hm[k] < win[1]) or not np.isfinite(P[k]):
            continue
        if (day[k], 1) not in used and h[k] > H[k] and c[k] < H[k] and c[k] > P[k]:
            used.add((day[k], 1))
            if bz is None or bz[k] == -1:
                side[k], stop[k], tgt[k] = -1, h[k], P[k]
        elif (day[k], 0) not in used and l[k] < Lo[k] and c[k] > Lo[k] and c[k] < P[k]:
            used.add((day[k], 0))
            if bz is None or bz[k] == 1:
                side[k], stop[k], tgt[k] = 1, l[k], P[k]
    return side, stop, tgt


def vp_80(x, poc="ppoc", vah="pvah", val="pval", win=(420, 1200), hold_bars=6):
    """80% rule: the day opens outside yesterday's value area, price comes back inside and stays inside for hold_bars
    candles (30 min) → trade to the other edge; stop just outside the edge it re-entered (0.1 daily ATR)."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    H, Lo, day, datr = x[vah].to_numpy(), x[val].to_numpy(), x["day"].to_numpy(), x["datr"].to_numpy()
    n = len(x)
    side, stop, tgt = _arr(n)
    first_open, inside, done = {}, {}, set()
    for k in range(n):
        d = day[k]
        if d not in first_open:
            first_open[d] = o[k]
        if d in done or not np.isfinite(H[k]) or not (win[0] <= hm[k] < win[1]):
            continue
        op = first_open[d]
        if Lo[k] <= op <= H[k]:
            done.add(d)
            continue
        if Lo[k] < c[k] < H[k]:
            inside[d] = inside.get(d, 0) + 1
        else:
            inside[d] = 0
        if inside[d] >= hold_bars:
            done.add(d)
            b = 0.1 * datr[k]
            if op > H[k]:
                side[k], stop[k], tgt[k] = -1, H[k] + b, Lo[k]
            else:
                side[k], stop[k], tgt[k] = 1, Lo[k] - b, H[k]
    return side, stop, tgt


def ema_cross(x, fast=9, slow=21, tf=1, bias=None, vwap=False, rr=2.0, win=(420, 1200), swing=5):
    """EMA fast crosses EMA slow (on 5-min, or on tf x 5-min candles mapped back), optional HTF bias and VWAP side;
    stop at the last `swing` candles' extreme, target rr x risk."""
    c, h, l, hm = x["Close"], x["High"], x["Low"], x["hm"]
    if tf > 1:
        cc = c.resample(f"{5 * tf}min").last().dropna()
        ef, es = L.ema(cc, fast), L.ema(cc, slow)
        cr = np.sign(ef - es)
        cr = cr.shift().reindex(x.index, method="ffill")       # last finished bigger candle
    else:
        cr = np.sign(L.ema(c, fast) - L.ema(c, slow))
    flip = (cr != cr.shift()) & (cr != 0)
    inwin = (hm >= win[0]) & (hm < win[1])
    s = np.where(flip & inwin, cr, 0).astype(float)
    if vwap:
        s = np.where((s > 0) & (c > x["vwap"]) | (s < 0) & (c < x["vwap"]), s, 0)
    if bias:
        s = np.where(s == x[bias], s, 0)
    st = np.where(s > 0, l.rolling(swing).min(), h.rolling(swing).max())
    return s.astype(float), st, (c + rr * (c - st)).to_numpy()


def vwap_cross(x, bias=None, rr=2.0, win=(420, 1200), swing=5):
    """Price crosses the session VWAP with EMA9 above / below EMA21 → with it; stop at the swing; target rr."""
    c, h, l, vw = x["Close"], x["High"], x["Low"], x["vwap"]
    e9, e21 = L.ema(c, 9), L.ema(c, 21)
    up = (c > vw) & (c.shift() <= vw.shift()) & (e9 > e21)
    dn = (c < vw) & (c.shift() >= vw.shift()) & (e9 < e21)
    inwin = (x["hm"] >= win[0]) & (x["hm"] < win[1])
    s = np.where(up & inwin, 1, np.where(dn & inwin, -1, 0)).astype(float)
    if bias:
        s = np.where(s == x[bias], s, 0)
    st = np.where(s > 0, l.rolling(swing).min(), h.rolling(swing).max())
    return s.astype(float), st, (c + rr * (c - st)).to_numpy()


def htf_pullback(x, rr=2.0, win=(420, 1200), swing=6):
    """4H bias (EMA20 vs EMA50) and 1H on the same side of its EMA50; on 5-min price dips to EMA20 and a candle closes
    back above the previous candle's high (mirror short); stop at the swing; target rr."""
    o, h, l, c, hm = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm"))
    e20 = L.ema(x["Close"], 20).to_numpy()
    b4, b1 = x["bias4h"].to_numpy(), x["bias1h"].to_numpy()
    n = len(x)
    side, stop, tgt = _arr(n)
    touched = 0
    for k in range(swing, n):
        if not (win[0] <= hm[k] < win[1]):
            touched = 0
            continue
        b = b4[k] if b4[k] == b1[k] else 0
        if not b:
            touched = 0
            continue
        if (b > 0 and l[k] <= e20[k]) or (b < 0 and h[k] >= e20[k]):
            touched = b
            continue
        if touched == b and ((b > 0 and c[k] > h[k - 1]) or (b < 0 and c[k] < l[k - 1])):
            st = l[k - swing + 1:k + 1].min() if b > 0 else h[k - swing + 1:k + 1].max()
            side[k], stop[k], tgt[k] = b, st, c[k] + b * rr * abs(c[k] - st)
            touched = 0
    return side, stop, tgt
