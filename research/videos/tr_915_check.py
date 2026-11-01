import numpy as np, pandas as pd
from tr_915_lib import frames, signals, run
from video_lib import summ
res = []
N, B, _ = frames(5)
for sym, F, step in (("BANKNIFTY", B, 100), ("NIFTY", N, 50)):
    for sk in (0.25, 0.3, 0.35, 0.4, 0.5):
        L, S, _, _ = signals(F, sk, 0.5, "any close above")
        for rr in (1.5, 2.0, 3.0):
            tr = run(F, L, S, rr=rr, itm_steps=1, step=step)
            r = summ(tr, f"{sym} 5m slope>={sk} any-close RR{rr}")
            y = tr.groupby(tr.t.dt.year).fut.mean().mul(100).round(3).to_dict()
            r["by_year"] = " ".join(f"{k%100}:{v:+.2f}" for k, v in y.items()); res.append(r)
R = pd.DataFrame(res); pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 120)
print(R[["setup","trades","per_yr","win","fut_pct","fut_t","fut_1H","fut_2H","yrs_pos","opt_pct","opt_1H","opt_2H","by_year"]].to_string())
