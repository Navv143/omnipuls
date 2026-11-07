"""ADX-gated setups: does a momentum regime filter (ADX(14) >= 25 and rising, +DI / -DI agreeing with the trade) turn
setups into winners? Every setup alone and with the ADX gate, same exits for all (entry next candle's open, stop 1.5 ATR,
target 2R, max 24 candles; Indian intraday: entries 9:30-14:30, out 15:15). Costs: index 0.02%, BTC 0.08%, gold /
commodities 0.03%, forex 0.01%. Train / test = halves of the period; a setup passes with >= 50 trades, net > 0 in
both halves and PF > 1.2.

Setups: EMA 9/21 cross; VWAP cross; Bollinger breakout (20/2, 20/1.5, 50/2); Bollinger squeeze breakout (20/2, width
lowest of 50); RSI(14) 50-cross; RSI(2) dip in the DI trend; Donchian 20 breakout; liquidity sweep (20-bar high / low
taken, close back inside -> reverse); order block retest (last opposite candle before a > 1.5 ATR impulse, retested
within 30 candles); BOS (close beyond the last 3/3 swing in the swing trend); CHoCH (first close beyond the last swing
against the swing trend).

Usage: python research/adx_setups.py <scratchpad dir>
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def prep(df, tz):
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d = d.droplevel(1, axis=1)
    idx = pd.DatetimeIndex(d.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    d.index = idx.tz_convert(tz).tz_localize(None)
    d = d[(d.index.second == 0)]
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def wilder(x, n):
    return x.ewm(alpha=1 / n, adjust=False).mean()


def indicators(d, india):
    c, h, l, o = d["Close"], d["High"], d["Low"], d["Open"]
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = wilder(tr, 14)
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pdi = 100 * wilder(pd.Series(pdm, index=d.index), 14) / atr
    mdi = 100 * wilder(pd.Series(mdm, index=d.index), 14) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = wilder(dx.fillna(0), 14)
    day = d.index.normalize()
    tp = (h + l + c) / 3
    v = d["Volume"].fillna(0)
    vw = (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum().replace(0, np.nan)
    vw = vw.fillna(tp.groupby(day).cumsum() / (d.groupby(day).cumcount() + 1))
    e9, e21 = c.ewm(span=9, adjust=False).mean(), c.ewm(span=21, adjust=False).mean()
    ch = c.diff()
    rsi = lambda n: 100 - 100 / (1 + wilder(ch.clip(lower=0), n) / wilder(-ch.clip(upper=0), n).replace(0, np.nan))  # noqa: E731
    r14, r2 = rsi(14), rsi(2)
    S = {}
    S["EMA 9/21 cross"] = np.where((e9 > e21) & (e9.shift() <= e21.shift()), 1, np.where((e9 < e21) & (e9.shift() >= e21.shift()), -1, 0))
    S["VWAP cross"] = np.where((c > vw) & (pc <= vw.shift()), 1, np.where((c < vw) & (pc >= vw.shift()), -1, 0))
    for n, k in ((20, 2.0), (20, 1.5), (50, 2.0)):
        m, sd = c.rolling(n).mean(), c.rolling(n).std()
        ub, lb = m + k * sd, m - k * sd
        S[f"Bollinger {n}/{k} breakout"] = np.where((c > ub) & (pc <= ub.shift()), 1, np.where((c < lb) & (pc >= lb.shift()), -1, 0))
    m, sd = c.rolling(20).mean(), c.rolling(20).std()
    bw = (4 * sd / m)
    sq = bw.shift() <= bw.shift().rolling(50).min() * 1.0001
    S["Bollinger squeeze breakout"] = np.where(sq & (c > m + 2 * sd), 1, np.where(sq & (c < m - 2 * sd), -1, 0))
    S["RSI 50 cross"] = np.where((r14 > 50) & (r14.shift() <= 50), 1, np.where((r14 < 50) & (r14.shift() >= 50), -1, 0))
    S["RSI(2) dip in DI trend"] = np.where((r2 < 10) & (pdi > mdi), 1, np.where((r2 > 90) & (mdi > pdi), -1, 0))
    dh, dl = h.shift().rolling(20).max(), l.shift().rolling(20).min()
    S["Donchian 20 breakout"] = np.where((c > dh) & (pc <= dh.shift()), 1, np.where((c < dl) & (pc >= dl.shift()), -1, 0))
    S["Liquidity sweep (reverse)"] = np.where((h > dh) & (c < dh), -1, np.where((l < dl) & (c > dl), 1, 0))
    # swings (3 left / 3 right), known 3 candles later
    hv, lv = h.to_numpy(), l.to_numpy()
    n_ = len(d)
    sh = np.full(n_, np.nan)
    sl = np.full(n_, np.nan)
    for i in range(3, n_ - 3):
        if hv[i] == hv[i - 3:i + 4].max():
            sh[i + 3] = hv[i]
        if lv[i] == lv[i - 3:i + 4].min():
            sl[i + 3] = lv[i]
    last_sh, last_sl = pd.Series(sh).ffill().to_numpy(), pd.Series(sl).ffill().to_numpy()
    prev_sh = pd.Series(sh).dropna().shift().reindex(range(n_)).ffill().to_numpy()
    prev_sl = pd.Series(sl).dropna().shift().reindex(range(n_)).ffill().to_numpy()
    trend = np.where((last_sh > prev_sh) & (last_sl > prev_sl), 1, np.where((last_sh < prev_sh) & (last_sl < prev_sl), -1, 0))
    cv, pcv = c.to_numpy(), pc.to_numpy()
    bu = (cv > last_sh) & (pcv <= last_sh)
    bd = (cv < last_sl) & (pcv >= last_sl)
    S["BOS (continuation)"] = np.where(bu & (trend > 0), 1, np.where(bd & (trend < 0), -1, 0))
    S["CHoCH (reversal)"] = np.where(bu & (trend < 0), 1, np.where(bd & (trend > 0), -1, 0))
    # order block retest
    ov, a_ = o.to_numpy(), atr.to_numpy()
    ob = np.zeros(n_)
    zones = []
    for i in range(1, n_):
        if np.isfinite(a_[i]) and abs(cv[i] - ov[i]) > 1.5 * a_[i]:
            sd_ = 1 if cv[i] > ov[i] else -1
            for j in range(i - 1, max(i - 4, 0), -1):
                if (cv[j] < ov[j]) == (sd_ > 0):
                    zones.append([sd_, lv[j], hv[j], i, False])
                    break
        for z in zones:
            if z[4] or i <= z[3] or i - z[3] > 30:
                continue
            if z[0] > 0 and lv[i] <= z[2] and cv[i] > z[1]:
                ob[i], z[4] = 1, True
            elif z[0] < 0 and hv[i] >= z[1] and cv[i] < z[2]:
                ob[i], z[4] = -1, True
        zones = [z for z in zones if not z[4] and i - z[3] <= 30]
    S["Order block retest"] = ob
    gate_up = (adx >= 25) & (adx > adx.shift(3)) & (pdi > mdi)
    gate_dn = (adx >= 25) & (adx > adx.shift(3)) & (mdi > pdi)
    return S, atr.to_numpy(), gate_up.to_numpy(), gate_dn.to_numpy()


def simulate(d, sig, atr, gu, gd, gated, cost, india, tf_min):
    o, h, l, c = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx = d.index
    hm = (idx + pd.Timedelta(minutes=tf_min)).strftime("%H:%M") if india else None
    day = idx.normalize()
    out, i, n = [], 50, len(d)
    while i < n - 1:
        s = int(sig[i])
        if not s or not np.isfinite(atr[i]) or atr[i] <= 0:
            i += 1
            continue
        if gated and not (gu[i] if s > 0 else gd[i]):
            i += 1
            continue
        if india and not ("09:30" <= hm[i] <= "14:30"):
            i += 1
            continue
        e = o[i + 1]
        stop = e - s * 1.5 * atr[i]
        tg = e + s * 3.0 * atr[i]
        x, j = None, i + 1
        while j < n and j <= i + 24:
            if india and (day[j] != day[i + 1] or hm[j] > "15:15"):
                x = o[j] if day[j] == day[i + 1] else c[j - 1]
                break
            if (l[j] <= stop) if s > 0 else (h[j] >= stop):
                x = min(o[j], stop) if s > 0 else max(o[j], stop)
                break
            if (h[j] >= tg) if s > 0 else (l[j] <= tg):
                x = max(o[j], tg) if s > 0 else min(o[j], tg)
                break
            j += 1
        if x is None:
            x, j = c[min(j, n - 1)], min(j, n - 1)
        risk = 1.5 * atr[i]
        out.append((idx[i], s * (x - e) / risk - cost / (risk / e * 100)))
        i = max(j, i + 1)
    return out


def stats(x: pd.Series):
    if len(x) < 10:
        return {"n": len(x)}
    mid = x.index[len(x) // 2]
    tr, te = x[x.index < mid], x[x.index >= mid]
    pf = x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else np.inf
    return {"n": len(x), "win%": round((x > 0).mean() * 100), "PF": round(pf, 2), "avg R": round(x.mean(), 3),
            "t": round(x.mean() / x.std() * np.sqrt(len(x)), 2), "h1": round(tr.mean(), 3), "h2": round(te.mean(), 3),
            "pass": bool(len(x) >= 50 and tr.mean() > 0 and te.mean() > 0 and pf > 1.2)}


def main(argv):
    S = Path(argv[1])
    idx5 = pd.read_pickle(S / "yahoo_idx5m.pkl")
    y1h = pd.read_pickle(S / "yahoo1h.pkl")
    pdd = pd.read_pickle(S / "pdf_data.pkl")
    btc = pd.read_pickle(S / "btc5m.pkl").resample("15min").agg(AGG).dropna(subset=["Close"])
    gold = pd.read_pickle(S / "paxg5m.pkl").resample("15min").agg(AGG).dropna(subset=["Close"])
    markets = [
        ("Nifty 5m (60d)", prep(idx5["NIFTY"], "Asia/Kolkata"), 0.02, True, 5, "India"),
        ("Bank Nifty 5m (60d)", prep(idx5["BANKNIFTY"], "Asia/Kolkata"), 0.02, True, 5, "India"),
        ("Nifty 1h (3y)", prep(y1h["NIFTY"], "Asia/Kolkata"), 0.02, True, 60, "India"),
        ("Bank Nifty 1h (3y)", prep(y1h["BANKNIFTY"], "Asia/Kolkata"), 0.02, True, 60, "India"),
        ("BTC 15m (3.5y)", prep(btc, "UTC"), 0.08, False, 15, "Crypto & gold"),
        ("Gold 15m (3.5y)", prep(gold, "UTC"), 0.03, False, 15, "Crypto & gold"),
        ("Crude 1h (2y)", prep(pdd[("CRUDE", "1h")], "UTC"), 0.03, False, 60, "Commodities & FX"),
        ("Natural gas 1h (2y)", prep(pdd[("NATGAS", "1h")], "UTC"), 0.03, False, 60, "Commodities & FX"),
        ("Silver 1h (2y)", prep(pdd[("SILVER", "1h")], "UTC"), 0.03, False, 60, "Commodities & FX"),
        ("EUR/USD 1h (2y)", prep(pdd[("EURUSD", "1h")], "UTC"), 0.01, False, 60, "Commodities & FX"),
    ]
    rows, pooled = [], {}
    for name, d, cost, india, tf, grp in markets:
        if india:
            d = d[(d.index.strftime("%H:%M") >= "09:15") & (d.index.strftime("%H:%M") < "15:30")]
        sig, atr, gu, gd = indicators(d, india)
        for k, s in sig.items():
            for gated in (False, True):
                tr = simulate(d, s, atr, gu, gd, gated, cost, india, tf)
                x = pd.Series([r for _, r in tr], index=[t for t, _ in tr], dtype=float)
                tag = "with ADX gate" if gated else "alone"
                rows.append({"market": name, "setup": k, "filter": tag, **stats(x)})
                pooled.setdefault((grp, k, tag), []).append(x)
        print(f"{name} done", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(S / "adx_setups.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    print("\nDOES THE ADX GATE HELP? average R per trade (after costs), pooled by group:")
    piv = []
    for (grp, k, tag), xs in pooled.items():
        x = pd.concat(xs)
        piv.append({"group": grp, "setup": k, "filter": tag, "n": len(x), "avg R": round(x.mean(), 3),
                    "PF": round(x[x > 0].sum() / -x[x < 0].sum(), 2) if (x < 0).any() else np.inf})
    P = pd.DataFrame(piv)
    w = P.pivot_table(index=["group", "setup"], columns="filter", values="avg R").reset_index()
    w["ADX helps by"] = (w["with ADX gate"] - w["alone"]).round(3)
    print(w.sort_values(["group", "with ADX gate"], ascending=[True, False]).to_string(index=False))
    print(f"\nADX gate improved {int((w['ADX helps by'] > 0).sum())} of {len(w)} setup x group cells; "
          f"positive after costs with the gate: {int((w['with ADX gate'] > 0).sum())}")
    print("\nPASSING (>= 50 trades, both halves > 0, PF > 1.2), per market:")
    print(res[res["pass"] == True].sort_values("avg R", ascending=False).to_string(index=False))  # noqa: E712
    print(f"\n(for scale: {len(res)} market x setup x filter combinations tested)")


if __name__ == "__main__":
    main(sys.argv)
