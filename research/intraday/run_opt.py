import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data, slot
import strategies as S, optbt as B
pd.set_option("display.width", 280, "display.max_columns", 30, "display.max_rows", 200)
d=Data()
def pk(df, side, es): return pd.DataFrame({"s":df.s.values,"d":df.d.values,"side":side,"entry_slot":es})
res=[]; keep={}
def run(name, picks, **kw):
    t=B.simulate(d,picks,**kw); keep[name]=t; res.append(B.stats(t,name)); return t
# ---- ML picks at 9:30
m=pd.read_parquet("ml_oos_k3_xs.parquet")
L=m.sort_values("pred",ascending=False).groupby("date").head(1); Sh=m.sort_values("pred").groupby("date").head(1)
L2=m.sort_values("pred",ascending=False).groupby("date").head(2); S2=m.sort_values("pred").groupby("date").head(2)
for st in (0.5,1.0):
    run(f"ML 9:30 top long + top short, stop {st} ATR", pd.concat([pk(L,1,3),pk(Sh,-1,3)]), stop_atr=st)
run("ML 9:30 top-2 longs, stop 0.5 ATR", pk(L2,1,3), stop_atr=0.5)
run("ML 9:30 top-2 shorts, stop 0.5 ATR", pk(S2,-1,3), stop_atr=0.5)
run("ML 9:30 top long+short, 0.5 stop, 1 ATR trail", pd.concat([pk(L,1,3),pk(Sh,-1,3)]), stop_atr=0.5, trail_atr=1.0)
# ---- gap setups, earliest option entry 9:20
si=np.array(d.stock_idx)
rows=[]
for day in range(len(d.days)):
    g=np.where(d.valid[si,day],d.gap[si,day],np.nan); c=np.where(np.abs(g)>=0.03)[0]; c=c[np.argsort(-np.abs(g[c]))][:2]
    for k in c:
        s=si[k]; side=-int(np.sign(g[k])); conf= side*(d.C[s,day,0]-d.O[s,day,0])>0
        rows.append((s,day,side,1,conf,g[k]))
G=pd.DataFrame(rows,columns=["s","d","side","entry_slot","confirm","gap"])
run("Gap fade top-2 >=3%, enter 9:20, stop 0.5 ATR", G[["s","d","side","entry_slot"]], stop_atr=0.5)
run("Gap fade 9:20, only if 9:15 candle reverses, 0.5 ATR", G[G.confirm][["s","d","side","entry_slot"]], stop_atr=0.5)
# ---- V3 (simplified and as specified) entries
for nm,kw in [("V3 as specified",{}),("V3 simplified (no vol/Nifty filter)",{"vol_filter":False,"nifty_filter":False})]:
    v=S.v3(d,**kw); v["s"]=[d.idx(x) for x in v.sym]; v["d"]=[d.days.get_loc(x) for x in v.date]
    v["entry_slot"]=[slot(x)+1 for x in v.signal]; v["side_i"]=np.where(v.side=="long",1,-1)
    P=pd.DataFrame({"s":v.s,"d":v.d,"side":v.side_i,"entry_slot":v.entry_slot,"with_gap":v.with_gap})
    t=run(nm+", 0.5 stop, 1 ATR trail", P, stop_atr=0.5, trail_atr=1.0)
    res.append(B.stats(t[~t.with_gap], nm+" - only breakouts AGAINST gap"))
out=pd.DataFrame(res); print(out.to_string(index=False))
import pickle; pickle.dump(keep,open("opt_trades.pkl","wb"))
print(pd.DataFrame({k:B.yearly(t) for k,t in keep.items()}).T.to_string())
