import numpy as np, pandas as pd, engine as E, grid_engine as G
import video_lib as V
from tr_915_lib import signals, run
from video_lib import summ
D = E.Data()
def frame(sym):
    i = D.syms.index(sym); rows = []
    t = (D.days.values[:, None] + (np.timedelta64(9*60+15, "m") + np.arange(75) * np.timedelta64(5, "m"))[None, :]).ravel()
    df = pd.DataFrame({"o": D.O[i].ravel(), "h": D.H[i].ravel(), "l": D.L[i].ravel(), "c": D.C[i].ravel(), "v": 1.0}, index=pd.DatetimeIndex(t)).dropna()
    F = G.Frame(df, first="09:20", last="14:45", exit_at="15:15")
    F.iv = V.vix_day.reindex(F.t.normalize(), method="ffill").to_numpy() * (1.2 if "BANK" in sym else 1.0)
    wd = F.t.weekday.values; F.dte_cal = (3 - wd) % 7
    F.mins_left = ((15 * 60 + 30) - (F.t.hour * 60 + F.t.minute + 5)).values
    return F
res = []
for sym, step in (("NIFTY BANK", 100), ("NIFTY 50", 50)):
    F = frame(sym)
    for sk in (0.3, 0.35, 0.4, 0.5):
        L, S, _, _ = signals(F, sk, 0.5, "any close above")
        tr = run(F, L, S, rr=2.0, itm_steps=1, step=step)
        r = summ(tr, f"{sym} 5m INDEX slope>={sk} RR2")
        y = tr.groupby(tr.t.dt.year).agg(f=("fut", "mean"), o=("opt", "mean"))
        r["by_year fut%/opt%"] = " ".join(f"{k%100}:{a*100:+.2f}/{b*100:+.0f}" for k, (a, b) in y.iterrows()); res.append(r)
R = pd.DataFrame(res); pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 200)
print(R[["setup","trades","per_yr","win","fut_pct","fut_t","yrs_pos","opt_pct","by_year fut%/opt%"]].to_string())
