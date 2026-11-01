"""Momentum measures on the continuous 5-min series of an index, returned as [day, slot] arrays (known at bar close)."""
import numpy as np, pandas as pd
from engine import Data, NSLOT

def _flat(d, s):
    O, H, L, C = (a[s].reshape(-1) for a in (d.O, d.H, d.L, d.C)); idx = np.where(np.isfinite(C))[0]
    return O[idx], H[idx], L[idx], C[idx], idx, d.C[s].shape

def _back(arr, idx, shape):
    f = np.full(shape[0] * shape[1], np.nan); f[idx] = arr; return f.reshape(shape)

def measures(d: Data, sym: str, vwap_other=None):
    s = d.idx(sym); o, h, l, c, idx, shape = _flat(d, s)
    rma = lambda x, n: pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); atr = rma(tr, 14)
    up = np.r_[0, np.diff(h)]; dn = np.r_[0, -np.diff(l)]
    pdm = np.where((up > dn) & (up > 0), up, 0); mdm = np.where((dn > up) & (dn > 0), dn, 0)
    pdi = 100 * rma(pdm, 14) / atr; mdi = 100 * rma(mdm, 14) / atr
    adx = rma(100 * abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9), 14)
    ch = np.diff(c, prepend=c[0]); g = rma(np.maximum(ch, 0), 14); ls = rma(np.maximum(-ch, 0), 14)
    rsi = 100 - 100 / (1 + g / np.maximum(ls, 1e-9))
    ema = lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()
    macd = ema(c, 12) - ema(c, 26); hist = macd - ema(macd, 9); hist_prev = np.r_[0, hist[:-1]]
    rng = h - l; avg_rng = pd.Series(rng).rolling(20).mean().shift(1).to_numpy()
    body = (c - o) / np.where(rng > 0, rng, np.nan)
    m = {k: _back(v, idx, shape) for k, v in dict(adx=adx, pdi=pdi, mdi=mdi, rsi=rsi, hist=hist, hist_prev=hist_prev,
                                                     rng_x=rng / avg_rng, body=body).items()}
    day_open = d.O[s, :, 0][:, None]; datr = d.atr[s][:, None]
    m["day_mom"] = (d.C[s] - day_open) / datr   # move from today's open in daily-ATR units
    return m
