"""Explosion study: what is visible BEFORE a quick momentum burst? For every candle close, label whether a long (short)
entered at the next candle's open reaches +T before -T within 30 minutes (T: Nifty 30, Bank Nifty 70, BTC 450, gold
$6.5). Then the share of 'wins' under conditions known at that close, on the FIRST half of the data; the best single
conditions and pairs (chosen on the first half) are then checked on the SECOND half. Break-even after costs at 1:1:
win% > 50 + 50 x cost / T.

Conditions (each split into fixed buckets):
  coil        last 6 candles' range / its 20-day usual (low = coiled)
  vol         this candle's volume / its usual for the time of day (indices: the weighted volume of their stocks)
  at_extreme  close within 0.1 ATR of the day's high (long side) / low (short side) - or breaking it now
  body        this candle's body in ATR, signed with the trade
  run         number of consecutive candles closing the trade's way
  vwap        close above (long) / below (short) the day's VWAP
  tod         time of day (hour)
  breadth     India: change in the weighted % of stocks up over the last 3 candles, with the trade
  heavy       India: top-5 heavyweights' last-15-min move minus the index's, with the trade

Usage: python research/explosion_study.py <scratchpad dir>
"""
import itertools
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import indices as IX     # noqa: E402

OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


def prep(df, to_ist=False):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
        if to_ist:
            idx = idx + pd.Timedelta(hours=5, minutes=30)
    d.index = idx
    d = d[d.index.second == 0]
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def labels(d, T, H, india):
    o, h, l = d["Open"].to_numpy(), d["High"].to_numpy(), d["Low"].to_numpy()
    day = d.index.normalize().to_numpy()
    n = len(d)
    L = np.full(n, np.nan)
    S = np.full(n, np.nan)
    for i in range(n - 1):
        if day[i + 1] != day[i] and india:
            continue
        e = o[i + 1]
        up, dn = e + T, e - T
        lw = sw = None
        for j in range(i + 1, min(n, i + 1 + H)):
            if india and day[j] != day[i + 1]:
                break
            hi, lo = h[j], l[j]
            if lw is None:
                if lo <= dn:
                    lw = 0
                elif hi >= up:
                    lw = 1
            if sw is None:
                if hi >= up:
                    sw = 0
                elif lo <= dn:
                    sw = 1
            if lw is not None and sw is not None:
                break
        L[i] = 0 if lw is None else lw                         # neither reached = not a win
        S[i] = 0 if sw is None else sw
    return L, S


def features(d, stocks=None, weights=None):
    c, h, l, o = d["Close"], d["High"], d["Low"], d["Open"]
    day = d.index.normalize()
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    r6 = h.rolling(6).max() - l.rolling(6).min()
    slot = d.index.strftime("%H:%M")
    piv = pd.DataFrame({"r6": r6.values, "day": day, "slot": slot}).pivot_table(index="day", columns="slot", values="r6")
    us = piv.rolling(20, min_periods=8).mean().shift(1).stack()
    usual = us.reindex(pd.MultiIndex.from_arrays([day, slot])).to_numpy()
    F = pd.DataFrame(index=d.index)
    F["coil"] = r6.to_numpy() / usual
    if stocks is not None:
        vol = None
        for s, w in weights.items():
            b = stocks.get(s)
            if b is None:
                continue
            v = b["Volume"].reindex(d.index).fillna(0) * w
            vol = v if vol is None else vol + v
        v = vol
    else:
        v = d["Volume"].fillna(0)
    pv = pd.DataFrame({"v": v.values, "day": day, "slot": slot}).pivot_table(index="day", columns="slot", values="v")
    uv = pv.rolling(20, min_periods=8).mean().shift(1).stack().reindex(pd.MultiIndex.from_arrays([day, slot])).to_numpy()
    F["vol"] = v.to_numpy() / np.where(uv > 0, uv, np.nan)
    dh, dl = h.groupby(day).cummax(), l.groupby(day).cummin()
    F["near_hi"] = ((dh - c) / atr).to_numpy()
    F["near_lo"] = ((c - dl) / atr).to_numpy()
    F["brk_hi"] = (h >= dh.groupby(day).shift().fillna(np.inf)).to_numpy()
    F["brk_lo"] = (l <= dl.groupby(day).shift().fillna(-np.inf)).to_numpy()
    F["body"] = ((c - o) / atr).to_numpy()
    up = (c > pc).astype(int)
    dn = (c < pc).astype(int)
    F["run_up"] = up.groupby((up == 0).cumsum()).cumsum().to_numpy()
    F["run_dn"] = dn.groupby((dn == 0).cumsum()).cumsum().to_numpy()
    tp = (h + l + c) / 3
    vv = d["Volume"].fillna(0)
    vw = (tp * vv).groupby(day).cumsum() / vv.groupby(day).cumsum().replace(0, np.nan)
    vw = vw.fillna(tp.groupby(day).cumsum() / (d.groupby(day).cumcount() + 1))
    F["above_vwap"] = (c > vw).to_numpy()
    F["hour"] = d.index.hour
    if stocks is not None:
        upw = dnw = None
        tot = 0.0
        for s, w in weights.items():
            b = stocks.get(s)
            if b is None:
                continue
            b = b.reindex(d.index)
            op = b["Open"].groupby(day).transform("first")
            u, dd = (b["Close"] > op).astype(float) * w, (b["Close"] < op).astype(float) * w
            upw = u if upw is None else upw + u
            dnw = dd if dnw is None else dnw + dd
            tot += w
        net = (upw - dnw) / tot * 100
        F["breadth_chg"] = (net - net.shift(3)).to_numpy()
        top = sorted(weights.items(), key=lambda kv: -kv[1])[:5]
        hv = sum(((stocks[s]["Close"].reindex(d.index) / stocks[s]["Close"].reindex(d.index).shift(3) - 1) * 100 * w)
                 for s, w in top if s in stocks) / sum(w for s, w in top if s in stocks)
        F["heavy_lead"] = (hv - (c / c.shift(3) - 1) * 100).to_numpy()
    return F


def conditions(F, side):
    """{name: boolean array} for one trade side (+1 long, -1 short)."""
    s = side
    C = {}
    for a, b in ((0, 0.6), (0.6, 0.9), (0.9, 1.3), (1.3, 99)):
        C[f"coil {a}-{b}"] = (F["coil"] >= a) & (F["coil"] < b)
    for a, b in ((0, 0.7), (0.7, 1.5), (1.5, 3), (3, 999)):
        C[f"vol {a}-{b}x"] = (F["vol"] >= a) & (F["vol"] < b)
    near = F["near_hi"] if s > 0 else F["near_lo"]
    C["at day extreme (<0.1 ATR)"] = near <= 0.1
    C["breaking day extreme now"] = F["brk_hi"] if s > 0 else F["brk_lo"]
    bd = F["body"] * s
    for a, b in ((-99, -0.5), (-0.5, 0), (0, 0.5), (0.5, 1.0), (1.0, 99)):
        C[f"body {a}..{b} ATR (trade side)"] = (bd >= a) & (bd < b)
    run = F["run_up"] if s > 0 else F["run_dn"]
    for k in (0, 1, 2, 3):
        C[f"run {k}"] = run == k
    C["run >= 4"] = run >= 4
    C["VWAP side"] = F["above_vwap"] if s > 0 else ~F["above_vwap"]
    C["against VWAP"] = ~F["above_vwap"] if s > 0 else F["above_vwap"]
    for hr in sorted(F["hour"].unique()):
        C[f"hour {hr:02d}"] = F["hour"] == hr
    if "breadth_chg" in F:
        bc = F["breadth_chg"] * s
        C["breadth speeding with (>5)"] = bc > 5
        C["breadth against (<-5)"] = bc < -5
        hl = F["heavy_lead"] * s
        C["heavyweights lead with (>0.05%)"] = hl > 0.05
        C["heavyweights lead against"] = hl < -0.05
    return {k: np.asarray(v.fillna(False) if hasattr(v, "fillna") else v, dtype=bool) for k, v in C.items()}


def study(name, d, T, cost, H, india, stocks=None, weights=None):
    if india:
        d = d[(d.index.strftime("%H:%M") >= "09:15") & (d.index.strftime("%H:%M") < "15:30")]
    L, Sh = labels(d, T, H, india)
    F = features(d, stocks, weights)
    ok_t = np.ones(len(d), bool)
    if india:
        hm = d.index.strftime("%H:%M")
        ok_t = (hm >= "09:30") & (hm <= "14:45")
    days = np.array(sorted(set(d.index.normalize())))
    split = days[len(days) // 2]
    tr = (d.index < split) & ok_t
    te = (d.index >= split) & ok_t
    be = 50 + 50 * cost / T
    say(f"\n=== {name}: target / stop {T} pts, 30 min | break-even win {be:.1f}% | {len(days)} days ===")
    for side, lab in ((1, L), (-1, Sh)):
        sname = "LONG" if side > 0 else "SHORT"
        valid = ~np.isnan(lab)
        base_tr = np.nanmean(lab[tr & valid]) * 100
        base_te = np.nanmean(lab[te & valid]) * 100
        say(f"{sname}: base win rate (any candle) train {base_tr:.1f}% / test {base_te:.1f}%")
        C = conditions(F, side)
        single = []
        for k, m in C.items():
            a, b = tr & valid & m, te & valid & m
            if a.sum() < 40 or b.sum() < 20:
                continue
            single.append((k, lab[a].mean() * 100, int(a.sum()), lab[b].mean() * 100, int(b.sum())))
        single.sort(key=lambda x: -x[1])
        say("  best single conditions (picked on train):")
        for k, w1, n1, w2, n2 in single[:6]:
            say(f"    {k:36s} train {w1:5.1f}% (n {n1:5d}) | test {w2:5.1f}% (n {n2:5d})" + ("  <== above break-even in BOTH" if w1 > be and w2 > be else ""))
        top = [x[0] for x in single[:10]]
        pairs = []
        for a_, b_ in itertools.combinations(top, 2):
            if a_.split()[0] == b_.split()[0]:
                continue
            m = C[a_] & C[b_]
            a, b = tr & valid & m, te & valid & m
            if a.sum() < 30 or b.sum() < 15:
                continue
            pairs.append((f"{a_} + {b_}", lab[a].mean() * 100, int(a.sum()), lab[b].mean() * 100, int(b.sum())))
        pairs.sort(key=lambda x: -x[1])
        say("  best PAIRS (picked on train):")
        for k, w1, n1, w2, n2 in pairs[:5]:
            exp = (w2 / 100 * T - (1 - w2 / 100) * T - cost)
            say(f"    {k:70s} train {w1:5.1f}% (n {n1:4d}) | test {w2:5.1f}% (n {n2:4d}) | test net {exp:+.1f} pts/trade"
                + ("  <== HOLDS" if w1 > be and w2 > be else ""))


def main(argv):
    S = Path(argv[1])
    idx5 = pd.read_pickle(S / "yahoo_idx5m.pkl")
    st, _ = pickle.load(open(S / "fno60_new.pkl", "rb"))
    stocks = {s: prep(df) for s, df in st.items() if df is not None and len(df)}
    W = {k: d.get("w", {}) for k, d in IX.load().items()}
    study("Nifty 5m (60 d)", prep(idx5["NIFTY"]), 30, 3, 6, True, stocks, W["NIFTY"])
    study("Bank Nifty 5m (60 d)", prep(idx5["BANKNIFTY"]), 70, 6, 6, True, stocks, W["BANKNIFTY"])
    btc = prep(pd.read_pickle(S / "btc5m.pkl"), to_ist=True)
    gold = prep(pd.read_pickle(S / "paxg5m.pkl"), to_ist=True)
    gold = gold[gold.index.dayofweek < 5]
    study("BTC 5m (3.5 y, IST hours)", btc, 450, 0.0005 * float(btc["Close"].median()), 6, False)
    study("Gold 5m (3.5 y, IST hours)", gold, 6.5, 0.5, 6, False)
    (S / "explosion_study.txt").write_text("\n".join(OUT))


if __name__ == "__main__":
    main(sys.argv)
