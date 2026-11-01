"""The user's other TradingView scripts: the trade each one implies, ported from its Pine logic, tested after costs.

5  BB By Navneet Solanki (15-min): candles fully outside Bollinger(35, 1.5); the run's lowest high (buys) is the
   trigger; a close above it -> buy at that close; stop = low of the last candle fully below; target 4R (TP1).
6  Momentum Zone + Channel (5-min, India): today's 9:15 open inside yesterday's 14:30-15:30 range; first close
   above yesterday's high AND above VWAP on a green candle -> buy ("BO"); mirror "BD". Stop: VWAP at entry;
   target 2R; out 15:15. (The script's own yesterday-high skips each day's first candle: kept as coded.)
7  EMA Ribbon BOS (5-min): EMA 5 crosses above EMA 9 arms a buy; the next close above the latest 2-bar swing high
   -> buy; stop the latest 2-bar swing low; target 2R; mirror for sells. India out 15:15.
8  Auto Key Reaction Candle (crypto / gold, 15-min): the key candles (IST) BTC 09:15 13:15 21:00, ETH 11:00 13:00
   21:45, XAU 11:15 13:15 20:30; first later close beyond the box -> trade that way (also the fade), stop at the
   other side of the box, target 2R, out after 4 hours.
9  5:30-6:30 IST Range Zone + Fib (crypto / gold, 5-min): after 6:30 IST the first close beyond the zone -> trade
   that way, stop at the zone middle, target 2R, out after 12 hours; also the fade (back inside).
10 Ultimate 9:30 Sniper (stocks, 5-min): after 9:30 a close above the 9:15-9:30 high AND yesterday's high AND the
   stock up > 1% more than Nifty since 9:15 -> buy, stop at the 9:15-9:30 low, target 2R, out 15:15; until 11:00.
11 Atomic Swing Scalper: Supertrend(1, 1) flips, always in the market (index 1 and 5-min, crypto / gold 5-min).
12 AMD HTF Break + MSS (crypto / gold / index 5-min): wick beyond the previous 1H or 4H high -> bearish manipulation
   armed; then the script's BOS (close crosses back below the latest 10-bar swing HIGH) + bearish engulfing ->
   sell; stop the high since the sweep; target the current 4H low if beyond 1R, else 2R. Mirror for buys.
13 First Candle + Market Regime (index 5-min): the script's bias score (3-day and 5-day closes, where yesterday
   closed in its range, gap, first 5-min candle, open vs 10-day average, high-volatility boost); |score| >= 3 ->
   trade the bias from 9:20 to 15:15 (checks whether the prediction is right more than half the time).
14 Master For All: RSI(14) back below 70 -> sell, back above 30 -> buy (its blue / yellow candles); stop 1 ATR,
   target 1.5 ATR, India out 15:15.
Costs a round trip: Nifty 2 pts, Bank Nifty 5, stocks 0.06%, BTC / ETH 0.10%, gold 0.5 $.
Usage (Omnipuls folder): .venv\\Scripts\\python research\\my_scripts2.py
"""
from __future__ import annotations

import glob
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from my_scripts import COST, atr, binance, ema, exit_walk, pivots, prep, record, rsi, sma, stats  # noqa: E402

AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def rs(df, rule, india):
    kw = dict(origin="start_day", offset="15min") if india else {}
    return df.resample(rule, **kw).agg(AGG).dropna(subset=["Close"])


def arrays(df):
    return (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close", "Volume"))


def ind_ok(df, india, hours=None):
    hm = df.index.strftime("%H:%M").to_numpy()
    day = df.index.normalize()
    if india:
        return lambda k: (lambda j: hm[j] <= "15:14" and day[j] == day[k])
    if hours:
        ts = df.index
        return lambda k: (lambda j: ts[j] - ts[k] <= pd.Timedelta(hours=hours))
    return lambda k: (lambda j: True)


# 5 ------------------------------------------------------------------------------------------
def bb_script(df, market, kind, india, rr=4.0):
    O, H, L, C, V = arrays(df)
    mid = sma(C, 35)
    sd = pd.Series(C).rolling(35).std(ddof=0).to_numpy()
    up, lo = mid + 1.5 * sd, mid - 1.5 * sd
    hm = df.index.strftime("%H:%M").to_numpy()
    mk = ind_ok(df, india, 24)
    rows, busy = [], -1
    bseq = bsl = sseq = ssh = np.nan
    bready = sready = False
    for k in range(40, len(C)):
        if O[k] < lo[k] and H[k] < lo[k] and L[k] < lo[k] and C[k] < lo[k]:
            bseq = H[k] if np.isnan(bseq) else min(bseq, H[k])
            bsl, bready = L[k], True
        if O[k] > up[k] and H[k] > up[k] and L[k] > up[k] and C[k] > up[k]:
            sseq = L[k] if np.isnan(sseq) else max(sseq, L[k])
            ssh, sready = H[k], True
        for side in (1, -1):
            ready, trig, stop = (bready, bseq, bsl) if side > 0 else (sready, sseq, ssh)
            if not ready or not ((side > 0 and H[k] > trig and C[k] > trig) or (side < 0 and L[k] < trig and C[k] < trig)):
                continue
            if side > 0:
                bseq = bsl = np.nan
                bready = False
            else:
                sseq = ssh = np.nan
                sready = False
            if k <= busy or (india and hm[k] > "15:00"):
                continue
            e = C[k]
            risk = side * (e - stop)
            if risk <= 0:
                continue
            px, j, how = exit_walk(H, L, C, k, side, stop, e + side * rr * risk, mk(k))
            record(rows, market, kind, df.index[k], side, e, px, risk, how)
            busy = j
    return rows


# 6 ------------------------------------------------------------------------------------------
def momentum_zone(df, market, kind):
    O, H, L, C, V = arrays(df)
    hm = df.index.strftime("%H:%M").to_numpy()
    day = df.index.normalize()
    tp = (H + L + C) / 3
    g = pd.Series(np.arange(len(C))).groupby(day)
    cv = pd.Series(tp * V).groupby(day).cumsum().to_numpy()
    cvol = pd.Series(V).groupby(day).cumsum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.where(cvol > 0, cv / cvol, C)
    days = day.unique()
    first = (g.transform("min") == np.arange(len(C)))
    # yesterday's high / low as coded: the day's candles after the first one
    st = pd.DataFrame({"d": day, "H": np.where(first, np.nan, H), "L": np.where(first, np.nan, L)})
    dh = st.groupby("d")["H"].max().shift(1)
    dl = st.groupby("d")["L"].min().shift(1)
    win = (hm >= "14:30") & (hm < "15:30")
    rh = pd.Series(np.where(win, H, np.nan)).groupby(day).max().reindex(days).shift(1)
    rl = pd.Series(np.where(win, L, np.nan)).groupby(day).min().reindex(days).shift(1)
    rh.index = rl.index = days
    mk = ind_ok(df, True)
    rows = []
    for d in days[2:]:
        idx = np.flatnonzero(day == d)
        k0 = idx[0]
        if not (rl[d] <= O[k0] <= rh[d]):
            continue
        done = set()
        busy = -1
        for k in idx:
            if hm[k] > "15:00" or k <= busy:
                continue
            for side in (1, -1):
                if side in done:
                    continue
                if side > 0 and not (C[k] > dh[d] and C[k] > vwap[k] and C[k] > O[k]):
                    continue
                if side < 0 and not (C[k] < dl[d] and C[k] < vwap[k] and C[k] < O[k]):
                    continue
                done.add(side)
                e, stop = C[k], vwap[k]
                risk = side * (e - stop)
                if risk <= 0:
                    continue
                px, j, how = exit_walk(H, L, C, k, side, stop, e + side * 2 * risk, mk(k))
                record(rows, market, kind, df.index[k], side, e, px, risk, how)
                busy = j
                break
    return rows


# 7 ------------------------------------------------------------------------------------------
def ema_ribbon(df, market, kind, india):
    O, H, L, C, V = arrays(df)
    e1, e2 = ema(C, 5), ema(C, 9)
    ph, pl = pivots(H, 2, True), pivots(L, 2, False)
    hm = df.index.strftime("%H:%M").to_numpy()
    mk = ind_ok(df, india, 12)
    rows, busy = [], -1
    res = sup = np.nan
    bull = bear = False
    for k in range(20, len(C)):
        if np.isfinite(ph[k]):
            res = ph[k]
        if np.isfinite(pl[k]):
            sup = pl[k]
        if e1[k] > e2[k] and e1[k - 1] <= e2[k - 1]:
            bull, bear = True, False
        if e1[k] < e2[k] and e1[k - 1] >= e2[k - 1]:
            bear, bull = True, False
        sig = 0
        if bull and np.isfinite(res) and C[k] > res and C[k - 1] <= res:
            sig, bull, lvl_stop = 1, False, sup
            res = np.nan
        elif bear and np.isfinite(sup) and C[k] < sup and C[k - 1] >= sup:
            sig, bear, lvl_stop = -1, False, res
            sup = np.nan
        if not sig or k <= busy or (india and hm[k] > "15:00") or not np.isfinite(lvl_stop):
            continue
        e = C[k]
        risk = sig * (e - lvl_stop)
        if risk <= 0:
            continue
        px, j, how = exit_walk(H, L, C, k, sig, lvl_stop, e + sig * 2 * risk, mk(k))
        record(rows, market, kind, df.index[k], sig, e, px, risk, how)
        busy = j
    return rows


# 8 / 9 --------------------------------------------------------------------------------------
def box_trades(df, market, kind, boxes, fade, hours, stop_mid):
    """boxes: list of (start index after the box, box high, box low)."""
    O, H, L, C, V = arrays(df)
    ts = df.index
    rows, busy = [], -1
    for k0, hi, lo, end in boxes:
        for k in range(k0, min(end, len(C) - 1)):
            if k <= busy:
                break
            br = 1 if C[k] > hi else -1 if C[k] < lo else 0
            if not br:
                continue
            side = -br if fade else br
            e = C[k]
            if fade:
                stop = (max(H[k0:k + 1]) if side < 0 else min(L[k0:k + 1]))
            else:
                stop = (hi + lo) / 2 if stop_mid else (lo if side > 0 else hi)
            risk = side * (e - stop)
            if risk <= 0:
                break
            px, j, how = exit_walk(H, L, C, k, side, stop, e + side * 2 * risk,
                                   lambda j, k=k: ts[j] - ts[k] <= pd.Timedelta(hours=hours))
            record(rows, market, kind, ts[k], side, e, px, risk, how)
            busy = j
            break
    return rows


def key_candle_boxes(df15, times):
    ist = df15.index + pd.Timedelta(hours=5, minutes=30)
    hm = ist.strftime("%H:%M")
    out = []
    for k in np.flatnonzero(np.isin(hm, times)):
        out.append((k + 1, df15["High"].iloc[k], df15["Low"].iloc[k], k + 1 + 16))
    return out


def zone_boxes(df5):
    ist = df5.index + pd.Timedelta(hours=5, minutes=30)
    hm = ist.strftime("%H:%M").to_numpy()
    d = ist.normalize()
    out = []
    for day in d.unique():
        m = np.flatnonzero((d == day) & (hm >= "05:30") & (hm < "06:30"))
        if len(m) < 10:
            continue
        hi, lo = df5["High"].iloc[m].max(), df5["Low"].iloc[m].min()
        out.append((m[-1] + 1, hi, lo, m[-1] + 1 + 12 * 12))
    return out


# 10 -----------------------------------------------------------------------------------------
def sniper930(raw, nifty, market="F&O stocks 5-min", kind="STOCK"):
    n = prep(nifty, True)
    nopen = n.groupby(n.index.normalize())["Open"].first()
    nclose = n["Close"]
    rows = []
    for s, df in raw.items():
        O, H, L, C, V = arrays(df)
        hm = df.index.strftime("%H:%M").to_numpy()
        day = df.index.normalize()
        dh = df.groupby(day)["High"].max().shift(1)
        mk = ind_ok(df, True)
        for d in day.unique()[1:]:
            idx = np.flatnonzero(day == d)
            orb = idx[(hm[idx] >= "09:15") & (hm[idx] < "09:30")]
            if len(orb) < 3 or d not in nopen.index or not np.isfinite(dh.get(d, np.nan)):
                continue
            oh, ol, o915 = H[orb].max(), L[orb].min(), O[orb[0]]
            for k in idx[(hm[idx] >= "09:30") & (hm[idx] <= "11:00")]:
                ts = df.index[k]
                if ts not in nclose.index:
                    continue
                relst = (C[k] / o915 - 1) * 100 - (nclose[ts] / nopen[d] - 1) * 100
                if C[k] > oh and C[k] > dh[d] and relst > 1.0:
                    e, stop = C[k], ol
                    risk = e - stop
                    px, j, how = exit_walk(H, L, C, k, 1, stop, e + 2 * risk, mk(k))
                    record(rows, market, kind, ts, 1, e, px, risk, how)
                    break
    return rows


# 11 -----------------------------------------------------------------------------------------
def supertrend_dir(H, L, C, factor=1.0, n=1):
    a = atr(H, L, C, n)
    hl2 = (H + L) / 2
    up, dn = hl2 - factor * a, hl2 + factor * a
    d = np.ones(len(C), int)
    fu, fd = up.copy(), dn.copy()
    for i in range(1, len(C)):
        fu[i] = up[i] if C[i - 1] < fu[i - 1] else max(up[i], fu[i - 1])
        fd[i] = dn[i] if C[i - 1] > fd[i - 1] else min(dn[i], fd[i - 1])
        if d[i - 1] == -1:   # Pine: -1 = up trend
            d[i] = 1 if C[i] < fu[i] else -1
        else:
            d[i] = -1 if C[i] > fd[i] else 1
    return d


def atomic(df, market, kind, india):
    O, H, L, C, V = arrays(df)
    d = supertrend_dir(H, L, C)
    hm = df.index.strftime("%H:%M").to_numpy()
    day = df.index.normalize()
    rows = []
    pos, e, k_in = 0, 0.0, 0
    a = atr(H, L, C, 14)
    for k in range(2, len(C)):
        flip = d[k] != d[k - 1]
        end_day = india and (hm[k] >= "15:14" or (k + 1 < len(C) and day[k + 1] != day[k]))
        if pos and (flip or end_day):
            record(rows, market, kind, df.index[k_in], pos, e, C[k], a[k_in], "flip" if flip else "time")
            pos = 0
        if flip and not end_day and (not india or hm[k] <= "15:00"):
            pos, e, k_in = (1 if d[k] == -1 else -1), C[k], k
    return rows


# 12 -----------------------------------------------------------------------------------------
def amd(df, market, kind, india):
    O, H, L, C, V = arrays(df)
    ts = df.index
    h1 = df.resample("60min").agg(AGG).dropna(subset=["Close"])
    h4 = df.resample("240min").agg(AGG).dropna(subset=["Close"])
    def prev_of(htf, col):
        s = htf[col].shift(1)
        return s.reindex(ts, method="ffill").to_numpy()
    p1h, p1l, p4h, p4l = prev_of(h1, "High"), prev_of(h1, "Low"), prev_of(h4, "High"), prev_of(h4, "Low")
    # running 4H high / low so far
    g4 = ts.floor("240min")
    c4h = pd.Series(H).groupby(g4).cummax().to_numpy()
    c4l = pd.Series(L).groupby(g4).cummin().to_numpy()
    ph, pl = pivots(H, 10, True), pivots(L, 10, False)
    hm = ts.strftime("%H:%M").to_numpy()
    mk = ind_ok(df, india, 12)
    rows, busy = [], -1
    bear_on = bull_on = False
    bear_k = bull_k = 0
    bh = bl = np.nan
    bh_prev = bl_prev = np.nan
    for k in range(1, len(C)):
        bh_prev, bl_prev = bh, bl
        if np.isfinite(ph[k]):
            bh = ph[k]
        if np.isfinite(pl[k]):
            bl = pl[k]
        if (H[k] > p4h[k] or H[k] > p1h[k]) and not bear_on:
            bear_on, bull_on, bear_k = True, False, k
        if (L[k] < p4l[k] or L[k] < p1l[k]) and not bull_on:
            bull_on, bear_on, bull_k = True, False, k
        bos_bear = np.isfinite(bh) and C[k] < bh and C[k - 1] >= bh_prev
        bos_bull = np.isfinite(bl) and C[k] > bl and C[k - 1] <= bl_prev
        eng_bear = C[k] < O[k] and C[k] < L[k - 1] and O[k] >= C[k - 1]
        eng_bull = C[k] > O[k] and C[k] > H[k - 1] and O[k] <= C[k - 1]
        for side, on, bos, eng, k_m in ((1, bull_on, bos_bull, eng_bull, bull_k), (-1, bear_on, bos_bear, eng_bear, bear_k)):
            if not (on and bos and eng):
                continue
            if side > 0:
                bull_on = False
            else:
                bear_on = False
            if k <= busy or (india and hm[k] > "15:00"):
                continue
            e = C[k]
            stop = L[k_m:k + 1].min() if side > 0 else H[k_m:k + 1].max()
            risk = side * (e - stop)
            if risk <= 0:
                continue
            t4 = c4h[k] if side > 0 else c4l[k]
            tgt = t4 if side * (t4 - e) >= risk else e + side * 2 * risk
            px, j, how = exit_walk(H, L, C, k, side, stop, tgt, mk(k))
            record(rows, market, kind, ts[k], side, e, px, risk, how)
            busy = j
    return rows


# 13 -----------------------------------------------------------------------------------------
def first_candle(df, market, kind):
    O, H, L, C, V = arrays(df)
    day = df.index.normalize()
    D = df.groupby(day).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    rng = (D.h - D.l)
    vol_hi = rng.shift(1) > rng.rolling(10).mean().shift(1) * 1.2
    rows = []
    hm = df.index.strftime("%H:%M").to_numpy()
    days = D.index
    for i in range(11, len(days)):
        d = days[i]
        idx = np.flatnonzero(day == d)
        if len(idx) < 10:
            continue
        c = D.c.iloc[i - 11:i].to_numpy()  # 11 closes up to yesterday
        up3 = all(c[-3:] > c[-4:-1])
        dn3 = all(c[-3:] < c[-4:-1])
        ups5 = (c[-5:] > c[-6:-1]).sum()
        sc = 3 if up3 else -3 if dn3 else 0
        sc += 2 if ups5 >= 4 else 1 if ups5 == 3 else -2 if ups5 <= 1 else -1
        pr = D.h.iloc[i - 1] - D.l.iloc[i - 1]
        cp = (D.c.iloc[i - 1] - D.l.iloc[i - 1]) / pr * 100 if pr > 0 else 50
        sc += 2 if cp >= 70 else 1 if cp >= 60 else -2 if cp <= 30 else -1 if cp <= 40 else 0
        gap = (D.o.iloc[i] / D.c.iloc[i - 1] - 1) * 100
        sc += 2 if gap > 0.5 else 1 if gap > 0.1 else -2 if gap < -0.5 else -1 if gap < -0.1 else 0
        k0 = idx[0]
        body, r0 = C[k0] - O[k0], H[k0] - L[k0]
        if r0 > 0:
            sc += (2 if body > 0.6 * r0 else 1 if body > 0 else -2 if body < -0.6 * r0 else -1 if body < 0 else 0)
        ma10 = c[-10:].mean()
        sc += 1 if D.o.iloc[i] > ma10 * 1.01 else -1 if D.o.iloc[i] < ma10 * 0.99 else 0
        if vol_hi.iloc[i] and sc != 0:
            sc += 1 if sc > 0 else -1
        if abs(sc) < 3:
            continue
        side = 1 if sc > 0 else -1
        k = idx[1]
        e = O[k]
        last = idx[hm[idx] <= "15:10"][-1]
        record(rows, f"{market} score>=3", kind, df.index[k], side, e, C[last], r0 or 1, "close")
    return rows


# 14 -----------------------------------------------------------------------------------------
def rsi_turn(df, market, kind, india):
    O, H, L, C, V = arrays(df)
    r = rsi(C, 14)
    a = atr(H, L, C, 14)
    hm = df.index.strftime("%H:%M").to_numpy()
    mk = ind_ok(df, india, 12)
    rows, busy = [], -1
    for k in range(20, len(C) - 1):
        side = -1 if (r[k - 1] >= 70 > r[k]) else 1 if (r[k - 1] <= 30 < r[k]) else 0
        if not side or k <= busy or (india and not ("09:20" <= hm[k] <= "15:00")):
            continue
        e = C[k]
        px, j, how = exit_walk(H, L, C, k, side, e - side * a[k], e + side * 1.5 * a[k], mk(k))
        record(rows, market, kind, df.index[k], side, e, px, a[k], how)
        busy = j
    return rows


def main():
    n1 = prep(pickle.loads((HERE / "cache" / "y1m_IDX_13.pkl").read_bytes()), True)
    b1 = prep(pickle.loads((HERE / "cache" / "y1m_IDX_25.pkl").read_bytes()), True)
    i5 = {n: prep(pickle.loads(open(sorted(glob.glob(str(HERE / "cache" / f"IDX_I_{s}_5_1800_*.pkl")))[-1], "rb").read()), True)
          for n, s in (("NIFTY", 13), ("BANKNIFTY", 25))}
    from bigbars_dhan import load_cache
    _, raw = load_cache()
    raw = {s: prep(d, True) for s, d in raw.items()}
    raw = {s: d[d.index >= d.index.max() - pd.Timedelta(days=365)] for s, d in raw.items()}
    c5 = {"BTC": binance("BTCUSDT", "5m", 730), "ETH": binance("ETHUSDT", "5m", 730),
          "GOLD": binance("PAXGUSDT", "5m", 730)}
    out = []

    def keep(rows, label):
        out.append(stats(rows, label).assign(test=label))

    keep(sum([bb_script(rs(d, "15min", True), f"{n} 15-min (5y)", n, True) for n, d in i5.items()], []) +
         sum([bb_script(rs(d, "15min", True), "F&O stocks 15-min", "STOCK", True) for d in raw.values()], []) +
         sum([bb_script(rs(d, "15min", False), f"{n} 15-min (2y)", n, False) for n, d in c5.items()], []),
         "=== 5. BB By Navneet Solanki (15-min, stop signal low, target 4R)")
    keep(sum([momentum_zone(d, f"{n} 5-min (5y)", n) for n, d in i5.items()], []) +
         sum([momentum_zone(d, "F&O stocks 5-min", "STOCK") for d in raw.values()], []),
         "=== 6. Momentum Zone BO / BD (stop VWAP, 2R, out 15:15)")
    keep(sum([ema_ribbon(d, f"{n} 5-min (5y)", n, True) for n, d in i5.items()], []) +
         sum([ema_ribbon(d, "F&O stocks 5-min", "STOCK", True) for d in raw.values()], []) +
         sum([ema_ribbon(d, f"{n} 5-min (2y)", n, False) for n, d in c5.items()], []),
         "=== 7. EMA Ribbon BOS (swing stop, 2R)")
    times = {"BTC": ["09:15", "13:15", "21:00"], "ETH": ["11:00", "13:00", "21:45"], "GOLD": ["11:15", "13:15", "20:30"]}
    for fade in (False, True):
        keep(sum([box_trades(rs(d, "15min", False), f"{n} 15-min", n, key_candle_boxes(rs(d, "15min", False), times[n]),
                             fade, 4, False) for n, d in c5.items()], []),
             f"=== 8. Key Reaction Candle box {'FADE' if fade else 'breakout'} (2R, 4 h)")
        keep(sum([box_trades(d, f"{n} 5-min", n, zone_boxes(d), fade, 12, True) for n, d in c5.items()], []),
             f"=== 9. 5:30-6:30 IST zone {'FADE' if fade else 'breakout'} (stop mid, 2R, 12 h)")
    keep(sniper930(raw, i5["NIFTY"]), "=== 10. Ultimate 9:30 Sniper 'MONSTER MOVE' buys (stop 9:15-9:30 low, 2R)")
    keep(atomic(n1, "NIFTY 1-min", "NIFTY", True) + atomic(b1, "BANKNIFTY 1-min", "BANKNIFTY", True) +
         sum([atomic(d, f"{n} 5-min (5y)", n, True) for n, d in i5.items()], []) +
         sum([atomic(d, f"{n} 5-min (2y)", n, False) for n, d in c5.items()], []),
         "=== 11. Atomic Swing Scalper (Supertrend 1,1 flips, always in)")
    keep(sum([amd(d, f"{n} 5-min (2y)", n, False) for n, d in c5.items()], []) +
         sum([amd(d, f"{n} 5-min (5y)", n, True) for n, d in i5.items()], []),
         "=== 12. AMD HTF Break + MSS (as coded)")
    keep(sum([first_candle(d, n, n) for n, d in i5.items()], []),
         "=== 13. First Candle + Market Regime bias (trade 9:20 -> 15:10 when |score| >= 3)")
    keep(sum([rsi_turn(d, f"{n} 5-min (5y)", n, True) for n, d in i5.items()], []) +
         sum([rsi_turn(d, f"{n} 5-min (2y)", n, False) for n, d in c5.items()], []),
         "=== 14. Master For All RSI turn (70 / 30, stop 1 ATR, target 1.5 ATR)")
    pd.concat(out).to_csv(HERE / "results" / "my_scripts2.csv", index=False)


if __name__ == "__main__":
    main()
