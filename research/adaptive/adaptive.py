import pickle, numpy as np, pandas as pd, itertools
pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 200)
lib = pickle.load(open("library.pkl", "rb"))
days = pd.DatetimeIndex(sorted(set().union(*[set(t.date.dt.normalize()) for t in lib.values()])))
def daily(col):
    D = pd.DataFrame(0.0, index=days, columns=list(lib)); N = pd.DataFrame(0, index=days, columns=list(lib))
    for k, t in lib.items():
        g = t.groupby(t.date.dt.normalize())[col]
        D.loc[g.sum().index, k] = g.sum().values; N.loc[g.size().index, k] = g.size().values
    return D, N
R, N = daily("net"); RO, _ = daily("opt")
months = R.index.to_period("M")
MR = R.groupby(months).sum(); MRO = RO.groupby(months).sum()       # monthly sum of daily returns per strategy
MS = R.groupby(months).agg(lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0)
# 1) does the past predict the next month?  rank correlation across strategies, month by month
print("Does recent performance predict next month? (average cross-strategy rank correlation; 0 = no)")
for L in (1, 3, 6, 12):
    past = MR.rolling(L).sum().shift(1)
    ics = [past.loc[m].rank().corr(MR.loc[m].rank()) for m in MR.index[13:]]
    print(f"  last {L:2d} month(s) -> next month: {np.nanmean(ics):+.3f}   (positive in {100*np.mean(np.array(ics)>0):.0f}% of months)")
# 2) adaptive manager
def manage(L, K, metric, thr, src="net"):
    M_ = MR if src == "net" else MRO
    D_ = R if src == "net" else RO
    score = (MR.rolling(L).sum() if metric == "return" else
             R.groupby(months).agg(lambda x: x.mean()).rolling(L).mean() / R.groupby(months).agg(lambda x: x.std()).rolling(L).mean()).shift(1)
    out, sel_log, ntr = [], [], []
    for m in MR.index[12:]:
        sc = score.loc[m].dropna()
        sc = sc[sc > thr].sort_values(ascending=False)
        pick = list(sc.index[:K]) if K else list(sc.index)
        mask = months == m
        if pick:
            out.append(D_.loc[mask, pick].mean(axis=1)); ntr.append(N.loc[mask, pick].sum(axis=1))
        else:
            out.append(pd.Series(0.0, index=D_.index[mask])); ntr.append(pd.Series(0, index=D_.index[mask]))
        sel_log.append((str(m), pick))
    return pd.concat(out), pd.concat(ntr), sel_log
def summ(r, n, lab):
    mo = r.groupby(r.index.to_period("M")).sum(); yr = r.groupby(r.index.year).sum(); eq = r.cumsum()
    return {"portfolio": lab, "avg trades/day": round(n.mean(), 2), "% per month": round(100 * mo.mean(), 2),
            "months +": f"{100*(mo>0).mean():.0f}%", "years +": f"{(yr>0).sum()}/{len(yr)}",
            "sharpe": round(r.mean() / r.std() * np.sqrt(252), 2) if r.std() > 0 else 0, "max DD %": round(100 * (eq - eq.cummax()).min(), 1),
            "2016-21 %/mo": round(100 * mo[mo.index.year <= 2021].mean(), 2), "2022-26 %/mo": round(100 * mo[mo.index.year >= 2022].mean(), 2)}
rows = []
start = MR.index[12]
mask = R.index.to_period("M") >= start
rows.append(summ(R.loc[mask].mean(axis=1), N.loc[mask].sum(axis=1), "STATIC: all 26 strategies equally"))
core = ["BANKNIFTY momentum (6 rules)", "STOCKS gap fade at 9:20"]
rows.append(summ(R.loc[mask, core].mean(axis=1), N.loc[mask, core].sum(axis=1), "STATIC: our 2 final setups (BN momentum + gap fade 9:20)"))
for L, K, metric, thr in itertools.product((1, 3, 6, 12), (1, 3, 5, 0), ("return", "sharpe"), (0.0,)):
    r, n, _ = manage(L, K, metric, thr)
    rows.append(summ(r, n, f"ADAPTIVE: last {L}m, top {K or 'all positive'}, by {metric}"))
out = pd.DataFrame(rows); out.to_csv("adaptive_results.csv", index=False)
print(out.to_string(index=False))
# hindsight (impossible) for reference
best = MR.loc[MR.index >= start].sum().sort_values(ascending=False)
print("\nFull-period winners (hindsight, cannot be known in advance):", (100 * best.head(5)).round(1).to_dict())
r, n, log = manage(3, 3, "return", 0.0)
print("\nWhat 'last 3 months, top 3' picked in recent months:")
for m, p in log[-8:]: print(" ", m, p)
