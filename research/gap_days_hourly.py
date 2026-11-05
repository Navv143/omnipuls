import sys, pickle; sys.path.insert(0, "/home/user/omnipuls")
import numpy as np, pandas as pd, indices as IX
S='/tmp/claude-0/-home-user-omnipuls/43304a8f-14f6-5f5b-9345-780c9549450f/scratchpad'
H = pickle.load(open(S+'/yahoo1h.pkl','rb'))
COST = 0.0002
def days_of(df):
    d = df.copy(); d["day"] = d.index.normalize(); return d
def study(key, wkey):
    ix = days_of(H[key]); W = IX._norm(IX.BUILTIN[wkey])
    g = ix.groupby("day")
    dd = g.agg(o=("Open","first"), h=("High","max"), l=("Low","min"), c=("Close","last"))
    pc = dd.c.shift(1); tr = pd.concat([dd.h-dd.l,(dd.h-pc).abs(),(dd.l-pc).abs()],axis=1).max(axis=1); atr = tr.rolling(14).mean().shift(1)
    first = g.head(1).set_index("day")          # 9:15-10:15 bar
    second_open = g.nth(1).set_index("day")["Open"]  # entry at 10:15
    rows = pd.DataFrame({"pc": pc, "o": dd.o, "c": dd.c, "atr": atr, "f_o": first.Open, "f_c": first.Close, "f_h": first.High, "f_l": first.Low, "entry": second_open}).dropna()
    rows["gap_atr"] = (rows.o - rows.pc) / rows.atr
    rows["at1015_atr"] = (rows.f_c - rows.pc) / rows.atr    # where it stands vs yesterday at 10:15
    rows["first_dir"] = np.sign(rows.f_c - rows.f_o)
    # breadth vs previous close and money in the first hour (weighted)
    br_up = pd.Series(0.0, index=rows.index); br_dn = pd.Series(0.0, index=rows.index); mon = pd.Series(0.0, index=rows.index); wsum = 0
    for st, w in W.items():
        b = H.get(st)
        if b is None: continue
        b = days_of(b); gb = b.groupby("day")
        bpc = gb.Close.last().shift(1); bf = gb.head(1).set_index("day")
        chg = (bf.Close / bpc.reindex(bf.index) - 1)
        rng = (bf.High - bf.Low).replace(0, np.nan); press = ((bf.Close - bf.Open) / rng).fillna(0)
        br_up = br_up.add((chg > 0).reindex(rows.index).fillna(False) * w, fill_value=0)
        br_dn = br_dn.add((chg < 0).reindex(rows.index).fillna(False) * w, fill_value=0)
        mon = mon.add((press.reindex(rows.index).fillna(0)) * w, fill_value=0); wsum += w
    rows["br_up"], rows["br_dn"], rows["money"] = br_up / wsum * 100, br_dn / wsum * 100, mon / wsum
    return rows
def rep(r, side, label):
    ret = side * (r.c / r.entry - 1) - COST
    ret = ret[side != 0]
    if len(ret) < 8: print(f"  {label:62s} n {len(ret)}"); return
    yrs = ret.groupby(ret.index.year).mean()
    mid = ret.index[len(ret)//2]
    a, b = ret[ret.index < mid], ret[ret.index >= mid]
    t = ret.mean()/ret.std()*np.sqrt(len(ret))
    print(f"  {label:62s} n {len(ret):3d} {ret.mean()*100:+.3f}% win {(ret>0).mean()*100:3.0f}% t {t:+.1f} | halves {a.mean()*100:+.3f}/{b.mean()*100:+.3f}")
for key, wkey in (("NIFTY", "NIFTY"), ("BANKNIFTY", "BANKNIFTY")):
    r = study(key, wkey); print(f"\n{key}: {len(r)} days {r.index.min():%Y-%m-%d} to {r.index.max():%Y-%m-%d}")
    gs = np.sign(r.gap_atr)
    big = r.gap_atr.abs() >= 0.3
    brw = np.where(gs > 0, r.br_up, r.br_dn)
    rep(r[big], gs[big], "A gap >= 0.3 ATR, trade gap direction at 10:15")
    m = big & (r.first_dir == gs); rep(r[m], gs[m], "B + first hour closed in gap direction")
    m = big & (brw >= 70); rep(r[m], gs[m], "C + breadth vs yesterday >= 70%")
    m = big & (np.sign(r.money) == gs); rep(r[m], gs[m], "D + stocks' money (first hour) in gap direction")
    m = big & (r.first_dir == gs) & (brw >= 70) & (np.sign(r.money) == gs); rep(r[m], gs[m], "E = B + C + D (gap and go confirmed)")
    m = big & (r.first_dir == -gs); rep(r[m], -gs[m], "F first hour AGAINST the gap -> trade the fade")
    m = big & (r.first_dir == -gs) & (np.sign(r.money) == -gs); rep(r[m], -gs[m], "G fade + money against the gap")
    # any trend day measured from yesterday's close at 10:15 (gap or not)
    ds = np.sign(r.at1015_atr); tr_ = (r.at1015_atr.abs() >= 0.5)
    brd = np.where(ds > 0, r.br_up, r.br_dn)
    m = tr_ & (brd >= 70) & (np.sign(r.money) == ds); rep(r[m], ds[m], "H at 10:15 >= 0.5 ATR from yesterday + breadth 70% + money")
    m = tr_ & (brd >= 80) & (np.sign(r.money) == ds) & (r.first_dir == ds); rep(r[m], ds[m], "I = H with breadth 80% + first hour same way")

print("\n--- entries after 10:15 on gap days (stop / exit at the close) ---")
for key, wkey in (("NIFTY", "NIFTY"), ("BANKNIFTY", "BANKNIFTY")):
    r = study(key, wkey); ix = days_of(H[key]); gs = np.sign(r.gap_atr)
    brw = pd.Series(np.where(gs > 0, r.br_up, r.br_dn), index=r.index)
    out = {"ORB": [], "ORB+breadth": [], "PB": [], "PB+breadth": []}
    for day, x in r[r.gap_atr.abs() >= 0.3].iterrows():
        s = int(np.sign(x.gap_atr)); bars = ix[ix.day == day].iloc[1:]
        if bars.empty: continue
        hi, lo, mid = x.f_h, x.f_l, (x.f_h + x.f_l) / 2
        # ORB: first later bar breaking the first hour's high (long) / low (short); stop at the other side
        for _, b in bars.iterrows():
            if (s > 0 and b.High > hi) or (s < 0 and b.Low < lo):
                e = hi if s > 0 else lo; stp = lo if s > 0 else hi
                after = bars[bars.index >= _]
                hit = (after.Low <= stp).any() if s > 0 else (after.High >= stp).any()
                ret = (s * (stp / e - 1) if hit else s * (x.c / e - 1)) - COST
                out["ORB"].append(ret)
                if brw[day] >= 70: out["ORB+breadth"].append(ret)
                break
        # pullback: limit at the first hour's midpoint; stop 0.3 ATR beyond the first hour's extreme
        for _, b in bars.iterrows():
            if (s > 0 and b.Low <= mid) or (s < 0 and b.High >= mid):
                stp = lo - 0.3 * x.atr if s > 0 else hi + 0.3 * x.atr
                after = bars[bars.index >= _]
                hit = (after.Low <= stp).any() if s > 0 else (after.High >= stp).any()
                ret = (s * (stp / mid - 1) if hit else s * (x.c / mid - 1)) - COST
                out["PB"].append(ret)
                if brw[day] >= 70: out["PB+breadth"].append(ret)
                break
    for k, v in out.items():
        v = pd.Series(v)
        if len(v) > 5:
            h = len(v) // 2
            print(f"  {key:9s} {k:12s} n {len(v):3d} {v.mean()*100:+.3f}% win {(v>0).mean()*100:3.0f}% t {v.mean()/v.std()*np.sqrt(len(v)):+.1f} | halves {v[:h].mean()*100:+.3f}/{v[h:].mean()*100:+.3f}")
