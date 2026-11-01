import numpy as np, pandas as pd, warnings, itertools; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, five_star as FS, five_star2 as F2, momentum as MO, optmodel as M
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]; nz = vf["net_z"]
vr = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
m = MO.measures(d, "NIFTY BANK")
vix = pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1], d.C.shape[2])
rsiL, rsiS = m["rsi"] >= 65, m["rsi"] <= 35
cL = (m["rng_x"] >= 1.5) & (m["body"] >= 0.5); cS = (m["rng_x"] >= 1.5) & (m["body"] <= -0.5)
moms = {"RSI + mom candle": (rsiL & cL, rsiS & cS), "RSI only": (rsiL, rsiS)}
rows = []
for ema_n, (an, fac) in itertools.product((21, 9), ((10, 3.0), (10, 2.0), (7, 2.0), (10, 1.5), (7, 1.5), (5, 2.0), (5, 1.5))):
    ind = FS.indicators(d, "NIFTY BANK", turn, atr_n=an, factor=fac, ema_n=ema_n)
    for mname, (ml, ms) in moms.items():
        t = F2.run(d, "NIFTY BANK", ind, vr, nz, vol_thr=1.5, net_align=True, net_min=0.0, exit_mode="trail", mom_long=ml, mom_short=ms)
        net = t.pts - 12; a = t.date < "2022"; eq = net.cumsum(); ys = net.groupby(t.date.dt.year).sum()
        di = np.array([d.days.get_loc(x) for x in t.date]); iv = vix[di, t.signal_slot.values] / 100
        om, _ = M.option_return(t.entry.values, (t.entry + t.side * t.pts).values, t.side.values, np.full(len(t), 12.0),
                                t.entry_slot.values, t.exit_slot.values, iv, cost=0.02)
        rows.append({"EMA": ema_n, "Supertrend": f"{an}/{fac}", "momentum": mname, "trades/yr": round(len(t) / 11.2),
                     "win%": round(100 * (t.pts > 0).mean(), 1), "avg risk pts": round(t.risk.mean()), "avg hold min": round(5 * (t.exit_slot - t.entry_slot).mean()),
                     "net pts/trade": round(net.mean(), 1), "t": round(net.mean() / net.std() * np.sqrt(len(t)), 2),
                     "2015-21": round(net[a].mean(), 1), "2022-26": round(net[~a].mean(), 1), "yrs +": f"{(ys > 0).sum()}/{len(ys)}",
                     "total pts": round(net.sum()), "max DD": round((eq - eq.cummax()).min()), "monthly opt %": round(100 * om.mean(), 1)})
        print(rows[-1], flush=True)
out = pd.DataFrame(rows); out.to_csv("ema_supertrend_test.csv", index=False)
pd.set_option("display.width", 260, "display.max_columns", 30)
print(out.to_string(index=False))
