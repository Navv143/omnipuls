import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, five_star as FS, five_star2 as F2, optmodel as M
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]; nz = vf["net_z"]
vr = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
vix = pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1], d.C.shape[2])
def dte(dd, monthly=False):
    if monthly: return 12
    wd = 3 if dd < pd.Timestamp("2025-09-01") else 1; n, x = 0, dd
    while True:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: n += 1
        if x.weekday() == wd: return n
def report(t, lab, cost, monthly=False):
    net = t.pts - cost; a = t.date < "2022"
    di = np.array([d.days.get_loc(x) for x in t.date]); iv = vix[di, t.signal_slot.values] / 100
    exitpx = t.entry + t.side * t.pts
    o, _ = M.option_return(t.entry.values, exitpx.values, t.side.values, np.array([dte(x, monthly) for x in t.date]),
                           t.entry_slot.values, t.exit_slot.values, iv, cost=0.02)
    eq = net.cumsum(); yrs = net.groupby(t.date.dt.year).sum()
    return {"version": lab, "trades": len(t), "per yr": round(len(t) / 11.2), "win%": round(100 * (t.pts > 0).mean(), 1),
            "net pts/trade": round(net.mean(), 1), "t": round(net.mean() / net.std() * np.sqrt(len(t)), 2),
            "2015-21": round(net[a].mean(), 1), "2022-26": round(net[~a].mean(), 1), "yrs +": f"{(yrs > 0).sum()}/{len(yrs)}",
            "PF": round(net[net > 0].sum() / -net[net <= 0].sum(), 2), "max DD pts": round((eq - eq.cummax()).min()),
            "total pts": round(net.sum()), "options %/trade (2% cost)": round(100 * o.mean(), 2),
            "options 22-26": round(100 * o[(~a).values].mean(), 2)}, yrs
rows = []; byyr = {}
ind = FS.indicators(d, "NIFTY BANK", turn)
V = [("Your script (1R target, no volume)", dict(vol_thr=-1, exit_mode="target1R")),
     ("Previous: 2x volume + trail", dict(vol_thr=2.0, exit_mode="trail")),
     ("IMPROVED: 2x volume + net volume with trade + trail", dict(vol_thr=2.0, net_align=True, net_min=0.0, exit_mode="trail")),
     ("IMPROVED + breakeven at 1R", dict(vol_thr=2.0, net_align=True, net_min=0.0, exit_mode="be_trail")),
     ("IMPROVED, 2.5x volume", dict(vol_thr=2.5, net_align=True, net_min=0.0, exit_mode="trail"))]
for lab, kw in V:
    if kw.get("exit_mode") == "target1R":
        t = FS.run(d, "NIFTY BANK", ind, None, rr=1.0, exit_mode="target")
    else:
        t = F2.run(d, "NIFTY BANK", ind, vr, nz, **kw)
    r, y = report(t, lab, 12, monthly=False); rows.append(r); byyr[lab] = y.round(0)
    if lab.startswith("IMPROVED: 2x"):
        t.to_csv("five_star_improved_trades.csv", index=False)
        r2, _ = report(t, lab + " | MONTHLY options", 12, monthly=True); rows.append(r2)
out = pd.DataFrame(rows); out.to_csv("five_star_improved.csv", index=False)
pd.set_option("display.width", 260, "display.max_columns", 30)
print(out.to_string(index=False)); print(pd.DataFrame(byyr).T.to_string())
