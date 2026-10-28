import numpy as np, pandas as pd, warnings, pickle; warnings.filterwarnings("ignore")
from engine import Data, stats, by_year, walk, trade_row, slot
import strategies as S
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 200)
d=Data(); C=0.0012
def show(rows): 
    print(pd.DataFrame(rows)[["setup","trades","win%","avg net %","PF","t-stat","yrs +","max DD %","sharpe","22-26","2024-26"]].to_string(index=False))
def st(t,lab,c=C):
    r=stats(t,c,lab); r["22-26"]=round(100*(t[t.date>="2022"].gross-c).mean(),3); r["2024-26"]=round(100*(t[t.date>="2024"].gross-c).mean(),3); return r
rows=[]
# gap fade 9:15 robustness
for stop in (0.005,0.0075,0.01,0.015,0.02,0.03):
    rows.append(st(S.gap_setup(d,"fade",0.03,2,stop,"09:15"),f"GapFade 9:15 stop {stop:.2%}"))
for ex in ("12:00","14:00","15:00"):
    rows.append(st(S.gap_setup(d,"fade",0.03,2,0.01,"09:15",exit_at=ex),f"GapFade 9:15 exit {ex}"))
for n in (1,3,5):
    rows.append(st(S.gap_setup(d,"fade",0.03,n,0.01,"09:15"),f"GapFade 9:15 top {n}"))
for g in (0.04,0.05):
    rows.append(st(S.gap_setup(d,"fade",g,2,0.01,"09:15"),f"GapFade 9:15 gap>={g:.0%}"))
t=S.gap_setup(d,"fade",0.03,2,0.01,"09:15")
rows.append(st(t[t.side=="long"],"GapFade 9:15 longs (buy gap-downs)")); rows.append(st(t[t.side=="short"],"GapFade 9:15 shorts (sell gap-ups)"))
for c in (0.0005,0.002,0.003): rows.append(st(t,f"GapFade 9:15 cost {c:.2%}",c))
show(rows)
print("exit reasons", t.exit_by.value_counts(normalize=True).round(3).to_dict())
# how much of the move is in the first 5 minutes
si=[d.idx(s) for s in t.sym]; di=[d.days.get_loc(x) for x in t.date]
sd=np.where(t.side=="long",1,-1)
o915=np.array([d.O[s,k,0] for s,k in zip(si,di)]); c915=np.array([d.C[s,k,0] for s,k in zip(si,di)])
print("avg move in the 9:15 bar, in trade direction: %.3f%%"%(100*np.mean(sd*(c915/o915-1))))
# confirmation entry: 9:15 candle closes against the gap (in fade direction), enter 9:20 open
def confirm(d, gap_min=0.03, top=2, stop=0.01, mode="close_dir", stop_mode="pct"):
    si=np.array(d.stock_idx); gap=np.where(d.valid[si],d.gap[si],np.nan); out=[]
    for day in range(len(d.days)):
        g=gap[:,day]; cand=np.where(np.abs(g)>=gap_min)[0]; cand=cand[np.argsort(-np.abs(g[cand]))][:top]
        for k in cand:
            s=si[k]; side=-int(np.sign(g[k])); o,c,h,l=d.O[s,day,0],d.C[s,day,0],d.H[s,day,0],d.L[s,day,0]
            if mode=="close_dir" and not (side*(c-o)>0): continue
            e=d.O[s,day,1]
            if not np.isfinite(e): continue
            sp = (l if side>0 else h) if stop_mode=="bar" else e*(1-side*stop)
            if side*(e-sp)<=0: continue
            px,how,_=walk(d,s,day,side,1,e,sp,exit_slot=slot("15:20"))
            out.append(trade_row(d,s,day,side,e,px,how,abs(e-sp)/e))
    return pd.DataFrame(out)
rows=[st(confirm(d),"GapFade, 9:15 candle confirms, enter 9:20, 1% stop"),
      st(confirm(d,stop_mode="bar"),"GapFade, 9:15 candle confirms, enter 9:20, stop at 9:15 candle extreme"),
      st(confirm(d,stop=0.015),"GapFade, 9:15 candle confirms, enter 9:20, 1.5% stop")]
v=S.v3(d,vol_filter=False,nifty_filter=False); rows.append(st(v[~v.with_gap],"V3 simplified: only breakouts AGAINST the gap"))
rows.append(st(v[v.with_gap],"V3 simplified: only breakouts WITH the gap"))
show(rows)
# combined portfolio: gap fade 9:15 + V3 simplified, daily P&L correlation
g=t.assign(net=t.gross-C).groupby("date").net.mean(); vv=v.assign(net=v.gross-C).groupby("date").net.mean()
both=pd.concat([g,vv],axis=1,keys=["gap","v3"]).fillna(0); print("daily corr gap-fade vs V3:", round(both.corr().iloc[0,1],3))
