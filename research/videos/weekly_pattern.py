"""Video 3: 'If Friday's high < Thursday's high, Monday visits Friday's low' (and Mon/Wed -> Thu). Hit rates vs baseline + trade."""
import numpy as np, pandas as pd, engine as E
D = E.Data()
days = D.days; wd = days.weekday.values
def study(i, name, cost):
    H, L, O, C = D.dhigh[i], D.dlow[i], D.dopen[i], D.dclose[i]
    rows = []
    for a, b, c, lab in ((3, 4, 0, "Thu>Fri high -> Mon hits Fri low"), (0, 2, 3, "Mon>Wed high -> Thu hits Wed low")):
        for k in range(2, len(days)):
            if wd[k] != c: continue
            # find previous b-day and a-day in same chain (b = k-1 trading day must be weekday b)
            j = k - 1
            if wd[j] != b: continue
            # 'a' is the trading day with weekday a just before j (Thu before Fri = j-1; Mon before Wed = j-2 or j-1)
            ia = [t for t in range(j - 1, max(j - 4, 0), -1) if wd[t] == a]
            if not ia or not np.isfinite(H[k]): continue
            ia = ia[0]
            cond_dn = H[j] < H[ia]; cond_up = L[j] > L[ia]
            rows.append(dict(rule=lab, day=days[k], dn=cond_dn, up=cond_up,
                             hit_low=L[k] < L[j], hit_high=H[k] > H[j],
                             open_above_low=O[k] > L[j], open_below_high=O[k] < H[j],
                             short_ret=np.where(O[k] > L[j], (O[k] - max(L[j], min(C[k], O[k] * 9))) / O[k], np.nan),
                             O=O[k], C=C[k], Lp=L[j], Hp=H[j], Lk=L[k], Hk=H[k]))
    df = pd.DataFrame(rows)
    out = []
    for rule, g in df.groupby("rule"):
        for per, gg in (("all", g), ("2015-21", g[g.day < "2022"]), ("2022-26", g[g.day >= "2022"])):
            c = gg[gg.dn]
            # trade: short at open (if open above prev-day low), cover at prev low if touched else at close
            t = c[c.open_above_low]
            r = np.where(t.Lk <= t.Lp, (t.O - t.Lp) / t.O, (t.O - t.C) / t.O) - cost
            cu = gg[gg.up]; tu = cu[cu.open_below_high]
            ru = np.where(tu.Hk >= tu.Hp, (tu.Hp - tu.O) / tu.O, (tu.C - tu.O) / tu.O) - cost
            out.append(dict(sym=name, rule=rule, period=per, n=len(c), hit=c.hit_low.mean(),
                            base_hit_any=gg.hit_low.mean(), trade_n=len(t), trade_avg=r.mean() * 100, trade_win=(r > 0).mean(),
                            mirror_n=len(cu), mirror_hit=cu.hit_high.mean(), base_hit_high=gg.hit_high.mean(), mirror_trade=ru.mean() * 100))
    return out
res = []
for s, cost in (("NIFTY 50", 0.0003), ("NIFTY BANK", 0.0003)):
    res += study(D.syms.index(s), s, cost)
print(pd.DataFrame(res).round(3).to_string())
# stocks pooled
allr = []
for i in D.stock_idx:
    allr += study(i, D.syms[i], 0.001)
S = pd.DataFrame(allr)
print(S.groupby(["rule", "period"]).apply(lambda g: pd.Series(dict(n=g.n.sum(), hit=(g.hit*g.n).sum()/g.n.sum(), base=g.base_hit_any.mean(),
      trade=(g.trade_avg*g.trade_n).sum()/g.trade_n.sum(), mirror_hit=(g.mirror_hit*g.mirror_n).sum()/g.mirror_n.sum(), base_hi=g.base_hit_high.mean(),
      mirror_trade=(g.mirror_trade*g.mirror_n).sum()/g.mirror_n.sum()))).round(3).to_string())
