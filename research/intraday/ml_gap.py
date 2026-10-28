"""Walk-forward model on gap candidates only (|gap|>=1.5%), decision 09:20: predict the fade return to 15:20 (ATR units)."""
import numpy as np, pandas as pd, lightgbm as lgb
from panel import feature_cols
p=pd.read_parquet("panel_k1.parquet")
c=p[p.gap.abs()>=0.015].copy().reset_index(drop=True)
sg=-np.sign(c.gap)
# features oriented in the fade direction so long/short share one model
feats=feature_cols(c)
signed=[f for f in feats if any(x in f for x in ("gap","ret","dist","vs_sector","sector_day","prev_oc","above","below","pos"))]
X=c[feats].copy()
for f in signed:
    if f.endswith("_xr") or f in ("pos_k","open_pos_k","prev_close_pos"): X[f]=np.where(sg>0,X[f],1-X[f])
    elif f in ("above_prev_high","below_prev_low"): pass
    else: X[f]=X[f]*sg
X["side"]=sg
y=(sg*c.ret_eod_atr).clip(-4,4)
params=dict(objective="huber",alpha=1.0,learning_rate=0.03,num_leaves=15,min_data_in_leaf=300,feature_fraction=0.7,
            bagging_fraction=0.8,bagging_freq=1,lambda_l2=10,verbose=-1,seed=7,deterministic=True,num_threads=2)
days=np.sort(c.date.unique()); preds=[]
for yr in range(2017,2027):
    test=c.date.dt.year==yr; cut=days[max(np.searchsorted(days,pd.Timestamp(f"{yr}-01-01"))-10,0)]; tr=c.date<cut
    m=lgb.train(params,lgb.Dataset(X[tr],y[tr]),num_boost_round=300)
    pr=m.predict(X[test]); preds.append(pd.Series(pr,index=c.index[test]))
    print(yr,test.sum(),"IC %.3f"%np.corrcoef(pr,y[test])[0,1],flush=True)
c["pred"]=pd.concat(preds); c["side"]=sg.astype(int); c=c[c.pred.notna()]
c.to_parquet("ml_gap_oos.parquet")
c["fade_gross"]=c.side*c.ret_eod
for q in (0.0,0.2,0.4):
    for per in ("<2022",">=2022"):
        x=c[(c.date<"2022") if per=="<2022" else (c.date>="2022")]
        x=x[x.pred>q]
        print(f"pred>{q} {per}: n={len(x)} avg fade gross {100*x.fade_gross.mean():.3f}%")
