"""Option buying needs BIG moves, so: (1) same bars, but hold the option with a trailing exit until 15:15
(stop -30% of premium; once up, exit if premium falls 30% from its peak); (2) a day-level 'trend day' model that
decides at 10:15 / 11:00 whether to buy a call, a put or nothing, holding with the same trailing exit.
Walk-forward (train on earlier years only), real 1-min futures volume + OI, 2015-2023."""
import sys, numpy as np, pandas as pd, lightgbm as lgb, warnings
from scipy.stats import norm
warnings.filterwarnings("ignore")
sym = sys.argv[1]
b = pd.read_parquet(f"idx5_{sym}.parquet")
b["date"] = b.index.normalize()
C, Hh, Ll = b.c.values, b.h.values, b.l.values
mins = b.mins.values; dayid = pd.factorize(b.date)[0]
iv = b.vix.values / 100 * (1.2 if sym == "BANKNIFTY" else 1.0)
dte = ((3 - b.index.weekday.values) % 7).astype(float)
step = 100 if sym == "BANKNIFTY" else 50
def bs(S, K, Tt, s, call):
    Tt = max(Tt, 1e-6); d1 = (np.log(S / K) + 0.5 * s**2 * Tt) / (s * np.sqrt(Tt)); d2 = d1 - s * np.sqrt(Tt)
    c = S * norm.cdf(d1) - K * norm.cdf(d2); return c if call else c - S + K
def T(i_dte, m): return (i_dte + max(375 - (m + 5), 0) / 375) / 252
starts = np.r_[0, np.flatnonzero(np.diff(dayid)) + 1]; ends = np.r_[starts[1:], len(C)]
day_end = np.empty(len(C), int)
for s_, e_ in zip(starts, ends): day_end[s_:e_] = e_
def trail_trade(i, call, stop=0.30, give=0.30):
    K = round(C[i] / step) * step; p0 = bs(C[i], K, T(dte[i], mins[i]), iv[i], call); peak = 0.0
    for j in range(i + 1, day_end[i]):
        if mins[j] >= 365: return bs(C[j], K, T(dte[i], mins[j]), iv[i], call) / p0 - 1 - 0.02
        worst = Ll[j] if call else Hh[j]
        rw = bs(worst, K, T(dte[i], mins[j]), iv[i], call) / p0 - 1
        if rw <= -stop and peak < 0.3: return -stop - 0.02
        best = Hh[j] if call else Ll[j]
        peak = max(peak, bs(best, K, T(dte[i], mins[j]), iv[i], call) / p0 - 1)
        rc = bs(C[j], K, T(dte[i], mins[j]), iv[i], call) / p0 - 1
        if peak >= 0.3 and rc <= (1 + peak) * (1 - give) - 1: return rc - 0.02
    j = day_end[i] - 1
    return bs(C[j], K, T(dte[i], mins[j]), iv[i], call) / p0 - 1 - 0.02
# ---------- (2) day-level model at decision times
rows = []
for s_, e_ in zip(starts, ends):
    d = b.iloc[s_:e_]
    for dt_ in ("10:15", "11:00"):
        k = np.flatnonzero(d.tm.values == dt_)
        if not len(k) or pd.isna(d.atr.iloc[0]): continue
        i = s_ + k[0]; r = b.iloc[i]
        first = d.iloc[:k[0] + 1]
        rows.append(dict(date=r.date, dtime=dt_, i=i, gap=r.gap, vix=r.vix, atr_pct=r.atr / r.c,
                         from_open=r.from_open_atr, rng_used=r.day_range_used, vwap=r.vwap_atr, cvd_n=r.cvd_n,
                         dlt12=r.dlt12, oi_day=r.oi_chg_day, vol_x=first.vol_x.mean(), rsi=r.rsi,
                         ema_gap=r.ema_gap_atr, macd=r.macd_hist_atr, bbw=r.bb_bw_rank, d_pdh=r.d_pdh_atr,
                         d_pdl=r.d_pdl_atr, dow=r.dow, build=(np.sign(r.from_open_atr) * np.sign(r.oi_chg_day)),
                         fwd_close=(d.c.iloc[-3] / r.c - 1) / (r.atr / r.c)))
Dd = pd.DataFrame(rows)
print(sym, "computing trailing option outcomes for", len(Dd), "decision points ...", flush=True)
Dd["opt_call"] = [trail_trade(i, True) for i in Dd.i]
Dd["opt_put"] = [trail_trade(i, False) for i in Dd.i]
Dd.to_parquet(f"idx_days_{sym}.parquet")
X = ["gap", "vix", "atr_pct", "from_open", "rng_used", "vwap", "cvd_n", "dlt12", "oi_day", "vol_x", "rsi", "ema_gap",
     "macd", "bbw", "d_pdh", "d_pdl", "dow", "build"]
Dd["year"] = pd.to_datetime(Dd.date).dt.year
print(f"\n===== {sym}: buy at decision time, trail to 15:15 =====")
for dt_, g in Dd.groupby("dtime"):
    print(f"{dt_}: always call {g.opt_call.mean()*100:+.1f}% | always put {g.opt_put.mean()*100:+.1f}% | "
          f"follow the move (call if above open & VWAP & net buying, put if mirror): ", end="")
    up = (g.from_open > 0.2) & (g.vwap > 0) & (g.cvd_n > 0); dn = (g.from_open < -0.2) & (g.vwap < 0) & (g.cvd_n < 0)
    r = pd.concat([g[up].opt_call, g[dn].opt_put])
    print(f"{len(r)} trades {r.mean()*100:+.1f}% win {(r>0).mean()*100:.0f}%")
    for thr in (0.4, 0.6, 0.8):
        up = (g.from_open > thr) & (g.vwap > 0) & (g.cvd_n > 0) & (g.oi_day > 0); dn = (g.from_open < -thr) & (g.vwap < 0) & (g.cvd_n < 0) & (g.oi_day > 0)
        r = pd.concat([g[up].opt_call, g[dn].opt_put]); yy = pd.concat([g[up].year, g[dn].year])
        print(f"     strong move {thr} ATR + VWAP + net buying + OI rising: {len(r)} trades ({len(r)/8:.0f}/yr) {r.mean()*100:+.1f}%  win {(r>0).mean()*100:.0f}%  "
              f"2015-18 {r[yy<2019].mean()*100:+.1f}% 2019-23 {r[yy>=2019].mean()*100:+.1f}%")
# walk-forward model per decision time
params = dict(objective="regression", learning_rate=0.03, num_leaves=7, min_data_in_leaf=60, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=10, verbose=-1, num_threads=2)
for dt_, g in Dd.groupby("dtime"):
    out = []
    for Y in range(2018, 2024):
        tr, te = g[g.year < Y], g[g.year == Y]
        if te.empty: continue
        pc = lgb.train(params, lgb.Dataset(tr[X], tr.opt_call.clip(-0.35, 1.5)), 200).predict(te[X])
        pp = lgb.train(params, lgb.Dataset(tr[X], tr.opt_put.clip(-0.35, 1.5)), 200).predict(te[X])
        for (_, r), a, c_ in zip(te.iterrows(), pc, pp):
            best = max(a, c_)
            out.append(dict(year=Y, pred=best, ret=r.opt_call if a >= c_ else r.opt_put))
    o = pd.DataFrame(out)
    for thr in (0.0, 0.05, 0.10):
        s = o[o.pred > thr]
        if len(s) < 10: continue
        by = s.groupby("year").ret.mean() * 100
        print(f"  model {dt_} pred>{thr:.2f}: {len(s)} trades ({len(s)/5.2:.0f}/yr) {s.ret.mean()*100:+.1f}% win {(s.ret>0).mean()*100:.0f}%  t {s.ret.mean()/s.ret.std()*np.sqrt(len(s)):.1f} | "
              + " ".join(f"{y%100}:{v:+.0f}" for y, v in by.items()))
