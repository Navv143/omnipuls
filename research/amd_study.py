"""ICT 'AMD model' (accumulation, manipulation, distribution) from an envxytrades reel: liquidity sweep of the higher-
timeframe range + SMT divergence with a correlated market + CISD on 5-min as the trigger.

- Accumulation: the high / low of the last `n_range` finished higher-timeframe candles (htf minutes).
- Sweep: a 5-min candle trades above the range high (sell setup) or below the range low (buy setup); one setup per
  range side per higher-timeframe candle.
- SMT (optional): at the same 5-min candle the partner market does NOT trade beyond its own range high / low.
- CISD: the run of same-colour candles that made the sweep (up candles into a high sweep) started at an open; a
  5-min close back through that open within `window` candles is the trigger. Entry at the next open; stop at the
  extreme since the sweep; target rr x risk ('rr') or the opposite side of the range ('range').
Run with strategy_lab.simulate (stop first when stop and target share a candle, costs, max trades a day).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def htf_range(x: pd.DataFrame, htf: int, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Range of the last n finished htf-minute candles, mapped to each 5-min candle, and the htf candle id."""
    g = x[["High", "Low"]].resample(f"{htf}min").agg({"High": "max", "Low": "min"}).dropna()
    hi = g["High"].rolling(n).max().shift()
    lo = g["Low"].rolling(n).min().shift()
    key = x.index.floor(f"{htf}min")
    return hi.reindex(key).to_numpy(), lo.reindex(key).to_numpy(), key.asi8


def signals(x: pd.DataFrame, partner: pd.DataFrame | None, htf=30, n_range=6, window=12, rr=2.0, target="rr",
            smt=True):
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    Rh, Rl, key = htf_range(x, htf, n_range)
    if smt and partner is not None:
        p = partner.reindex(x.index).ffill()
        ph, pl = p["High"].to_numpy(float), p["Low"].to_numpy(float)
        PRh, PRl, _ = htf_range(p, htf, n_range)
    n = len(x)
    side, stop, tgt = np.zeros(n), np.full(n, np.nan), np.full(n, np.nan)
    used = set()
    k = 1
    while k < n - 1:
        if not (np.isfinite(Rh[k]) and np.isfinite(Rl[k])):
            k += 1
            continue
        s = 0
        if h[k] > Rh[k] and (key[k], -1) not in used:
            s = -1
        elif l[k] < Rl[k] and (key[k], 1) not in used:
            s = 1
        if not s:
            k += 1
            continue
        used.add((key[k], s))
        if smt and partner is not None:
            if not (np.isfinite(PRh[k]) and np.isfinite(PRl[k])):
                k += 1
                continue
            if (s < 0 and ph[k] > PRh[k]) or (s > 0 and pl[k] < PRl[k]):
                k += 1          # the partner swept too: no divergence
                continue
        # CISD level: the open of the run of candles into the sweep (up candles for a high sweep)
        j = k
        if s < 0:
            while j - 1 >= 0 and c[j - 1] > o[j - 1]:
                j -= 1
        else:
            while j - 1 >= 0 and c[j - 1] < o[j - 1]:
                j -= 1
        lvl = o[j] if j < k else o[k]
        ext = h[k] if s < 0 else l[k]
        fired = False
        for m in range(k + 1, min(k + 1 + window, n - 1)):
            ext = max(ext, h[m]) if s < 0 else min(ext, l[m])
            if (s < 0 and c[m] < lvl) or (s > 0 and c[m] > lvl):
                st = ext
                if s * (c[m] - st) <= 0:
                    break
                side[m], stop[m] = s, st
                tgt[m] = c[m] + s * rr * abs(c[m] - st) if target == "rr" else (Rl[k] if s < 0 else Rh[k])
                fired = True
                k = m + 1
                break
        if not fired:
            k += 1
    return side, stop, tgt
