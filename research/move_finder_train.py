# Research only (needs: pip install lightgbm scikit-learn). Usage: python research/<this>.py <folder with move_panel.parquet>
import sys,numpy as np,pandas as pd,lightgbm as lgb
from sklearn.metrics import roc_auc_score
sys.path.insert(0,'research'); from move_finder import mirrored, FEATS
S=sys.argv[1] if len(sys.argv) > 1 else '.'
t=pd.read_parquet(S+'/move_panel.parquet'); m=mirrored(t)
m[FEATS]=m[FEATS].replace([np.inf,-np.inf],np.nan)
m=m[m.res.notna()]
days=sorted(m.day.unique()); days=[d for d in days if m[m.day==d].vx1.notna().mean()>0.5]
m=m[m.day.isin(days)]
cut=days[int(len(days)*0.55)]
tr,te=m[m.day<cut],m[m.day>=cut]
print('days',len(days),'train',tr.day.nunique(),'test',te.day.nunique(),'base train %.4f test %.4f'%(tr.win.mean(),te.win.mean()))
mdl=lgb.LGBMClassifier(n_estimators=400,learning_rate=0.03,num_leaves=31,min_child_samples=300,subsample=0.8,subsample_freq=1,colsample_bytree=0.7,reg_lambda=5,verbose=-1)
mdl.fit(tr[FEATS],tr.win)
te=te.copy(); te['p']=mdl.predict_proba(te[FEATS])[:,1]
print('AUC test %.3f'%roc_auc_score(te.win,te.p))
te['q']=pd.qcut(te.p.rank(method='first'),100,labels=False)
for lo in (0,50,90,95,98,99):
  z=te[te.q>=lo]; print(f'top {100-lo:3d}%: n={len(z):6d} hit {z.win.mean()*100:5.2f}%  avg trade {z.res.mean()-0.12:+.3f}% (gross {z.res.mean():+.3f})')
# per day top-K, one per stock per day, no new entry while that stock in trade ignored (first only)
for K in (1,3,5):
  pk=te.sort_values('p',ascending=False).drop_duplicates(['day','sym']).groupby('day').head(K)
  r=pk.res-0.12; hd=sorted(pk.day.unique()); h=hd[len(hd)//2]
  print(f'top{K}/day: n={len(pk)} hit {pk.win.mean()*100:.1f}% avg {r.mean():+.3f}% halves {r[pk.day<h].mean():+.3f}/{r[pk.day>=h].mean():+.3f} win {(r>0).mean()*100:.0f}%')
imp=pd.Series(mdl.booster_.feature_importance('gain'),index=FEATS).sort_values(ascending=False)
print((imp/imp.sum()*100).round(1).head(15).to_string())
top=te[te.q>=99]
cmp=pd.DataFrame({'top1% picks':top[FEATS].median(),'all':te[FEATS].median(),'real fast moves':te[te.win==1][FEATS].median()})
print(cmp.loc[imp.index[:15]].round(2).to_string())
te[['day','sym','hm','side','p','win','res']+FEATS].to_parquet(S+'/mf_test.parquet')
