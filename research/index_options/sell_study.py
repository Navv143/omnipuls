"""Index option SELLING, intraday (enter 09:20 or 09:45, flat by 15:15), Nifty & Bank Nifty, 5-min 2015 - Apr 2026.
Premiums: Black-Scholes with the LIVE intraday India VIX as implied vol (Bank Nifty = VIX x 1.2), so premiums expand
when VIX spikes. Real expiry calendar: Nifty monthly -> weekly Thu (Feb 2019) -> weekly Tue (Sep 2025);
Bank Nifty weekly Thu (May 2016) -> weekly Wed (Sep 2023) -> monthly (Nov 2024, last Thu, last Tue from Sep 2025).
Stops checked on each 5-min bar's worst price (bar high for calls, low for puts) and the bar's VIX high.
Costs per leg: slippage 0.5 pt Nifty / 2 pt Bank Nifty each side (double on stop-loss exits) + 1% of premium charges."""
import sys, numpy as np, pandas as pd, itertools, warnings
from scipy.stats import norm
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/bt")
import engine as E
D = E.Data()
days = D.days
iv_i = D.syms.index("INDIA VIX")
VO, VH, VC = D.O[iv_i] / 100, D.H[iv_i] / 100, D.C[iv_i] / 100

def last_wd(y, m, wd):
    d = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    return d - pd.Timedelta(days=(d.weekday() - wd) % 7)

def expiry_for(sym, day):
    def weekly(wd):
        return day + pd.Timedelta(days=(wd - day.weekday()) % 7)
    def monthly(wd):
        e = last_wd(day.year, day.month, wd)
        if e < day:
            nx = day + pd.offsets.MonthBegin(1); e = last_wd(nx.year, nx.month, wd)
        return e
    if sym == "NIFTY 50":
        if day < pd.Timestamp("2019-02-11"): return monthly(3)
        if day < pd.Timestamp("2025-09-01"): return weekly(3)
        return weekly(1)
    if day < pd.Timestamp("2016-05-27"): return monthly(3)
    if day < pd.Timestamp("2023-09-04"): return weekly(3)
    if day < pd.Timestamp("2024-11-20"): return weekly(2)
    if day < pd.Timestamp("2025-09-01"): return monthly(3)
    return monthly(1)

def snap(e):   # expiry on a holiday -> previous trading day
    k = days.searchsorted(e, side="right") - 1
    return days[k] if k >= 0 else e

from scipy.special import ndtr
def bs(S, K, T, s, call):
    T = np.maximum(T, 1e-7); s = np.maximum(s, 0.05)
    d1 = (np.log(S / K) + 0.5 * s**2 * T) / (s * np.sqrt(T)); d2 = d1 - s * np.sqrt(T)
    c = S * ndtr(d1) - K * ndtr(d2)
    return np.where(call, c, c - S + K)

SLOT_END_MIN = np.arange(75) * 5 + 5
EXIT_SLOT = 71
_cache = {}

def day_arrays(sym, di):
    key = (sym, di)
    if key in _cache: return _cache[key]
    si = D.syms.index(sym)
    exp = snap(expiry_for(sym, days[di])); dte = max(days.searchsorted(exp) - di, 0)
    # calendar time (India VIX is computed on calendar minutes): minutes from each bar close to expiry 15:30
    now_min = (days[di] - exp).days * 1440 + 555 + SLOT_END_MIN            # 09:15 = minute 555
    Tt = np.maximum(930 - now_min, 1) / 525600.0                            # 15:30 = minute 930 of expiry day
    r = (D.O[si, di], D.H[si, di], D.L[si, di], D.C[si, di], Tt, dte, D.atr[si, di])
    _cache[key] = r
    return r

def run_day(sym, di, entry_slot, kind, sl, width_atr, wing_atr, comb_sl):
    m = 1.2 if sym == "NIFTY BANK" else 1.0
    step = 100 if sym == "NIFTY BANK" else 50; slip = 2.0 if sym == "NIFTY BANK" else 0.5
    O, H, L, C, Tt, dte, atr = day_arrays(sym, di)
    if np.isnan(C[entry_slot]) or np.isnan(C[EXIT_SLOT]) or np.isnan(VC[di, entry_slot]) or np.isnan(atr): return None
    S0 = C[entry_slot]
    v0 = VC[di, entry_slot]
    ivh = np.nan_to_num(VH[di], nan=v0) * m; ivc = np.nan_to_num(VC[di], nan=v0) * m
    Cf = np.where(np.isnan(C), S0, C); Hf = np.where(np.isnan(H), Cf, H); Lf = np.where(np.isnan(L), Cf, L)
    if kind == "straddle":
        Kc = Kp = round(S0 / step) * step
    else:
        w = width_atr * atr; Kc = np.ceil((S0 + w) / step) * step; Kp = np.floor((S0 - w) / step) * step
    legs = [("C", Kc, True), ("P", Kp, False)]
    wings = [("WC", np.ceil((S0 + wing_atr * atr) / step) * step, True),
             ("WP", np.floor((S0 - wing_atr * atr) / step) * step, False)] if wing_atr else []
    p0 = {n: float(bs(S0, K, Tt[entry_slot], ivc[entry_slot], c)) for n, K, c in legs + wings}
    prem = p0["C"] + p0["P"]
    sl_ = slice(entry_slot + 1, EXIT_SLOT + 1)
    close_v = {n: bs(Cf[sl_], K, Tt[sl_], ivc[sl_], c) for n, K, c in legs + wings}
    worst_v = {n: bs(Hf[sl_] if c else Lf[sl_], K, Tt[sl_], ivh[sl_], c) for n, K, c in legs}
    cost = sum(slip + 0.01 * p0[n] for n in p0)
    nb = EXIT_SLOT - entry_slot
    stop_at = {}
    for n, K, c in legs:
        stop_at[n] = None
        if sl is not None:
            hit = np.flatnonzero(worst_v[n] >= p0[n] * (1 + sl))
            stop_at[n] = hit[0] if len(hit) else None
    if comb_sl:
        mtm = sum(p0[n] - close_v[n] for n, _, _ in legs) + sum(close_v[n] - p0[n] for n, _, _ in wings)
        hit = np.flatnonzero(mtm <= -comb_sl * prem)
        if len(hit):
            j = hit[0]
            return dict(pnl=mtm[j] - cost - 2 * slip * len(legs + wings) - 0.01 * sum(close_v[n][j] for n in close_v),
                        prem=prem, S0=S0, dte=dte, hit="comb", exit=j)
    pnl = 0.0
    for n, K, c in legs:
        j = stop_at[n]
        if j is not None:
            px = p0[n] * (1 + sl); pnl += p0[n] - px - slip; cost += slip + 0.01 * px
        else:
            v = close_v[n][-1]; pnl += p0[n] - v; cost += slip + 0.01 * v
    for n, K, c in wings:
        v = close_v[n][-1]; pnl += v - p0[n]; cost += slip + 0.01 * v
    return dict(pnl=pnl - cost, prem=prem, S0=S0, dte=dte, hit=",".join(n for n in stop_at if stop_at[n] is not None), exit=nb)

CONFIGS = []
for entry in (1, 6):                                   # 09:20, 09:45 (close of the bar ending then)
    for sl in (0.25, 0.40, 0.60, None):
        CONFIGS.append(("straddle", entry, sl, 0, 0, 0.30 if sl is None else 0))
    for w, sl in itertools.product((0.4, 0.7), (0.5, 1.0)):
        CONFIGS.append(("strangle", entry, sl, w, 0, 0))
    for wing, comb in itertools.product((0.7, 1.2), (0, 0.25)):
        CONFIGS.append(("ironfly", entry, None, 0, wing, comb))
rows = []
for sym in ("NIFTY 50", "NIFTY BANK"):
    for kind, entry, sl, w, wing, comb in CONFIGS:
        res = []
        for di in range(20, len(days)):
            r = run_day(sym, di, entry, "straddle" if kind == "ironfly" else kind, sl, w, wing, comb)
            if r: res.append(dict(day=days[di], vix=VC[di, entry] * 100, gap=D.gap[D.syms.index(sym), di], **r))
        R = pd.DataFrame(res)
        R["pct_spot"] = R.pnl / R.S0 * 100
        name = f"{sym} {kind} {'09:20' if entry == 1 else '09:45'} " + (f"legSL {int(sl*100)}%" if sl else "") + \
               (f" strikes ±{w}ATR" if w else "") + (f" wings ±{wing}ATR" if wing else "") + (f" combSL {int(comb*100)}%" if comb else "")
        R.to_parquet(f"res_{abs(hash(name)) % 10**8}.parquet")
        yr = R.day.dt.year; by = R.groupby(yr).pct_spot.sum()
        eq = R.pct_spot.cumsum(); dd = (eq - eq.cummax()).min()
        for bucket, g in [("all days", R), ("expiry day", R[R.dte == 0]), ("1 day before", R[R.dte == 1]), ("2+ days before", R[R.dte >= 2])]:
            if len(g) < 50: continue
            gy = g.day.dt.year
            rows.append(dict(setup=name, days=bucket, n=len(g), avg_pts=round(g.pnl.mean(), 1), kept_pct=round(g.pnl.sum() / g.prem.sum() * 100, 1),
                             win=round((g.pnl > 0).mean() * 100), avg_pct_spot=round(g.pct_spot.mean(), 3),
                             worst_pct=round(g.pct_spot.min(), 2), t=round(g.pct_spot.mean() / g.pct_spot.std() * np.sqrt(len(g)), 1),
                             y15_19=round(g[gy < 2020].pct_spot.mean(), 3), y20_23=round(g[(gy >= 2020) & (gy < 2024)].pct_spot.mean(), 3),
                             y24_26=round(g[gy >= 2024].pct_spot.mean(), 3),
                             yrs_pos=f"{(g.groupby(gy).pct_spot.sum() > 0).sum()}/{gy.nunique()}",
                             maxDD_pct=round(dd, 1) if bucket == "all days" else np.nan, file=f"res_{abs(hash(name)) % 10**8}.parquet"))
        print(name, "done", flush=True)
out = pd.DataFrame(rows); out.to_csv("sell_results.csv", index=False)
