import nifty_sweep_backtest as S, pandas as pd
from dataclasses import replace
df=S.load_csv('/home/claude/udata/NIFTY 50_5minute.csv')
df=df[df.dt.dt.time<=pd.Timestamp('15:25').time()]
rows=[]
for confirm in ("close","break"):
    for rr in (1.5,2.0,3.0):
        for lv,ud,uo in (("day",True,False),("OR",False,True),("both",True,True)):
            p=replace(S.Params(),confirm=confirm,rr=rr,use_day=ud,use_or=uo)
            t=S.run_backtest(df,p); t["year"]=pd.to_datetime(t.date).dt.year
            s=S.summary(t,p)
            gross=t.points+2*p.slippage
            yrs=(t.groupby("year").points.sum()>0).sum()
            r22=t[t.year>=2022]
            rows.append({"confirm":confirm,"rr":rr,"levels":lv,"trades":s["trades"],"win%":s["win_rate_%"],
              "avg pts (2pt cost)":s["avg_points"],"avg pts gross":round(gross.mean(),2),
              "avg pts @6pt cost":round((gross-6).mean(),2),"PF":s["profit_factor"],
              "yrs + /12":yrs,"2022-26 avg pts":round(r22.points.mean(),2),"maxDD pts":s["max_drawdown_pts"]})
            print(rows[-1],flush=True)
out=pd.DataFrame(rows).sort_values("avg pts (2pt cost)",ascending=False)
out.to_csv("sweep_variants.csv",index=False); print(out.to_string(index=False))
