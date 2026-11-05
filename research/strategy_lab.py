"""Strategy lab: popular intraday setups from GitHub (freqtrade), YouTube and papers, tested on BTC and gold with the
same rules as sniper_study.py: entry at the next candle's open, stop and target in the same candle = stop, costs per
round trip (BTC 0.05%, gold 0.02%), at most N trades a day, one position at a time, tune 2023-24 / confirm 2025-26.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- indicators

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n):
    d = s.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df, n=10, mult=3.0):
    a = atr(df, n).to_numpy()
    hl2 = ((df["High"] + df["Low"]) / 2).to_numpy()
    c = df["Close"].to_numpy()
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fu, fl, d, line = ub.copy(), lb.copy(), np.ones(len(c)), np.zeros(len(c))
    for i in range(1, len(c)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = 1 if c[i] > fu[i - 1] else -1 if c[i] < fl[i - 1] else d[i - 1]
        line[i] = fl[i] if d[i] > 0 else fu[i]
    return pd.Series(d, index=df.index), pd.Series(line, index=df.index)


def stochrsi(s, n=14, k=3, d=3):
    r = rsi(s, n)
    st = (r - r.rolling(n).min()) / (r.rolling(n).max() - r.rolling(n).min()).replace(0, np.nan) * 100
    kk = st.rolling(k).mean()
    return kk, kk.rolling(d).mean()


def resample(df, rule):
    x = df.resample(rule, label="left", closed="left").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                                          "Volume": "sum"}).dropna()
    return x


def local(df, tz):
    lt = df.index.tz_convert(tz)
    x = df.copy()
    x["day"] = lt.normalize().tz_localize(None)
    x["hm"] = lt.hour * 60 + lt.minute
    return x


# ---------------------------------------------------------------- generic simulator

def simulate(x, side, stop, target, cost, max_per_day=1, exit_hm=None, max_hold=None, exit_sig=None, days_from=None):
    """side/stop/target: arrays aligned to x (signal at the candle's close, NaN / 0 = none). Enter at the next open; one
    position at a time; exit at stop / target (stop first if both), exit_sig (close of that candle), the first candle at
    or after exit_hm (that candle's open), or max_hold candles. Returns the trades."""
    o, h, l, c = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    hm, day = x["hm"].to_numpy(), x["day"].to_numpy()
    sd, sp, tg = np.nan_to_num(side), stop, target
    ex = exit_sig if exit_sig is not None else None
    out, k, n = [], 0, len(x)
    per_day = {}
    idx = np.flatnonzero(sd != 0)
    j = 0
    busy_until = -1
    for k in idx:
        if k <= busy_until or k + 1 >= n:
            continue
        d = day[k]
        if per_day.get(d, 0) >= max_per_day:
            continue
        s = int(sd[k])
        i = k + 1
        e = o[i]
        st_, tp = sp[k], tg[k]
        if not np.isfinite(st_) or s * (e - st_) <= 0:
            continue
        if np.isfinite(tp) and s * (tp - e) <= 0:
            continue
        px, how, m = None, "end", i
        for m in range(i, n):
            if exit_hm is not None and m > i and (day[m] != d or hm[m] >= exit_hm):
                px, how = o[m], "time"
                break
            if max_hold is not None and m - i >= max_hold:
                px, how = o[m], "time"
                break
            if (s > 0 and l[m] <= st_) or (s < 0 and h[m] >= st_):
                px, how = st_, "stop"
                break
            if np.isfinite(tp) and ((s > 0 and h[m] >= tp) or (s < 0 and l[m] <= tp)):
                px, how = tp, "target"
                break
            if ex is not None and ((s > 0 and ex[m] > 0) or (s < 0 and ex[m] < 0)):
                px, how = c[m], "exit"
                break
        if px is None:
            px = c[m]
        risk = abs(e - st_)
        out.append({"day": pd.Timestamp(d), "side": s, "r": (s * (px - e) - e * cost / 100) / risk,
                    "pct": s * (px / e - 1) * 100 - cost, "how": how, "stop_pct": risk / e * 100, "bars": m - i})
        per_day[d] = per_day.get(d, 0) + 1
        busy_until = m
    return pd.DataFrame(out)


def report(name, t, split="2025-01-01"):
    if t is None or t.empty or len(t) < 20:
        print(f"{name:58s} n={0 if t is None else len(t)}")
        return None
    a, b = t[t["day"] < split], t[t["day"] >= split]
    f = lambda z: (z["r"].mean() if len(z) else np.nan)  # noqa: E731
    tt = t["r"].mean() / t["r"].std(ddof=1) * np.sqrt(len(t))
    yrs = t.groupby(t["day"].dt.year)["r"].mean()
    pos_y = int((yrs > 0).sum())
    days = t["day"].nunique()
    span = (t["day"].max() - t["day"].min()).days or 1
    print(f"{name:58s} n={len(t):5d} ({len(t) / span * 7:.1f}/wk) win={(t['r'] > 0).mean() * 100:3.0f}% "
          f"avgR={t['r'].mean():+.3f} t={tt:+.2f} | tune {f(a):+.3f} test {f(b):+.3f} | yrs+ {pos_y}/{len(yrs)} "
          f"| stop {t['stop_pct'].median():.2f}% | %/trade {t['pct'].mean():+.3f}")
    return {"name": name, "n": len(t), "avgR": t["r"].mean(), "t": tt, "tune": f(a), "test": f(b), "yrs_pos": pos_y,
            "yrs": len(yrs)}


# ---------------------------------------------------------------- strategies (each returns side, stop, target arrays + kwargs)

def s_silver_bullet(x, win=(600, 660), rr=2.0, look=12):
    """ICT Silver Bullet: inside the window a candle sweeps the high / low of the previous `look` candles, then a
    displacement leaves a fair value gap (3-candle gap) the other way inside the window; entry when price retests the
    gap (signal on the retest candle's close back out of it), stop beyond the sweep extreme, target rr x risk."""
    o, h, l, c, hm, day = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm", "day"))
    n = len(x)
    side, stop, tgt = np.zeros(n), np.full(n, np.nan), np.full(n, np.nan)
    state = {}
    for k in range(look + 2, n):
        if not (win[0] <= hm[k] < win[1]):
            continue
        d = day[k]
        s = state.setdefault(d, {"sweep": 0, "ext": None, "fvg": None, "done": False})
        if s["done"]:
            continue
        hi, lo = h[k - look:k].max(), l[k - look:k].min()
        if s["sweep"] == 0:
            if h[k] > hi:
                s.update(sweep=-1, ext=h[k])     # swept highs -> look for a short
            elif l[k] < lo:
                s.update(sweep=1, ext=l[k])
            continue
        s["ext"] = max(s["ext"], h[k]) if s["sweep"] < 0 else min(s["ext"], l[k])
        if s["fvg"] is None:
            if s["sweep"] > 0 and l[k] > h[k - 2] and c[k] > o[k]:
                s["fvg"] = (h[k - 2], l[k])          # bullish gap: [top of k-2, bottom of k]
            elif s["sweep"] < 0 and h[k] < l[k - 2] and c[k] < o[k]:
                s["fvg"] = (h[k], l[k - 2])
            continue
        lo_g, hi_g = s["fvg"]
        if s["sweep"] > 0 and l[k] <= hi_g and c[k] > lo_g:
            side[k], stop[k] = 1, s["ext"]
            tgt[k] = c[k] + rr * (c[k] - s["ext"])
            s["done"] = True
        elif s["sweep"] < 0 and h[k] >= lo_g and c[k] < hi_g:
            side[k], stop[k] = -1, s["ext"]
            tgt[k] = c[k] - rr * (s["ext"] - c[k])
            s["done"] = True
    return side, stop, tgt


def s_binhv45(x, tp_pct=1.0, sl_pct=1.0):
    """freqtrade BinHV45 (long only): BB(40,2); lower band falling, band width > 0.8% of price, close-to-close move
    > 1.75%, small lower tail, close below the previous lower band and not above the previous close."""
    c, l = x["Close"], x["Low"]
    mid, sd = c.rolling(40).mean(), c.rolling(40).std()
    lower = mid - 2 * sd
    bbdelta = (mid - lower).abs()
    closedelta = (c - c.shift()).abs()
    tail = (c - l).abs()
    sig = (lower.shift() > 0) & (bbdelta > c * 0.008) & (closedelta > c * 0.0175) & (tail < bbdelta * 0.25) & \
          (c < lower.shift()) & (c <= c.shift())
    side = np.where(sig, 1, 0).astype(float)
    return side, (c * (1 - sl_pct / 100)).to_numpy(), (c * (1 + tp_pct / 100)).to_numpy()


def s_clucmay(x, sl_pct=1.0):
    """freqtrade ClucMay72018 (long only): close < EMA100, close < 0.985 x BB(20,2) lower, volume < 20 x its 30-bar
    mean; exit when the close is above the middle band."""
    c, v = x["Close"], x["Volume"]
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    lower = mid - 2 * sd
    sig = (c < ema(c, 100)) & (c < 0.985 * lower) & (v < v.rolling(30).mean().shift() * 20)
    side = np.where(sig, 1, 0).astype(float)
    ex = np.where(c > mid, 1, 0).astype(float)
    return side, (c * (1 - sl_pct / 100)).to_numpy(), np.full(len(c), np.nan), ex


def s_ema200_macd(x, rr=1.5):
    """YouTube classic: price above EMA200 and MACD(12,26,9) crosses above its signal below zero → long (mirror short);
    stop at EMA200, target rr x risk."""
    c = x["Close"]
    e200 = ema(c, 200)
    macd = ema(c, 12) - ema(c, 26)
    sg = ema(macd, 9)
    up = (macd > sg) & (macd.shift() <= sg.shift()) & (macd < 0) & (c > e200)
    dn = (macd < sg) & (macd.shift() >= sg.shift()) & (macd > 0) & (c < e200)
    side = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    st = e200.to_numpy()
    tg = (c + rr * (c - e200)).to_numpy()
    return side, st, tg


def s_supertrend_stoch(x, rr=1.5):
    """Viral video: price above EMA200, Supertrend(10,3) up, Stoch RSI K crosses above D from below 20 → long (mirror);
    stop at the Supertrend line, target rr x risk."""
    c = x["Close"]
    e200 = ema(c, 200)
    d, line = supertrend(x)
    k, dd = stochrsi(c)
    up = (c > e200) & (d > 0) & (k > dd) & (k.shift() <= dd.shift()) & (k.shift() < 20)
    dn = (c < e200) & (d < 0) & (k < dd) & (k.shift() >= dd.shift()) & (k.shift() > 80)
    side = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    return side, line.to_numpy(), (c + rr * (c - line)).to_numpy()


def s_ema_cross_vwap(x, rr=2.0, win=(480, 1200)):
    """EMA 9 crosses EMA 21 on the side of the session VWAP, in the window; stop at the last 5 candles' extreme."""
    c, h, l = x["Close"], x["High"], x["Low"]
    tp = (x["High"] + x["Low"] + c) / 3
    v = x["Volume"].replace(0, np.nan).fillna(1e-9)
    vw = (tp * v).groupby(x["day"]).cumsum() / v.groupby(x["day"]).cumsum()
    e9, e21 = ema(c, 9), ema(c, 21)
    inwin = (x["hm"] >= win[0]) & (x["hm"] < win[1])
    up = inwin & (e9 > e21) & (e9.shift() <= e21.shift()) & (c > vw)
    dn = inwin & (e9 < e21) & (e9.shift() >= e21.shift()) & (c < vw)
    side = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    st = np.where(up, l.rolling(5).min(), h.rolling(5).max())
    return side, st, (c + rr * (c - st)).to_numpy()


def s_squeeze(x, rr=2.0, win=(480, 1200)):
    """Bollinger squeeze: BB(20,2) inside Keltner(20,1.5 ATR) for 6+ candles, then the close breaks the band; stop at
    the middle band, target rr x risk."""
    c = x["Close"]
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    a = atr(x, 20)
    sq = ((mid + 2 * sd) < (mid + 1.5 * a)) & ((mid - 2 * sd) > (mid - 1.5 * a))
    was = sq.shift().rolling(6).sum() >= 6
    inwin = (x["hm"] >= win[0]) & (x["hm"] < win[1])
    up = inwin & was & (c > mid + 2 * sd)
    dn = inwin & was & (c < mid - 2 * sd)
    side = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    return side, mid.to_numpy(), (c + rr * (c - mid)).to_numpy()


def s_rsi2(x, lo=10, hi=90, sl_atr=2.0):
    """Connors RSI(2): above EMA200 and RSI(2) < 10 → long; exit when the close is above SMA5 (mirror short); stop
    sl_atr x ATR(14)."""
    c = x["Close"]
    r2, e200, s5, a = rsi(c, 2), ema(c, 200), c.rolling(5).mean(), atr(x)
    up, dn = (c > e200) & (r2 < lo), (c < e200) & (r2 > hi)
    side = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    st = np.where(up, c - sl_atr * a, c + sl_atr * a)
    ex = np.where(c > s5, 1, np.where(c < s5, -1, 0)).astype(float)
    return side, st, np.full(len(c), np.nan), ex


def s_donchian(x, n=20, rr=2.0, win=(480, 1200)):
    """Turtle: close beyond the last n candles' high / low in the window; stop at the n/2-candle opposite extreme."""
    c, h, l = x["Close"], x["High"], x["Low"]
    hi, lo = h.shift().rolling(n).max(), l.shift().rolling(n).min()
    inwin = (x["hm"] >= win[0]) & (x["hm"] < win[1])
    up, dn = inwin & (c > hi), inwin & (c < lo)
    side = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    st = np.where(up, l.rolling(n // 2).min(), h.rolling(n // 2).max())
    return side, st, (c + rr * (c - st)).to_numpy()


def s_open_mom(x, a=(500, 530), sl_pct=0.5):
    """First 30 minutes after an open (gold: COMEX 8:20 ET) → trade its direction from a[1]; stop sl_pct; exit by
    the simulator's exit_hm."""
    c, o, hm, day = x["Close"].to_numpy(), x["Open"].to_numpy(), x["hm"].to_numpy(), x["day"].to_numpy()
    n = len(x)
    side, st = np.zeros(n), np.full(n, np.nan)
    first = {}
    for k in range(n):
        if hm[k] == a[0]:
            first[day[k]] = o[k]
        if hm[k] == a[1] - 5 and day[k] in first:
            s = 1 if c[k] > first[day[k]] else -1
            side[k], st[k] = s, c[k] * (1 - s * sl_pct / 100)
    return side, st, np.full(n, np.nan)


def s_time_bias(x, at=600, sl_pct=1.0, side_=1):
    """Gold 'bias' (vendor): long at 10:00 New York, exit 2:00 next morning (max_hold); stop sl_pct."""
    c, hm = x["Close"].to_numpy(), x["hm"].to_numpy()
    n = len(x)
    side = np.where(hm == at - 5, side_, 0).astype(float)
    return side, c * (1 - side_ * sl_pct / 100), np.full(n, np.nan)


def s_flash(x, drop_pct=1.0, tp_pct=1.0, sl_pct=1.0, both=True, z=None):
    """Capitulation / spike fade (the idea behind BinHV45): a 5-min close-to-close drop of drop_pct% or more (or, with
    z, a move of z x the 20-day 5-min stdev) → buy at the next open, target tp_pct, stop sl_pct (mirror for spikes)."""
    c = x["Close"]
    ch = c.pct_change() * 100
    if z:
        sd = ch.rolling(288 * 20, min_periods=288 * 5).std().shift()
        up, dn = ch <= -z * sd, ch >= z * sd
    else:
        up, dn = ch <= -drop_pct, ch >= drop_pct
    side = np.where(up, 1, np.where(dn & both, -1, 0)).astype(float)
    st = np.where(up, c * (1 - sl_pct / 100), c * (1 + sl_pct / 100))
    tg = np.where(up, c * (1 + tp_pct / 100), c * (1 - tp_pct / 100))
    return side, st, tg
