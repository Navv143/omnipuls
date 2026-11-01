import pickle, numpy as np, pandas as pd, itertools
exec(open("adaptive.py").read().split("rows = []")[0])   # reuse data prep + manage/summ definitions
designed = [k for k in lib if "momentum" in k]
pd.set_option("display.width", 250, "display.max_columns", 30)
def manage_sub(L, K, metric, cols, src="net"):
    D_ = (R if src == "net" else RO)[cols]; MRs = MR[cols]
    score = (MRs.rolling(L).sum() if metric == "return" else
             R[cols].groupby(months).agg(lambda x: x.mean()).rolling(L).mean() / R[cols].groupby(months).agg(lambda x: x.std()).rolling(L).mean()).shift(1)
    out, ntr = [], []
    for m in MR.index[12:]:
        sc = score.loc[m].dropna(); sc = sc[sc > 0].sort_values(ascending=False); pick = list(sc.index[:K]) if K else list(sc.index)
        mask = months == m
        out.append(D_.loc[mask, pick].mean(axis=1) if pick else pd.Series(0.0, index=D_.index[mask]))
        ntr.append(N.loc[mask, pick].sum(axis=1) if pick else pd.Series(0, index=D_.index[mask]))
    return pd.concat(out), pd.concat(ntr)
generic = [k for k in lib if k not in designed]
rows = []
for cols, clab in ((list(lib), "all 26"), (generic, "22 generic (no tuned momentum)")):
    for L, K, metric in ((6, 3, "sharpe"), (12, 5, "sharpe"), (12, 3, "return"), (6, 0, "return")):
        for src in ("net", "opt"):
            r, n = manage_sub(L, K, metric, cols, src)
            row = summ(r, n, f"[{clab}] last {L}m, top {K or 'all+'}, {metric} | {'FUTURES/CASH' if src=='net' else 'OPTIONS (% of premium)'}")
            rows.append(row)
out = pd.DataFrame(rows); out.to_csv("adaptive_check.csv", index=False); print(out.to_string(index=False))
# static generic equal weight, for contrast
mask = R.index.to_period("M") >= MR.index[12]
print(summ(R.loc[mask, generic].mean(axis=1), N.loc[mask, generic].sum(axis=1), "STATIC all generic"))
