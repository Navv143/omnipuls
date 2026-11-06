import pickle, numpy as np, pandas as pd
from intra import D, COST, days, trade
rows = []
for k in D:
    h = D[k]["1h"]; dd = D[k]["1d"]; datr = (dd.High - dd.Low).rolling(14).mean().shift(); pdc = dd.Close.shift()
    dys = days(h)
    for thr in (0.3, 0.5, 0.7):
        for at in ("17:30", "18:30", "19:30"):
            for st in (0.3, 0.5, 0.8):
                res = []
                for d, g in dys.items():
                    A = datr.get(d, np.nan)
                    if not np.isfinite(A): continue
                    hm = g.index.strftime("%H:%M"); ii = np.flatnonzero(hm == at)
                    if not len(ii) or ii[0] < 2: continue
                    i = ii[0]; mv = g.Close.iloc[i - 1] - g.Open.iloc[0]
                    if abs(mv) > thr * A:
                        sd = int(np.sign(mv)); r = trade(g, i, sd, g.Open.iloc[i] - sd * st * A, COST[k])
                        if r: res.append((d,) + r)
                t = pd.DataFrame(res, columns=["d", "pct", "R"])
                if len(t) < 20: continue
                mid = t.d.iloc[len(t) // 2]
                rows.append({"setup": "NY continue", "mkt": k, "thr": thr, "at": at, "stop": st, "n": len(t), "avgR": t.R.mean(),
                             "avg%": t.pct.mean(), "t": t.pct.mean() / t.pct.std() * np.sqrt(len(t)),
                             "h1": t.R[t.d < mid].mean(), "h2": t.R[t.d >= mid].mean()})
    for thr in (0.15, 0.25, 0.4):
        for st in (0.3, 0.5, 0.8):
            for ex in ("13:30", "18:30", "22:30"):
                res = []
                for d, g in dys.items():
                    A = datr.get(d, np.nan); pc = pdc.get(d, np.nan)
                    if not (np.isfinite(A) and np.isfinite(pc)): continue
                    gp = g.Open.iloc[0] - pc
                    if abs(gp) > thr * A:
                        sd = -int(np.sign(gp)); gg = g[g.index.strftime("%H:%M") <= ex]
                        r = trade(gg, 0, sd, g.Open.iloc[0] - sd * st * A, COST[k])
                        if r: res.append((d,) + r)
                t = pd.DataFrame(res, columns=["d", "pct", "R"])
                if len(t) < 20: continue
                mid = t.d.iloc[len(t) // 2]
                rows.append({"setup": "Gap fade", "mkt": k, "thr": thr, "at": ex, "stop": st, "n": len(t), "avgR": t.R.mean(),
                             "avg%": t.pct.mean(), "t": t.pct.mean() / t.pct.std() * np.sqrt(len(t)),
                             "h1": t.R[t.d < mid].mean(), "h2": t.R[t.d >= mid].mean()})
r = pd.DataFrame(rows).round(3)
r["both+"] = (r.h1 > 0) & (r.h2 > 0)
pd.set_option("display.width", 200)
print(r.groupby(["setup", "mkt"]).agg(cells=("n", "size"), pos_share=("avgR", lambda x: round((x > 0).mean(), 2)),
      both_share=("both+", "mean"), med_R=("avgR", "median"), med_t=("t", "median"), max_t=("t", "max")).round(2))
print(r[(r.setup == "NY continue") & (r.mkt == "NATGAS")].to_string(index=False)); r.to_pickle("grid.pkl")

