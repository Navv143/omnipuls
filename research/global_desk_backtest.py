"""Global Intraday Desk (desk_intraday.py) replayed on past candles: ATLAS, VEGA, LUNA, TITAN and NOVA at every
15-minute close, exactly as live (closed candles only, the session at that time, max 4 open / 1 per class, correlation).
ORION has no news history offline (neutral); crypto Fear & Greed uses the previous day's value. Trades enter at the
next candle's open; stop first, then target; out after 8 hours (non-crypto: at 21:00 UTC). Costs a round trip:
crypto 0.08%, forex 0.01%, commodities 0.03%.

Usage: python research/global_desk_backtest.py <pdf_data.pkl> [--long]
  default: every market, last 60 days of 15-min candles (Yahoo)
  --long : BTC and gold (PAXG) 2023-2026 (5-min resampled), dollar index from Yahoo 1h where available
"""
import sys
import time
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import desk_agents as DA     # noqa: E402
import desk_intraday as DI   # noqa: E402

COST = {"Crypto": 0.08, "Forex": 0.01, "Gold & metals": 0.03, "Energy": 0.03}
MAP = {"GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F", "CRUDE": "CL=F", "NATGAS": "NG=F", "EURUSD": "EURUSD=X",
       "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X", "USDINR": "USDINR=X"}
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def yget(t, tf, period):
    for k in range(3):
        d = yf.download(t, interval=tf, period=period, progress=False, auto_adjust=False)
        if len(d):
            return d.droplevel(1, axis=1) if isinstance(d.columns, pd.MultiIndex) else d
        time.sleep(3)
    return None


def fng_history() -> pd.Series:
    try:
        js = requests.get("https://api.alternative.me/fng/?limit=0", timeout=20).json()["data"]
        s = pd.Series({pd.Timestamp(int(x["timestamp"]), unit="s").normalize(): int(x["value"]) for x in js}).sort_index()
        return s.shift(1).dropna()          # yesterday's value: known at any time today
    except Exception as e:
        print("fear & greed history:", e)
        return pd.Series(dtype=float)


def replay(m15: dict, h1: dict, fng: pd.Series, start=None) -> pd.DataFrame:
    m15 = {s: DA._clean(d) for s, d in m15.items() if d is not None and len(d)}
    h1 = {s: DA._clean(d) for s, d in h1.items() if d is not None and len(d)}
    syms = [s for s in m15 if s in DI.CLASS_OF]
    idx15 = {s: m15[s].index.to_numpy() for s in m15}
    idx1 = {s: (h1[s].index + pd.Timedelta(hours=1)).to_numpy() for s in h1}
    grid = sorted(set().union(*[set(m15[s].index + pd.Timedelta(minutes=15)) for s in syms]))
    if start is not None:
        grid = [g for g in grid if g >= start]
    open_tr, done = [], []
    t0 = time.time()
    for gi, T in enumerate(grid):
        Tn = np.datetime64(T)
        cut15, cut1 = {}, {}
        for s in set(syms) | {"DX-Y.NYB", "BTC-USD"}:
            if s in m15:
                p = np.searchsorted(idx15[s], Tn - np.timedelta64(15, "m"), side="right")
                cut15[s] = m15[s].iloc[max(0, p - 1100):p]
            if s in h1:
                p = np.searchsorted(idx1[s], Tn, side="right")
                cut1[s] = h1[s].iloc[max(0, p - 700):p]
        # manage open trades on the candle that just closed
        for tr in list(open_tr):
            d = cut15.get(tr["symbol"])
            if d is None or d.empty or d.index[-1] < tr["entry_ts"]:
                continue
            b = d.iloc[-1]
            if d.index[-1] == tr.get("last"):
                continue
            tr["last"] = d.index[-1]
            s_ = tr["side"]
            x = why = None
            if d.index[-1] >= tr["end"]:
                x, why = float(b["Open"]), "time-out"
            elif (b["Low"] <= tr["stop"]) if s_ > 0 else (b["High"] >= tr["stop"]):
                x, why = (min(float(b["Open"]), tr["stop"]) if s_ > 0 else max(float(b["Open"]), tr["stop"])), "loss"
            elif (b["High"] >= tr["target"]) if s_ > 0 else (b["Low"] <= tr["target"]):
                x, why = tr["target"], "win"
            if x is not None:
                risk = abs(tr["entry"] - tr["stop0"])
                tr.update(exit=x, result=why, r=s_ * (x - tr["entry"]) / risk - COST[tr["class"]] / (risk / tr["entry"] * 100),
                          pct=s_ * (x / tr["entry"] - 1) * 100 - COST[tr["class"]])
                done.append(tr)
                open_tr.remove(tr)
        a = DI.atlas(cut15, cut1, T.to_pydatetime().replace(tzinfo=timezone.utc))
        now = T.to_pydatetime().replace(tzinfo=timezone.utc)
        fv = fng.asof(T.normalize()) if len(fng) else None
        fg = {"value": int(fv), "label": ""} if fv is not None and np.isfinite(fv) else None
        cands = []
        for s in syms:
            d = cut15.get(s)
            if d is None or len(d) < 80 or d.index[-1] + pd.Timedelta(minutes=15) != T:
                continue                         # only markets with a candle closing now
            v = DI.vega(s, d, cut1.get(s), now)
            if v and v["side"]:
                cands.append(v)
        if not cands:
            continue
        approved = [{"symbol": t["symbol"], "class": t["class"]} for t in open_tr]
        rets = pd.DataFrame({s: cut15[s]["Close"].pct_change().tail(192).reset_index(drop=True)
                             for s in {v["symbol"] for v in cands} | {t["symbol"] for t in open_tr} if s in cut15})
        for v in sorted(cands, key=lambda x: -abs(x["score"])):
            if any(t["symbol"] == v["symbol"] for t in open_tr):
                continue
            lun = DI.luna(v, cut15[v["symbol"]], fg)
            tit = DI.titan(v, a, 1_000_000, 0.5, approved, rets, now)
            nv = DA.nova(v, DI.atlas_bias(v["symbol"], a), None, lun, tit)
            if nv["call"] != "TRADE":
                continue
            full = m15[v["symbol"]]
            nxt = full[full.index >= T]
            if nxt.empty:
                continue
            e = float(nxt["Open"].iloc[0])
            shift = e - tit["entry"]
            end = T + pd.Timedelta(hours=8)
            if v["class"] != "Crypto":
                close = T.normalize() + pd.Timedelta(hours=21)
                end = min(end, close if close > T else close + pd.Timedelta(days=1))
            tr = {"time": T, "symbol": v["symbol"], "class": v["class"], "side": tit["side"], "entry": e,
                  "stop": tit["stop"] + shift, "stop0": tit["stop"] + shift, "target": tit["target"] + shift,
                  "rr": tit["rr"], "setup": v["setup"].split(" (")[0], "session": a["session"], "entry_ts": nxt.index[0],
                  "end": end}
            open_tr.append(tr)
            approved.append({"symbol": v["symbol"], "class": v["class"]})
        if gi % 2000 == 0:
            print(f"  {T} ({gi}/{len(grid)}, {time.time() - t0:.0f}s, {len(done)} closed)", flush=True)
    return pd.DataFrame(done)


def report(t: pd.DataFrame) -> str:
    if t.empty:
        return "no trades"
    p = t["r"]
    mid = t["time"].sort_values().iloc[len(t) // 2]
    pf = p[p > 0].sum() / -p[p < 0].sum() if (p < 0).any() else np.inf
    nd = t["time"].dt.normalize().nunique()
    out = [f"ALL: {len(t)} trades ({len(t) / max(nd, 1):.1f} per active day) | win {(p > 0).mean() * 100:.0f}% | PF {pf:.2f} | "
           f"avg {p.mean():+.3f}R ({t['pct'].mean():+.3f}%) | t {p.mean() / p.std() * np.sqrt(len(p)):+.2f} | "
           f"halves {p[t['time'] < mid].mean():+.3f} / {p[t['time'] >= mid].mean():+.3f}R | total {p.sum():+.1f}R",
           "by exit: " + ", ".join(f"{k} {len(z)} ({z['r'].mean():+.2f}R)" for k, z in t.groupby("result"))]
    for col in ("class", "symbol", "setup", "session"):
        out.append(f"by {col}: " + ", ".join(f"{k} {len(z)} (win {(z['r'] > 0).mean() * 100:.0f}%, {z['r'].mean():+.2f}R)"
                                             for k, z in t.groupby(col)))
    out.append("by month: " + ", ".join(f"{k} {z['r'].sum():+.1f}R" for k, z in t.groupby(t["time"].dt.strftime("%Y-%m"))))
    return "\n".join(out)


def main(argv):
    data = pd.read_pickle(argv[1])
    fng = fng_history()
    if "--long" in argv:
        m15 = {"BTC-USD": data[("BTC", "15m")], "GC=F": data[("PAXG_GOLD", "15m")]}
        h1 = {"BTC-USD": data[("BTC", "1h")], "GC=F": data[("PAXG_GOLD", "1h")]}
        dx = yget("DX-Y.NYB", "1h", "730d")
        if dx is not None:
            h1["DX-Y.NYB"] = dx
        t = replay(m15, h1, fng, start=pd.Timestamp("2023-02-01"))
        print("\nLONG TEST (BTC + gold via PAXG, 2023-2026; ORION neutral, dollar index only from mid-2024):")
    else:
        m15, h1 = {}, {}
        for k, s in MAP.items():
            if (k, "15m") in data:
                m15[s], h1[s] = data[(k, "15m")], data[(k, "1h")]
        for s in ("BTC-USD", "ETH-USD", "SOL-USD", "AUDUSD=X", "DX-Y.NYB"):
            a, b = yget(s, "15m", "60d"), yget(s, "1h", "730d")
            if a is not None:
                m15[s] = a
            if b is not None:
                h1[s] = b
        t = replay(m15, h1, fng)
        print("\n60-DAY TEST, every market (15-min; ORION neutral):")
    print(report(t))
    t.to_pickle(Path(argv[1]).resolve().parent / ("global_desk_bt_long.pkl" if "--long" in argv else "global_desk_bt.pkl"))


if __name__ == "__main__":
    main(sys.argv)
