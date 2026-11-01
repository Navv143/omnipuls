"""Short-term dip-buying (quantifiedstrategies) on Indian cash stocks, daily bars 2012-2026.
A 'RSI(3) dip': RSI(3) closes < 22, EMA100 > its value 5 days ago, close >= 1% below the 10-day rolling VWAP;
   buy next open; sell at the close of the day RSI(3) closes > 55.
B 'Triple RSI': RSI(5) < 30, RSI(5) fell 3 days in a row, RSI(5) < 60 three days ago, close > SMA200; buy at the close;
   sell at the close when RSI(5) crosses above 50.
Universe: NSE F&O stocks (current list) + Nifty 50 / Bank Nifty index. Costs 0.25% round trip (delivery STT etc.).
Yardstick: random entries in the same stock on days passing only the trend filter, held the same number of days.
Portfolio: max 5 positions (20% each), lowest RSI first, vs buying and holding the Nifty 50."""
import sys, glob, os, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/navv"); sys.path.insert(0, "/home/claude/bt")
import universe as U
COST = 0.0025; START = pd.Timestamp("2012-01-01"); MAXHOLD = 30
rng = np.random.default_rng(3)

def rsi(c, n):
    d = c.diff(); g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l)

def load_stock(sym):
    f = f"/tmp/eod2probe/daily/{sym.lower()}.csv"
    if not os.path.exists(f): return None
    h = pd.read_csv(f, usecols=["Date", "Open", "High", "Low", "Close", "Volume", "Series"])
    h["Date"] = pd.to_datetime(h["Date"]); h = h.drop_duplicates("Date").sort_values("Date")
    h = h[h["Series"].astype(str).str.strip().isin(["EQ", "BE"])].set_index("Date")
    return h[["Open", "High", "Low", "Close", "Volume"]].astype(float)

def signals(d):
    c = d.Close
    r3, r5 = rsi(c, 3), rsi(c, 5)
    e100 = c.ewm(span=100, adjust=False).mean(); s200 = c.rolling(200).mean()
    tp = (d.High + d.Low + d.Close) / 3
    vw10 = (tp * d.Volume).rolling(10).sum() / d.Volume.rolling(10).sum() if d.Volume.sum() > 0 else tp.rolling(10).mean()
    bad = (c.pct_change().abs() > 0.25).rolling(5, min_periods=1).max().astype(bool)   # splits / bad prints
    A = (r3 < 22) & (e100 > e100.shift(5)) & (c <= vw10 * 0.99) & ~bad
    B = (r5 < 30) & (r5 < r5.shift(1)) & (r5.shift(1) < r5.shift(2)) & (r5.shift(2) < r5.shift(3)) & (r5.shift(3) < 60) & (c > s200) & ~bad
    trendA = (e100 > e100.shift(5)) & ~bad; trendB = (c > s200) & ~bad
    return dict(A=(A, trendA, r3, "next_open", lambda i, r: r[i] > 55), B=(B, trendB, r5, "close", lambda i, r: r[i] > 50 and r[i - 1] <= 50))

def trades_for(sym, d):
    out = []
    o, c = d.Open.values, d.Close.values; idx = d.index
    for name, (sig, trend, r, entry, exit_rule) in signals(d).items():
        rv = r.values; s = sig.values; i = 0; n = len(d)
        while i < n - 2:
            if not s[i] or idx[i] < START: i += 1; continue
            e_i = i + 1 if entry == "next_open" else i
            e_px = o[e_i] if entry == "next_open" else c[i]
            j = e_i if entry == "next_open" else i + 1
            while j < n - 1 and not exit_rule(j, rv) and j - e_i < MAXHOLD: j += 1
            ret = c[j] / e_px - 1 - COST
            out.append(dict(strat=name, sym=sym, signal=idx[i], entry=idx[e_i], exit=idx[j], days=j - e_i, ret=ret, rsi=rv[i]))
            i = j + 1
    return out

def baseline(sym, d, T):
    out = []
    o, c = d.Open.values, d.Close.values
    for name, (sig, trend, r, entry, _) in signals(d).items():
        ok = np.flatnonzero(trend.values & (d.index >= START))
        ok = ok[ok < len(d) - MAXHOLD - 2]
        tt = T[(T.sym == sym) & (T.strat == name)]
        for days in tt.days.values:
            if not len(ok): break
            k = ok[rng.integers(len(ok))]
            e_px = o[k + 1] if entry == "next_open" else c[k]; e_i = k + 1 if entry == "next_open" else k
            out.append(dict(strat=name, ret=c[min(e_i + max(days, 1), len(c) - 1)] / e_px - 1 - COST))
    return out

syms = sorted(set(U.FNO_SECTOR_OF))
data, T = {}, []
for s in syms:
    d = load_stock(s)
    if d is None or len(d) < 400: continue
    data[s] = d; T += trades_for(s, d)
# index (cube daily) - tradable via index ETFs / futures
import engine as E
Dc = E.Data()
for nm in ("NIFTY 50", "NIFTY BANK"):
    k = Dc.syms.index(nm)
    d = pd.DataFrame({"Open": Dc.dopen[k], "High": Dc.dhigh[k], "Low": Dc.dlow[k], "Close": Dc.dclose[k], "Volume": 1.0}, index=Dc.days).dropna()
    data[nm] = d
    for t in trades_for(nm, d):
        t["ret"] += COST - 0.0005    # futures/ETF cost ~0.05%
        T.append(t)
T = pd.DataFrame(T)
Bl = pd.DataFrame(sum((baseline(s, data[s], T) for s in data if s not in ("NIFTY 50", "NIFTY BANK")), []))
T.to_csv("mr_trades.csv", index=False)
pd.set_option("display.width", 220)
for strat in ("A", "B"):
    t = T[T.strat == strat]; st = t[~t.sym.isin(["NIFTY 50", "NIFTY BANK"])]; b = Bl[Bl.strat == strat]
    print(f"\n===== Strategy {strat} {'RSI(3) dip' if strat == 'A' else 'Triple RSI(5)'} =====")
    y = pd.to_datetime(st.entry).dt.year
    print(f"Stocks: {len(st)} trades ({len(st)/14.8:.0f}/yr), avg {st.ret.mean()*100:+.2f}% after 0.25% cost, median {st.ret.median()*100:+.2f}%, "
          f"win {(st.ret>0).mean()*100:.0f}%, avg hold {st.days.mean():.1f} days | random same-hold {b.ret.mean()*100:+.2f}% | edge {(st.ret.mean()-b.ret.mean())*100:+.2f}%")
    print("   by year:", " ".join(f"{k%100}:{v*100:+.2f}" for k, v in st.groupby(y).ret.mean().items()))
    print(f"   worst trade {st.ret.min()*100:.1f}%, trades losing >10%: {(st.ret < -0.10).mean()*100:.1f}%")
    for nm in ("NIFTY 50", "NIFTY BANK"):
        ti = t[t.sym == nm]
        if len(ti): print(f"   {nm}: {len(ti)} trades, avg {ti.ret.mean()*100:+.2f}%, win {(ti.ret>0).mean()*100:.0f}%, hold {ti.days.mean():.1f}d, "
                          f"by period 2015-19 {ti[pd.to_datetime(ti.entry).dt.year<2020].ret.mean()*100:+.2f}% / 2020-26 {ti[pd.to_datetime(ti.entry).dt.year>=2020].ret.mean()*100:+.2f}%")
# ---- portfolio: max 5 positions, 20% each, lowest RSI first
cal = Dc.days[Dc.days >= START] if Dc.days[0] <= START else pd.bdate_range(START, "2026-10-23")
allc = pd.DataFrame({s: d.Close for s, d in data.items() if s not in ("NIFTY 50", "NIFTY BANK")})
allc = allc[allc.index >= START]
for strat in ("A", "B"):
    t = T[(T.strat == strat) & ~T.sym.isin(["NIFTY 50", "NIFTY BANK"])].sort_values(["entry", "rsi"])
    eq, open_pos, curve = 1.0, [], {}
    byday = {k: g for k, g in t.groupby("entry")}
    for day in allc.index:
        open_pos = [p for p in open_pos if p["exit"] > day or (p.update(done=True) or False)]
        # realise exits that happen today
        for p in list(open_pos):
            pass
        g = byday.get(day)
        if g is not None:
            for _, r in g.iterrows():
                if len(open_pos) >= 5: break
                if any(p["sym"] == r.sym for p in open_pos): continue
                open_pos.append(dict(sym=r.sym, exit=r.exit, ret=r.ret))
                eq_add = 0.2 * r.ret
                curve.setdefault(r.exit, 0.0); curve[r.exit] += eq_add
    pnl = pd.Series(curve).sort_index()
    eqc = (1 + pnl.reindex(allc.index).fillna(0)).cumprod()
    yrs = (eqc.index[-1] - eqc.index[0]).days / 365.25
    cagr = eqc.iloc[-1] ** (1 / yrs) - 1; dd = (eqc / eqc.cummax() - 1).min()
    print(f"\nPortfolio {strat} (max 5 x 20%, simple compounding at exit): CAGR {cagr*100:.1f}%, max drawdown {dd*100:.1f}%, "
          f"final x{eqc.iloc[-1]:.2f}")
    print("   by year %:", " ".join(f"{k%100}:{v*100:+.0f}" for k, v in (eqc.resample('YE').last().pct_change().fillna(eqc.resample('YE').last().iloc[0]-1)).groupby(lambda x: x.year).first().items()))
k = Dc.syms.index("NIFTY 50"); n = pd.Series(Dc.dclose[k], index=Dc.days).dropna()
yrs = (n.index[-1] - n.index[0]).days / 365.25
print(f"\nNifty 50 buy & hold {n.index[0]:%Y}-{n.index[-1]:%Y}: CAGR {( (n.iloc[-1]/n.iloc[0])**(1/yrs)-1)*100:.1f}%, max drawdown {((n/n.cummax())-1).min()*100:.1f}%")
