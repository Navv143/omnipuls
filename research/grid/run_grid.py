"""Run every setting on one instrument, store monthly returns per setting (fixed size per trade, after costs)."""
import sys, time, pickle
import numpy as np, pandas as pd
import mtf_data as MD, grid_engine as G, families as FA

inst = sys.argv[1]  # NIFTY | BANKNIFTY | BTC
t0 = time.time()
if inst == "BTC":
    m1 = pd.read_parquet("btc_1m.parquet").loc["2020-01-01":]
    frames = {k: G.Frame(MD.resample(m1, k, "00:00"), session=False) for k in (3, 5, 15, 30, 60)}
    cost = 0.0008
else:
    m1 = pd.read_parquet(f"{inst.lower()}_1m.parquet")
    frames = {k: G.Frame(MD.resample(m1, k)) for k in (3, 5, 15, 30, 60)}
    cost = 0.0003
print(inst, {k: len(f.c) for k, f in frames.items()}, round(time.time() - t0), "s", flush=True)
monthly, counts, meta = {}, {}, []
for fam in FA.ALL:
    for family, params, tf, long, short, stop, rr, hold in fam(frames):
        F = frames[tf]
        tr = F.run(long, short, stop, rr, hold, cost)
        key = f"{family} | {params}"
        if len(tr) == 0:
            continue
        mp = tr.t.dt.to_period("M")
        monthly[key] = tr.groupby(mp)["ret"].sum()
        counts[key] = tr.groupby(mp).size()
        meta.append({"key": key, "family": family, "tf": tf, "trades": len(tr), "avg_ret": tr.ret.mean(),
                     "win": (tr.ret > 0).mean(), "avg_bars": tr.bars.mean()})
    print(fam.__name__, len(meta), round(time.time() - t0), "s", flush=True)
M = pd.DataFrame(monthly).fillna(0.0).sort_index()
N = pd.DataFrame(counts).fillna(0).sort_index()
pickle.dump({"M": M, "N": N, "meta": pd.DataFrame(meta)}, open(f"grid_{inst}.pkl", "wb"))
print("done", M.shape, round(time.time() - t0), "s")
