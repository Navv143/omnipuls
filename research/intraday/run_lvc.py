import numpy as np, pandas as pd, warnings, pickle; warnings.filterwarnings("ignore")
from engine import Data
import lvc
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 200)
d=Data(); C=0.0012
def st(t,lab):
    g=t.gross-C; a=t[t.date<"2022"]; b=t[t.date>="2022"]; yrs=g.groupby(t.date.dt.year).mean()
    return {"setup":lab,"n":len(t),"per day":round(len(t)/t.date.nunique(),1),"win%":round(100*(g>0).mean(),1),"stock %":round(100*g.mean(),3),
            "avg R":round((g/t.risk_pct).mean(),3),"15-21":round(100*(a.gross-C).mean(),3),"22-26":round(100*(b.gross-C).mean(),3),
            "2025-26":round(100*(t[t.date>="2025"].gross-C).mean(),3),"yrs +":f"{(yrs>0).sum()}/{len(yrs)}",
            "opt %":round(100*t.opt.mean(),2),"opt 22-26":round(100*b.opt.mean(),2),"opt @4%":round(100*t.opt4.mean(),2),
            "t":round(g.mean()/g.std()*np.sqrt(len(g)),2)}
if __name__=="__main__":
    R=[]; T={}
    for rb in ("prev_close","open"):
        for fresh in (False,True):
            sig=lvc.signals(d,rank_by=rb,fresh_cross=fresh)
            for stop in ("ref","atr"):
                t=lvc.simulate(d,sig,stop=stop); lab=f"rank vs {rb} | {'fresh cross' if fresh else 'any close beyond'} | stop {stop}"
                T[lab]=t; R.append(st(t,lab))
    out=pd.DataFrame(R); print(out.to_string(index=False))
    pickle.dump(T,open("lvc_trades.pkl","wb"))
    base=T["rank vs prev_close | any close beyond | stop ref"]
    R=[st(base[base.side==1],"base: gainers long"),st(base[base.side==-1],"base: losers short"),
       st(base[base.beyond10],"base: already beyond level at 10:00"),st(base[~base.beyond10],"base: fresh break after 10:00")]
    for r in range(1,6): R.append(st(base[base["rank"]==r],f"base: rank {r}"))
    print(pd.DataFrame(R).to_string(index=False))
    