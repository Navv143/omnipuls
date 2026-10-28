import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data
import lvc
from run_lvc import st
d=Data()
R=[]
sig=lvc.signals(d,rank_by="open",fresh_cross=True)
R.append(st(lvc.simulate(d,sig,stop="atr",trail_atr=1.0),"open | fresh | 0.5 ATR stop + 1 ATR trail"))
R.append(st(lvc.simulate(d,sig[sig.signal_slot<=21],stop="atr"),"open | fresh | entries by 11:00 only"))
R.append(st(lvc.simulate(d,sig[sig["rank"]==1],stop="atr"),"open | fresh | top-1 gainer/loser only"))
R.append(st(lvc.simulate(d,sig[sig.ref_vol_x<0.5],stop="atr"),"open | fresh | ref candle volume < half the 9:15-10 average"))
R.append(st(lvc.simulate(d,lvc.signals(d,rank_by="open",fresh_cross=True,min_move=0.02),stop="atr"),"open | fresh | only stocks moved 2%+ by 10:00"))
f=sig.copy(); f["side"]=-f["side"]
R.append(st(lvc.simulate(d,f,stop="atr"),"OPPOSITE trade (fade the break), 0.5 ATR stop"))
print(pd.DataFrame(R).to_string(index=False))
