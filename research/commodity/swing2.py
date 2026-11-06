import pickle, numpy as np, pandas as pd
from swing import atr, run, rsi
D = pickle.load(open("cmd.pkl", "rb"))
rows = []
for k in ("GOLD", "SILVER", "COPPER", "CRUDE", "NATGAS"):
    d = D[k]["1d"]; d = d[(d.index >= "2004-01-01") & (d.High >= d.Low)].copy(); d["ATR"] = atr(d)
    c = d.Close; ma200 = c.rolling(200).mean(); C = c.values
    fwd = {h: (c.shift(-h) / d.Open.shift(-1) - 1) * 100 for h in (10, 20)}
    base = fwd[20][(c > ma200) & (d.index >= "2005")].mean()
    for lb in (10, 20, 30, 55):
        hh = d.High.rolling(lb).max().shift()
        for ex in (10, 20):
            L = d.Low.rolling(ex).min().values
            for sa in (2, 3):
                sg = pd.Series(np.where((c > hh) & (c > ma200), 1, 0), d.index)
                t = run(d, sg, sa, lambda j, s: C[j] <= L[j - 1], 120, "")
                t = t[t.date >= "2005"]
                h1 = t[t.date < "2016"]; h2 = t[t.date >= "2016"]
                rows.append({"mkt": k, "lookback": lb, "exit": ex, "stopATR": sa, "n": len(t), "win%": round((t.pct > 0).mean() * 100),
                             "avg%": round(t.pct.mean(), 2), "avgR": round(t.R.mean(), 2), "h1 R": round(h1.R.mean(), 2), "h2 R": round(h2.R.mean(), 2),
                             "days": round(t.days.mean()), "drift%/day": round(base / 20, 3), "edge%/day": round(t.pct.mean() / t.days.mean() - base / 20, 3)})
r = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(r.groupby("mkt")[["avgR", "h1 R", "h2 R", "edge%/day"]].agg(["mean", "min"]).round(2))
print(r[r.mkt.isin(["GOLD", "SILVER"])].to_string(index=False))
