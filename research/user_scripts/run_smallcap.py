"""Run smallcap_screener.py's own rules (add_indicators, signal_mask, simulate) on local NSE daily data (eod2),
plus a baseline: on each signal day, a random stock from the same price band / liquidity / trend filters
(but without the breakout + volume-surge trigger), traded with the same stop, target and holding period."""
import sys, glob, os, pandas as pd, numpy as np
import smallcap_screener as SC
SRC = "/tmp/eod2probe/daily"
start = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else pd.Timestamp("2012-01-01")
rules, tr = SC.Rules(), SC.TradeRules()
rng = np.random.default_rng(7)
trades, data, elig_by_date = [], {}, {}
files = sorted(glob.glob(f"{SRC}/*.csv"))
for i, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-4].upper()
    try:
        h = pd.read_csv(f)
    except Exception:
        continue
    if len(h) < 260 or "Close" not in h:
        continue
    h = h.rename(columns=str.lower)
    h["date"] = pd.to_datetime(h["date"])
    h = h.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if not h["close"].between(rules.min_price, rules.max_price).any():
        continue
    d = SC.add_indicators(h, rules)
    eq = (d["series"].astype(str).str.strip() == "EQ") & (d["date"] >= start)
    sig = SC.signal_mask(d, rules) & eq
    base = (d["close"].between(rules.min_price, rules.max_price) & (d["avg_turnover20"] >= rules.min_avg_turnover)
            & (d["close"] > d["sma50"]) & (d["close"] > d["sma200"]) & eq).fillna(False)
    if base.any():
        data[sym] = d
        for k in np.flatnonzero(base.to_numpy()):
            elig_by_date.setdefault(d["date"].iat[k], []).append((sym, k))
    if sig.any():
        trades += SC.simulate(d, sig, tr, sym)
    if i % 500 == 0:
        print(f"{i}/{len(files)} files, {len(trades)} trades", flush=True)
t = pd.DataFrame(trades)
t.to_csv("smallcap_trades.csv", index=False)
# baseline: same count, same signal dates, random eligible stock that day (3 draws per signal)
base_trades = []
for r in t.itertuples():
    pool = elig_by_date.get(pd.Timestamp(r.signal_date), [])
    for _ in range(3):
        if not pool:
            break
        sym, k = pool[rng.integers(len(pool))]
        d = data[sym]
        m = pd.Series(False, index=d.index); m.iat[k] = True
        base_trades += SC.simulate(d, m, tr, sym)
b = pd.DataFrame(base_trades)
for name, x in (("SCREENER (your rules)", t), ("BASELINE random stock, same filters minus breakout/volume", b)):
    print(f"\n=== {name} ===")
    for k, v in SC.summarise(x).items():
        print(f"{k:>20}: {v}")
t["year"] = pd.to_datetime(t.entry_date).dt.year
b["year"] = pd.to_datetime(b.entry_date).dt.year
by = pd.DataFrame({"trades": t.groupby("year").size(), "screener avg %": t.groupby("year").return_pct.mean().round(2),
                   "screener win %": (100 * t.groupby("year").return_pct.apply(lambda x: (x > 0).mean())).round(1),
                   "baseline avg %": b.groupby("year").return_pct.mean().round(2)})
print(by.to_string())
by.to_csv("smallcap_by_year.csv")
