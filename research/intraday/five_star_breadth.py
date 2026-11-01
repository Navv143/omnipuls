import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, five_star as FS, five_star2 as F2, momentum as MO, internals as IN
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]; nz = vf["net_z"]
vr = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
m = MO.measures(d, "NIFTY BANK")
base_L = (m["rsi"] >= 65) & (m["rng_x"] >= 1.5) & (m["body"] >= 0.5)
base_S = (m["rsi"] <= 35) & (m["rng_x"] >= 1.5) & (m["body"] <= -0.5)
fb = IN.build(d, "NIFTY BANK"); fn = IN.build(d, "NIFTY 50")
rows = []
for st in ((10, 3.0), (5, 2.0)):
    ind = FS.indicators(d, "NIFTY BANK", turn, atr_n=st[0], factor=st[1])
    V = {"current (no breadth)": (base_L, base_S)}
    for lab, f in (("bank stocks", fb), ("Nifty 50 stocks", fn)):
        for thr in (0.6, 0.7):
            V[f"+ {lab} above VWAP >= {int(thr*100)}%"] = (base_L & (f["breadth_vwap"] >= thr), base_S & (f["breadth_vwap"] <= 1 - thr))
        V[f"+ {lab} range expansion >= 1.2x"] = (base_L & (f["range_x"] >= 1.2), base_S & (f["range_x"] >= 1.2))
        V[f"+ {lab} new day highs/lows >= 20%"] = (base_L & (f["pct_new_hi"] >= 0.2), base_S & (f["pct_new_lo"] >= 0.2))
    V["+ heavyweights leading the move"] = (base_L & (fb["heavy_minus_rest"] > 0), base_S & (fb["heavy_minus_rest"] < 0))
    for lab, (ml, ms) in V.items():
        t = F2.run(d, "NIFTY BANK", ind, vr, nz, vol_thr=1.5, net_align=True, net_min=0.0, exit_mode="trail", mom_long=ml, mom_short=ms)
        if len(t) < 50: continue
        net = t.pts - 12; a = t.date < "2022"; ys = net.groupby(t.date.dt.year).sum(); eq = net.cumsum()
        rows.append({"Supertrend": f"{st[0]}/{st[1]}", "version": lab, "trades/yr": round(len(t) / 11.2), "win%": round(100 * (t.pts > 0).mean(), 1),
                     "net pts": round(net.mean(), 1), "t": round(net.mean() / net.std() * np.sqrt(len(t)), 2),
                     "2015-21": round(net[a].mean(), 1), "2022-26": round(net[~a].mean(), 1), "yrs +": f"{(ys > 0).sum()}/{len(ys)}",
                     "total": round(net.sum()), "max DD": round((eq - eq.cummax()).min())})
out = pd.DataFrame(rows); out.to_csv("five_star_breadth.csv", index=False)
pd.set_option("display.width", 250, "display.max_columns", 20, "display.max_rows", 50)
print(out.to_string(index=False))
