"""Small-cap cash buying, 3-4 month hold: Bollinger (35, 1.5) close OUTSIDE (above) the upper band on a daily or
weekly candle, then wait for a later candle to BREAK that candle's high and CLOSE above it with volume.
Universe: NSE EQ stocks priced Rs 10-30 (as in the earlier small-cap test) and a wider small-cap band Rs 10-200,
20-day avg turnover >= Rs 1 Cr. Entry at the breakout candle's close. Cost 0.5% round trip.
Baseline: random eligible stocks (same price/turnover/date) with the same exit -> is the setup better than luck?"""
import glob, os, sys, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
SRC = "/tmp/eod2probe/daily"
START, COST = pd.Timestamp("2012-01-01"), 0.005
rng = np.random.default_rng(11)

def load(f):
    h = pd.read_csv(f, usecols=["Date", "Open", "High", "Low", "Close", "Volume", "Series"])
    h["Date"] = pd.to_datetime(h["Date"]); h = h.drop_duplicates("Date").sort_values("Date")
    h = h[h["Series"].astype(str).str.strip().isin(["EQ", "BE", "BZ"])]
    return h.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]].astype(float)

def weekly(d):
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    w["last_day"] = d["Close"].resample("W-FRI").apply(lambda s: s.index[-1] if len(s) else pd.NaT)
    return w.dropna()

def signals(b, n=35, k=1.5, wait=5, vol_k=1.5):
    """b: bars. returns list of (entry_bar_idx, signal_idx) - signal = close above upper band; trigger = later bar
    within `wait` bars whose high > signal high and close > signal high, volume >= vol_k x 20-bar avg."""
    c, h, v = b["Close"].values, b["High"].values, b["Volume"].values
    mid = pd.Series(c).rolling(n).mean().values; sd = pd.Series(c).rolling(n).std(ddof=0).values
    up = mid + k * sd
    av = pd.Series(v).rolling(20).mean().shift(1).values
    sig = c > up
    out = []; i = 0; N = len(c)
    while i < N:
        if not sig[i] or np.isnan(up[i]):
            i += 1; continue
        hit = None
        for j in range(i + 1, min(i + 1 + wait, N)):
            if h[j] > h[i] and c[j] > h[i] and (vol_k == 0 or v[j] >= vol_k * av[j]):
                hit = j; break
        if hit is not None:
            out.append((hit, i)); i = hit + 1
        else:
            i += 1
    return out, mid

def exit_trade(d, e_day, e_px, stop, mode, hold, mid_daily):
    """Daily simulation from the day after entry. mode: 'time' (stop + time), 'trail' (close < 35-SMA, daily) , 'half30'."""
    idx = d.index.searchsorted(e_day, side="right")
    o, h, l, c = (d[x].values for x in ("Open", "High", "Low", "Close"))
    end = min(idx + hold, len(d)) - 1
    if idx > end: return None
    half = None
    for j in range(idx, end + 1):
        if l[j] <= stop:
            px = min(o[j], stop); r = px / e_px - 1
            return (r if half is None else 0.5 * half + 0.5 * r), j - idx + 1, d.index[j]
        if mode == "half30" and half is None and h[j] >= e_px * 1.30:
            half = 0.30
        if mode == "trail" and c[j] < mid_daily[j]:
            r = c[j] / e_px - 1; return (r if half is None else 0.5 * half + 0.5 * r), j - idx + 1, d.index[j]
    r = c[end] / e_px - 1
    return (r if half is None else 0.5 * half + 0.5 * r), end - idx + 1, d.index[end]

CONFIGS = []
for tf in ("D", "W"):
    for vol_k in (0, 1.5, 2.0):
        for mode, hold, stopk in (("time", 63, "sig_low"), ("time", 84, "sig_low"), ("time", 84, "12pct"),
                                  ("trail", 84, "12pct"), ("half30", 84, "12pct")):
            CONFIGS.append((tf, vol_k, mode, hold, stopk))
BANDS = {"Rs 10-30": (10, 30), "Rs 10-200": (10, 200)}

trades = {(b, *cfg): [] for b in BANDS for cfg in CONFIGS}
base = {(b, *cfg): [] for b in BANDS for cfg in CONFIGS}
elig = {b: {} for b in BANDS}
data = {}
files = sorted(glob.glob(f"{SRC}/*.csv"))
for fi, f in enumerate(files):
    try:
        d = load(f)
    except Exception:
        continue
    if len(d) < 300: continue
    turn20 = (d["Close"] * d["Volume"]).rolling(20).mean()
    mid_d = d["Close"].rolling(35).mean().values
    okb = {b: (d["Close"].between(lo, hi) & (turn20 >= 1e7) & (d.index >= START)) for b, (lo, hi) in BANDS.items()}
    if not any(m.any() for m in okb.values()): continue
    sym = os.path.basename(f)[:-4]
    data[sym] = (d, mid_d)
    for b, m in okb.items():
        for k in np.flatnonzero(m.values[::5]) * 5:      # every 5th eligible day is enough for the baseline pool
            elig[b].setdefault(d.index[k].to_period("W"), []).append((sym, k))
    W = weekly(d)
    for tf in ("D", "W"):
        bars = d if tf == "D" else W
        for vol_k in (0, 1.5, 2.0):
            sigs, _ = signals(bars, vol_k=vol_k, wait=5 if tf == "D" else 3)
            for ent, si in sigs:
                e_day = bars.index[ent] if tf == "D" else bars["last_day"].iloc[ent]
                if e_day < START: continue
                k = d.index.get_loc(e_day); e_px = d["Close"].iloc[k]
                for b, m in okb.items():
                    if not m.iloc[k]: continue
                    for cfg in CONFIGS:
                        if cfg[0] != tf or cfg[1] != vol_k: continue
                        _, _, mode, hold, stopk = cfg
                        stop = bars["Low"].iloc[si] if stopk == "sig_low" else e_px * 0.88
                        stop = min(stop, e_px * 0.995)
                        r = exit_trade(d, e_day, e_px, stop, mode, hold, mid_d)
                        if r: trades[(b, *cfg)].append((sym, e_day, r[0] - COST, r[1], (e_px - stop) / e_px))
    if fi % 500 == 0: print(fi, len(files), flush=True)

# baseline: for each trade, 2 random eligible stocks in the same week, same exit rule, stop 12% (or same % distance)
rows = []
for key, tl in trades.items():
    b, tf, vol_k, mode, hold, stopk = key
    if not tl: continue
    t = pd.DataFrame(tl, columns=["sym", "day", "ret", "days", "risk"])
    br = []
    for r in t.itertuples():
        pool = elig[b].get(pd.Timestamp(r.day).to_period("W"), [])
        for _ in range(2):
            if not pool: break
            s, k = pool[rng.integers(len(pool))]
            d, mid_d = data[s]; e_px = d["Close"].iloc[k]
            x = exit_trade(d, d.index[k], e_px, e_px * (1 - r.risk), mode, hold, mid_d)
            if x: br.append(x[0] - COST)
    br = np.array(br)
    y = pd.to_datetime(t.day).dt.year
    by = t.groupby(y).ret.mean()
    rows.append(dict(band=b, tf=tf, vol=f">={vol_k}x" if vol_k else "none", exit=f"{mode} {hold}d stop {stopk}",
                     trades=len(t), per_yr=round(len(t) / 14.8), avg=round(t.ret.mean() * 100, 2),
                     median=round(t.ret.median() * 100, 2), win=round((t.ret > 0).mean() * 100, 1),
                     base_avg=round(br.mean() * 100, 2) if len(br) else np.nan,
                     edge=round((t.ret.mean() - br.mean()) * 100, 2) if len(br) else np.nan,
                     y2012_19=round(t[y < 2020].ret.mean() * 100, 2), y2020_26=round(t[y >= 2020].ret.mean() * 100, 2),
                     yrs_pos=f"{(by > 0).sum()}/{len(by)}", days=round(t.days.mean())))
    pd.DataFrame(tl, columns=["sym", "day", "ret", "days", "risk"]).assign(cfg=str(key)).to_csv(
        f"trades_{b[:5].replace(' ', '')}_{tf}_{vol_k}_{mode}_{hold}_{stopk}.csv", index=False)
R = pd.DataFrame(rows); R.to_csv("bb_results.csv", index=False)
pd.set_option("display.width", 250)
print(R.to_string())
