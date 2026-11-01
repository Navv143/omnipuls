"""Monthly re-tuning: each month pick the K settings with the best trailing-L-month record, trade them next month."""
import sys, pickle, itertools
import numpy as np, pandas as pd
pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 100)

def wf(M, N, L, K, metric="sharpe", min_trades=20, family_cap=None, meta=None):
    out, picks = [], []
    months = M.index
    for i in range(L, len(months)):
        hist = M.iloc[i - L:i]; ntr = N.iloc[i - L:i].sum()
        ok = ntr >= min_trades
        if metric == "sharpe":
            sc = hist.mean() / hist.std().replace(0, np.nan)
        else:
            sc = hist.sum()
        sc = sc[ok & (hist.sum() > 0)].dropna().sort_values(ascending=False)
        chosen = []
        if family_cap and meta is not None:   # avoid picking 10 near-identical settings
            fam = meta.set_index("key")["family"]
            used = {}
            for k in sc.index:
                f = fam[k]
                if used.get(f, 0) < family_cap:
                    chosen.append(k); used[f] = used.get(f, 0) + 1
                if len(chosen) == K: break
        else:
            chosen = list(sc.index[:K])
        r = M.iloc[i][chosen].mean() if chosen else 0.0
        n = N.iloc[i][chosen].sum() if chosen else 0
        out.append((months[i], r, n, len(chosen))); picks.append((str(months[i]), chosen))
    return pd.DataFrame(out, columns=["month", "ret", "trades", "n_sel"]).set_index("month"), picks

def summ(r, lab, days_per_month=21):
    m = r["ret"]; yrs = m.groupby(m.index.year).sum(); eq = m.cumsum()
    return {"setup": lab, "trades/day": round(r.trades.mean() / days_per_month / max(r.n_sel.replace(0, np.nan).mean(), 1), 2),
            "% / month": round(100 * m.mean(), 2), "months +": f"{100*(m > 0).mean():.0f}%", "years +": f"{(yrs > 0).sum()}/{len(yrs)}",
            "sharpe (monthly→yr)": round(m.mean() / m.std() * np.sqrt(12), 2) if m.std() > 0 else 0,
            "max DD %": round(100 * (eq - eq.cummax()).min(), 1), "last 12m %": round(100 * m.iloc[-12:].sum(), 1)}

if __name__ == "__main__":
    inst = sys.argv[1]
    G_ = pickle.load(open(f"grid_{inst}.pkl", "rb")); M, N, meta = G_["M"], G_["N"], G_["meta"]
    dpm = 30 if inst == "BTC" else 21
    print(f"{inst}: {M.shape[1]} settings, {M.shape[0]} months ({M.index[0]} - {M.index[-1]})")
    full = M.sum().sort_values(ascending=False)
    print(f"Settings profitable over the whole period: {100*(full > 0).mean():.0f}%  | median setting {100*full.median():.1f}% total")
    # persistence: does trailing record predict next month across settings?
    for L in (3, 6, 12):
        ic = []
        for i in range(L, len(M)):
            past = M.iloc[i - L:i].sum(); nxt = M.iloc[i]
            ic.append(past.rank().corr(nxt.rank()))
        print(f"  trailing {L:2d}m -> next month rank corr: {np.nanmean(ic):+.3f} (positive {100*np.mean(np.array(ic) > 0):.0f}% of months)")
    rows = []
    for L, K, met, cap in itertools.product((3, 6, 12), (1, 3, 5, 10), ("sharpe", "return"), (None, 2)):
        r, _ = wf(M, N, L, K, met, family_cap=cap, meta=meta)
        r = r[r.index >= M.index[12]]   # same evaluation window for every L
        rows.append(summ(r, f"last {L}m, top {K}, {met}{', max 2 per family' if cap else ''}", dpm))
    # random-pick benchmark: K random settings each month
    rng = np.random.default_rng(0)
    rr = []
    for _ in range(50):
        ret = [M.iloc[i][rng.choice(M.columns, 5, replace=False)].mean() for i in range(12, len(M))]
        rr.append(np.mean(ret))
    out = pd.DataFrame(rows).sort_values("sharpe (monthly→yr)", ascending=False)
    print(out.head(15).to_string(index=False))
    print(f"\nRandom 5 settings each month (50 tries): average {100*np.mean(rr):.2f}% / month")
    out.to_csv(f"wf_{inst}.csv", index=False)
    r, picks = wf(M, N, 12, 5, "sharpe", family_cap=2, meta=meta)
    print("\nLatest picks (12m, top 5, max 2 per family):"); [print(" ", p) for p in picks[-1][1]]
