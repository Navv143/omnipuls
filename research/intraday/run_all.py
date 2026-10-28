import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data, stats, by_year
import strategies as S
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 200)
d=Data()
T={}
T["V3 ORB top-2 movers (as specified)"]=S.v3(d)
T["V3 simplified (no volume/Nifty filter)"]=S.v3(d,vol_filter=False,nifty_filter=False)
T["Gap fade top-2 >=3%, 1% stop, enter 9:15"]=S.gap_setup(d,"fade",0.03,2,0.01,"09:15")
T["Gap fade top-2 >=3%, 1% stop, enter 9:20"]=S.gap_setup(d,"fade",0.03,2,0.01,"09:20")
T["Gap fade top-2 >=3%, 1.5% stop, enter 9:20"]=S.gap_setup(d,"fade",0.03,2,0.015,"09:20")
T["Gap fade top-2 >=2%, 1% stop, enter 9:15"]=S.gap_setup(d,"fade",0.02,2,0.01,"09:15")
T["Gap-and-go top-2 >=3% (follow gap), 1% stop"]=S.gap_setup(d,"go",0.03,2,0.01,"09:15")
T["Panic gap-down buy (Nifty<=-0.5%), 1.5% stop, 9:15"]=S.gap_setup(d,"fade",0.03,2,0.015,"09:15",nifty_max=-0.005)
T["Panic gap-down buy, 1.5% stop, enter 9:20"]=S.gap_setup(d,"fade",0.03,2,0.015,"09:20",nifty_max=-0.005)
T["Panic gap-down buy >=2%, 1.5% stop, 9:15"]=S.gap_setup(d,"fade",0.02,2,0.015,"09:15",nifty_max=-0.005)
T["Sector overreaction buy, 1.5% stop, 9:15"]=S.gap_setup(d,"fade",0.025,2,0.015,"09:15",sector_gap=0.025)
T["Sector overreaction buy, enter 9:20"]=S.gap_setup(d,"fade",0.025,2,0.015,"09:20",sector_gap=0.025)
T["Nifty 15-min ORB, stop other side"]=S.index_orb(d,"NIFTY 50")
T["Bank Nifty 15-min ORB, stop other side"]=S.index_orb(d,"NIFTY BANK")
on,intr=S.index_overnight(d,"NIFTY 50"); T["Nifty overnight (15:20 -> 9:20)"]=on; T["Nifty intraday (9:20 -> 15:20)"]=intr
on,intr=S.index_overnight(d,"NIFTY BANK"); T["Bank Nifty overnight (15:20 -> 9:20)"]=on
import pickle; pickle.dump(T,open("all_trades.pkl","wb"))
idx={"Nifty","Bank"}
rows=[]; yrs={}
for k,t in T.items():
    c = 0.0005 if (k.startswith("Nifty") or k.startswith("Bank")) else 0.0012
    r=stats(t,c,k); r["cost"]=f"{c:.2%}"
    r["@0.05% avg"]=round(100*(t.gross-0.0005).mean(),3)
    r["15-21 avg%"]=round(100*(t[t.date<"2022"].gross-c).mean(),3); r["22-26 avg%"]=round(100*(t[t.date>="2022"].gross-c).mean(),3)
    r["2025 avg%"]=round(100*(t[(t.date>="2025")&(t.date<"2026")].gross-c).mean(),3); r["2026 avg%"]=round(100*(t[t.date>="2026"].gross-c).mean(),3)
    rows.append(r); yrs[k]=by_year(t,c)
out=pd.DataFrame(rows); out.to_csv("all_setups.csv",index=False)
print(out.to_string(index=False))
print(pd.DataFrame(yrs).T.to_string())
