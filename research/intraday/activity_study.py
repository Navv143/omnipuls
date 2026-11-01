"""Which 'unusual activity' measures predict the next 30/60 minutes / close? Nifty 100 stocks, 5-min, 2015-2026.
All baselines are same-time-of-day averages over the previous 20 sessions (no look-ahead)."""
import numpy as np, pandas as pd, engine as E, warnings
warnings.filterwarnings("ignore")
D = E.Data()
S = D.stock_idx
O, H, L, C, V = (x[S] for x in (D.O, D.H, D.L, D.C, D.V))       # [stock, day, slot]
ns, nd, nt = C.shape
tp = (H + L + C) / 3
turn = np.nan_to_num(V) * np.nan_to_num(tp)
cumV = np.nancumsum(np.nan_to_num(V), 2)
def slot_base(x, n=20):     # mean over previous n days, same slot -> [stock, day, slot]
    s = pd.DataFrame(x.transpose(1, 0, 2).reshape(nd, -1))
    m = s.rolling(n, min_periods=10).mean().shift(1).values
    return m.reshape(nd, ns, nt).transpose(1, 0, 2)
rng_sofar = np.fmax.accumulate(H, 2) - np.fmin.accumulate(L, 2)
vol_x_slot = V / slot_base(np.nan_to_num(V))
cumvol_x = cumV / slot_base(cumV)
range_x = rng_sofar / slot_base(rng_sofar)
cand_rng_x = (H - L) / slot_base(H - L)
dopen = O[:, :, :1]
chg_open = C / dopen - 1
gap = (dopen[..., 0] / D.prev_close[S] - 1)[:, :, None] * np.ones((1, 1, nt))
absgap_base = pd.DataFrame(np.abs(gap[:, :, 0]).T).rolling(20, min_periods=10).mean().shift(1).values.T[:, :, None]
gap_x = np.abs(gap) / absgap_base
vwap = np.nancumsum(turn, 2) / np.where(cumV > 0, cumV, np.nan)
vw_dist = C / vwap - 1
atr = D.atr[S][:, :, None]
mom_atr = (C - dopen) / atr                                     # move from open in daily ATRs
body = (C - O) / np.where(H - L > 0, H - L, np.nan)
# RSI(14) on 5-min closes, continuous across days
def rsi(c, n=14):
    flat = c.reshape(ns, -1); out = np.full_like(flat, np.nan)
    for k in range(ns):
        s = pd.Series(flat[k]); d = s.diff()
        g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
        out[k] = (100 - 100 / (1 + g / l)).values
    return out.reshape(ns, nd, nt)
R = rsi(C)
# forward returns from the close of slot t
def fwd(k):
    f = np.full_like(C, np.nan); f[:, :, :nt - k] = C[:, :, k:] / C[:, :, :nt - k] - 1; return f
F30, F60 = fwd(6), fwd(12)
Fcl = C[:, :, 72:73] / C - 1                                     # to 15:15
feat = dict(vol_x_slot=vol_x_slot, cumvol_x=cumvol_x, range_x=range_x, cand_rng_x=cand_rng_x, gap_x=gap_x)
signed = dict(chg_open=chg_open, mom_atr=mom_atr, vw_dist=vw_dist, rsi=R - 50, body=body, gap=gap)
slots = range(3, 66, 3)      # 09:30 .. 14:45 every 15 min
yrs = D.days.year.values
rows = []
def ic(x, y, mask=None):     # cross-sectional rank correlation per (day, slot), averaged
    out = []
    for t in slots:
        xs, ys = x[:, :, t], y[:, :, t]
        a = pd.DataFrame(xs.T).rank(axis=1); b = pd.DataFrame(ys.T).rank(axis=1)
        c = a.sub(a.mean(1), axis=0).mul(b.sub(b.mean(1), axis=0)).sum(1) / np.sqrt((a.sub(a.mean(1), axis=0)**2).sum(1) * (b.sub(b.mean(1), axis=0)**2).sum(1))
        out.append(c.values)
    M = np.array(out)     # [slot, day]
    return np.nanmean(M), np.nanmean(M[:, yrs >= 2022]), M
print("Signed signals: rank correlation with forward return (positive = continuation)")
for nm, x in signed.items():
    for fn, y in (("30m", F30), ("60m", F60), ("close", Fcl)):
        a, b, _ = ic(x, y); rows.append(dict(sig=nm, fwd=fn, IC=round(a, 4), IC_2022=round(b, 4)))
print(pd.DataFrame(rows).pivot(index="sig", columns="fwd", values=["IC", "IC_2022"]).round(4))
# Activity (unsigned) as amplifier: does momentum continue more when activity is unusual?
print("\nMomentum (move from open, ATRs) continuation by activity bucket: avg fwd return to 15:15 in %, long top-decile mover / short bottom-decile")
out = []
for an, A in feat.items():
    for lo, hi in ((0, 1), (1, 2), (2, 3), (3, 1e9)):
        res, res22 = [], []
        for t in slots:
            m = mom_atr[:, :, t]; a = A[:, :, t]; f = Fcl[:, :, t]
            q90 = np.nanpercentile(m, 90, axis=0); q10 = np.nanpercentile(m, 10, axis=0)
            sel_l = (m >= q90) & (a >= lo) & (a < hi); sel_s = (m <= q10) & (a >= lo) & (a < hi)
            r = np.where(sel_l, f, np.where(sel_s, -f, np.nan))
            res.append(r)
        r = np.array(res)
        out.append(dict(activity=an, bucket=f"{lo}-{hi if hi < 1e8 else 'inf'}", n=int(np.isfinite(r).sum()),
                        fwd_close_pct=round(np.nanmean(r) * 100, 3), since2022=round(np.nanmean(r[:, :, yrs >= 2022]) * 100, 3)))
print(pd.DataFrame(out).to_string())
