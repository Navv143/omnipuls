"""Index option-buying discovery dataset. Nifty / Bank Nifty near-month futures, real 1-min volume + OI, 2015-2023.
Each 5-min bar (close) gets: cumulative delta (buy-sell volume from 1-min candles), OI buildup, RSI, MACD, VWAP, EMA,
Bollinger, levels (PDH/PDL/opening range/day high-low) with sweep / breakout flags, time, ATR, VIX, gap.
Outcomes: futures move and ATM weekly option P&L for a CALL and a PUT bought at that close (stop -25% premium,
target +50%, max 60 min, exit by 15:20)."""
import sys, numpy as np, pandas as pd
from scipy.stats import norm
import swing1m as S1, grid_engine as G
sym = sys.argv[1]
m = S1.load(sym)
m["dt"] = m["dt"] - pd.Timedelta(minutes=1)           # bar start
m = m.set_index("dt")
rng1 = (m.h - m.l).replace(0, np.nan)
m["delta"] = (m.v * ((m.c - m.o) / rng1).fillna(np.sign(m.c - m.c.shift(1)).fillna(0)))
day = m.index.normalize(); base = day + pd.Timedelta(hours=9, minutes=15)
k = ((m.index - base) // pd.Timedelta(minutes=5)).astype(int)
lab = base + pd.to_timedelta(k * 5, unit="m")
b = m.groupby(lab).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum"),
                       oi=("oi", "last"), delta=("delta", "sum")).dropna()
b = b[(b.index.time >= pd.Timestamp("09:15").time()) & (b.index.time <= pd.Timestamp("15:25").time())]
b["day"] = b.index.normalize(); b["tm"] = b.index.strftime("%H:%M")
g = b.groupby("day")
# daily context
D = g.agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum"), oi=("oi", "last"))
pc = D.c.shift(1)
tr = pd.concat([D.h - D.l, (D.h - pc).abs(), (D.l - pc).abs()], axis=1).max(axis=1)
D["atr"] = tr.rolling(14).mean().shift(1); D["pdh"] = D.h.shift(1); D["pdl"] = D.l.shift(1); D["pc"] = pc
D["poi"] = D.oi.shift(1); D["gap"] = D.o / pc - 1
for c_ in ("atr", "pdh", "pdl", "pc", "poi", "gap"):
    b[c_] = b.day.map(D[c_])
vix = pd.read_csv("/home/claude/udata/INDIA VIX_5minute.csv", parse_dates=["date"])
b["vix"] = b.day.map(vix.groupby(vix.date.dt.normalize()).open.first()).ffill()
# intraday running
b["cum_v"] = g.v.cumsum(); b["cvd"] = g.delta.cumsum()
b["cvd_n"] = b.cvd / b.cum_v                                     # day's net buying share (-1..1)
vavg = b.v.rolling(75 * 5).mean()
for w in (3, 6, 12):
    b[f"dlt{w}"] = b.delta.rolling(w).sum() / (vavg * w)          # recent net buying vs normal volume
b["dlt_flip_up"] = (b.dlt6 > 0.15) & (b.dlt6.shift(6) < -0.15)
b["dlt_flip_dn"] = (b.dlt6 < -0.15) & (b.dlt6.shift(6) > 0.15)
slot = b.tm
b["vol_x"] = b.v / b.groupby(slot).v.transform(lambda s: s.rolling(20, min_periods=5).mean().shift(1))
b["oi_chg_day"] = b.oi / b.poi - 1
b["oi_chg3"] = b.oi.pct_change(3)
b.loc[b.tm <= "09:25", "oi_chg3"] = np.nan
b["px_chg3"] = b.c.pct_change(3)
b["build3"] = np.select([(b.px_chg3 > 0) & (b.oi_chg3 > 0), (b.px_chg3 > 0) & (b.oi_chg3 < 0),
                         (b.px_chg3 < 0) & (b.oi_chg3 > 0), (b.px_chg3 < 0) & (b.oi_chg3 < 0)],
                        ["long_build", "short_cover", "short_build", "long_unwind"], "none")
c = b.c.values
b["rsi"] = G.rsi(c, 14); b["rsi_d3"] = b.rsi - b.rsi.shift(3)
macd = G.ema(c, 12) - G.ema(c, 26); sig = G.ema(macd, 9); hist = macd - sig
b["macd_hist_atr"] = hist / b.atr
b["macd_flip_up"] = (hist > 0) & (np.r_[np.nan, hist[:-1]] <= 0)
b["macd_flip_dn"] = (hist < 0) & (np.r_[np.nan, hist[:-1]] >= 0)
b["vwap"] = (b.c * b.v).groupby(b.day).cumsum() / b.cum_v
b["vwap_atr"] = (b.c - b.vwap) / b.atr
e9, e21 = G.ema(c, 9), G.ema(c, 21)
b["ema_gap_atr"] = (e9 - e21) / b.atr
b["ema_cross_up"] = (e9 > e21) & (np.r_[np.nan, e9[:-1]] <= np.r_[np.nan, e21[:-1]])
b["ema_cross_dn"] = (e9 < e21) & (np.r_[np.nan, e9[:-1]] >= np.r_[np.nan, e21[:-1]])
mid = pd.Series(c).rolling(20).mean().values; sd = pd.Series(c).rolling(20).std().values
b["bb_pctb"] = (c - (mid - 2 * sd)) / (4 * sd)
bw = 4 * sd / mid
b["bb_bw_rank"] = pd.Series(bw).rolling(750, min_periods=100).rank(pct=True).values   # squeeze = low rank
b["day_hi"] = g.h.cummax(); b["day_lo"] = g.l.cummin()
orh = b[b.tm < "09:30"].groupby("day").h.max(); orl = b[b.tm < "09:30"].groupby("day").l.min()
b["orh"] = b.day.map(orh); b["orl"] = b.day.map(orl)
b.loc[b.tm < "09:30", ["orh", "orl"]] = np.nan
prev_hi = g.h.transform(lambda s: s.cummax().shift(1)); prev_lo = g.l.transform(lambda s: s.cummin().shift(1))
for nm, lvl in (("pdh", b.pdh), ("pdl", b.pdl), ("orh", b.orh), ("orl", b.orl)):
    b[f"d_{nm}_atr"] = (b.c - lvl) / b.atr
# sweeps: this bar pierced a level and closed back (bull sweep below support / bear sweep above resistance)
b["sweep_low"] = ((b.l < b.pdl) & (b.c > b.pdl)) | ((b.l < b.orl) & (b.c > b.orl)) | ((b.l < prev_lo) & (b.c > prev_lo) & (b.tm >= "10:00"))
b["sweep_high"] = ((b.h > b.pdh) & (b.c < b.pdh)) | ((b.h > b.orh) & (b.c < b.orh)) | ((b.h > prev_hi) & (b.c < prev_hi) & (b.tm >= "10:00"))
b["break_up"] = ((b.c > b.pdh) & (b.c.shift(1) <= b.pdh)) | ((b.c > b.orh) & (b.c.shift(1) <= b.orh))
b["break_dn"] = ((b.c < b.pdl) & (b.c.shift(1) >= b.pdl)) | ((b.c < b.orl) & (b.c.shift(1) >= b.orl))
b["range_x"] = (b.h - b.l) / (b.h - b.l).rolling(20).mean()
b["body"] = (b.c - b.o) / (b.h - b.l).replace(0, np.nan)
b["from_open_atr"] = (b.c - b.groupby("day").o.transform("first")) / b.atr
b["day_range_used"] = (b.day_hi - b.day_lo) / b.atr
b["mins"] = (b.index.hour * 60 + b.index.minute) - 555
b["dow"] = b.index.weekday
# ---------------- outcomes (vectorised over the next 12 bars)
n = len(b); H = 12
C = b.c.values; Hh = b.h.values; Ll = b.l.values; dayid = pd.factorize(b.day)[0]; mins = b.mins.values
Fc = np.full((n, H), np.nan); Fh = Fc.copy(); Fl = Fc.copy(); Fm = Fc.copy()
for j in range(1, H + 1):
    ok = np.r_[dayid[j:] == dayid[:-j], np.zeros(j, bool)]
    sl = slice(j, None)
    Fc[:n - j, j - 1] = np.where(ok[:n - j], C[sl], np.nan); Fh[:n - j, j - 1] = np.where(ok[:n - j], Hh[sl], np.nan)
    Fl[:n - j, j - 1] = np.where(ok[:n - j], Ll[sl], np.nan); Fm[:n - j, j - 1] = np.where(ok[:n - j], mins[sl], np.nan)
b["fwd30"] = Fc[:, 5] / C - 1; b["fwd60"] = Fc[:, 11] / C - 1
b["mfe60_up"] = (np.nanmax(Fh, 1) / C - 1); b["mfe60_dn"] = (1 - np.nanmin(Fl, 1) / C)
iv = (b.vix.values / 100) * (1.2 if sym == "BANKNIFTY" else 1.0)
dte = ((3 - b.index.weekday.values) % 7).astype(float)
step = 100 if sym == "BANKNIFTY" else 50
K = np.round(C / step) * step
def T(minutes_since_open):
    left = np.clip(375 - (minutes_since_open + 5), 0, 375) / 375
    return np.maximum((dte[:, None] if np.ndim(minutes_since_open) == 2 else dte) + left, 1e-4) / 252 if True else 0
def bs(S, K_, Tt, s, call):
    Tt = np.maximum(Tt, 1e-6); d1 = (np.log(S / K_) + 0.5 * s**2 * Tt) / (s * np.sqrt(Tt)); d2 = d1 - s * np.sqrt(Tt)
    cval = S * norm.cdf(d1) - K_ * norm.cdf(d2)
    return cval if call else cval - S + K_
for side, call in (("call", True), ("put", False)):
    p0 = bs(C, K, T(mins), iv, call)
    # worst/best underlying inside each future bar approximated by its low/high
    adverse = Fl if call else Fh; favour = Fh if call else Fl
    Tf = T(Fm)
    pa = bs(adverse, K[:, None], Tf, iv[:, None], call) / p0[:, None] - 1
    pf = bs(favour, K[:, None], Tf, iv[:, None], call) / p0[:, None] - 1
    pc_ = bs(Fc, K[:, None], Tf, iv[:, None], call) / p0[:, None] - 1
    res = np.full(n, np.nan)
    for i in range(n):
        r = np.nan
        for j in range(H):
            if np.isnan(Fc[i, j]) or Fm[i, j] >= 365:           # 15:20 square-off
                break
            if pa[i, j] <= -0.25: r = -0.25; break                # stop first (conservative)
            if pf[i, j] >= 0.50: r = 0.50; break
            r = pc_[i, j]
        res[i] = r
    b[f"opt_{side}"] = res - 0.02                                   # 2% of premium costs
    b[f"prem_{side}"] = p0 / C
b.drop(columns=["day"]).to_parquet(f"idx5_{sym}.parquet")
print(sym, b.shape, b.index.min(), b.index.max())
