import pickle, numpy as np, pandas as pd
exec(open("adaptive.py").read().split("rows = []")[0])
generic = [k for k in lib if "momentum" not in k]
cols = generic; L, K = 12, 5
sh = (R[cols].groupby(months).agg(lambda x: x.mean()).rolling(L).mean() / R[cols].groupby(months).agg(lambda x: x.std()).rolling(L).mean())
score = sh.shift(1)
rets, ntr, log = [], [], []
for m in MR.index[12:]:
    sc = score.loc[m].dropna(); sc = sc[sc > 0].sort_values(ascending=False); pick = list(sc.index[:K])
    mask = months == m
    rets.append(R.loc[mask, pick].mean(axis=1) if pick else pd.Series(0.0, index=R.index[mask]))
    ntr.append(N.loc[mask, pick].sum(axis=1) if pick else pd.Series(0, index=R.index[mask]))
    log.append({"month": str(m), **{f"pick {i+1}": p for i, p in enumerate(pick)}})
r = pd.concat(rets); n = pd.concat(ntr)
mo = (100 * r.groupby(r.index.to_period("M")).sum()).round(2)
yr = (100 * r.groupby(r.index.year).sum()).round(1)
print("Yearly % (unlevered notional):", yr.to_dict())
print("Monthly: best", mo.max(), "worst", mo.min(), "| worst 3 months:", mo.nsmallest(3).to_dict())
print("Trades/day: mean", round(n.mean(), 1), "median", n.median(), "| days with 0 trades:", f"{100*(n==0).mean():.0f}%")
lg = pd.DataFrame(log); lg.to_csv("adaptive_picks_by_month.csv", index=False)
print("\nHow often each strategy was selected (months):")
print(pd.Series(lg.drop(columns="month").values.ravel()).value_counts().to_string())
# next month's picks (using data to Apr 2026)
last = sh.iloc[-1].dropna().sort_values(ascending=False)
print("\nPicks for the next month (from the latest 12 months of data):", list(last[last > 0].index[:5]))
mo.to_csv("adaptive_monthly.csv")
