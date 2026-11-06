"""Swing setups on daily continuous futures, 2005-2026. Entry next day's open, stop first (intraday low/high vs stop),
cost 0.06% a round trip. Results per trade in % and in R (risk = entry-stop)."""
import pickle, numpy as np, pandas as pd
D = pickle.load(open("cmd.pkl", "rb"))
COST = 0.06

def atr(d, n=14):
    pc = d.Close.shift()
    tr = pd.concat([d.High - d.Low, (d.High - pc).abs(), (d.Low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1/n).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1/n).mean()
    return 100 - 100 / (1 + up / dn)

def run(d, sig, stop_atr, exit_fn, max_hold, name):
    """sig: Series +1/-1/0 on day t close -> enter t+1 open. exit_fn(i, side) -> True to exit at close of i."""
    o, h, l, c, a = d.Open.values, d.High.values, d.Low.values, d.Close.values, d.ATR.values
    s = sig.values; idx = d.index; trades = []; i = 0; n = len(d)
    while i < n - 1:
        if s[i] == 0 or np.isnan(a[i]):
            i += 1; continue
        side = int(s[i]); e = o[i + 1]; risk = stop_atr * a[i]; stop = e - side * risk; j = i + 1; out = None
        while j < n:
            if side > 0 and l[j] <= stop: out = (min(stop, o[j]) if o[j] < stop else stop); break
            if side < 0 and h[j] >= stop: out = (max(stop, o[j]) if o[j] > stop else stop); break
            if exit_fn(j, side) or j - i >= max_hold: out = c[j]; break
            j += 1
        if out is None: break
        pct = side * (out / e - 1) * 100 - COST
        trades.append((idx[i + 1], side, pct, pct / (risk / e * 100), j - i))
        i = j + 1
    t = pd.DataFrame(trades, columns=["date", "side", "pct", "R", "days"])
    t["setup"] = name
    return t

def setups(d):
    d = d.copy(); d["ATR"] = atr(d); c = d.Close
    ma200, ma50, ma20, ma5 = c.rolling(200).mean(), c.rolling(50).mean(), c.ewm(span=20).mean(), c.rolling(5).mean()
    hh20, ll20 = d.High.rolling(20).max().shift(), d.Low.rolling(20).min().shift()
    hh55, ll55 = d.High.rolling(55).max().shift(), d.Low.rolling(55).min().shift()
    hh10, ll10 = d.Low.rolling(10).min(), d.High.rolling(10).max()
    r2 = rsi(c, 2); C = c.values
    out = []
    z = lambda x: x.fillna(0).astype(int)
    # 1. Donchian 20 breakout both ways, exit on 10-day opposite extreme, stop 2 ATR
    sg = z(pd.Series(np.where(c > hh20, 1, np.where(c < ll20, -1, 0)), d.index))
    L10, H10 = d.Low.rolling(10).min().values, d.High.rolling(10).max().values
    out.append(run(d, sg, 2, lambda j, s: (s > 0 and C[j] <= L10[j - 1]) or (s < 0 and C[j] >= H10[j - 1]), 60, "Donchian 20/10"))
    # 2. Donchian 55/20
    sg = z(pd.Series(np.where(c > hh55, 1, np.where(c < ll55, -1, 0)), d.index))
    L20, H20 = d.Low.rolling(20).min().values, d.High.rolling(20).max().values
    out.append(run(d, sg, 2, lambda j, s: (s > 0 and C[j] <= L20[j - 1]) or (s < 0 and C[j] >= H20[j - 1]), 120, "Donchian 55/20"))
    # 2b. long-only Donchian 20 above 200MA
    sg = z(pd.Series(np.where((c > hh20) & (c > ma200), 1, 0), d.index))
    out.append(run(d, sg, 2, lambda j, s: C[j] <= L10[j - 1], 60, "Donchian 20 long, >200MA"))
    # 3. RSI2 pullback with the 200MA trend, exit close beyond 5MA, stop 2.5 ATR, max 10 days
    M5 = ma5.values
    sg = z(pd.Series(np.where((r2 < 10) & (c > ma200), 1, np.where((r2 > 90) & (c < ma200), -1, 0)), d.index))
    out.append(run(d, sg, 2.5, lambda j, s: (s > 0 and C[j] > M5[j]) or (s < 0 and C[j] < M5[j]), 10, "RSI2 pullback in trend"))
    sg = z(pd.Series(np.where((r2 < 10) & (c > ma200), 1, 0), d.index))
    out.append(run(d, sg, 2.5, lambda j, s: C[j] > M5[j], 10, "RSI2 pullback long only"))
    # 4. EMA20 pullback in a strong trend (50>200, close crosses back above EMA20 after touching it)
    up = (ma50 > ma200) & (c > ma50); dn = (ma50 < ma200) & (c < ma50)
    touch_up = (d.Low <= ma20) & (c > ma20) & up; touch_dn = (d.High >= ma20) & (c < ma20) & dn
    sg = z(pd.Series(np.where(touch_up, 1, np.where(touch_dn, -1, 0)), d.index))
    E20 = ma20.values
    out.append(run(d, sg, 1.5, lambda j, s: (s > 0 and C[j] < E20[j] - 0.5 * d.ATR.values[j]) or (s < 0 and C[j] > E20[j] + 0.5 * d.ATR.values[j]), 30, "EMA20 pullback in trend"))
    # 5. NR7 + inside day breakout: next day stop-entry approximated by close beyond the NR7 day's range, hold 5 days
    rng = d.High - d.Low; nr7 = rng == rng.rolling(7).min()
    hi_p, lo_p = d.High.shift(), d.Low.shift(); nr_p = nr7.shift().fillna(False).astype(bool)
    sg = z(pd.Series(np.where(nr_p & (c > hi_p), 1, np.where(nr_p & (c < lo_p), -1, 0)), d.index))
    out.append(run(d, sg, 1.5, lambda j, s: False, 5, "NR7 breakout, hold 5d"))
    # 6. 3 lower closes in an uptrend (Connors-style), exit close > prior high, max 7 days
    dn3 = (c < c.shift()) & (c.shift() < c.shift(2)) & (c.shift(2) < c.shift(3))
    sg = z(pd.Series(np.where(dn3 & (c > ma200), 1, 0), d.index)); Hp = d.High.shift().values
    out.append(run(d, sg, 2.5, lambda j, s: C[j] > Hp[j], 7, "3 down days in uptrend"))
    # 7. time-series momentum: monthly, sign of 12-month return (approximation: enter on month change, hold ~21 days)
    m = c.pct_change(252); first = d.index.to_series().dt.month != d.index.to_series().shift().dt.month
    sg = z(pd.Series(np.where(first & (m > 0), 1, np.where(first & (m < 0), -1, 0)), d.index))
    out.append(run(d, sg, 4, lambda j, s: False, 21, "12-month momentum, monthly"))
    return pd.concat(out)

def stats(t):
    if t.empty: return pd.Series(dtype=float)
    w = t.pct > 0; pf = t.pct[w].sum() / max(-t.pct[~w].sum(), 1e-9)
    y = t.date.dt.year; half = t.date < "2016-01-01"
    by = t.groupby(y).pct.sum()
    return pd.Series({"n": len(t), "per yr": round(len(t) / max(y.nunique(), 1), 1), "win%": round(w.mean() * 100),
                      "avg%": round(t.pct.mean(), 2), "avgR": round(t.R.mean(), 2), "PF": round(pf, 2),
                      "05-15 avg%": round(t.pct[half].mean(), 2), "16-26 avg%": round(t.pct[~half].mean(), 2),
                      "last2y avg%": round(t.pct[t.date >= "2024-11-01"].mean(), 2),
                      "yrs +": f"{(by > 0).sum()}/{len(by)}", "days": round(t.days.mean(), 1)})

allt = []
for k, d in D.items():
    x = d["1d"]; x = x[x.index >= "2004-01-01"]
    x = x[(x.High >= x.Low) & (x.Close > 0)]
    t = setups(x); t = t[t.date >= "2005-01-01"]; t["mkt"] = k; allt.append(t)
T = pd.concat(allt); T.to_pickle("swing_trades.pkl")
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
res = T.groupby(["setup", "mkt"]).apply(stats).unstack() if False else T.groupby(["setup", "mkt"]).apply(stats)
print(res.to_string())
print("\nALL MARKETS")
print(T.groupby("setup").apply(stats).sort_values("avgR", ascending=False).to_string())
