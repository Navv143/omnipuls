import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, five_star as FS, five_star2 as F2, momentum as MO, optmodel as M
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]; nz = vf["net_z"]
vr = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
ind = FS.indicators(d, "NIFTY BANK", turn); m = MO.measures(d, "NIFTY BANK")
vix = pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1], d.C.shape[2])
def dte(dd):
    wd = 3 if dd < pd.Timestamp("2025-09-01") else 1; n, x = 0, dd
    while True:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: n += 1
        if x.weekday() == wd: return n
rsiL, rsiS = m["rsi"] >= 65, m["rsi"] <= 35
cL = (m["rng_x"] >= 1.5) & (m["body"] >= 0.5); cS = (m["rng_x"] >= 1.5) & (m["body"] <= -0.5)
V = [("Improved (last step): 2x vol + net vol", dict(vol_thr=2.0)),
     ("+ RSI 65/35, 1.5x vol", dict(vol_thr=1.5, mom_long=rsiL, mom_short=rsiS)),
     ("+ momentum candle, 1.5x vol", dict(vol_thr=1.5, mom_long=cL, mom_short=cS)),
     ("+ RSI 65/35 OR momentum candle, 1.5x vol", dict(vol_thr=1.5, mom_long=rsiL | cL, mom_short=rsiS | cS)),
     ("+ RSI 65/35 AND momentum candle, 1.5x vol", dict(vol_thr=1.5, mom_long=rsiL & cL, mom_short=rsiS & cS)),
     ("+ RSI 65/35, 1.5x vol, breakeven at 1R", dict(vol_thr=1.5, mom_long=rsiL, mom_short=rsiS, exit_mode="be_trail"))]
rows, yr = [], {}
for lab, kw in V:
    kw = {"net_align": True, "net_min": 0.0, "exit_mode": "trail", **kw}
    t = F2.run(d, "NIFTY BANK", ind, vr, nz, **kw)
    net = t.pts - 12; a = t.date < "2022"; eq = net.cumsum(); ys = net.groupby(t.date.dt.year).sum()
    di = np.array([d.days.get_loc(x) for x in t.date]); iv = vix[di, t.signal_slot.values] / 100
    o, _ = M.option_return(t.entry.values, (t.entry + t.side * t.pts).values, t.side.values, np.array([dte(x) for x in t.date]),
                           t.entry_slot.values, t.exit_slot.values, iv, cost=0.02)
    om, _ = M.option_return(t.entry.values, (t.entry + t.side * t.pts).values, t.side.values, np.full(len(t), 12.0),
                            t.entry_slot.values, t.exit_slot.values, iv, cost=0.02)
    rows.append({"version": lab, "trades": len(t), "per yr": round(len(t) / 11.2), "win%": round(100 * (t.pts > 0).mean(), 1),
                 "net pts/trade": round(net.mean(), 1), "t": round(net.mean() / net.std() * np.sqrt(len(t)), 2),
                 "2015-21": round(net[a].mean(), 1), "2022-26": round(net[~a].mean(), 1), "yrs +": f"{(ys > 0).sum()}/{len(ys)}",
                 "PF": round(net[net > 0].sum() / -net[net <= 0].sum(), 2), "total pts": round(net.sum()),
                 "max DD pts": round((eq - eq.cummax()).min()), "weekly opt %": round(100 * o.mean(), 1), "monthly opt %": round(100 * om.mean(), 1)})
    yr[lab] = ys.round(0)
    if lab == "+ RSI 65/35, 1.5x vol": t.to_csv("five_star_momentum_trades.csv", index=False)
out = pd.DataFrame(rows); out.to_csv("five_star_momentum.csv", index=False)
pd.set_option("display.width", 260, "display.max_columns", 30)
print(out.to_string(index=False)); print(pd.DataFrame(yr).T.to_string())
