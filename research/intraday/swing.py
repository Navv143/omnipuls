"""Multi-day stock setups traded with options. Entry and exit at the 15:20 price."""
import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data, slot
import optmodel as M
pd.set_option("display.width", 280, "display.max_columns", 30, "display.max_rows", 300)
d=Data(); si=np.array(d.stock_idx)
P=d.O[si,:,slot("15:20")]           # 15:20 price
val=d.valid[si]
Pd=pd.DataFrame(P.T).ffill()
ret1=Pd.pct_change()
def rsi(n):
    ch=Pd.diff(); up=ch.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-ch.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return (100-100/(1+up/dn)).values.T
R2=rsi(2); ma200=Pd.rolling(200).mean().values.T; ma5=Pd.rolling(5).mean().values.T; ma20=Pd.rolling(20).mean().values.T
hi20=Pd.rolling(20).max().shift(1).values.T; lo20=Pd.rolling(20).min().shift(1).values.T
vol=pd.DataFrame(d.dvol[si].T); vr=(vol/vol.rolling(20).mean().shift(1)).values.T
rv=np.log(Pd).diff().rolling(20).std().values.T
r1=ret1.values.T; P=Pd.values.T
dte_cache={}
def dte(h):
    if h not in dte_cache: dte_cache[h]=M.dte_table(d.days,roll=h+5)
    return dte_cache[h]
def run(name, sig, side, hold=5, exit_rule=None, top=3, rank=None):
    rows=[]; D=P.shape[1]
    for day in range(201, D-hold-1):
        c=np.where(sig[:,day] & val[:,day] & np.isfinite(P[:,day]))[0]
        if len(c)==0: continue
        if rank is not None: c=c[np.argsort(rank[c,day])][:top]
        else: c=c[:top]
        for s in c:
            e=P[s,day]; x_day=day+hold
            if exit_rule is not None:
                for j in range(1,hold+1):
                    if exit_rule(s,day+j): x_day=day+j; break
            x=P[s,x_day]
            if not np.isfinite(x): continue
            h=x_day-day; dt=dte(hold)[day]
            iv=max(rv[s,day]*np.sqrt(252)*1.15,0.18)
            T0=(dt+0.03)/252; T1=(dt-h+0.03)/252
            call=side>0
            p0=M.bs(np.array([e]),np.array([e]),np.array([T0]),iv,np.array([call]))[0]
            p1=M.bs(np.array([x]),np.array([e]),np.array([T1]),iv,np.array([call]))[0]
            rows.append((d.days[day],d.syms[si[s]],side*(x/e-1),h,p1/p0-1-0.02))
    t=pd.DataFrame(rows,columns=["date","sym","gross","held","opt"])
    o=t.opt; yrs=o.groupby(t.date.dt.year).mean()
    return {"setup":name,"trades":len(t),"per yr":round(len(t)/11),"stock avg %":round(100*(t.gross-0.0012).mean(),3),"days held":round(t.held.mean(),1),
            "opt win%":round(100*(o>0).mean(),1),"opt avg %":round(100*o.mean(),2),"opt PF":round(o[o>0].sum()/-o[o<=0].sum(),2),
            "t-stat":round(o.mean()/o.std()*np.sqrt(len(o)),2),"yrs +":f"{(yrs>0).sum()}/{len(yrs)}",
            "15-21 opt %":round(100*o[t.date<"2022"].mean(),2),"22-26 opt %":round(100*o[t.date>="2022"].mean(),2),"2025-26 opt %":round(100*o[t.date>="2025"].mean(),2)}, t
res=[]; T={}
def add(*a,**k):
    r,t=run(*a,**k); res.append(r); T[r["setup"]]=t
up=P>ma200; dn=P<ma200
add("RSI2<10 above 200DMA, buy CE, exit >5DMA or 5d", (R2<10)&up, 1, 5, lambda s,j: P[s,j]>ma5[s,j], rank=R2)
add("RSI2>90 below 200DMA, buy PE, exit <5DMA or 5d", (R2>90)&dn, -1, 5, lambda s,j: P[s,j]<ma5[s,j], rank=-R2)
add("Fell 5%+ today above 200DMA, buy CE, hold 1d", (r1<-0.05)&up, 1, 1, rank=r1)
add("Fell 5%+ today above 200DMA, buy CE, hold 3d", (r1<-0.05)&up, 1, 3, rank=r1)
add("Fell 5%+ today (any), buy CE, hold 2d", (r1<-0.05), 1, 2, rank=r1)
add("Rose 5%+ today below 200DMA, buy PE, hold 2d", (r1>0.05)&dn, -1, 2, rank=-r1)
add("20-day high breakout on 2x volume, buy CE, hold 5d", (P>hi20)&(vr>2)&up, 1, 5, rank=-vr)
add("20-day high breakout on 2x volume, buy CE, hold 10d", (P>hi20)&(vr>2)&up, 1, 10, rank=-vr)
add("20-day low breakdown on 2x volume, buy PE, hold 5d", (P<lo20)&(vr>2)&dn, -1, 5, rank=-vr)
out=pd.DataFrame(res); out.to_csv("swing.csv",index=False)
import pickle; pickle.dump(T,open("swing_trades.pkl","wb"))

# ---- baselines to separate edge from bull market + survivorship
rng=np.random.default_rng(1); rnd=rng.random(P.shape)
res=[]
add("BASELINE random 3 stocks above 200DMA, buy CE, hold 5d", up, 1, 5, rank=rnd)
add("BASELINE random 3 stocks above 200DMA, buy CE, hold 10d", up, 1, 10, rank=rnd)
add("BASELINE random 3 stocks (any), buy CE, hold 10d", np.isfinite(P), 1, 10, rank=rnd)
add("Breakout 2x vol above 200DMA, hold 10d, only if Nifty above its 50DMA", (P>hi20)&(vr>2)&up, 1, 10, rank=-vr)
print(pd.DataFrame(res).to_string(index=False))
# relative to baseline per year
b=T["BASELINE random 3 stocks above 200DMA, buy CE, hold 10d"]; s=T["20-day high breakout on 2x volume, buy CE, hold 10d"]
print(pd.DataFrame({"breakout":(100*s.opt).groupby(s.date.dt.year).mean().round(1),"random":(100*b.opt).groupby(b.date.dt.year).mean().round(1),
   "breakout stock%":(100*s.gross).groupby(s.date.dt.year).mean().round(2),"random stock%":(100*b.gross).groupby(b.date.dt.year).mean().round(2)}).T.to_string())
