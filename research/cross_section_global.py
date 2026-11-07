"""Cross-sectional scan for crypto, commodities and forex (24-hour markets), 2 years of 1-hour candles (Yahoo).
Rank every instrument of a class against the others at fixed UTC hours; grid fixed in advance:
  rank hour   00 (crypto only), 08 (London), 13 (New York), 16 UTC
  measure     move since 00:00 UTC, move over the last 4 hours, move over the last 24 hours
  hold        4 hours, 8 hours
  leg         short bottom k, long top k, spread (long top k + short bottom k), reversal (long bottom k + short top k)
  k           crypto 5, commodities 3, forex 3
Costs a round trip per instrument: crypto 0.10%, commodities 0.03%, forex 0.01%. Gross and net.
Train = first year, test = second year; a rule counts only if net > 0 in both, with t >= 1.5 in train.

Usage: python research/cross_section_global.py <scratchpad dir>
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

CLASSES = {
    "Crypto": (["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "TRX", "LTC", "BCH", "NEAR",
                "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARB", "OP", "INJ", "HBAR", "VET", "ICP", "AAVE", "ALGO",
                "SAND", "MANA"], "-USD", 0.10, 5),
    "Commodities": (["GC=F", "SI=F", "PL=F", "PA=F", "HG=F", "CL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "ZC=F", "ZW=F",
                     "ZS=F", "KC=F", "SB=F", "CC=F"], "", 0.03, 3),
    "Forex": (["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "NZDUSD=X", "USDCAD=X", "USDCHF=X", "EURJPY=X",
               "GBPJPY=X", "USDINR=X"], "", 0.01, 3),
}


def load(cls, S: Path) -> pd.DataFrame:
    f = S / f"xs_{cls}.pkl"
    if f.exists():
        return pd.read_pickle(f)
    names, suf, _, _ = CLASSES[cls]
    tick = [n + suf for n in names]
    closes = {}
    for i in range(0, len(tick), 10):
        for k in range(3):
            try:
                d = yf.download(tick[i:i + 10], period="730d", interval="1h", group_by="ticker", progress=False,
                                auto_adjust=False, threads=True)
                break
            except Exception as e:
                print(e)
                time.sleep(5)
        for t in tick[i:i + 10]:
            try:
                c = d[t]["Close"].dropna()
                if len(c) > 2000:
                    idx = pd.DatetimeIndex(c.index)
                    c.index = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
                    closes[t] = c[~c.index.duplicated()]
            except Exception:
                pass
        time.sleep(1)
    P = pd.DataFrame(closes).sort_index()
    P.to_pickle(f)
    return P


def rule(P: pd.DataFrame, cls: str, hour: int, meas: str, hold: int, leg: str) -> pd.Series:
    _, _, cost, k = CLASSES[cls]
    out = {}
    times = P.index[(P.index.hour == hour) & (P.index.minute == 0)]
    if cls != "Crypto":
        times = times[times.dayofweek < 5]
    for t in times:
        if meas == "since 00 UTC":
            base = t.normalize()
        elif meas == "last 4h":
            base = t - pd.Timedelta(hours=4)
        else:
            base = t - pd.Timedelta(hours=24)
        end = t + pd.Timedelta(hours=hold)
        if base not in P.index or end not in P.index:
            continue
        a, b, e = P.loc[base], P.loc[t], P.loc[end]
        ok = a.notna() & b.notna() & e.notna()
        if ok.sum() < 2 * k + 2:
            continue
        mv = (b[ok] / a[ok] - 1) * 100
        fwd = (e[ok] / b[ok] - 1) * 100
        srt = mv.sort_values()
        bot, top = fwd[srt.index[:k]].mean(), fwd[srt.index[-k:]].mean()
        if leg == "short bottom":
            r = -bot - cost
        elif leg == "long top":
            r = top - cost
        elif leg == "spread (long top, short bottom)":
            r = (top - bot) / 2 - cost
        else:
            r = (bot - top) / 2 - cost
        out[t] = r
    return pd.Series(out).sort_index()


def summ(x):
    if len(x) < 10:
        return {"n": len(x)}
    pf = x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else np.inf
    return {"n": len(x), "avg": round(x.mean(), 3), "t": round(x.mean() / x.std() * np.sqrt(len(x)), 2),
            "win%": round((x > 0).mean() * 100), "PF": round(pf, 2)}


def main(argv):
    S = Path(argv[1])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    for cls in CLASSES:
        P = load(cls, S)
        print(f"\n===== {cls}: {P.shape[1]} instruments, {P.index.min().date()} .. {P.index.max().date()} =====", flush=True)
        if P.shape[1] < 2 * CLASSES[cls][3] + 2:
            print("too few instruments")
            continue
        split = P.index.min() + (P.index.max() - P.index.min()) / 2
        rows = []
        hours = [0, 8, 13, 16] if cls == "Crypto" else [8, 13, 16]
        for h in hours:
            for meas in ("since 00 UTC", "last 4h", "last 24h"):
                for hold in (4, 8):
                    for leg in ("short bottom", "long top", "spread (long top, short bottom)", "reversal (long bottom, short top)"):
                        x = rule(P, cls, h, meas, hold, leg)
                        if len(x) < 20:
                            continue
                        tr, te = x[x.index < split], x[x.index >= split]
                        cost = CLASSES[cls][2]
                        rows.append({"rule": f"{h:02d}:00 {meas} hold {hold}h {leg}",
                                     "gross %": round(x.mean() + cost, 3),
                                     **{f"train {a}": b for a, b in summ(tr).items() if a in ("avg", "t", "win%")},
                                     **{f"test {a}": b for a, b in summ(te).items() if a in ("avg", "t", "win%", "PF")}})
        r = pd.DataFrame(rows)
        r.to_csv(S / f"xs_global_{cls}.csv", index=False)
        ok = r[(r["train avg"] > 0) & (r["test avg"] > 0) & (r["train t"] >= 1.5)]
        print(f"{len(r)} rules; HOLD in both years (net > 0 both, train t >= 1.5): {len(ok)}")
        if len(ok):
            print(ok.sort_values("test t", ascending=False).to_string(index=False))
        print("best 8 by gross (no costs), for reference:")
        print(r.sort_values("gross %", ascending=False).head(8).to_string(index=False))
        r["leg"] = r["rule"].str.extract(r"h (short bottom|long top|spread.*|reversal.*)$")[0]
        print("average gross by leg:", r.groupby("leg")["gross %"].mean().round(3).to_dict())


if __name__ == "__main__":
    main(sys.argv)
