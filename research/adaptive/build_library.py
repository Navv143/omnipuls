import pickle, time, pandas as pd, numpy as np
from engine import Data
import library as LB
t0 = time.time(); d = Data()
lib = LB.add_costs(d, LB.build_all(d))
pickle.dump(lib, open("library.pkl", "wb"))
rows = []
for k, t in lib.items():
    a = t.date < "2022"
    rows.append({"strategy": k, "trades": len(t), "per day": round(len(t) / t.date.dt.normalize().nunique() * t.date.dt.normalize().nunique() / 2770, 2),
                 "net %/trade": round(100 * t.net.mean(), 3), "15-21": round(100 * t.net[a].mean(), 3), "22-26": round(100 * t.net[~a].mean(), 3),
                 "opt %/trade": round(100 * t.opt.mean(), 2)})
pd.set_option("display.width", 220, "display.max_rows", 100)
print(pd.DataFrame(rows).to_string(index=False)); print("secs", round(time.time() - t0))
