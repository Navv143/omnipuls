import pickle, numpy as np, pandas as pd, itertools
exec(open("adaptive.py").read().split("rows = []")[0])
MRO_ = RO.groupby(months).sum()
pd.set_option("display.width", 230, "display.max_columns", 20)
rows = []
for L, K in itertools.product((3, 6, 12), (1, 2, 3)):
    score = MRO_.rolling(L).sum().shift(1)
    out, ntr = [], []
    for m in MR.index[12:]:
        sc = score.loc[m].dropna(); sc = sc[sc > 0].sort_values(ascending=False); pick = list(sc.index[:K])
        mask = months == m
        out.append(RO.loc[mask, pick].mean(axis=1) if pick else pd.Series(0.0, index=RO.index[mask]))
        ntr.append(N.loc[mask, pick].sum(axis=1) if pick else pd.Series(0, index=RO.index[mask]))
    r = pd.concat(out); n = pd.concat(ntr)
    mo = r.groupby(r.index.to_period("M")).sum(); yr = r.groupby(r.index.year).sum()
    rows.append({"option manager": f"last {L}m, top {K}", "trades/day": round(n.mean(), 2), "premium units/month": round(mo.mean(), 2),
                 "months +": f"{100*(mo>0).mean():.0f}%", "years +": f"{(yr>0).sum()}/{len(yr)}", "sharpe": round(r.mean()/r.std()*np.sqrt(252), 2),
                 "2016-21": round(mo[mo.index.year <= 2021].mean(), 2), "2022-26": round(mo[mo.index.year >= 2022].mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))
# per-strategy option returns (full sample) for reference
print((100 * pd.Series({k: t.opt.mean() for k, t in lib.items()})).round(1).sort_values(ascending=False).head(8).to_string())
