import time, pickle, numpy as np, pandas as pd
from engine import Data, stats, by_year
import strategies as S
pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 200)
t0=time.time(); d=Data(); print("loaded", time.time()-t0, len(d.days), d.days[0].date(), d.days[-1].date(), len(d.stock_idx), "stocks")
t=S.v3(d); print("v3", time.time()-t0, len(t))
pickle.dump(d, open("/home/claude/bt/data.pkl","wb"), protocol=4) if False else None
t.to_parquet("v3_trades.parquet")
rows=[]
for c in (0.0005, 0.0012):
    rows.append(stats(t,c,f"V3 all, cost {c:.2%}"))
c=0.0005
P1=t[(t.date>="2016-01-01")&(t.date<"2022-01-01")]; P2=t[t.date>="2022-01-01"]; P3=t[t.date>="2025-12-01"]
for lab,x in [("2016-21 (rules chosen)",P1),("2022-26 (unseen)",P2),("Dec25-Apr26",P3),("Long",t[t.side=="long"]),("Short",t[t.side=="short"]),
              ("A+",t[t.a_plus]),("Not A+",t[~t.a_plus]),("With gap",t[t.with_gap]),("Against gap",t[~t.with_gap]),
              ("Rank 1 pick",t[t["rank"]==1]),("Rank 2 pick",t[t["rank"]==2])]:
    rows.append(stats(x,c,lab+" @0.05%"))
print(pd.DataFrame(rows).to_string(index=False))
print(pd.DataFrame({"0.05%":by_year(t,0.0005),"0.12%":by_year(t,0.0012),"n":t.groupby(t.date.dt.year).size()}).T.to_string())
print(t.exit_by.value_counts(normalize=True).round(3).to_dict(), "avg risk %", round(100*t.risk_pct.mean(),2))
