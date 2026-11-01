"""Two popular intraday methods, coded as written and tested after costs.

A. "Gautam Jha" previous-day level reversal (rules from a user-uploaded guide; no official version found), 1-minute:
   BUY: price breaks yesterday's low (a 1-min candle closes below it); after that a STRONG green candle (body >= 60%
   of its range, range >= 1.5x the last 20 candles' average); if the NEXT candle breaks that candle's high -> buy at
   that high (or the open, if it opens above). Stop: below the swing low (lowest low of the last 5 candles up to the
   green candle). Target: the nearest swing high above the entry from before the break ("where the fall started");
   if none, 2x the risk. Out at 15:15 otherwise. SELL is the mirror after a break of yesterday's high.
   One trade per side per day, entries 9:16-14:30. Variants: target 1.5R / 2R instead of the swing; strong candle
   1x average range; only days that did NOT open beyond the level.
   Data: Nifty and Bank Nifty 1-minute, Oct 2025 - Oct 2026 (Dhan); 206 F&O stocks 1-minute, 21 Sep - 29 Oct 2026.

B. Order block (the usual "smart money" definition; order-block.com does not publish its rules), 5-minute:
   bullish: a candle closes above the latest swing high (break of structure) with a big candle (range >= 1.5x
   average); the order block is the last red candle before that up-move. Buy the first later return to the block's
   top, stop below the block's low, target 2x risk, out at 15:15. Bearish is the mirror. Same day only, entries
   until 14:30, one trade per block.
   Data: Nifty and Bank Nifty 5-minute Dec 2021 - Oct 2026; 206 F&O stocks 5-minute last 1 year.

Costs a round trip: Nifty 2 pts, Bank Nifty 5 pts, stocks 0.06%. Results in R (multiples of the risk taken) and in
points / %.  Usage (Omnipuls folder): .venv\\Scripts\\python research\\jha_orderblock.py
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
pd.set_option("display.width", 250)
COST = {"NIFTY": ("pts", 2.0), "BANKNIFTY": ("pts", 5.0), "STOCK": ("pct", 0.06)}


def naive(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    if d.index.tz is not None:
        d.index = d.index.tz_convert("Asia/Kolkata").tz_localize(None)
    t = d.index.strftime("%H:%M")
    return d[(t >= "09:15") & (t <= "15:29")].sort_index()


def swings(H, L, n=2):
    """Fractal swing highs / lows; a swing at j is known only after candle j+n."""
    sh = np.zeros(len(H), bool)
    sl = np.zeros(len(H), bool)
    for j in range(n, len(H) - n):
        if H[j] >= H[j - n:j + n + 1].max() and H[j] > H[j - 1]:
            sh[j] = True
        if L[j] <= L[j - n:j + n + 1].min() and L[j] < L[j - 1]:
            sl[j] = True
    return sh, sl


def manage(H, L, C, hm, k, side, e, stop, tgt, out="15:14"):
    """Walk candles after entry candle k: stop first, then target, else the close at `out`."""
    for j in range(k + 1, len(C)):
        if (side > 0 and L[j] <= stop) or (side < 0 and H[j] >= stop):
            return stop, "stop"
        if (side > 0 and H[j] >= tgt) or (side < 0 and L[j] <= tgt):
            return tgt, "target"
        if hm[j] >= out:
            return C[j], "time"
    return C[-1], "time"


# ------------------------------------------------------------------ A. Jha reversal
def jha(df: pd.DataFrame, name: str, kind: str, strong_x=1.5, target="swing") -> list[dict]:
    rows = []
    df = naive(df)
    days = df.index.normalize()
    ud = days.unique()
    prev = None
    for d in ud:
        g = df[days == d]
        if prev is None or len(g) < 100:
            prev = g
            continue
        pdh, pdl = prev["High"].max(), prev["Low"].min()
        prev = g
        O, H, L, C = (g[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
        hm = g.index.strftime("%H:%M").to_numpy()
        rng = H - L
        avg = pd.Series(rng).shift(1).rolling(20, min_periods=10).mean().to_numpy()
        sh, sl = swings(H, L)
        for side, lvl in ((1, pdl), (-1, pdh)):  # buy after the LOW breaks, sell after the HIGH breaks
            opened_beyond = bool(side * (lvl - O[0]) > 0)
            br = np.flatnonzero(side * (lvl - C) > 0)
            if not len(br):
                continue
            kb = int(br[0])
            for j in range(kb + 1, len(C) - 1):
                if hm[j] > "14:30":
                    break
                body = side * (C[j] - O[j])
                if not (body > 0 and body >= 0.6 * rng[j] and np.isfinite(avg[j]) and rng[j] >= strong_x * avg[j]):
                    continue
                trig = H[j] if side > 0 else L[j]
                n_ = j + 1
                if not ((side > 0 and H[n_] > trig) or (side < 0 and L[n_] < trig)):
                    continue
                e = max(trig, O[n_]) if side > 0 else min(trig, O[n_])
                stop = (L[max(0, j - 4):j + 1].min() if side > 0 else H[max(0, j - 4):j + 1].max())
                risk = side * (e - stop)
                if risk <= 0:
                    break
                tg = None
                if target == "swing":
                    # nearest confirmed swing (before the break) beyond the entry
                    cands = [H[s] for s in np.flatnonzero(sh[:kb]) if s + 2 < kb and H[s] > e] if side > 0 else \
                        [L[s] for s in np.flatnonzero(sl[:kb]) if s + 2 < kb and L[s] < e]
                    if cands:
                        tg = min(cands) if side > 0 else max(cands)
                if tg is None:
                    rr = {"swing": 2.0, "1.5R": 1.5, "2R": 2.0}[target]
                    tg = e + side * rr * risk
                # the entry candle itself can hit the stop: check it (stop first)
                if (side > 0 and L[n_] <= stop) or (side < 0 and H[n_] >= stop):
                    px, how = stop, "stop"
                else:
                    px, how = manage(H, L, C, hm, n_, side, e, stop, tg)
                unit, c = COST[kind]
                cost = c if unit == "pts" else e * c / 100
                pts = side * (px - e) - cost
                rows.append({"method": "Jha", "market": name, "kind": kind, "date": d, "side": side, "time": hm[n_],
                             "opened_beyond": opened_beyond, "entry": e, "risk": risk, "rr": side * (tg - e) / risk,
                             "how": how, "pts": pts, "pct": 100 * pts / e, "R": pts / risk})
                break
    return rows


# ------------------------------------------------------------------ B. order block
def order_blocks(df: pd.DataFrame, name: str, kind: str, rr=2.0) -> list[dict]:
    rows = []
    df = naive(df)
    days = df.index.normalize()
    for d in days.unique():
        g = df[days == d]
        if len(g) < 40:
            continue
        O, H, L, C = (g[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
        hm = g.index.strftime("%H:%M").to_numpy()
        rng = H - L
        avg = pd.Series(rng).shift(1).rolling(20, min_periods=6).mean().to_numpy()
        sh, sl = swings(H, L)
        used = set()
        for k in range(5, len(C)):
            if hm[k] > "14:30":
                break
            for side in (1, -1):
                # latest confirmed swing before k
                sw = [s for s in np.flatnonzero(sh if side > 0 else sl) if s + 2 < k]
                if not sw:
                    continue
                s = sw[-1]
                lvl = H[s] if side > 0 else L[s]
                if (side, s) in used:
                    continue
                if not (side * (C[k] - lvl) > 0 and side * (C[k - 1] - lvl) <= 0 and np.isfinite(avg[k])
                        and rng[k] >= 1.5 * avg[k] and side * (C[k] - O[k]) > 0):
                    continue
                used.add((side, s))
                # the last opposite candle before the up-move (search back from k)
                ob = None
                for j in range(k - 1, max(-1, k - 25), -1):
                    if side * (C[j] - O[j]) < 0:
                        ob = j
                        break
                if ob is None:
                    continue
                top, bot = (H[ob], L[ob]) if side > 0 else (L[ob], H[ob])  # top = where the retest buys
                e_lvl, stop = top, bot - side * 0.0
                risk = side * (e_lvl - stop)
                if risk <= 0:
                    continue
                ent = None
                for j in range(k + 1, len(C)):
                    if hm[j] > "14:30":
                        break
                    if (side > 0 and L[j] <= e_lvl) or (side < 0 and H[j] >= e_lvl):
                        ent = j
                        break
                if ent is None:
                    continue
                e = min(O[ent], e_lvl) if side > 0 else max(O[ent], e_lvl)
                risk = side * (e - stop)
                if risk <= 0:
                    continue
                tg = e + side * rr * risk
                if (side > 0 and L[ent] <= stop) or (side < 0 and H[ent] >= stop):
                    px, how = stop, "stop"
                else:
                    px, how = manage(H, L, C, hm, ent, side, e, stop, tg)
                unit, c = COST[kind]
                cost = c if unit == "pts" else e * c / 100
                pts = side * (px - e) - cost
                rows.append({"method": "Order block", "market": name, "kind": kind, "date": d, "side": side,
                             "time": hm[ent], "entry": e, "risk": risk, "how": how, "pts": pts,
                             "pct": 100 * pts / e, "R": pts / risk})
    return rows


def summary(T: pd.DataFrame, label: str):
    if T.empty:
        print(label, "no trades")
        return
    T = T.sort_values("date")
    mid = T["date"].iloc[len(T) // 2]
    g = lambda x: pd.Series({  # noqa: E731
        "trades": len(x), "win %": 100 * (x["pts"] > 0).mean(), "avg R": x["R"].mean(),
        "avg pts": x["pts"].mean() if x["kind"].iloc[0] != "STOCK" else np.nan,
        "avg %": x["pct"].mean(), "1st half R": x[x["date"] < mid]["R"].mean(),
        "2nd half R": x[x["date"] >= mid]["R"].mean(), "target %": 100 * (x["how"] == "target").mean(),
        "stop %": 100 * (x["how"] == "stop").mean(), "median risk": x["risk"].median()})
    print(f"\n{label}")
    print(T.groupby(["market"]).apply(g).round(2).to_string())


def main():
    n1 = pickle.loads((HERE / "cache" / "y1m_IDX_13.pkl").read_bytes())
    b1 = pickle.loads((HERE / "cache" / "y1m_IDX_25.pkl").read_bytes())
    import dhan as D
    ids = {v: k for k, v in D.equity_ids().items()}
    stocks1 = {}
    for f in glob.glob(str(HERE / "cache" / "m1_*.pkl")):
        key = Path(f).stem[3:]
        if key.isdigit() and int(key) in ids:
            stocks1[ids[int(key)]] = pickle.loads(Path(f).read_bytes())
    print(f"1-minute stocks: {len(stocks1)}")
    out = []
    for variant in (dict(strong_x=1.5, target="swing"), dict(strong_x=1.5, target="1.5R"),
                    dict(strong_x=1.5, target="2R"), dict(strong_x=1.0, target="swing")):
        rows = jha(n1, "NIFTY", "NIFTY", **variant) + jha(b1, "BANKNIFTY", "BANKNIFTY", **variant)
        for s, d in stocks1.items():
            rows += jha(d, "F&O stocks (6 weeks)", "STOCK", **variant)
        T = pd.DataFrame(rows)
        tag = f"strong {variant['strong_x']}x, target {variant['target']}"
        summary(T, f"=== A. Jha reversal: {tag}")
        if variant == dict(strong_x=1.5, target="swing") and not T.empty:
            summary(T[~T["opened_beyond"]], "    same, only days that did not open beyond the level")
            summary(T[T["opened_beyond"]], "    same, only days that OPENED beyond the level")
        out.append(T.assign(variant=tag))
    # B. order blocks
    rows = []
    for name, sid in (("NIFTY", 13), ("BANKNIFTY", 25)):
        d5 = pickle.loads(open(sorted(glob.glob(str(HERE / "cache" / f"IDX_I_{sid}_5_1800_*.pkl")))[-1], "rb").read())
        rows += order_blocks(d5, name, name)
    from bigbars_dhan import load_cache
    _, raw = load_cache()
    for s, d in raw.items():
        d = naive(d)
        rows += order_blocks(d[d.index >= d.index.max() - pd.Timedelta(days=365)], "F&O stocks (1 year)", "STOCK")
    T = pd.DataFrame(rows)
    summary(T, "=== B. Order block retest, 2R target (index 5 years, stocks 1 year)")
    for name, X in T.groupby("market"):
        y = X.groupby(pd.to_datetime(X["date"]).dt.year)["R"].mean().round(2)
        print(f"  {name} avg R by year: {y.to_dict()}")
    out.append(T.assign(variant="order block 2R"))
    pd.concat(out).to_csv(HERE / "results" / "jha_orderblock.csv", index=False)


if __name__ == "__main__":
    main()
