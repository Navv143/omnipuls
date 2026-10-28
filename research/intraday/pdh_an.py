import numpy as np, pandas as pd
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 300)
ev=pd.read_parquet("pdh_events_sim.parquet"); C=0.0012
ev["p1"]=ev.date<"2022"
def st(x, lab, sc="atr05"):
    g=x[f"g_{sc}"]-C; o=x[f"o_{sc}"]
    a=x[x.p1]; b=x[~x.p1]
    return {"setup":lab,"n":len(x),"per day":round(len(x)/x.date.nunique(),1) if len(x) else 0,"win%":round(100*(g>0).mean(),1),
            "stock %":round(100*g.mean(),3),"15-21":round(100*(a[f"g_{sc}"]-C).mean(),3),"22-26":round(100*(b[f"g_{sc}"]-C).mean(),3),
            "2025-26":round(100*(x[x.date>="2025"][f"g_{sc}"]-C).mean(),3),
            "opt %":round(100*o.mean(),2),"opt 22-26":round(100*b[f"o_{sc}"].mean(),2),"t":round(g.mean()/g.std()*np.sqrt(len(g)),2) if len(g)>2 else np.nan}
R=[]
for sc in ("atr05","struct","atr05_trail1","candle"):
    R.append(st(ev,f"ALL signals, exit {sc}",sc))
for s,lab in ((1,"long PDH break"),(-1,"short PDL break")): R.append(st(ev[ev.side==s],lab))
print(pd.DataFrame(R).to_string(index=False)); R=[]
# single-filter buckets (stop 0.5 ATR)
def buck(col,bins):
    x=ev.copy(); x["b"]=pd.cut(x[col],bins)
    rows=[st(g,f"{col} {k}") for k,g in x.groupby("b") if len(g)>300]
    print(pd.DataFrame(rows).to_string(index=False)); print()
buck("cumvol_x10",[0,0.7,1,1.5,2,3,1e9])
buck("cumvol_x20",[0,1,1.5,2,3,1e9])
buck("candle_vol_x",[0,1,1.5,2,3,5,1e9])
buck("move_atr",[0,0.3,0.5,0.75,1,1.5,99])
buck("range_atr",[0,0.5,0.75,1,1.5,99])
buck("level_dist_atr",[-9,0.2,0.4,0.6,1,99])
buck("signal_slot",[-1,3,9,15,21,33,45,63])
buck("close_strength",[-0.1,0.5,0.75,0.9,1.01])
buck("above_vwap",[-9,0,0.2,0.4,0.7,99])
buck("atr_pct",[0,0.02,0.025,0.03,0.04,1])
x=ev.copy(); print(pd.DataFrame([st(g,f"nifty same direction={k}") for k,g in x.groupby("nifty_with")]).to_string(index=False))
