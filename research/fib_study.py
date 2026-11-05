"""Trend-based Fibonacci on 5-minute charts ("MAGIC" template: 0, 0.5, 0.618, 1.414, 1.618, 2, 2.272, 2.618): do the
levels hold more often than ordinary (non-Fibonacci) levels?

Swings: pivot highs / lows with N candles on each side (known only N candles later), consecutive pivots of opposite
type, swing size ≥ min_atr x ATR(14) of 5-min candles.
1. Retracement (A → B, then price comes back): first touch of B + r x (A - B) for r in Fibonacci and control ratios;
   'held' = price turns back by R (= react x |A - B|) before going R further through. Watched until B or A breaks.
2. Extension (A → B → C, C a confirmed pivot between A and B): first touch of C - e x (A - B) (in the A → B direction)
   for e in the template's ratios and controls; 'held' = turns back by R before going R further.
Random-walk baseline: ~50% held. Fibonacci matters only if its levels hold clearly more often than the controls.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RET_FIB = [0.382, 0.5, 0.618, 0.786]
RET_CTRL = [0.3, 0.45, 0.55, 0.7, 0.85]
EXT_FIB = [0.5, 0.618, 1.0, 1.414, 1.618, 2.0, 2.272, 2.618]
EXT_CTRL = [0.8, 1.2, 1.5, 1.8, 2.4]


def pivots(h, l, n):
    """Pivot highs / lows (strict max / min of the 2n+1 window), returned as (index, type, price), confirmed at i+n."""
    out = []
    for i in range(n, len(h) - n):
        if h[i] == h[i - n:i + n + 1].max() and (h[i - n:i] < h[i]).all():
            out.append((i, 1, h[i]))
        elif l[i] == l[i - n:i + n + 1].min() and (l[i - n:i] > l[i]).all():
            out.append((i, -1, l[i]))
    # keep alternating: for runs of the same type keep the extreme
    alt = []
    for p in out:
        if alt and alt[-1][1] == p[1]:
            if (p[1] == 1 and p[2] > alt[-1][2]) or (p[1] == -1 and p[2] < alt[-1][2]):
                alt[-1] = p
        else:
            alt.append(p)
    return alt


def _held(h, l, start, level, toward_up, R, maxbars):
    """From the touch at `start`: does price move R away from the level on the 'held' side before R through it?
    toward_up=True: price arrived from below (level is resistance): held = falls to level - R first."""
    # the touch candle itself: only a break-through counts (its far side was printed before the touch)
    if (toward_up and h[start] >= level + R) or (not toward_up and l[start] <= level - R):
        return False
    for j in range(start + 1, min(start + maxbars, len(h))):
        if toward_up:
            through, back = h[j] >= level + R, l[j] <= level - R
        else:
            through, back = l[j] <= level - R, h[j] >= level + R
        if through and back:
            return None   # both in one candle: unknown
        if back:
            return True
        if through:
            return False
    return None


def study(df: pd.DataFrame, n: int = 12, min_atr: float = 6.0, react: float = 0.15, maxbars: int = 288):
    x = df[~df.index.duplicated(keep="last")].sort_index()
    h, l, c = (x[k].to_numpy(float) for k in ("High", "Low", "Close"))
    pc = np.r_[c[0], c[:-1]]
    atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    P = pivots(h, l, n)
    ret, ext = [], []
    for k in range(1, len(P)):
        (ia, ta, pa), (ib, tb, pb) = P[k - 1], P[k]
        size = abs(pa - pb)
        if size < min_atr * atr[ib]:
            continue
        down = ta == 1                     # A high -> B low
        R = react * size
        t0 = ib + n                         # B confirmed
        # 1. retracement: watch from confirmation until A or B breaks
        end = min(len(h), t0 + maxbars)
        seg_h, seg_l = h[t0:end], l[t0:end]
        brk = np.flatnonzero((seg_l < pb) if down else (seg_h > pb))
        stop_at = t0 + (brk[0] if len(brk) else len(seg_h))
        for r, kind in [(r, "fib") for r in RET_FIB] + [(r, "ctrl") for r in RET_CTRL]:
            lvl = pb + r * (pa - pb)
            hit = np.flatnonzero((h[t0:stop_at] >= lvl) if down else (l[t0:stop_at] <= lvl))
            if not len(hit):
                continue
            j = t0 + hit[0]
            res = _held(h, l, j, lvl, down, R, maxbars)
            if res is not None:
                ret.append({"t": x.index[j], "ratio": r, "kind": kind, "held": res, "dir": -1 if down else 1})
        # 2. extension from C (the next pivot, a retracement inside A-B)
        if k + 1 < len(P):
            ic, tc, pcv = P[k + 1]
            if (down and pb < pcv < pa) or (not down and pa < pcv < pb):
                t1 = ic + n
                end2 = min(len(h), t1 + maxbars)
                for e, kind in [(e, "fib") for e in EXT_FIB] + [(e, "ctrl") for e in EXT_CTRL]:
                    lvl = pcv - e * (pa - pb) if not down else pcv - e * (pa - pb)
                    # down swing: pa > pb, levels below C: C - e*(A-B); up swing: pa < pb, levels above C
                    hit = np.flatnonzero((l[t1:end2] <= lvl) if down else (h[t1:end2] >= lvl))
                    if not len(hit):
                        continue
                    j = t1 + hit[0]
                    res = _held(h, l, j, lvl, not down, R, maxbars)
                    if res is not None:
                        ext.append({"t": x.index[j], "ratio": e, "kind": kind, "held": res, "dir": -1 if down else 1})
    return pd.DataFrame(ret), pd.DataFrame(ext)


def summary(t: pd.DataFrame) -> pd.DataFrame:
    if t.empty:
        return t
    g = t.groupby(["kind", "ratio"])["held"].agg(touches="size", held_pct=lambda s: s.mean() * 100)
    return g.round(1)
