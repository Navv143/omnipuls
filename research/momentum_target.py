"""Small fixed-target momentum trades: enter on momentum, take a fixed target, or get stopped, or leave after a set time.

The user's targets: Nifty 25-30 pts, Bank Nifty 45-50 pts, F&O stocks 2-3%, gold 8-10 $, BTC 400-500 $, ETH 15-20 $.
Prices have moved a lot over the years, so each target is turned into a % of today's price (e.g. 27.5 Nifty points
is 0.11% of Nifty now) and that % is used over the whole history.

Data: 5-minute bars. Nifty, Bank Nifty and 52 F&O stocks (every 4th of 206) from the Dhan cache (Nov 2021 - Oct 2026); BTC, ETH and
gold (PAXG, a gold-backed token that tracks XAU; real XAU 5-minute history is not free) from Binance, last 2 years.

Momentum entries (decided at a candle's close, entered at the next candle's open):
  breakout : close above the high of the last 6 candles (30 min), or below the low -> short
  burst    : candle range >= 2x the last 20 candles' average, closing in its top (bottom) quarter
  trend3   : 3 candles in a row closing the same way, all above (below) the 20-candle average
Baseline: the same trade (same target, stop and time) taken at EVERY candle in both directions. A momentum entry is
only worth anything if it hits the target more often than this "any time" trade.

Each trade: target T, stop S (tried at 1x, 0.75x and 0.5x the target), time exit after 30 / 60 / 120 minutes, and
for Indian markets no entries after 14:30 and everything out by 15:15. If target and stop are both inside one
candle the stop is assumed first (conservative). One trade at a time per market. Costs per round trip: Nifty 2 pts,
Bank Nifty 5 pts (futures slippage + charges), stocks 0.06%, crypto and gold 0.10%.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\momentum_target.py
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import truststore

truststore.inject_into_ssl()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
CACHE = HERE / "cache"

# name: (target low, target high, unit) - unit "pts" = price points, "pct" = %
TARGETS = {"NIFTY": (25, 30, "pts"), "BANKNIFTY": (45, 50, "pts"), "STOCKS": (2, 3, "pct"),
           "GOLD": (8, 10, "pts"), "BTC": (400, 500, "pts"), "ETH": (15, 20, "pts")}
COST = {"NIFTY": ("pts", 2), "BANKNIFTY": ("pts", 5), "STOCKS": ("pct", 0.06), "GOLD": ("pct", 0.10),
        "BTC": ("pct", 0.10), "ETH": ("pct", 0.10)}
STOPS = (1.0, 0.75, 0.5)
HOLDS = (30, 60, 120)  # minutes


def binance_5m(symbol: str, days: int = 730) -> pd.DataFrame:
    f = CACHE / f"binance_{symbol}_5m_{days}.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        return pickle.loads(f.read_bytes())
    start = int((time.time() - days * 86400) * 1000)
    rows = []
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": symbol, "interval": "5m", "startTime": start, "limit": 1000}, timeout=30)
        r.raise_for_status()
        k = r.json()
        if not k:
            break
        rows += k
        start = k[-1][0] + 300000
        if len(k) < 1000:
            break
        time.sleep(0.15)
    df = pd.DataFrame([[float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in rows],
                      columns=["Open", "High", "Low", "Close", "Volume"],
                      index=pd.to_datetime([x[0] for x in rows], unit="ms"))
    df = df[~df.index.duplicated()].sort_index()
    f.write_bytes(pickle.dumps(df))
    return df


def signals(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """+1 long, -1 short, 0 none, decided at each candle's close."""
    O, H, L, C = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
    hi6 = pd.Series(H).shift(1).rolling(6).max().to_numpy()
    lo6 = pd.Series(L).shift(1).rolling(6).min().to_numpy()
    brk = np.where(C > hi6, 1, np.where(C < lo6, -1, 0))
    rng = H - L
    avg = pd.Series(rng).shift(1).rolling(20).mean().to_numpy()
    pos = np.where(rng > 0, (C - L) / np.where(rng > 0, rng, 1), 0.5)
    big = rng >= 2 * avg
    burst = np.where(big & (pos >= 0.75), 1, np.where(big & (pos <= 0.25), -1, 0))
    up, dn = C > O, C < O
    ma = pd.Series(C).rolling(20).mean().to_numpy()
    u3 = up & np.roll(up, 1) & np.roll(up, 2) & (C > ma) & (np.roll(C, 1) > np.roll(ma, 1)) & (np.roll(C, 2) > np.roll(ma, 2))
    d3 = dn & np.roll(dn, 1) & np.roll(dn, 2) & (C < ma) & (np.roll(C, 1) < np.roll(ma, 1)) & (np.roll(C, 2) < np.roll(ma, 2))
    tr3 = np.where(u3, 1, np.where(d3, -1, 0))
    tr3[:2] = 0
    return {"breakout": brk, "burst": burst, "trend3": tr3}


def outcomes(df: pd.DataFrame, side: int, tgt: float, stp: float, hold: int, india: bool):
    """For every candle i (entry at i+1 open): result % after costs-free, and how it ended (1 target, -1 stop, 0 time).
    tgt / stp are fractions of the entry price."""
    O, H, L, C = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
    n, N = len(df), hold // 5
    idx = df.index
    # the last bar a trade entered at bar j may use
    if india:
        t = idx.strftime("%H:%M").to_numpy()
        day = idx.normalize().to_numpy()
        ok_entry = (t >= "09:20") & (t <= "14:30")
        # bar index of 15:10 bar (exit at 15:15 open = 15:10 close) per day
        last_of_day = pd.Series(np.where(t <= "15:10", np.arange(n), -1)).groupby(day).transform("max").to_numpy()
    else:
        ok_entry = np.ones(n, bool)
        last_of_day = np.full(n, n - 1)
        gaps = np.diff(idx.values.astype("datetime64[s]").astype(np.int64)) != 300
        ok_entry[:-1] &= ~gaps  # do not enter across a data gap
    e = np.full(n, np.nan)
    e[:-1] = O[1:]
    res = np.full(n, np.nan)
    how = np.zeros(n, int)
    pad = N + 1
    Hp = np.concatenate([H, np.full(pad, np.nan)])
    Lp = np.concatenate([L, np.full(pad, np.nan)])
    Cp = np.concatenate([C, np.full(pad, np.nan)])
    from numpy.lib.stride_tricks import sliding_window_view as sw
    WH = sw(Hp[1:], N)[:n]  # bars i+1 .. i+N
    WL = sw(Lp[1:], N)[:n]
    WC = sw(Cp[1:], N)[:n]
    k = np.arange(N)
    allowed = (np.arange(n)[:, None] + 1 + k[None, :]) <= last_of_day[:, None]
    tp = e * (1 + side * tgt)
    sl = e * (1 - side * stp)
    if side > 0:
        hit_t, hit_s = (WH >= tp[:, None]) & allowed, (WL <= sl[:, None]) & allowed
    else:
        hit_t, hit_s = (WL <= tp[:, None]) & allowed, (WH >= sl[:, None]) & allowed
    BIG = N + 5
    ft = np.where(hit_t.any(1), hit_t.argmax(1), BIG)
    fs = np.where(hit_s.any(1), hit_s.argmax(1), BIG)
    last_k = np.clip(np.where(allowed.any(1), allowed.sum(1) - 1, 0), 0, N - 1)
    close_exit = WC[np.arange(n), last_k]
    stop_first = fs <= ft
    res = np.where((fs < BIG) & stop_first, -stp * 100,
                   np.where(ft < BIG, tgt * 100, side * (close_exit / e - 1) * 100))
    how = np.where((fs < BIG) & stop_first, -1, np.where(ft < BIG, 1, 0))
    bars = np.where((fs < BIG) & stop_first, fs, np.where(ft < BIG, ft, last_k)) + 1
    valid = ok_entry & np.isfinite(e) & allowed[:, 0]
    return res, how, bars, valid


def trade_list(sig, res_l, how_l, bars_l, res_s, how_s, bars_s, valid):
    """One trade at a time: walk through the signals, skip while a trade is open."""
    out, free = [], 0
    for i in np.flatnonzero((sig != 0) & valid):
        if i < free:
            continue
        r, h, b = (res_l[i], how_l[i], bars_l[i]) if sig[i] > 0 else (res_s[i], how_s[i], bars_s[i])
        out.append((i, sig[i], r, h))
        free = i + 1 + b
    return out


def test(name: str, frames: dict[str, pd.DataFrame], tgt_pct: float, india: bool) -> list[dict]:
    unit, c = COST[name]
    rows = []
    for stop_x in STOPS:
        for hold in HOLDS:
            acc = {k: [] for k in ("any time", "breakout", "burst", "trend3")}
            for sym, df in frames.items():
                df = df.dropna()
                if len(df) < 500:
                    continue
                cost_pct = c if unit == "pct" else c / df["Close"].iloc[-1] * 100
                L_ = outcomes(df, 1, tgt_pct / 100, stop_x * tgt_pct / 100, hold, india)
                S_ = outcomes(df, -1, tgt_pct / 100, stop_x * tgt_pct / 100, hold, india)
                v = L_[3]
                acc["any time"].append(pd.DataFrame({"r": np.concatenate([L_[0][v], S_[0][v]]) - cost_pct,
                                                     "how": np.concatenate([L_[1][v], S_[1][v]]),
                                                     "yr": np.concatenate([df.index.year[v]] * 2)}))
                for sname, sig in signals(df).items():
                    tl = trade_list(sig, L_[0], L_[1], L_[2], S_[0], S_[1], S_[2], v)
                    if tl:
                        a = np.array(tl, dtype=float)
                        acc[sname].append(pd.DataFrame({"r": a[:, 2] - cost_pct, "how": a[:, 3],
                                                        "yr": df.index.year[a[:, 0].astype(int)]}))
            for sname, parts in acc.items():
                if not parts:
                    continue
                T = pd.concat(parts)
                yrs = T.groupby("yr")["r"].mean()
                half = len(T) // 2
                rows.append({"market": name, "target %": round(tgt_pct, 3), "stop x": stop_x, "hold min": hold,
                             "entry": sname, "trades": len(T), "target hit %": round(100 * (T["how"] == 1).mean(), 1),
                             "stopped %": round(100 * (T["how"] == -1).mean(), 1),
                             "avg % after cost": round(T["r"].mean(), 4),
                             "1st half": round(T["r"].iloc[:half].mean(), 4),
                             "2nd half": round(T["r"].iloc[half:].mean(), 4),
                             "years +": f"{int((yrs > 0).sum())}/{len(yrs)}"})
    return rows


def main():
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    from bigbars_dhan import load_cache
    import glob
    nifty, raw = load_cache()
    bn = pickle.loads(open(sorted(glob.glob(str(CACHE / "IDX_I_25_5_1800_*.pkl")))[-1], "rb").read())
    naive = lambda d: d.set_axis(d.index.tz_localize(None)) if d.index.tz is not None else d  # noqa: E731
    markets = {"NIFTY": ({"NIFTY": naive(nifty)}, True), "BANKNIFTY": ({"BANKNIFTY": naive(bn)}, True),
               "STOCKS": ({k: naive(raw[k]) for k in sorted(raw)[::4]}, True),  # every 4th stock (52) for speed
               "GOLD": ({"PAXG": binance_5m("PAXGUSDT")}, False), "BTC": ({"BTC": binance_5m("BTCUSDT")}, False),
               "ETH": ({"ETH": binance_5m("ETHUSDT")}, False)}
    rows = []
    only = set(sys.argv[1:])
    for name, (frames, india) in markets.items():
        if only and name not in only:
            continue
        lo, hi, unit = TARGETS[name]
        for t in (lo, hi):
            if unit == "pct":
                pct = t
            else:
                px = next(iter(frames.values()))["Close"].dropna().iloc[-1]
                pct = t / px * 100
            print(f"{name}: target {t} {unit} = {pct:.3f}% ...", flush=True)
            rows += [dict(r, **{"target": f"{t} {unit}"}) for r in test(name, frames, pct, india)]
    R = pd.DataFrame(rows)
    old = HERE / "results" / "momentum_target.csv"
    if only and old.exists():  # keep the other markets' earlier rows
        R = pd.concat([pd.read_csv(old).query("market not in @only").drop(columns=["vs any time"], errors="ignore"), R])
    R.to_csv(HERE / "results" / "momentum_target.csv", index=False)
    base = R[R["entry"] == "any time"].set_index(["market", "target", "stop x", "hold min"])["target hit %"]
    R["vs any time"] = R.apply(lambda r: round(r["target hit %"] - base[(r["market"], r["target"], r["stop x"],
                                                                         r["hold min"])], 1), axis=1)
    R.to_csv(HERE / "results" / "momentum_target.csv", index=False)
    print("\nBest momentum version per market (by average after cost):")
    m = R[R["entry"] != "any time"]
    print(m.sort_values("avg % after cost", ascending=False).groupby("market").head(3).to_string(index=False))
    print("\nHow many momentum versions make money after cost (out of", len(m) // 6, "per market):")
    print(m.groupby("market").apply(lambda g: f"{(g['avg % after cost'] > 0).sum()} positive, "
                                              f"{((g['1st half'] > 0) & (g['2nd half'] > 0)).sum()} in both halves").to_string())


if __name__ == "__main__":
    main()
