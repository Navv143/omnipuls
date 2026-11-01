"""Backtests of the strategies in the user's screen recordings (Nov 2026).
1) EMA9 / VWAP(OHLC4) crossover on 3-min (austin.daytrades): plain cross, and first pullback after cross.
   Exit: a candle closes beyond EMA9 against the trade; option premium stop -25%/-30%; 15:15 square-off.
2) 9/15 EMA crossover (trend following).
3) Fibonacci retracement of the first-hour impulse (38.2/50/61.8 entries).
Real 1-min Nifty / Bank Nifty futures 2015-03 .. 2023-02. Futures cost 0.03%; options: Black-Scholes, ATM weekly
(next Thursday), IV = India VIX (x1.2 for Bank Nifty), 2% of premium round-trip cost."""
import sys, numpy as np, pandas as pd
from scipy.stats import norm
import mtf_data as MD, grid_engine as G

vix = pd.read_csv("/home/claude/udata/INDIA VIX_5minute.csv", parse_dates=["date"])
vix_day = vix.groupby(vix.date.dt.normalize()).open.first() / 100

def bs_call_put(S, K, T, sig, call):
    T = max(T, 1e-6); d1 = (np.log(S / K) + 0.5 * sig**2 * T) / (sig * np.sqrt(T)); d2 = d1 - sig * np.sqrt(T)
    c = S * norm.cdf(d1) - K * norm.cdf(d2)
    return c if call else c - S + K

def load(sym, tf):
    m1 = pd.read_parquet(f"{sym.lower()}_1m.parquet")
    b = MD.resample(m1, tf)
    F = G.Frame(b, first="09:20", last="14:45", exit_at="15:15")
    d = F.t.normalize()
    F.iv = vix_day.reindex(d, method="ffill").to_numpy() * (1.2 if sym == "BANKNIFTY" else 1.0)
    # trading days to next Thursday expiry (0 on Thursday), calendar approx
    wd = F.t.weekday.values
    F.dte_cal = ((3 - wd) % 7)
    F.mins_left = ((15 * 60 + 30) - (F.t.hour * 60 + F.t.minute + tf)).values
    F.tf = tf
    return F

def T_years(F, i):
    return (F.dte_cal[i] * 1.0 + F.mins_left[i] / 375.0) / 252.0 if F.dte_cal[i] > 0 else F.mins_left[i] / 375.0 / 252.0

def run(F, long_sig, short_sig, exit_fn, opt_stop=None, fut_stop=None, tgt=None, cost_fut=0.0003, cost_opt=0.02, max_per_day=99):
    """exit_fn(i, side) -> True to exit at bar i close. fut_stop/tgt: arrays of price levels set at entry (or None)."""
    c, h, l = F.c, F.h, F.l; n = len(c); out = []; i = 0; day_count = {}
    while i < n - 1:
        side = 1 if long_sig[i] else (-1 if short_sig[i] else 0)
        if side == 0 or not F.can_enter[i] or day_count.get(F.day_id[i], 0) >= max_per_day:
            i += 1; continue
        e = c[i]; K = round(e / 50) * 50; call = side > 0; iv = F.iv[i]
        p0 = bs_call_put(e, K, T_years(F, i), iv, call)
        st = fut_stop(i, side) if fut_stop else None; tg = tgt(i, side) if tgt else None
        j = i + 1; px = None; why = ""
        while j < n:
            if F.day_id[j] != F.day_id[i]: j -= 1; px = c[j]; why = "eod"; break
            if st is not None and ((side > 0 and l[j] <= st) or (side < 0 and h[j] >= st)): px = st; why = "stop"; break
            if tg is not None and ((side > 0 and h[j] >= tg) or (side < 0 and l[j] <= tg)): px = tg; why = "tgt"; break
            if opt_stop is not None:
                worst = l[j] if side > 0 else h[j]
                if bs_call_put(worst, K, T_years(F, j), iv, call) <= p0 * (1 - opt_stop):
                    # exit at the premium stop: solve the underlying level approximately = worst
                    px = None; why = "optstop"; break
            if F.must_exit[j] == 1: px = c[j]; why = "eod"; break
            if exit_fn(j, side): px = c[j]; why = "rule"; break
            j += 1
        if j >= n: j = n - 1; px = c[j]
        if why == "optstop":
            opt_r = -opt_stop - cost_opt; fut_px = l[j] if side > 0 else h[j]
        else:
            opt_r = bs_call_put(px, K, T_years(F, j), iv, call) / p0 - 1 - cost_opt; fut_px = px
        out.append(dict(t=F.t[i], side=side, fut=side * (fut_px / e - 1) - cost_fut, opt=opt_r, bars=j - i, why=why))
        day_count[F.day_id[i]] = day_count.get(F.day_id[i], 0) + 1
        i = j + 1
    return pd.DataFrame(out)

def summ(tr, name):
    if len(tr) == 0: return dict(setup=name, trades=0)
    y = tr.t.dt.year; yrs = (tr.t.max() - tr.t.min()).days / 365.25
    a, b = tr[tr.t < "2019-07-01"], tr[tr.t >= "2019-07-01"]
    yearly = tr.groupby(y).fut.sum()
    return dict(setup=name, trades=len(tr), per_yr=round(len(tr) / yrs), win=round((tr.fut > 0).mean(), 2),
                fut_pct=round(tr.fut.mean() * 100, 3), fut_t=round(tr.fut.mean() / tr.fut.std() * np.sqrt(len(tr)), 1),
                fut_1H=round(a.fut.mean() * 100, 3), fut_2H=round(b.fut.mean() * 100, 3), yrs_pos=f"{(yearly > 0).sum()}/{len(yearly)}",
                opt_pct=round(tr.opt.mean() * 100, 1), opt_win=round((tr.opt > 0).mean(), 2),
                opt_1H=round(a.opt.mean() * 100, 1), opt_2H=round(b.opt.mean() * 100, 1), bars=round(tr.bars.mean(), 1))

def cross_up(a, b): return (a > b) & (np.r_[np.nan, a[:-1]] <= np.r_[np.nan, b[:-1]])
def cross_dn(a, b): return (a < b) & (np.r_[np.nan, a[:-1]] >= np.r_[np.nan, b[:-1]])

def vwap_ohlc4(F):
    tp = (F.o + F.h + F.l + F.c) / 4
    df = pd.DataFrame({"pv": tp * F.v, "v": F.v, "d": F.day_id}); g = df.groupby("d")
    return (g.pv.cumsum() / g.v.cumsum()).to_numpy()

