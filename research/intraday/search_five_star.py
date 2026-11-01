import numpy as np, pandas as pd, itertools, time, warnings, pickle; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, five_star as FS, five_star2 as F2
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]; nz = vf["net_z"]
banks = [d.idx(b) for b in ["HDFCBANK","ICICIBANK","KOTAKBANK","AXISBANK","SBIN","BANKBARODA","PNB","CANBK","UNIONBANK"]]
bturn = np.nansum(np.nan_to_num(d.C[banks] * d.V[banks]), axis=0)
with np.errstate(all="ignore"):
    rng = d.H[banks] - d.L[banks]; press = np.where(rng > 0, (d.C[banks] - d.O[banks]) / rng, 0)
bnet = np.nansum(np.nan_to_num(d.C[banks] * d.V[banks]) * np.nan_to_num(press), axis=0)
def ratio_of(x): return x / pd.DataFrame(x).rolling(20, min_periods=10).mean().shift(1).values
def z_of(n):
    a = pd.DataFrame(np.abs(n)).rolling(20, min_periods=10).mean().shift(1).values; return n / np.where(a > 0, a, np.nan)
srcs = {"market": (ratio_of(turn), nz), "banks": (ratio_of(bturn), z_of(bnet))}
cases = [("NIFTY BANK", "market", 12), ("NIFTY BANK", "banks", 12), ("NIFTY 50", "market", 6)]
rows = []; t0 = time.time()
for sym, src, cost in cases:
    vr, nzz = srcs[src]
    for stp in ((10, 3.0), (10, 2.0), (7, 3.0)):
        ind = FS.indicators(d, sym, turn if src == "market" else bturn, atr_n=stp[0], factor=stp[1])
        for vt, na, last, tr, ex in itertools.product((1.5, 2.0, 2.5), ((False, 0), (True, 0.0), (True, 0.5)),
                                                     ("15:00", "13:00", "11:30"), (False, True), ("trail", "be_trail", "half_trail")):
            t = F2.run(d, sym, ind, vr, nzz, vol_thr=vt, net_align=na[0], net_min=na[1], last=last, trend=tr, exit_mode=ex)
            if t.empty: continue
            net = t.pts - cost; a = t.date < "2022"; b = ~a
            rows.append({"sym": sym, "vol": src, "st": f"{stp[0]}/{stp[1]}", "vol_thr": vt, "net_align": f"{na[0]}:{na[1]}", "last": last,
                         "trend": tr, "exit": ex, "n_in": int(a.sum()), "n_out": int(b.sum()),
                         "in_net": net[a].mean(), "in_t": net[a].mean() / net[a].std() * np.sqrt(a.sum()) if a.sum() > 2 else np.nan,
                         "in_yrs": int((net[a].groupby(t.date[a].dt.year).sum() > 0).sum()),
                         "out_net": net[b].mean(), "out_t": net[b].mean() / net[b].std() * np.sqrt(b.sum()) if b.sum() > 2 else np.nan,
                         "out_yrs": int((net[b].groupby(t.date[b].dt.year).sum() > 0).sum())})
        print(sym, src, stp, len(rows), round(time.time() - t0), flush=True)
r = pd.DataFrame(rows); r.to_csv("five_star_search.csv", index=False)
