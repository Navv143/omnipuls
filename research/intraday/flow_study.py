"""Does net money flow (turnover x candle pressure) predict the next 30/60 min or the close? Stock and sector level.
Nifty 100 stocks, 5-min 2015-2026. Flow so far today normalised by the stock's usual daily turnover (20d)."""
import numpy as np, pandas as pd, engine as E, warnings
warnings.filterwarnings("ignore")
D = E.Data(); S = D.stock_idx
O, H, L, C, V = (x[S] for x in (D.O, D.H, D.L, D.C, D.V))
ns, nd, nt = C.shape
turn = np.nan_to_num(V * (H + L + C) / 3)
rng = H - L
press = np.where(rng > 0, (C - O) / np.where(rng > 0, rng, 1), 0.0)
flow = turn * np.nan_to_num(press)
dturn = turn.sum(2)
usual = pd.DataFrame(dturn.T).rolling(20, min_periods=10).mean().shift(1).values.T[:, :, None]
cumflow = np.cumsum(flow, 2) / usual                      # today's net flow so far, in units of a usual day's turnover
roll12 = np.zeros_like(flow); cs = np.cumsum(flow, 2)
roll12[:, :, 12:] = cs[:, :, 12:] - cs[:, :, :-12]; roll12[:, :, :12] = cs[:, :, :12]; roll12 /= usual   # last 60 min
def fwd(k):
    f = np.full_like(C, np.nan); f[:, :, :nt - k] = C[:, :, k:] / C[:, :, :nt - k] - 1; return f
F = {"30m": fwd(6), "60m": fwd(12), "close": C[:, :, 72:73] / C - 1}
chg = C / O[:, :, :1] - 1
slots = range(6, 66, 3); yrs = D.days.year.values
def ic(x, y):
    out = []
    for t in slots:
        a = pd.DataFrame(x[:, :, t].T).rank(axis=1); b = pd.DataFrame(y[:, :, t].T).rank(axis=1)
        a = a.sub(a.mean(1), axis=0); b = b.sub(b.mean(1), axis=0)
        out.append(((a * b).sum(1) / np.sqrt((a**2).sum(1) * (b**2).sum(1))).values)
    M = np.array(out); return round(np.nanmean(M), 4), round(np.nanmean(M[:, yrs >= 2022]), 4)
# flow beyond price: residual of flow rank after price change (does flow add info over just the move?)
def resid(x, p):
    r = np.full_like(x, np.nan)
    for t in slots:
        a = pd.DataFrame(x[:, :, t].T).rank(axis=1, pct=True).values; b = pd.DataFrame(p[:, :, t].T).rank(axis=1, pct=True).values
        r[:, :, t] = (a - b).T
    return r
rows = []
for nm, x in (("flow today", cumflow), ("flow last 60m", roll12), ("price chg from open", chg), ("flow minus price rank", resid(cumflow, chg))):
    for fn, y in F.items():
        a, b = ic(x, y); rows.append(dict(signal=nm, fwd=fn, IC=a, IC_since2022=b))
print(pd.DataFrame(rows).pivot(index="signal", columns="fwd", values=["IC", "IC_since2022"]).to_string())
# sector level: sector net flow today (sum of flows / sum usual) -> next 60m sector return, rank across sectors
sec = np.array([D.sector[D.syms[i]] for i in S]); us = sorted(set(sec)); us = [u for u in us if (sec == u).sum() >= 3]
SF = np.stack([np.nansum(np.where((sec == u)[:, None, None], np.cumsum(flow, 2), 0), 0) / np.nansum(np.where((sec == u)[:, None, None], usual, 0), 0) for u in us])
SR = {k: np.stack([np.nanmean(np.where((sec == u)[:, None, None], y, np.nan), 0) for u in us]) for k, y in F.items()}
SC = np.stack([np.nanmean(np.where((sec == u)[:, None, None], chg, np.nan), 0) for u in us])
print("\nSector level (", len(us), "sectors )")
for nm, x in (("sector flow today", SF), ("sector price chg", SC)):
    print(nm, {k: ic(x, y) for k, y in SR.items()})
# top-3 vs bottom-3 sectors by flow, next 60m spread
for k in ("60m", "close"):
    sp = []
    for t in slots:
        f = SF[:, :, t]; r = SR[k][:, :, t]
        o = np.argsort(np.nan_to_num(f, nan=0), 0)
        top = np.take_along_axis(r, o[-3:], 0).mean(0); bot = np.take_along_axis(r, o[:3], 0).mean(0); sp.append(top - bot)
    sp = np.array(sp); print(f"top-3 minus bottom-3 flow sectors, fwd {k}: {np.nanmean(sp)*100:+.3f}%  since 2022 {np.nanmean(sp[:, yrs>=2022])*100:+.3f}%")
