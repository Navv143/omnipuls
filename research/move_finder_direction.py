# Research only (needs: pip install lightgbm scikit-learn). Usage: python research/<this>.py <folder with move_panel.parquet>
import sys,numpy as np,pandas as pd,lightgbm as lgb
from sklearn.metrics import roc_auc_score
sys.path.insert(0,'research'); from move_finder import mirrored, FEATS
S=sys.argv[1] if len(sys.argv) > 1 else '.'
te=pd.read_parquet(S+'/mf_test.parquet')
w=te.pivot_table(index=['day','sym','hm'],columns='side',values=['p','win'])
w.columns=[f'{a}{b}' for a,b in w.columns]
w['pmax']=w[['p1','p-1']].max(axis=1)
w['anymove']=((w['win1']+w['win-1'])>0)
w['q']=pd.qcut(w.pmax.rank(method='first'),100,labels=False)
for lo in (0,90,99):
  z=w[w.q>=lo]; side=np.where(z.p1>=z['p-1'],1,-1)
  right=np.where(side>0,z.win1,z['win-1']); wrong=np.where(side>0,z['win-1'],z.win1)
  print(f'top {100-lo}%: any fast move {z.anymove.mean()*100:.2f}% | model side right {right.mean()*100:.2f}% wrong side {wrong.mean()*100:.2f}%  corr(pL,pS)={z.p1.corr(z["p-1"]):.2f}')
# direction model: among candles with a fast move either way, can features tell which way? (train early / test late)
t=pd.read_parquet(S+'/move_panel.parquet'); t[FEATS]=t[FEATS].replace([np.inf,-np.inf],np.nan)
mv=t[(t.win_L+t.win_S)==1].copy(); mv['up']=mv.win_L
days=sorted(t.day.unique()); cut=days[int(len(days)*0.55)]
a,b=mv[mv.day<cut],mv[mv.day>=cut]
mdl=lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=15,min_child_samples=100,verbose=-1).fit(a[FEATS],a.up)
pb=mdl.predict_proba(b[FEATS])[:,1]
print('direction model, moves only: n train',len(a),'test',len(b),'AUC %.3f'%roc_auc_score(b.up,pb),'up share %.2f'%b.up.mean())
for f in ('day_atr','open_atr','r3','r12','vwap_dist','rel','sec_day','n_day','clv'):
  try: print(f, 'AUC alone %.3f'%roc_auc_score(b.up,b[f].fillna(0)))
  except Exception as e: print(f,e)
