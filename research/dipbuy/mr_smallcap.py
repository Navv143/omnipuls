"""The two dip-buying setups on SMALL CAPS: all NSE EQ stocks, signal day price Rs 10-30 (and Rs 10-200),
20-day average turnover >= Rs 1 Cr, 2012-2026, cost 0.5% round trip. Yardstick: random entries in eligible
small caps (same band/turnover/trend filter) held the same number of days. Portfolio: max 5 x 20%."""
import glob, os, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
src = open("/home/claude/mr/mr_test.py").read()
ns = {}
exec(src.split("syms = sorted(set(U.FNO_SECTOR_OF))")[0], ns)
signals, rsi, load_stock = ns["signals"], ns["rsi"], ns["load_stock"]
COST, START, MAXHOLD = 0.005, pd.Timestamp("2012-01-01"), 30
rng = np.random.default_rng(9)
BANDS = {"Rs 10-30": (10, 30), "Rs 10-200": (10, 200)}
T, B = [], []
files = sorted(glob.glob("/tmp/eod2probe/daily/*.csv"))
for fi, f in enumerate(files):
    sym = os.path.basename(f)[:-4]
    try:
        d = load_stock(sym)
    except Exception:
        continue
    if d is None or len(d) < 300: continue
    turn = (d.Close * d.Volume).rolling(20).mean()
    o, c, idx = d.Open.values, d.Close.values, d.index
    for name, (sig, trend, r, entry, exit_rule) in signals(d).items():
        rv = r.values
        for band, (lo, hi) in BANDS.items():
            elig = (d.Close.between(lo, hi) & (turn >= 1e7) & (idx >= START)).values
            s = sig.values & elig; i = 0; n = len(d); held = []
            while i < n - 2:
                if not s[i]: i += 1; continue
                e_i = i + 1 if entry == "next_open" else i
                e_px = o[e_i] if entry == "next_open" else c[i]
                j = e_i if entry == "next_open" else i + 1
                while j < n - 1 and not exit_rule(j, rv) and j - e_i < MAXHOLD: j += 1
                ret = c[j] / e_px - 1 - COST
                T.append(dict(strat=name, band=band, sym=sym, entry=idx[e_i], exit=idx[j], days=j - e_i, ret=ret, rsi=rv[i]))
                held.append(j - e_i); i = j + 1
            pool = np.flatnonzero(trend.values & elig)
            pool = pool[pool < n - MAXHOLD - 2]
            for days in held:
                if not len(pool): break
                k = pool[rng.integers(len(pool))]; e_i = k + 1 if entry == "next_open" else k
                e_px = o[k + 1] if entry == "next_open" else c[k]
                B.append(dict(strat=name, band=band, ret=c[min(e_i + max(days, 1), n - 1)] / e_px - 1 - COST))
    if fi % 1000 == 0: print(fi, len(files), flush=True)
T, B = pd.DataFrame(T), pd.DataFrame(B)
T.to_csv("mr_smallcap_trades.csv", index=False)
for (strat, band), t in T.groupby(["strat", "band"]):
    b = B[(B.strat == strat) & (B.band == band)]
    y = pd.to_datetime(t.entry).dt.year
    print(f"\n===== {'RSI(3) dip' if strat == 'A' else 'Triple RSI(5)'} | small caps {band} =====")
    print(f"{len(t)} trades ({len(t)/14.8:.0f}/yr) avg {t.ret.mean()*100:+.2f}% after 0.5% cost, median {t.ret.median()*100:+.2f}%, "
          f"win {(t.ret>0).mean()*100:.0f}%, hold {t.days.mean():.1f}d | random same-hold {b.ret.mean()*100:+.2f}% | edge {(t.ret.mean()-b.ret.mean())*100:+.2f}%")
    print("   by year:", " ".join(f"{k%100}:{v*100:+.1f}" for k, v in t.groupby(y).ret.mean().items()))
    print(f"   trades losing >10%: {(t.ret < -0.10).mean()*100:.1f}%, worst {t.ret.min()*100:.0f}%")
    # portfolio max 5 x 20%, lowest RSI first
    t2 = t.sort_values(["entry", "rsi"]); pos, pnl = [], {}
    for day, g in t2.groupby("entry"):
        pos = [p for p in pos if p > day]
        for _, r in g.iterrows():
            if len(pos) >= 5: break
            pos.append(r.exit); pnl[r.exit] = pnl.get(r.exit, 0) + 0.2 * r.ret
    cal = pd.bdate_range(START, "2026-10-23")
    eq = (1 + pd.Series(pnl).sort_index().reindex(cal).fillna(0)).cumprod()
    yrs = (cal[-1] - cal[0]).days / 365.25
    yr = eq.resample("YE").last(); yr = yr.pct_change().fillna(yr.iloc[0] - 1)
    print(f"   portfolio 5 x 20%: CAGR {(eq.iloc[-1]**(1/yrs)-1)*100:.1f}%, max drawdown {(eq/eq.cummax()-1).min()*100:.0f}%, "
          "by year " + " ".join(f"{k.year%100}:{v*100:+.0f}" for k, v in yr.items()))
