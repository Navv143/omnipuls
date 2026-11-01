"""Fast grid backtester: thousands of indicator settings x timeframes, then walk-forward (monthly re-tuning).

Signals are evaluated at a bar's close; entry at that close. One position at a time per setting.
Exit: stop (k x ATR or the signal candle's extreme), target R x risk, max bars, or the session end (index).
Inside a bar the stop is assumed hit before the target (conservative).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit


# ---------------------------------------------------------------- indicators (pandas, cached by caller)

def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return rma(tr, n)


def rsi(c, n):
    ch = np.diff(c, prepend=c[0])
    g, ls = rma(np.maximum(ch, 0), n), rma(np.maximum(-ch, 0), n)
    return 100 - 100 / (1 + g / np.maximum(ls, 1e-12))


def vwap_session(h, l, c, v, day_id):
    tp = (h + l + c) / 3
    df = pd.DataFrame({"pv": tp * v, "v": v, "d": day_id})
    g = df.groupby("d")
    return (g["pv"].cumsum() / g["v"].cumsum().replace(0, np.nan)).to_numpy()


def supertrend_dir(h, l, c, n, mult):
    a = atr(h, l, c, n)
    hl2 = (h + l) / 2
    up, dn = hl2 - mult * a, hl2 + mult * a
    return _st(c, up, dn)


@njit(cache=True)
def _st(c, up, dn):
    n = len(c)
    d = np.ones(n)
    line = np.empty(n)
    fu, fd = up[0], dn[0]
    for i in range(n):
        if i > 0:
            fu = max(up[i], fu) if c[i - 1] > fu else up[i]
            fd = min(dn[i], fd) if c[i - 1] < fd else dn[i]
            if d[i - 1] > 0 and c[i] < fu:
                d[i] = -1
            elif d[i - 1] < 0 and c[i] > fd:
                d[i] = 1
            else:
                d[i] = d[i - 1]
        line[i] = fu if d[i] > 0 else fd
    return d, line


# ---------------------------------------------------------------- simulator

@njit(cache=True)
def simulate(o, h, l, c, day_id, can_enter, must_exit, long_sig, short_sig, stop_dist, rr, max_hold):
    """Returns arrays: entry_idx, exit_idx, side, entry_price, exit_price."""
    n = len(c)
    ei = np.empty(n, np.int64); xi = np.empty(n, np.int64); sd = np.empty(n, np.int64)
    ep = np.empty(n); xp = np.empty(n)
    k = 0
    i = 0
    while i < n - 1:
        side = 0
        if can_enter[i] and stop_dist[i] > 0:
            if long_sig[i]:
                side = 1
            elif short_sig[i]:
                side = -1
        if side == 0:
            i += 1
            continue
        e = c[i]
        stop = e - side * stop_dist[i]
        tgt = e + side * rr * stop_dist[i] if rr > 0 else np.nan
        j = i + 1
        px = np.nan
        while j < n:
            if day_id[j] != day_id[i] and must_exit[i] >= 0:  # session ended (index): exit at prior close
                px = c[j - 1]; j = j - 1; break
            if side > 0 and l[j] <= stop:
                px = min(o[j], stop); break
            if side < 0 and h[j] >= stop:
                px = max(o[j], stop); break
            if rr > 0 and side > 0 and h[j] >= tgt:
                px = max(o[j], tgt); break
            if rr > 0 and side < 0 and l[j] <= tgt:
                px = min(o[j], tgt); break
            if must_exit[j] == 1 or j - i >= max_hold:
                px = c[j]; break
            j += 1
        if j >= n:
            j = n - 1; px = c[j]
        ei[k] = i; xi[k] = j; sd[k] = side; ep[k] = e; xp[k] = px
        k += 1
        i = j + 1
    return ei[:k], xi[:k], sd[:k], ep[:k], xp[:k]


# ---------------------------------------------------------------- one timeframe bundle

class Frame:
    def __init__(self, bars: pd.DataFrame, session=True, first="09:20", last="14:45", exit_at="15:15"):
        self.bars = bars
        self.t = bars.index
        self.o, self.h, self.l, self.c, self.v = (bars[k].to_numpy(float) for k in ("o", "h", "l", "c", "v"))
        dates = self.t.normalize()
        self.day_id = pd.factorize(dates)[0].astype(np.int64)
        tm = self.t.strftime("%H:%M")
        if session:
            self.can_enter = ((tm >= first) & (tm <= last)).astype(np.bool_)
            self.must_exit = (tm >= exit_at).astype(np.int64)
        else:
            self.can_enter = np.ones(len(bars), np.bool_)
            self.must_exit = np.full(len(bars), -1, np.int64)  # never forced (24h market)
        self.atr = atr(self.h, self.l, self.c, 14)
        self.month = self.t.to_period("M")
        self._cache = {}

    def get(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def run(self, long_sig, short_sig, stop_dist, rr, max_hold, cost):
        ei, xi, sd, ep, xp = simulate(self.o, self.h, self.l, self.c, self.day_id, self.can_enter, self.must_exit,
                                      np.asarray(long_sig, np.bool_), np.asarray(short_sig, np.bool_),
                                      np.nan_to_num(np.asarray(stop_dist, float)), float(rr), int(max_hold))
        ret = sd * (xp / ep - 1) - cost
        return pd.DataFrame({"t": self.t[ei], "side": sd, "ret": ret, "bars": xi - ei})
