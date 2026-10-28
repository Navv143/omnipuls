import numpy as np, pandas as pd, warnings, pickle; warnings.filterwarnings("ignore")
from engine import Data
import optbt as B
pd.set_option("display.width", 280, "display.max_columns", 30, "display.max_rows", 300)
d=Data(); keep=pickle.load(open("opt_trades.pkl","rb"))
sets={"Gap fade 9:20":"Gap fade top-2 >=3%, enter 9:20, stop 0.5 ATR","Gap fade 9:20 confirmed":"Gap fade 9:20, only if 9:15 candle reverses, 0.5 ATR",
 "ML long+short 9:30":"ML 9:30 top long + top short, stop 0.5 ATR","V3 simplified":"V3 simplified (no vol/Nifty filter), 0.5 stop, 1 ATR trail"}
res=[]
for nm,key in sets.items():
    t=keep[key]; P=t[["s","d","side","entry_slot"]]
    for st in (0.3,0.5,1.0):
        for tg in (None,0.5,1.0,1.5):
            x=B.simulate(d,P,stop_atr=st,target_atr=tg); res.append(B.stats(x,f"{nm} | stop {st} | target {tg}"))
out=pd.DataFrame(res); out.to_csv("opt_targets.csv",index=False)
print(out[["setup","trades","opt win%","opt avg %","opt PF","opt avg (4% cost)","t-stat","yrs +","22-26 opt %","2025-26 opt %"]].to_string(index=False))
