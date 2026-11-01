"""Trader-style setting grids. Each generator yields (family, params_str, tf, long, short, stop_dist, rr, max_hold)."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

import grid_engine as G

STOPS = (("1.0ATR", 1.0), ("1.5ATR", 1.5))
RRS = (1.5, 2.0, 3.0)
HOLDS = (20, 60)


def _cross_up(a, b):
    a_prev, b_prev = np.r_[np.nan, a[:-1]], np.r_[np.nan, b[:-1]] if np.ndim(b) else b
    return (a > b) & (a_prev <= b_prev)


def _cross_dn(a, b):
    a_prev, b_prev = np.r_[np.nan, a[:-1]], np.r_[np.nan, b[:-1]] if np.ndim(b) else b
    return (a < b) & (a_prev >= b_prev)


def _exits(F, long, short, fam, p, tf, extra_stop=None):
    for (sn, sk), rr, hold in itertools.product(STOPS, RRS, HOLDS):
        yield fam, f"{p} | stop {sn} | {rr}R | hold {hold}", tf, long, short, sk * F.atr, rr, hold
    if extra_stop is not None:
        for rr, hold in itertools.product(RRS, HOLDS):
            yield fam, f"{p} | stop candle | {rr}R | hold {hold}", tf, long, short, extra_stop, rr, hold


def htf_to_ltf(htf: G.Frame, ltf: G.Frame, values: np.ndarray, htf_min: int, ltf_min: int):
    """Value of the last HTF bar fully completed by the close of each LTF bar."""
    h_end = (htf.t + pd.Timedelta(minutes=htf_min)).values
    l_close = (ltf.t + pd.Timedelta(minutes=ltf_min)).values
    pos = np.searchsorted(h_end, l_close, side="right") - 1
    out = np.full(len(ltf.t), np.nan)
    ok = pos >= 0
    out[ok] = values[pos[ok]]
    return out


def mtf_ema_retest(frames: dict, htfs=(15, 30, 60), ltfs=(3, 5), lens=(9, 21, 50)):
    for H, Lm, n in itertools.product(htfs, ltfs, lens):
        if H not in frames or Lm not in frames or H <= Lm:
            continue
        hf, lf = frames[H], frames[Lm]
        he = hf.get(f"ema{n}", lambda: G.ema(hf.c, n))
        bias_h = np.sign(hf.c - he)                       # HTF close above/below its EMA
        bias = htf_to_ltf(hf, lf, bias_h, H, Lm)
        le = lf.get(f"ema{n}", lambda: G.ema(lf.c, n))
        long = (bias > 0) & (lf.l <= le) & (lf.c > le)    # pulled back to touch the EMA, closed back above
        short = (bias < 0) & (lf.h >= le) & (lf.c < le)
        cand = np.where(long, lf.c - lf.l, np.where(short, lf.h - lf.c, 0)) + 0.1 * lf.atr
        yield from _exits(lf, long, short, "MTF EMA break + retest", f"HTF {H}m, LTF {Lm}m, EMA {n}", Lm, cand)


def ema_cross(frames: dict, tfs=(3, 5, 15), pairs=((5, 13), (9, 21), (9, 50), (13, 34), (21, 50))):
    for tf, (a, b) in itertools.product(tfs, pairs):
        if tf not in frames:
            continue
        F = frames[tf]
        fa, fb = F.get(f"ema{a}", lambda: G.ema(F.c, a)), F.get(f"ema{b}", lambda: G.ema(F.c, b))
        vw = F.get("vwap", lambda: G.vwap_session(F.h, F.l, F.c, F.v, F.day_id))
        up, dn = _cross_up(fa, fb), _cross_dn(fa, fb)
        yield from _exits(F, up, dn, "EMA cross", f"{tf}m EMA {a}/{b}", tf)
        yield from _exits(F, up & (F.c > vw), dn & (F.c < vw), "EMA cross + VWAP", f"{tf}m EMA {a}/{b} + VWAP side", tf)


def rsi_family(frames: dict, tfs=(3, 5, 15), periods=(2, 3, 5, 7, 9, 14, 21)):
    for tf, n in itertools.product(tfs, periods):
        if tf not in frames:
            continue
        F = frames[tf]
        r = F.get(f"rsi{n}", lambda: G.rsi(F.c, n))
        for lo in (10, 20, 30):   # mean reversion: crosses back up out of oversold
            yield from _exits(F, _cross_up(r, lo), _cross_dn(r, 100 - lo), "RSI reversion", f"{tf}m RSI{n} {lo}/{100-lo}", tf)
        for hi in (55, 60, 65, 70):  # momentum: crosses into strength
            yield from _exits(F, _cross_up(r, hi), _cross_dn(r, 100 - hi), "RSI momentum", f"{tf}m RSI{n} >{hi}/<{100-hi}", tf)


def multi_rsi(frames: dict, tfs=(3, 5, 15), sets=((3, 7, 14), (2, 5, 14), (5, 9, 21))):
    for tf, ps in itertools.product(tfs, sets):
        if tf not in frames:
            continue
        F = frames[tf]
        rs = [F.get(f"rsi{n}", lambda n=n: G.rsi(F.c, n)) for n in ps]
        for th in (55, 60, 65):
            allup = np.logical_and.reduce([x > th for x in rs]); alldn = np.logical_and.reduce([x < 100 - th for x in rs])
            up = allup & ~np.r_[False, allup[:-1]]; dn = alldn & ~np.r_[False, alldn[:-1]]
            yield from _exits(F, up, dn, "Multi-RSI agree", f"{tf}m RSI{ps} all >{th}", tf)


def macd_family(frames: dict, tfs=(3, 5, 15), sets=((12, 26, 9), (8, 21, 5), (5, 13, 3), (3, 10, 16))):
    for tf, (a, b, s) in itertools.product(tfs, sets):
        if tf not in frames:
            continue
        F = frames[tf]
        m = G.ema(F.c, a) - G.ema(F.c, b); sig = G.ema(m, s)
        yield from _exits(F, _cross_up(m, sig), _cross_dn(m, sig), "MACD", f"{tf}m MACD{a},{b},{s} signal cross", tf)
        yield from _exits(F, _cross_up(m, sig) & (m > 0), _cross_dn(m, sig) & (m < 0), "MACD", f"{tf}m MACD{a},{b},{s} cross with trend", tf)
        yield from _exits(F, _cross_up(m, 0), _cross_dn(m, 0), "MACD", f"{tf}m MACD{a},{b},{s} zero cross", tf)


def bollinger_family(frames: dict, tfs=(3, 5, 15), lens=(10, 20, 30), stds=(1.5, 2.0, 2.5)):
    for tf, n, k in itertools.product(tfs, lens, stds):
        if tf not in frames:
            continue
        F = frames[tf]
        mid = pd.Series(F.c).rolling(n).mean().to_numpy(); sd = pd.Series(F.c).rolling(n).std().to_numpy()
        up, lo = mid + k * sd, mid - k * sd
        yield from _exits(F, _cross_up(F.c, up), _cross_dn(F.c, lo), "Bollinger breakout", f"{tf}m BB{n},{k}", tf)
        yield from _exits(F, _cross_up(F.c, lo), _cross_dn(F.c, up), "Bollinger reversion", f"{tf}m BB{n},{k}", tf)


def supertrend_family(frames: dict, tfs=(3, 5, 15), ns=(7, 10, 14), mults=(1.5, 2.0, 3.0)):
    for tf, n, m in itertools.product(tfs, ns, mults):
        if tf not in frames:
            continue
        F = frames[tf]
        d, line = G.supertrend_dir(F.h, F.l, F.c, n, m)
        flip_up = (d > 0) & (np.r_[0, d[:-1]] < 0); flip_dn = (d < 0) & (np.r_[0, d[:-1]] > 0)
        yield from _exits(F, flip_up, flip_dn, "Supertrend flip", f"{tf}m ST {n},{m}", tf, np.abs(F.c - line))


ALL = (mtf_ema_retest, ema_cross, rsi_family, multi_rsi, macd_family, bollinger_family, supertrend_family)
