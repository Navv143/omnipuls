import numpy as np, pandas as pd, itertools
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 300)
ev=pd.read_parquet("pdh_events_sim.parquet"); C=0.0012; ev["p1"]=ev.date<"2022"
F={"cumvol":[None,1.5,2,3],"candle":[None,2,3,5],"move":[None,0.75,1.0],"nifty":[None,True],"time":[None,"after 10:30","after 12:00"],"vwap":[None,0.4]}
rows=[]
for cv,cd,mv,nf,tm,vw in itertools.product(*F.values()):
    m=np.ones(len(ev),bool)
    if cv: m&=ev.cumvol_x10>=cv
    if cd: m&=ev.candle_vol_x>=cd
    if mv: m&=ev.move_atr>=mv
    if nf: m&=ev.nifty_with
    if tm=="after 10:30": m&=ev.signal_slot>=15
    if tm=="after 12:00": m&=ev.signal_slot>=33
    if vw: m&=ev.above_vwap>=vw
    x=ev[m]
    for sc in ("atr05","struct","atr05_trail1"):
        a=x[x.p1]; b=x[~x.p1]
        if len(a)<300: continue
        rows.append({"filters":f"cumvol>={cv} candle>={cd} move>={mv} nifty={nf} time={tm} vwap>={vw}","exit":sc,"n 15-21":len(a),"n 22-26":len(b),
                     "stock 15-21":100*(a[f"g_{sc}"]-C).mean(),"stock 22-26":100*(b[f"g_{sc}"]-C).mean(),
                     "opt 15-21":100*a[f"o_{sc}"].mean(),"opt 22-26":100*b[f"o_{sc}"].mean()})
r=pd.DataFrame(rows).round(3)
print("combos tested:",len(r)); 
print("Best 15 by 2015-21 option return (chosen in-sample), with 2022-26 result:")
print(r.sort_values("opt 15-21",ascending=False).head(15).to_string(index=False))
print("\nBest 10 by 2015-21 stock return:"); print(r.sort_values("stock 15-21",ascending=False).head(10).to_string(index=False))
print("\nShare of combos positive in 15-21 (stock):", round((r["stock 15-21"]>0).mean(),3), " in both periods:", round(((r["stock 15-21"]>0)&(r["stock 22-26"]>0)).mean(),3))
