"""The user's own TradingView scripts, ported line by line from Pine and tested after costs.

1. PDH/PDL Reversal Pattern v3 (indicator): a RED candle whose high pokes above yesterday's high = short signal; if
   the NEXT candle breaks its low -> short at that candle's close; stop = signal candle high; target = the latest
   confirmed swing low (5-bar pivot). Long is the mirror (green candle below yesterday's low). The script's own
   filters are kept: one position at a time, a new short signal's low must be above the last traded signal's low
   until price trades back above that signal's high (same for longs).
2. Order Flow + Structure + Order Blocks (strategy): order flow = EMA(7) then EMA(5) of up / down closes weighted
   by volume vs its 20-bar average; BUY when buy flow crosses above sell flow while structure is bullish (last
   10-bar pivot high / low not lower than the one before); "full" signals also need price inside the latest
   bullish order block. Stop 1.5%, target 3% from the signal close; entry next candle's open; positions can run
   overnight, as in the script.
3. Momentum Scalper v1.0 (indicator, "best on 1-min"): HalfTrend flips up and at least 4 of 5 agree (HalfTrend,
   RSI 50-70, MACD 9/21/6, Stochastic 14/3/3, volume spike 1.5x on a green candle); entry at the close; stop 1 ATR,
   target 1.5 ATR (the script's TP / SL lines).
4. XAUUSD Confluence Scalper v4 (indicator): six checks (RSI, volume spike, Bollinger %B, EMA 5/8/13 stack,
   3-bar momentum > 2 pts, MACD histogram), grades and streaks, chop filter (EMA spread / slope / ADX), cooldown,
   exactly as coded. The script has no exits, so the test uses its sister script's: stop 1 ATR, target 1.5 ATR.

Indian markets: exit at 15:15 for 1 and 3 (intraday scalps); 1 is also run on gold and crypto. Costs a round trip:
Nifty 2 pts, Bank Nifty 5, stocks 0.06%, BTC / ETH 0.10%, gold 0.5 $.
Data: Nifty / Bank Nifty 1-minute (1 year) and 5-minute (5 years); 206 F&O stocks 5-minute (1 year);
Binance BTC, ETH, PAXG (gold) 1-minute (90 days) and 5-minute (2 years).

Usage (Omnipuls folder): .venv\\Scripts\\python research\\my_scripts.py
"""
from __future__ import annotations

import glob
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
pd.set_option("display.width", 250)
COST = {"NIFTY": ("pts", 2.0), "BANKNIFTY": ("pts", 5.0), "STOCK": ("pct", 0.06), "BTC": ("pct", 0.10),
        "ETH": ("pct", 0.10), "GOLD": ("pts", 0.5)}


# ------------------------------------------------------------------ helpers (Pine equivalents)
def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def atr(H, L, C, n):
    pc = np.r_[np.nan, C[:-1]]
    tr = np.nanmax(np.vstack([H - L, np.abs(H - pc), np.abs(L - pc)]), 0)
    return rma(tr, n)


def rsi(C, n=14):
    d = np.diff(C, prepend=C[0])
    up, dn = rma(np.clip(d, 0, None), n), rma(np.clip(-d, 0, None), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def pivots(X, n, high=True):
    """ta.pivothigh / pivotlow(n, n): value at bar t (confirmed n bars after the pivot)."""
    out = np.full(len(X), np.nan)
    for c in range(n, len(X) - n):
        win = X[c - n:c + n + 1]
        if high and X[c] == win.max() and X[c] > X[c - n:c].max():
            out[c + n] = X[c]
        if not high and X[c] == win.min() and X[c] < X[c - n:c].min():
            out[c + n] = X[c]
    return out


def cost_of(kind, px):
    u, c = COST[kind]
    return c if u == "pts" else px * c / 100


def prep(df, india: bool):
    df = df.copy()
    if df.index.tz is not None:
        df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
    df = df.sort_index()
    if india:
        t = df.index.strftime("%H:%M")
        df = df[(t >= "09:15") & (t <= "15:29")]
    return df[~df.index.duplicated()]


def stats(rows, label):
    T = pd.DataFrame(rows)
    if T.empty:
        print(f"\n{label}: no trades")
        return T
    T = T.sort_values("date")
    mid = T["date"].iloc[len(T) // 2]
    g = lambda x: pd.Series({  # noqa: E731
        "trades": len(x), "win %": 100 * (x["pts"] > 0).mean(), "avg R": x["R"].mean(),
        "avg pts": x["pts"].mean(), "avg %": x["pct"].mean(), "total %": x["pct"].sum(),
        "1st half %": x[x["date"] < mid]["pct"].mean(), "2nd half %": x[x["date"] >= mid]["pct"].mean(),
        "cost %": x["cost_pct"].mean(), "before cost %": (x["pct"] + x["cost_pct"]).mean()})
    print(f"\n{label}")
    print(T.groupby("market").apply(g).round(3).to_string())
    return T


def exit_walk(H, L, C, k, side, stop, tgt, last_ok):
    """From candle k+1: stop first, then target; else close of the last allowed candle."""
    for j in range(k + 1, len(C)):
        if not last_ok(j):
            return C[j - 1], j - 1, "time"
        if (side > 0 and L[j] <= stop) or (side < 0 and H[j] >= stop):
            return stop, j, "stop"
        if tgt is not None and np.isfinite(tgt) and ((side > 0 and H[j] >= tgt) or (side < 0 and L[j] <= tgt)):
            return tgt, j, "target"
    return C[-1], len(C) - 1, "time"


def record(rows, market, kind, ts, side, e, px, risk, how):
    c = cost_of(kind, e)
    pts = side * (px - e) - c
    rows.append({"market": market, "date": ts, "side": side, "entry": e, "exit": px, "how": how, "pts": pts,
                 "pct": 100 * pts / e, "cost_pct": 100 * c / e, "R": pts / risk if risk > 0 else np.nan})


# ------------------------------------------------------------------ 1. PDH/PDL Reversal Pattern v3
def pdh_reversal(df, market, kind, india, swing_len=5):
    df = prep(df, india)
    O, H, L, C = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
    day = df.index.normalize()
    d = df.groupby(day).agg(h=("High", "max"), l=("Low", "min"))
    pdh = pd.Series(day).map(d["h"].shift(1)).to_numpy()
    pdl = pd.Series(day).map(d["l"].shift(1)).to_numpy()
    hm = df.index.strftime("%H:%M").to_numpy()
    ph, pl = pivots(H, swing_len, True), pivots(L, swing_len, False)
    rows = []
    sw_lo1 = sw_hi1 = np.nan
    busy = -1                       # in a position up to and including this candle
    s_arm = l_arm = s_mon = l_mon = False
    prev_s_low = prev_l_high = np.nan
    s_sig = l_sig = (np.nan, np.nan)
    for k in range(len(C)):
        if np.isfinite(pl[k]):
            sw_lo1 = pl[k]
        if np.isfinite(ph[k]):
            sw_hi1 = ph[k]
        flat = k > busy
        late = india and hm[k] > "15:00"
        red, green = C[k] < O[k], C[k] > O[k]
        valid_s = red and H[k] > pdh[k] and flat and not s_arm and             (np.isnan(prev_s_low) or L[k] > prev_s_low) and not s_mon
        valid_l = green and L[k] < pdl[k] and flat and not l_arm and             (np.isnan(prev_l_high) or H[k] < prev_l_high) and not l_mon
        ok = (lambda j, k=k: hm[j] <= "15:14" and day[j] == day[k]) if india else (lambda j: True)
        if s_arm and flat and not late and L[k] < s_sig[0]:
            e, sl, tp = C[k], s_sig[1], sw_lo1
            px, jx, how = exit_walk(H, L, C, k, -1, sl, tp, ok)
            record(rows, market, kind, df.index[k], -1, e, px, sl - e, how)
            prev_s_low, s_mon, busy, flat = s_sig[0], True, jx, False
        s_arm = False
        if l_arm and flat and not late and H[k] > l_sig[0]:
            e, sl, tp = C[k], l_sig[1], sw_hi1
            px, jx, how = exit_walk(H, L, C, k, 1, sl, tp, ok)
            record(rows, market, kind, df.index[k], 1, e, px, e - sl, how)
            prev_l_high, l_mon, busy, flat = l_sig[0], True, jx, False
        l_arm = False
        if valid_s and flat:
            s_sig, s_arm = (L[k], H[k]), True
        if valid_l and flat:
            l_sig, l_arm = (H[k], L[k]), True
        if s_mon and H[k] > s_sig[1]:
            s_mon = False
        if l_mon and L[k] < l_sig[1]:
            l_mon = False
    return rows


# ------------------------------------------------------------------ 2. Order Flow + Structure + OB strategy
def order_flow(df, market, kind, sl_pct=1.5, tp_pct=3.0, length=10, ob_len=10):
    df = prep(df, False)
    O, H, L, C, V = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close", "Volume"))
    vb = V / sma(V, 20)
    ch = np.diff(C, prepend=np.nan)
    buy_raw = np.where(ch > 0, ch * vb, 0)
    sell_raw = np.where(ch < 0, -ch * vb, 0)
    bs, ss = ema(ema(np.nan_to_num(buy_raw), 7), 5), ema(ema(np.nan_to_num(sell_raw), 7), 5)
    fb = (bs > ss) & (np.r_[False, bs[:-1] <= ss[:-1]])
    fs = (ss > bs) & (np.r_[False, ss[:-1] <= bs[:-1]])
    ph, pl = pivots(H, length, True), pivots(L, length, False)
    oph, opl = pivots(H, ob_len, True), pivots(L, ob_len, False)
    avgc, avgv = sma(H - L, 20), sma(V, 20)
    rows = []
    lastPH = prevPH = lastPL = prevPL = np.nan
    bull = bear = False
    bt = bb = brt = brb = np.nan
    pos_until = -1
    for t in range(len(C)):
        if np.isfinite(ph[t]):
            prevPH, lastPH = lastPH, ph[t]
        if np.isfinite(pl[t]):
            prevPL, lastPL = lastPL, pl[t]
        isHH, isLH = lastPH > prevPH, lastPH < prevPH
        isHL, isLL = lastPL > prevPL, lastPL < prevPL
        if isHH or isHL:
            bull, bear = True, False
        if isLH or isLL:
            bear, bull = True, False
        for piv, want_red, is_bull in ((opl[t], True, True), (oph[t], False, False)):
            if np.isfinite(piv):
                for i in range(1, ob_len + 1):
                    j = t - (ob_len + i)
                    if j < 1:
                        break
                    if (C[j] < O[j]) if want_red else (C[j] > O[j]):
                        imp = j + 1
                        if (H[imp] - L[imp]) >= avgc[imp] * 1.5 and V[imp] >= avgv[imp] * 1.2:
                            if is_bull:
                                bt, bb = H[j], L[j]
                            else:
                                brt, brb = H[j], L[j]
                        break
        if t <= pos_until or t + 1 >= len(C):
            continue
        in_bull = np.isfinite(bt) and bb <= C[t] <= bt
        in_bear = np.isfinite(brt) and brb <= C[t] <= brt
        for side, sig, full in ((1, fb[t] and bull, in_bull), (-1, fs[t] and bear, in_bear)):
            if not sig:
                continue
            ref = C[t]
            stop, tgt = ref * (1 - side * sl_pct / 100), ref * (1 + side * tp_pct / 100)
            e = O[t + 1]
            px, j, how = exit_walk(H, L, C, t, side, stop, tgt, lambda j: True)
            record(rows, market + (" FULL (OB)" if full else " base"), kind, df.index[t], side, e, px,
                   abs(e - stop), how)
            pos_until = j
            break
    return rows


# ------------------------------------------------------------------ 3. Momentum Scalper v1.0
def halftrend(H, L, C, amp=2, dev=2.0):
    a = atr(H, L, C, 14)
    n = len(C)
    trend, next_trend = 0, 0
    max_low, min_high = L[0], H[0]
    up = down = 0.0
    hdir = np.zeros(n, int)
    hma, lma = sma(H, amp), sma(L, amp)
    d = 0
    for i in range(n):
        atr_high, atr_low = H[i] - a[i] * dev, L[i] + a[i] * dev
        if next_trend == 1:
            max_low = max(L[i], max_low)
            if atr_high < max_low and C[i] < (L[i - 1] if i else L[i]):
                trend, next_trend, min_high = 1, 0, H[i]
        else:
            min_high = min(H[i], min_high)
            if atr_low > min_high and C[i] > (H[i - 1] if i else H[i]):
                trend, next_trend, max_low = 0, 1, L[i]
        if trend == 0:
            if np.isfinite(lma[i]) and lma[i] < up:
                up = lma[i]
            else:
                up = lma[i] if np.isfinite(lma[i]) else up
                d = 1
        else:
            if np.isfinite(hma[i]) and hma[i] > down:
                down = hma[i]
            else:
                down = hma[i] if np.isfinite(hma[i]) else down
                d = -1
        hdir[i] = d
    return hdir


def mom_scalper(df, market, kind, india):
    df = prep(df, india)
    O, H, L, C, V = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close", "Volume"))
    hm = df.index.strftime("%H:%M").to_numpy()
    day = df.index.normalize()
    a = atr(H, L, C, 14)
    hd = halftrend(H, L, C)
    r = rsi(C, 14)
    ml = ema(C, 9) - ema(C, 21)
    sg = ema(ml, 6)
    hist = ml - sg
    ll, hh = pd.Series(L).rolling(14).min().to_numpy(), pd.Series(H).rolling(14).max().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = 100 * (C - ll) / (hh - ll)
    k_ = sma(raw, 3)
    d_ = sma(k_, 3)
    vm = sma(V, 20)
    vs = V > vm * 1.5
    rows = []
    free = 0
    for t in range(30, len(C) - 1):
        if t < free:
            continue
        if india and not ("09:20" <= hm[t] <= "15:00"):
            continue
        for side in (1, -1):
            flip = hd[t] == side and hd[t - 1] == -side
            if not flip:
                continue
            rs = (50 < r[t] < 70) if side > 0 else (30 < r[t] < 50)
            mc = (ml[t] > sg[t] and hist[t] > 0) if side > 0 else (ml[t] < sg[t] and hist[t] < 0)
            mcx = (ml[t] > sg[t] and ml[t - 1] <= sg[t - 1]) if side > 0 else (ml[t] < sg[t] and ml[t - 1] >= sg[t - 1])
            st = (k_[t] > d_[t] and k_[t] < 80) if side > 0 else (k_[t] < d_[t] and k_[t] > 20)
            vv = vs[t] and ((C[t] > O[t]) if side > 0 else (C[t] < O[t]))
            score = 1 + rs + (mc or mcx) + st + vv
            if score < 4:
                continue
            e = C[t]
            stop, tgt = e - side * a[t], e + side * 1.5 * a[t]
            ok = (lambda j, t=t: hm[j] <= "15:14" and day[j] == day[t]) if india else (lambda j: True)
            px, j, how = exit_walk(H, L, C, t, side, stop, tgt, ok)
            record(rows, market, kind, df.index[t], side, e, px, a[t], how)
            free = j + 1
            break
    return rows


# ------------------------------------------------------------------ 4. XAUUSD Confluence Scalper v4
def confluence(df, market, kind):
    df = prep(df, False)
    O, H, L, C, V = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close", "Volume"))
    r = rsi(C, 14)
    mid = sma(C, 20)
    sd = pd.Series(C).rolling(20).std(ddof=0).to_numpy()
    up_, lo_ = mid + 2 * sd, mid - 2 * sd
    with np.errstate(divide="ignore", invalid="ignore"):
        bbp = np.where(up_ == lo_, 50.0, (C - lo_) / (up_ - lo_) * 100)
    e5, e8, e13 = ema(C, 5), ema(C, 8), ema(C, 13)
    macd = ema(C, 12) - ema(C, 26)
    hist = macd - ema(macd, 9)
    a = atr(H, L, C, 14)
    vr = V / sma(V, 14)
    mom = C - np.r_[np.full(3, np.nan), C[:-3]]
    big = np.abs(C - O) > 1.2 * a
    spread = np.abs(e13 - e5) / a
    slope = np.abs(e13 - np.r_[np.full(5, np.nan), e13[:-5]]) / a
    # ADX (ta.dmi 14, 14)
    upm = np.diff(H, prepend=np.nan)
    dnm = -np.diff(L, prepend=np.nan)
    pdm = np.where((upm > dnm) & (upm > 0), upm, 0)
    ndm = np.where((dnm > upm) & (dnm > 0), dnm, 0)
    tr_ = atr(H, L, C, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi, ndi = 100 * rma(pdm, 14) / tr_, 100 * rma(ndm, 14) / tr_
        adx = rma(100 * np.abs(pdi - ndi) / (pdi + ndi), 14)
    trending = ((spread >= 0.15).astype(int) + (slope >= 0.10) + (adx >= 20)) >= 2
    sideways = ~trending
    bull = (r > 55).astype(int) + ((vr > 1.5) & (C > O)) + (bbp > 75) + ((C > e5) & (e5 > e8) & (e8 > e13)) + \
        (mom > 2.0) + (hist > 0)
    bear = (r < 45).astype(int) + ((vr > 1.5) & (C < O)) + (bbp < 25) + ((C < e5) & (e5 < e8) & (e8 < e13)) + \
        (mom < -2.0) + (hist < 0)
    rows = []
    bstreak = sstreak = 0
    since = 999
    free = 0
    for t in range(40, len(C) - 1):
        if bull[t] >= 5:
            bstreak, sstreak = bstreak + 1, 0
        elif bear[t] >= 5:
            sstreak, bstreak = sstreak + 1, 0
        else:
            bstreak = sstreak = 0
        gate_base = a[t] >= 1.5
        gate = gate_base and not sideways[t]
        bb_boost, sb_boost = big[t] and C[t] > O[t], big[t] and C[t] < O[t]
        buy_a = gate_base and bull[t] >= 7          # as coded: the score tops out at 6, so A never fires
        buy_b = gate and bull[t] >= 6 and bstreak >= (1 if bb_boost else 2)
        buy_be = gate and bull[t] >= 6 and bstreak >= 1 and not buy_b
        sell_a = gate_base and bear[t] >= 7
        sell_b = gate and bear[t] >= 6 and sstreak >= (1 if sb_boost else 2)
        sell_be = gate and bear[t] >= 6 and sstreak >= 1 and not sell_b
        cool = since <= 5
        buy = (buy_a or buy_b or buy_be) and (not cool or buy_a)
        sell = (sell_a or sell_b or sell_be) and (not cool or sell_a)
        if buy and sell:
            sell = False
        since = 0 if (buy or sell) else since + 1
        if not (buy or sell) or t < free:
            continue
        side = 1 if buy else -1
        e = C[t]
        stop, tgt = e - side * a[t], e + side * 1.5 * a[t]
        px, j, how = exit_walk(H, L, C, t, side, stop, tgt, lambda j: True)
        record(rows, market, kind, df.index[t], side, e, px, a[t], how)
        free = j + 1
    return rows


# ------------------------------------------------------------------ data
def binance(symbol, interval, days):
    f = HERE / "cache" / f"binance_{symbol}_{interval}_{days}.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        return pickle.loads(f.read_bytes())
    import requests
    import truststore
    from concurrent.futures import ThreadPoolExecutor
    truststore.inject_into_ssl()
    step = {"1m": 60000, "5m": 300000}[interval] * 1000
    now = int(time.time() * 1000)
    starts = list(range(now - days * 86400000, now, step))

    def page(s):
        for _ in range(3):
            try:
                r = requests.get("https://api.binance.com/api/v3/klines", timeout=30,
                                 params={"symbol": symbol, "interval": interval, "startTime": s, "limit": 1000})
                r.raise_for_status()
                return r.json()
            except Exception:
                time.sleep(1)
        return []
    with ThreadPoolExecutor(6) as ex:
        rows = [k for p in ex.map(page, starts) for k in p]
    df = pd.DataFrame([[float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in rows],
                      columns=["Open", "High", "Low", "Close", "Volume"], index=pd.to_datetime([x[0] for x in rows], unit="ms"))
    df = df[~df.index.duplicated()].sort_index()
    f.write_bytes(pickle.dumps(df))
    return df


def main():
    n1 = pickle.loads((HERE / "cache" / "y1m_IDX_13.pkl").read_bytes())
    b1 = pickle.loads((HERE / "cache" / "y1m_IDX_25.pkl").read_bytes())
    i5 = {n: pickle.loads(open(sorted(glob.glob(str(HERE / "cache" / f"IDX_I_{s}_5_1800_*.pkl")))[-1], "rb").read())
          for n, s in (("NIFTY", 13), ("BANKNIFTY", 25))}
    from bigbars_dhan import load_cache
    _, raw = load_cache()
    raw = {s: prep(d, True) for s, d in raw.items()}
    raw = {s: d[d.index >= d.index.max() - pd.Timedelta(days=365)] for s, d in raw.items()}
    c5 = {"BTC": binance("BTCUSDT", "5m", 730), "ETH": binance("ETHUSDT", "5m", 730),
          "GOLD": binance("PAXGUSDT", "5m", 730)}
    c1 = {"BTC": binance("BTCUSDT", "1m", 90), "ETH": binance("ETHUSDT", "1m", 90), "GOLD": binance("PAXGUSDT", "1m", 90)}
    out = []

    def keep(rows, label):
        out.append(stats(rows, label).assign(test=label))

    keep(pdh_reversal(n1, "NIFTY 1-min", "NIFTY", True) + pdh_reversal(b1, "BANKNIFTY 1-min", "BANKNIFTY", True) +
         pdh_reversal(i5["NIFTY"], "NIFTY 5-min (5y)", "NIFTY", True) +
         pdh_reversal(i5["BANKNIFTY"], "BANKNIFTY 5-min (5y)", "BANKNIFTY", True) +
         sum([pdh_reversal(d, "F&O stocks 5-min", "STOCK", True) for d in raw.values()], []) +
         sum([pdh_reversal(d, f"{k} 5-min (2y)", k, False) for k, d in c5.items()], []) +
         sum([pdh_reversal(d, f"{k} 1-min (90d)", k, False) for k, d in c1.items()], []),
         "=== 1. PDH/PDL Reversal Pattern v3")
    keep(sum([order_flow(d.resample("15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                                  "Volume": "sum"}).dropna(), f"{k} 15-min", k) for k, d in c5.items()], []) +
         sum([order_flow(d.resample("60min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                                  "Volume": "sum"}).dropna(), f"{k} 1-hour", k) for k, d in c5.items()], []) +
         sum([order_flow(d, "F&O stocks 5-min", "STOCK") for d in raw.values()], []),
         "=== 2. Order Flow + Structure + Order Blocks (strategy as coded: SL 1.5% TP 3%)")
    keep(mom_scalper(n1, "NIFTY 1-min", "NIFTY", True) + mom_scalper(b1, "BANKNIFTY 1-min", "BANKNIFTY", True) +
         sum([mom_scalper(d, f"{k} 1-min (90d)", k, False) for k, d in c1.items()], []),
         "=== 3. Momentum Scalper v1.0 (1-min, SL 1 ATR, TP 1.5 ATR)")
    keep(confluence(c1["GOLD"], "GOLD 1-min (90d)", "GOLD") + confluence(c5["GOLD"], "GOLD 5-min (2y)", "GOLD"),
         "=== 4. XAUUSD Confluence Scalper v4 (exits: SL 1 ATR, TP 1.5 ATR)")
    pd.concat(out).to_csv(HERE / "results" / "my_scripts.csv", index=False)


if __name__ == "__main__":
    main()
