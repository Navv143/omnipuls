import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data, walk, slot
import optmodel as M
pd.set_option("display.width", 260, "display.max_columns", 30)
d=Data(); ev=pd.read_parquet("pdh_events_sim.parquet"); C=0.0012
dte=M.dte_table(d.days); rv=pd.DataFrame(np.log(d.dclose/d.prev_close).T).rolling(20,min_periods=15).std().shift(1).values.T
X=slot("15:20")
for name,mode in (("fade_atr05","atr"),("fade_candle","candle")):
    g=np.full(len(ev),np.nan); xp=g.copy(); xs=np.zeros(len(ev),int); e_=g.copy()
    for i,r in enumerate(ev.itertuples()):
        s,day,es=r.s,r.d,r.entry_slot; side=-r.side; e=d.O[s,day,es]; atr=d.atr[s,day]
        sp = e-side*0.5*atr if mode=="atr" else (d.H[s,day,r.signal_slot] if side<0 else d.L[s,day,r.signal_slot])
        if side*(e-sp)<=0: sp=e-side*0.1*atr
        px,how,xt=walk(d,s,day,side,es,e,sp,exit_slot=X); g[i]=side*(px/e-1); xp[i]=px; xs[i]=xt; e_[i]=e
    ev["g_"+name]=g
    iv=np.maximum(rv[ev.s,ev.d]*np.sqrt(252)*1.15,0.18)
    ev["o_"+name],_=M.option_return(e_,xp,-ev.side.values,dte[ev.d],ev.entry_slot.values,xs,iv,cost=0.02)
ev.to_parquet("pdh_events_sim.parquet")
def st(x,lab,sc):
    a=x[x.date<"2022"]; b=x[x.date>="2022"]
    return {"setup":lab,"exit":sc,"n":len(x),"stock %":round(100*(x["g_"+sc]-C).mean(),3),"15-21":round(100*(a["g_"+sc]-C).mean(),3),"22-26":round(100*(b["g_"+sc]-C).mean(),3),
            "2025-26":round(100*(x[x.date>="2025"]["g_"+sc]-C).mean(),3),"opt %":round(100*x["o_"+sc].mean(),2),"opt 22-26":round(100*b["o_"+sc].mean(),2)}
R=[]
for sc in ("fade_atr05","fade_candle"):
    R.append(st(ev,"FADE all PDH/PDL breaks",sc))
    R.append(st(ev[ev.cumvol_x10<1],"FADE low-volume breaks (cumvol<1)",sc))
    R.append(st(ev[(ev.cumvol_x10<1)&(ev.candle_vol_x<1.5)],"FADE low-volume + weak candle",sc))
    R.append(st(ev[ev.signal_slot<=3],"FADE breaks in first 20 min",sc))
    R.append(st(ev[ev.move_atr>=1],"FADE extended breaks (move>=1 ATR)",sc))
print(pd.DataFrame(R).to_string(index=False))
