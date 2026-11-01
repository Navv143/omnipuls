import numpy as np, pandas as pd, warnings, itertools; warnings.filterwarnings("ignore")
from engine import Data
import sweep_smi as SM, five_star as FS, five_star2 as F2, momentum as MO
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]; nz = vf["net_z"]
vr = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
ind = FS.indicators(d, "NIFTY BANK", turn); m = MO.measures(d, "NIFTY BANK")
ni = FS.indicators(d, "NIFTY 50", turn); nC = d.C[d.idx("NIFTY 50")]
F = {"none": (None, None)}
for a in (20, 25, 30): F[f"ADX>={a}"] = (m["adx"] >= a, m["adx"] >= a)
for a in (20, 25): F[f"ADX>={a} & DI aligned"] = ((m["adx"] >= a) & (m["pdi"] > m["mdi"]), (m["adx"] >= a) & (m["mdi"] > m["pdi"]))
for r in (55, 60, 65): F[f"RSI {r}/{100-r}"] = (m["rsi"] >= r, m["rsi"] <= 100 - r)
for k in (0.2, 0.4, 0.6): F[f"day move >= {k} ATR"] = (m["day_mom"] >= k, m["day_mom"] <= -k)
for k in (1.0, 1.5): F[f"candle range >= {k}x, body>=0.5"] = ((m["rng_x"] >= k) & (m["body"] >= 0.5), (m["rng_x"] >= k) & (m["body"] <= -0.5))
F["MACD hist aligned & rising"] = ((m["hist"] > 0) & (m["hist"] > m["hist_prev"]), (m["hist"] < 0) & (m["hist"] < m["hist_prev"]))
F["Nifty same side of its VWAP"] = (nC > ni["vwap"], nC < ni["vwap"])
COST = 12
def ev(ml, ms, vthr=2.0):
    t = F2.run(d, "NIFTY BANK", ind, vr, nz, vol_thr=vthr, net_align=True, net_min=0.0, exit_mode="trail", mom_long=ml, mom_short=ms)
    if t.empty: return None
    net = t.pts - COST; a = t.date < "2022"; b = ~a
    f = lambda x: (x.mean(), x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 else np.nan)
    i, it = f(net[a]); o, ot = f(net[b])
    return {"n_in": int(a.sum()), "in_net": round(i, 1), "in_t": round(it, 2), "in_total": round(net[a].sum()),
            "in_yrs": int((net[a].groupby(t.date[a].dt.year).sum() > 0).sum()),
            "n_out": int(b.sum()), "out_net": round(o, 1), "out_t": round(ot, 2), "out_total": round(net[b].sum()),
            "out_yrs": int((net[b].groupby(t.date[b].dt.year).sum() > 0).sum())}
rows = []
for name, (ml, ms) in F.items():
    for vthr in (1.5, 2.0):
        r = ev(ml, ms, vthr)
        if r: rows.append({"filter": name, "vol>=": vthr, **r}); print(rows[-1], flush=True)
# pairs of single filters (2.0x volume)
singles = [k for k in F if k != "none"]
for a_, b_ in itertools.combinations(singles, 2):
    ml = F[a_][0] & F[b_][0]; ms = F[a_][1] & F[b_][1]
    r = ev(ml, ms, 2.0)
    if r and r["n_in"] >= 100: rows.append({"filter": f"{a_} + {b_}", "vol>=": 2.0, **r})
out = pd.DataFrame(rows); out.to_csv("momentum_search.csv", index=False)
pd.set_option("display.width", 250, "display.max_rows", 200, "display.max_columns", 20)
print("\nSINGLE FILTERS:\n", out[~out["filter"].str.contains(r"\+")].to_string(index=False))
print("\nTOP PAIRS BY IN-SAMPLE t:\n", out[out["filter"].str.contains(r"\+")].sort_values("in_t", ascending=False).head(12).to_string(index=False))
