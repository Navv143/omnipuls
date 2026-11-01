"""The Trade Room - 9 & 15 EMA scalping (Bank Nifty / Nifty, 5-min), rules from the video summary:
- Trend: EMA9 above EMA15 (buy) / below (sell); EMAs sloping strongly (>= ~30 degrees) - not flat/sideways.
- Signal candle: strong bullish candle (small wicks / big body) closing above both EMAs - crossing them from below or
  bouncing after a pullback. Entry: buy-stop at the signal candle's HIGH (sell: its LOW). Stop: candle's low (high).
- Target 1:2. ITM/ATM options. Optional: the other index agrees. Re-entry allowed.
Real 1-min futures 2015-2023 -> 5-min (and 3-min) bars. Futures cost 0.03%; options ATM / 1-strike ITM weekly."""
import numpy as np, pandas as pd, itertools
import grid_engine as G
from video_lib import load, bs_call_put, T_years, summ

def frames(tf):
    N, B = load("NIFTY", tf), load("BANKNIFTY", tf)
    common = N.t.intersection(B.t)
    return N, B, common

def signals(F, slope_k, body_min, kind):
    e9, e15 = G.ema(F.c, 9), G.ema(F.c, 15)
    sl = (e9 - np.r_[np.full(3, np.nan), e9[:-3]]) / 3 / F.atr          # EMA9 slope per bar in ATRs
    rng = F.h - F.l; body = np.abs(F.c - F.o) / np.where(rng > 0, rng, np.nan)
    up_t = (e9 > e15) & (sl >= slope_k); dn_t = (e9 < e15) & (sl <= -slope_k)
    bull = (F.c > F.o) & (body >= body_min) & (F.c > np.maximum(e9, e15))
    bear = (F.c < F.o) & (body >= body_min) & (F.c < np.minimum(e9, e15))
    if kind == "cross/pullback":   # candle came from at/below the EMAs (crossed them or touched EMA9 on a pullback)
        bull &= F.l <= e9; bear &= F.h >= e9
    return up_t & bull, dn_t & bear, up_t, dn_t

def run(F, L, S, other_up=None, other_dn=None, rr=2.0, wait=3, itm_steps=0, step=50, cost_fut=0.0003, cost_opt=0.02):
    c, h, l, o = F.c, F.h, F.l, F.o; n = len(c); out = []; i = 0
    while i < n - 2:
        side = 1 if L[i] else (-1 if S[i] else 0)
        if side and other_up is not None and not (other_up[i] if side > 0 else other_dn[i]): side = 0
        if side == 0 or not F.can_enter[i]: i += 1; continue
        trig = h[i] if side > 0 else l[i]; stop = l[i] if side > 0 else h[i]
        risk = abs(trig - stop)
        if risk <= 0: i += 1; continue
        # wait up to `wait` bars for the trigger
        k = None
        for j in range(i + 1, min(i + 1 + wait, n)):
            if F.day_id[j] != F.day_id[i] or F.must_exit[j]: break
            if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop): break      # invalidated first
            if (side > 0 and h[j] >= trig) or (side < 0 and l[j] <= trig): k = j; break
        if k is None: i += 1; continue
        e = max(trig, o[k]) if side > 0 else min(trig, o[k]); tg = e + side * rr * risk
        K = round(e / step) * step - side * itm_steps * step; call = side > 0; iv = F.iv[k]
        p0 = bs_call_put(e, K, T_years(F, k), iv, call)
        px = None; j = k
        if (side > 0 and l[k] <= stop) or (side < 0 and h[k] >= stop): px = stop   # same bar (conservative)
        else:
            for j in range(k + 1, n):
                if F.day_id[j] != F.day_id[k]: j -= 1; px = c[j]; break
                if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop): px = stop; break
                if (side > 0 and h[j] >= tg) or (side < 0 and l[j] <= tg): px = tg; break
                if F.must_exit[j] == 1: px = c[j]; break
            if px is None: j = n - 1; px = c[j]
        opt = bs_call_put(px, K, T_years(F, j), iv, call) / p0 - 1 - cost_opt
        out.append(dict(t=F.t[k], side=side, fut=side * (px / e - 1) - cost_fut, opt=opt, bars=j - k, why=""))
        i = j + 1   # re-entry allowed after exit
    return pd.DataFrame(out)

res = []
for tf in (5, 3):
    N, B, _ = frames(tf)
    for sym, F, Oth, step in (("BANKNIFTY", B, N, 100), ("NIFTY", N, B, 50)):
        # other index trend aligned on the same timestamp
        oe9, oe15 = G.ema(Oth.c, 9), G.ema(Oth.c, 15)
        o_up = pd.Series(oe9 > oe15, index=Oth.t).reindex(F.t).fillna(False).to_numpy()
        o_dn = pd.Series(oe9 < oe15, index=Oth.t).reindex(F.t).fillna(False).to_numpy()
        for slope_k, body_min, kind in itertools.product((0.0, 0.1, 0.2, 0.3), (0.5, 0.7), ("cross/pullback", "any close above")):
            L, S, _, _ = signals(F, slope_k, body_min, kind)
            for other in (False, True):
                tr = run(F, L, S, o_up if other else None, o_dn if other else None, itm_steps=1, step=step)
                r = summ(tr, f"{sym} {tf}m slope>={slope_k}ATR body>={body_min} {kind}{' +other idx' if other else ''}")
                res.append(r)
        # the most literal version, also ATM and with 1:1 / 1:3
        L, S, _, _ = signals(F, 0.2, 0.5, "cross/pullback")
        for rr in (1.0, 1.5, 3.0):
            res.append(summ(run(F, L, S, rr=rr, itm_steps=1, step=step), f"{sym} {tf}m literal slope0.2 RR 1:{rr}"))
        res.append(summ(run(F, L, S, itm_steps=0, step=step), f"{sym} {tf}m literal slope0.2 ATM option"))
R = pd.DataFrame(res); pd.set_option("display.width", 260)
R.to_csv("results_traderoom_915.csv", index=False)
print(R.drop(columns=["opt_win", "bars"]).sort_values("fut_pct", ascending=False).to_string())
