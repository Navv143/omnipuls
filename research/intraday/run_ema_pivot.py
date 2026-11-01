import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data
import ema_pivot as EP, optmodel as M
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 200)
d=Data(); vix=pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1],d.C.shape[2])
def weekly_dte(days):
    out=np.zeros(len(days))
    for i,dd in enumerate(days):
        wd=3 if dd<pd.Timestamp("2025-09-01") else 1
        k=i
        while True:
            k+=1
            if k>=len(days): out[i]=max(1,(wd-dd.weekday())%7 or 7); break
            # last trading day on/before the weekly expiry weekday in that week
            if days[k].weekday()>=wd or days[k].isocalendar()[1]!=dd.isocalendar()[1] and days[k-1].weekday()<wd:
                pass
            break
        # simple: trading days until next expiry weekday (strictly after today), holidays ignored
        n=0; x=dd
        while True:
            x+=pd.Timedelta(days=1)
            if x.weekday()<5: n+=1
            if x.weekday()==wd: break
        out[i]=n
    return out
DTE=weekly_dte(d.days)
def opt(t,cost):
    iv=np.array([vix[di, max(es-1,0)] for di,es in zip(t.d,t.entry_slot)])/100
    r,_=M.option_return(t.entry.values,t.exit.values,t.side.values,DTE[t.d],t.entry_slot.values,t.exit_slot.values,iv,cost=cost)
    return r
def st(t,lab,cost=0.0003):
    if t.empty: return {"setup":lab,"n":0}
    t=t.copy(); t["d"]=[d.days.get_loc(x) for x in t.date]
    g=t.gross-cost; o=opt(t,0.015); o3=opt(t,0.03); yrs=g.groupby(t.date.dt.year).mean()
    a=t.date<"2022"; b=t.date>="2022"
    return {"setup":lab,"trades":len(t),"per yr":round(len(t)/11.2),"win%":round(100*(g>0).mean(),1),"avg pts":round(t.pts.mean(),1),
            "avg R":round(((t.pts-cost*t.entry)/t.risk_pts).mean(),3),"fut %/trade":round(100*g.mean(),3),"PF":round(g[g>0].sum()/-g[g<=0].sum(),2),
            "yrs +":f"{(yrs>0).sum()}/{len(yrs)}","15-21":round(100*g[a].mean(),3),"22-26":round(100*g[b].mean(),3),
            "2025-26":round(100*g[t.date>="2025"].mean(),3),"opt %":round(100*o.mean(),2),"opt 22-26":round(100*o[b.values].mean(),2),
            "opt @3%":round(100*o3.mean(),2),"t":round(g.mean()/g.std()*np.sqrt(len(g)),2),"target hit%":round(100*(t.exit_by=="target").mean(),1)}
R=[]
for sym in ("NIFTY 50","NIFTY BANK"):
    for var in ("all","pivot_break"):
        R.append(st(EP.run(d,sym,variant=var,stop_mode="candle"),f"{sym} | {var} | candle stop | any R:R"))
        for rr in (2,3):
            R.append(st(EP.run(d,sym,variant=var,stop_mode="candle",min_rr=rr),f"{sym} | {var} | candle stop | R:R>={rr}"))
    R.append(st(EP.run(d,sym,variant="pivot_break",stop_mode="candle",min_rr=2,max_trades=1),f"{sym} | pivot_break | first trade of day | R:R>=2"))
    R.append(st(EP.run(d,sym,variant="pivot_break",stop_mode="candle",min_rr=2,first="10:30",last="13:30"),f"{sym} | pivot_break | 10:30-13:30 | R:R>=2"))
out=pd.DataFrame(R); print(out.to_string(index=False)); out.to_csv("ema_pivot_results.csv",index=False)
