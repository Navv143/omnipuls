"""Fibonacci retracement (Wizard Trader style), intraday:
Swing = first-hour (09:15-10:15) impulse. Up-impulse if the low came before the high (mirror for down).
After 10:15 wait for price to retrace to the fib level (38.2 / 50 / 61.8%).
 - 'limit': buy at the level the first time it is touched.
 - 'confirm': a candle touches the level and closes back above it (bullish rejection); enter at close.
Stop at 78.6% or 100% (swing low). Target swing high (0%) or the 127.2% extension. Exit 15:15. 1 trade/day."""
import numpy as np, pandas as pd, sys
import mtf_data as MD, grid_engine as G
from video_lib import load, bs_call_put, T_years, summ

def fib(sym, tf=5, min_imp=0.004):
    F = load(sym, tf)
    t = F.t; tm = t.strftime("%H:%M").values
    days = np.unique(F.day_id); res = {}
    starts = np.searchsorted(F.day_id, days); ends = np.r_[starts[1:], len(F.c)]
    for lvl in (0.382, 0.5, 0.618):
        for stp in (0.786, 1.0):
            for tgtx in (0.0, -0.272):
                for mode in ("limit", "confirm"):
                    rows = []
                    for s0, s1 in zip(starts, ends):
                        idx = np.arange(s0, s1); fh = idx[tm[s0:s1] < "10:15"]; rest = idx[(tm[s0:s1] >= "10:15") & (tm[s0:s1] <= "14:45")]
                        if len(fh) < 6 or len(rest) == 0: continue
                        hi_i = fh[np.argmax(F.h[fh])]; lo_i = fh[np.argmin(F.l[fh])]; H, L = F.h[hi_i], F.l[lo_i]
                        if (H - L) / L < min_imp: continue
                        side = 1 if lo_i < hi_i else -1
                        rng = H - L
                        if side > 0: lev = H - lvl * rng; stop = H - stp * rng; tg = H - tgtx * rng
                        else: lev = L + lvl * rng; stop = L + stp * rng; tg = L + tgtx * rng
                        ent = None
                        for i in rest:
                            # invalidated if stop hit before entry
                            if (side > 0 and F.l[i] <= stop) or (side < 0 and F.h[i] >= stop): break
                            touched = F.l[i] <= lev if side > 0 else F.h[i] >= lev
                            if not touched: continue
                            if mode == "limit": ent = (i, min(lev, F.o[i]) if side > 0 else max(lev, F.o[i])); break
                            if (side > 0 and F.c[i] > lev) or (side < 0 and F.c[i] < lev): ent = (i, F.c[i]); break
                        if ent is None: continue
                        i, e = ent; px = None; j = i
                        # same-bar stop check for limit fills (conservative)
                        if mode == "limit" and ((side > 0 and F.l[i] <= stop) or (side < 0 and F.h[i] >= stop)): px = stop
                        else:
                            for j in range(i + 1, s1):
                                if (side > 0 and F.l[j] <= stop) or (side < 0 and F.h[j] >= stop): px = stop; break
                                if (side > 0 and F.h[j] >= tg) or (side < 0 and F.l[j] <= tg): px = tg; break
                                if F.must_exit[j] == 1: px = F.c[j]; break
                            if px is None: j = s1 - 1; px = F.c[j]
                        K = round(e / 50) * 50; call = side > 0
                        p0 = bs_call_put(e, K, T_years(F, i), F.iv[i], call); p1 = bs_call_put(px, K, T_years(F, j), F.iv[i], call)
                        rows.append(dict(t=t[i], side=side, fut=side * (px / e - 1) - 0.0003, opt=max(p1 / p0 - 1, -1) - 0.02, bars=j - i, why=""))
                    res[f"{sym} {tf}m fib {lvl} {mode} | stop {stp} | tgt {'swing' if tgtx == 0 else '127.2%'}"] = pd.DataFrame(rows)
    return res
out = []
for sym in ("NIFTY", "BANKNIFTY"):
    for k, tr in fib(sym).items(): out.append(summ(tr, k))
R = pd.DataFrame(out); pd.set_option("display.width", 250); print(R.sort_values("fut_pct", ascending=False).to_string())
R.to_csv("results_video_fib.csv", index=False)
