import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, five_star as FS, optmodel as M
pd.set_option("display.width", 260, "display.max_columns", 30)
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]
ratio = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
vix = pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1], d.C.shape[2])
def dte(dd):
    wd = 3 if dd < pd.Timestamp("2025-09-01") else 1
    n, x = 0, dd
    while True:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: n += 1
        if x.weekday() == wd: return n
def st(t, lab, cost_pts):
    di = np.array([d.days.get_loc(x) for x in t.date])
    iv = vix[di, t.signal_slot.values] / 100
    o, _ = M.option_return(t.entry.values, t.exit.values, t.side.values, np.array([dte(x) for x in t.date]),
                           t.entry_slot.values, t.exit_slot.values, iv, cost=0.015)
    net = t.pts - cost_pts; yrs = net.groupby(t.date.dt.year).sum(); b = t.date >= "2022"
    return {"setup": lab, "trades": len(t), "win%": round(100 * (t.pts > 0).mean(), 1), "avg risk pts": round(t.risk.mean(), 1),
            "pts gross": round(t.pts.mean(), 2), f"pts after {cost_pts}": round(net.mean(), 2),
            "PF gross": round(t.pts[t.pts > 0].sum() / -t.pts[t.pts <= 0].sum(), 2), "yrs + net": f"{(yrs > 0).sum()}/{len(yrs)}",
            "15-21 gross": round(t.pts[~b].mean(), 2), "22-26 gross": round(t.pts[b].mean(), 2),
            "opt %": round(100 * o.mean(), 2), "opt 22-26": round(100 * o[b.values].mean(), 2),
            "t": round(t.pts.mean() / t.pts.std() * np.sqrt(len(t)), 2)}
R = []
for sym, cost in (("NIFTY 50", 6), ("NIFTY BANK", 12)):
    ind = FS.indicators(d, sym, turn)
    for vlab, vok in (("no volume filter", None), ("volume >= 20d avg", ratio >= 1), ("volume >= 1.5x avg", ratio >= 1.5)):
        for rr, mode in ((1.0, "target"), (2.0, "target"), (None, "trail")):
            t = FS.run(d, sym, ind, vok, rr=rr or 1, exit_mode=mode)
            R.append(st(t, f"{sym} | {vlab} | {'target ' + str(rr) + 'R' if mode == 'target' else 'trail Supertrend'}", cost))
out = pd.DataFrame(R); out.to_csv("five_star_results.csv", index=False); print(out.to_string(index=False))
