import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, optmodel as M
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 200)
d = Data(); vf = SM.volume_features(d)
vix = pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1], d.C.shape[2])
def dte(dd):
    wd = 3 if dd < pd.Timestamp("2025-09-01") else 1
    n, x = 0, dd
    while True:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: n += 1
        if x.weekday() == wd: return n
def st(t, lab):
    if t.empty: return {"setup": lab, "trades": 0}
    di = np.array([d.days.get_loc(x) for x in t.date])
    iv = vix[di, np.clip(t.entry_slot.values - 1, 0, 74)] / 100
    o, _ = M.option_return(t.entry.values, t.exit.values, t.side.values, np.array([dte(x) for x in t.date]),
                           t.entry_slot.values, t.exit_slot.values, iv, cost=0.015)
    yrs = (t.pts - 6).groupby(t.date.dt.year).sum()
    b = t.date >= "2022"
    return {"setup": lab, "trades": len(t), "per yr": round(len(t) / 11.2), "win%": round(100 * (t.pts > 0).mean(), 1),
            "pts gross": round(t.pts.mean(), 2), "pts @2 cost": round(t.pts.mean() - 2, 2), "pts @6 cost": round(t.pts.mean() - 6, 2),
            "PF gross": round(t.pts[t.pts > 0].sum() / -t.pts[t.pts <= 0].sum(), 2), "yrs + @6": f"{(yrs > 0).sum()}/{len(yrs)}",
            "15-21 gross": round(t.pts[~b].mean(), 2), "22-26 gross": round(t.pts[b].mean(), 2),
            "opt %": round(100 * o.mean(), 2), "t gross": round(t.pts.mean() / t.pts.std() * np.sqrt(len(t)), 2)}
R = []
for lv, ud, uo in (("both levels", True, True), ("prev-day only", True, False), ("opening range only", False, True)):
    for vfil in (None, "fakeout", "divergence", "no_fakeout"):
        R.append(st(SM.run(d, vf, "sweep", vfil, ud, uo), f"FADE sweep | {lv} | volume: {vfil or 'none (your script)'}"))
    for vfil in (None, "confirmed", "unconfirmed"):
        R.append(st(SM.run(d, vf, "break", vfil, ud, uo), f"FOLLOW break | {lv} | volume: {vfil or 'none'}"))
out = pd.DataFrame(R); out.to_csv("sweep_smi_results.csv", index=False); print(out.to_string(index=False))
