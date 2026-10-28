import numpy as np, pandas as pd, warnings, time; warnings.filterwarnings("ignore")
from engine import Data, walk, slot
import optmodel as M
d=Data(); ev=pd.read_parquet("pdh_events.parquet")
dte=M.dte_table(d.days)
rv=pd.DataFrame(np.log(d.dclose/d.prev_close).T).rolling(20,min_periods=15).std().shift(1).values.T
X=slot("15:20"); t0=time.time()
schemes={"atr05":dict(stop="atr",k=0.5,trail=None),"struct":dict(stop="level",k=0.25,trail=None),
         "atr05_trail1":dict(stop="atr",k=0.5,trail=1.0),"candle":dict(stop="candle",k=0,trail=None)}
out={}
for name,sc in schemes.items():
    g=np.full(len(ev),np.nan); xs=np.zeros(len(ev),int); xp=np.full(len(ev),np.nan); rk=np.full(len(ev),np.nan)
    for i,r in enumerate(ev.itertuples()):
        s,day,side,es=r.s,r.d,r.side,r.entry_slot
        e=d.O[s,day,es]; atr=d.atr[s,day]
        if not np.isfinite(e): continue
        if sc["stop"]=="atr": sp=e-side*sc["k"]*atr
        elif sc["stop"]=="level": sp=r.level-side*sc["k"]*atr
        else: sp=d.L[s,day,r.signal_slot] if side>0 else d.H[s,day,r.signal_slot]
        if side*(e-sp)<=0: sp=e-side*0.1*atr
        px,how,xt=walk(d,s,day,side,es,e,sp,trail=sc["trail"]*atr if sc["trail"] else None,exit_slot=X)
        g[i]=side*(px/e-1); xs[i]=xt; xp[i]=px; rk[i]=abs(e-sp)/e
    ev[f"g_{name}"]=g; ev[f"risk_{name}"]=rk
    e=np.array([d.O[s,day,es] for s,day,es in zip(ev.s,ev.d,ev.entry_slot)])
    iv=np.maximum(rv[ev.s,ev.d]*np.sqrt(252)*1.15,0.18)
    ev[f"o_{name}"],_=M.option_return(e,xp,ev.side.values,dte[ev.d],ev.entry_slot.values,xs,iv,cost=0.02)
    print(name,round(time.time()-t0),flush=True)
ev.to_parquet("pdh_events_sim.parquet")
