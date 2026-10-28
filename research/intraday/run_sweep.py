import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data, stats
import strategies as S
pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 200)
d=Data()
var=[("V3 as specified",{}),("no volume filter",{"vol_filter":False}),("no Nifty filter",{"nifty_filter":False}),
 ("no volume, no Nifty",{"vol_filter":False,"nifty_filter":False}),("only first breakout (no waiting)",{"first_only":True}),
 ("volume 1.2x",{"vol_mult":1.2}),("volume 2.0x",{"vol_mult":2.0}),("volume 3.0x",{"vol_mult":3.0}),
 ("stop 0.3 ATR",{"stop_atr":0.3}),("stop 0.4 ATR",{"stop_atr":0.4}),("stop 0.6 ATR",{"stop_atr":0.6}),("stop 0.75 ATR",{"stop_atr":0.75}),("stop 1.0 ATR",{"stop_atr":1.0}),
 ("trail 0.5 ATR",{"trail_atr":0.5}),("trail 0.75 ATR",{"trail_atr":0.75}),("trail 1.5 ATR",{"trail_atr":1.5}),("no trail",{"trail_atr":None}),
 ("top 1",{"top_n":1}),("top 3",{"top_n":3}),("top 5",{"top_n":5}),
 ("entries until 10:30",{"entry_until":"10:30"}),("entries until 11:00",{"entry_until":"11:00"}),("entries until 13:00",{"entry_until":"13:00"}),
 ("exit 15:00",{"exit_at":"15:00"}),("exit 14:00",{"exit_at":"14:00"}),
 ("score: ATR only",{"score":("atr",)}),("score: gap only",{"score":("gap",)}),("score: RVOL only",{"score":("rvol",)}),("score: OR range only",{"score":("orr",)}),
 ("score without gap",{"score":("atr","orr","rvol")}),
 ("FADE the breakout (opposite)",{"fade":True}),
]
rows=[]
for name,kw in var:
    t=S.v3(d,**kw)
    for c in (0.0005,0.0012):
        r=stats(t,c,name); r["cost"]=f"{c:.2%}"
        p2=t[t.date>="2022-01-01"]; r["22-26 avg%"]=round(100*(p2.gross-c).mean(),3); r["2026 avg%"]=round(100*(t[t.date>="2026-01-01"].gross-c).mean(),3)
        rows.append(r)
out=pd.DataFrame(rows); out.to_csv("v3_sweep.csv",index=False)
print(out[out.cost=="0.05%"].drop(columns="cost").to_string(index=False))
print(out[out.cost=="0.12%"][["setup","avg net %","PF","t-stat","yrs +","22-26 avg%","2026 avg%"]].to_string(index=False))
