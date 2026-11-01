"""Intraday study, last 1 year: describe what really happens, not test one fixed rule.

Study 1  Index, previous-day high / low (PDH / PDL) breaks. Nifty and Bank Nifty, 1-minute data from Dhan
         (Oct 2025 - Oct 2026) made into 3, 5, 10 and 15-minute candles. Each day's first candle that CLOSES beyond
         PDH (up) or PDL (down). At that candle: time, volume vs the same candle's 20-day average, RSI(14), distance
         from VWAP, the gap, how far the day had already moved, how far past the level it closed. After it: how many
         points it went your way (MFE) and against you (MAE) in the next 15 / 30 / 60 minutes and by the close,
         whether it fell back inside within 30 minutes, and whether it made a "clean" move (Nifty +30 before -15,
         Bank Nifty +60 before -30; only a yardstick, not a trading rule). Days that OPEN beyond the level are
         counted apart.
Study 3  Same-time candle breaks. Each day, the candle at 9:15, 9:30, 9:45, 10:00, 10:30, 11:00, 12:00, 13:00,
         14:00 (3 / 5 / 10 / 15-minute candles): which side breaks first (a later candle closing beyond its high
         or low), how long it takes, how many points it then goes each way, how often the other side breaks too.
Study 2  F&O stocks (206, 5-minute, last 1 year). Each day's 5 biggest gainers and 5 biggest losers, leaving out
         gaps over 3%. How the move unfolded after the open (when the day's low / high was made, how much of the move
         was done by 10:00, 11:00, 12:00) and which trigger came first: 15-minute opening-range break, volume burst
         (3x the same candle's usual volume), VWAP reclaim, previous-day high / low break. Then the honest check:
         the same triggers on ALL stock-days, to see how often a trigger actually led to a big move (studying only
         the winners always makes the triggers look better than they are).

Usage (Omnipuls folder; Nifty / Bank Nifty 1-minute in research/cache/y1m_IDX_13.pkl and _25.pkl):
    .venv\\Scripts\\python research\\intraday_study.py
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
OUT = HERE / "results"
TFS = (3, 5, 10, 15)
CLEAN = {"NIFTY": (30, 15), "BANKNIFTY": (60, 30)}
CANDLES = ("09:15", "09:30", "09:45", "10:00", "10:30", "11:00", "12:00", "13:00", "14:00")
LAST_ENTRY = "15:00"
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 400)
pd.set_option("display.max_columns", 40)


# ---------------------------------------------------------------- grids: days x candles
def load_1m(sid: int) -> pd.DataFrame:
    d = pickle.loads((HERE / "cache" / f"y1m_IDX_{sid}.pkl").read_bytes())
    if d.index.tz is not None:
        d.index = d.index.tz_convert("Asia/Kolkata").tz_localize(None)
    t = d.index.strftime("%H:%M")
    return d[(t >= "09:15") & (t <= "15:29")]


def to_grid(df: pd.DataFrame, tf: int, days: list | None = None):
    """Candles of tf minutes from 9:15, as arrays [day, slot]."""
    b = df.resample(f"{tf}min", origin="start_day", offset="15min").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])
    t = b.index.strftime("%H:%M")
    b = b[(t >= "09:15") & (t <= "15:29")]
    n = int(np.ceil(375 / tf))
    day = b.index.normalize()
    days = days if days is not None else sorted(day.unique())
    di = pd.Index(days).get_indexer(day)
    slot = ((b.index.hour * 60 + b.index.minute - 555) // tf).to_numpy()
    ok = (di >= 0) & (slot < n)
    G = {}
    for c in ("Open", "High", "Low", "Close", "Volume"):
        a = np.full((len(days), n), np.nan)
        a[di[ok], slot[ok]] = b[c].to_numpy(float)[ok]
        G[c[0]] = a
    return list(days), G


def slot_of(hhmm: str, tf: int) -> int:
    h, m = map(int, hhmm.split(":"))
    return (h * 60 + m - 555) // tf


def slot_time(k: int, tf: int) -> str:
    m = 555 + k * tf
    return f"{m // 60:02d}:{m % 60:02d}"


def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    s = pd.Series(close)
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn)).to_numpy()


def features(G: dict, days: list) -> dict:
    O, H, L, C, V = G["O"], G["H"], G["L"], G["C"], G["V"]
    flat = C.reshape(-1)
    good = np.isfinite(flat)
    r = np.full(flat.shape, np.nan)
    r[good] = rsi(flat[good])
    tp = (H + L + C) / 3
    vv = np.where(np.isfinite(V) & np.isfinite(tp), V, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.cumsum(np.nan_to_num(tp) * vv, 1) / np.cumsum(vv, 1)
    vwap = np.where(np.cumsum(vv, 1) > 0, vwap, np.nan)
    vavg = pd.DataFrame(V).rolling(20, min_periods=10).mean().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        volx = V / vavg
    first = np.argmax(np.isfinite(O), 1)
    dO = O[np.arange(len(days)), first]
    last = C.shape[1] - 1 - np.argmax(np.isfinite(C[:, ::-1]), 1)
    dC = C[np.arange(len(days)), last]
    dH, dL = np.nanmax(H, 1), np.nanmin(L, 1)
    pC = np.r_[np.nan, dC[:-1]]
    tr = np.maximum(dH - dL, np.maximum(np.abs(dH - pC), np.abs(dL - pC)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().shift(1).to_numpy()
    return {"rsi": r.reshape(C.shape), "vwap": vwap, "volx": volx, "dO": dO, "dC": dC, "dH": dH, "dL": dL,
            "pC": pC, "pH": np.r_[np.nan, dH[:-1]], "pL": np.r_[np.nan, dL[:-1]], "atr": atr, "last": last}


def after(G, d: int, k: int, side: int, e: float, bars: int | None):
    """Points your way (MFE) and against you (MAE) from the close of candle k, over the next `bars` candles."""
    end = None if bars is None else k + 1 + bars
    h, l = G["H"][d, k + 1:end], G["L"][d, k + 1:end]
    if not np.isfinite(h).any():
        return np.nan, np.nan
    mx, mn = np.nanmax(h), np.nanmin(l)
    return (mx - e, e - mn) if side > 0 else (e - mn, mx - e)


def clean(G, d, k, side, e, fav, adv, bars):
    for j in range(k + 1, min(G["C"].shape[1], k + 1 + bars)):
        h, l = G["H"][d, j], G["L"][d, j]
        if not np.isfinite(h):
            continue
        bad = (l <= e - adv) if side > 0 else (h >= e + adv)
        if bad:
            return False
        if (h >= e + fav) if side > 0 else (l <= e - fav):
            return True
    return False


def bucket(x, edges, labels):
    return pd.cut(pd.Series(x), edges, labels=labels).astype(str).to_numpy()


def summarize(E: pd.DataFrame, by) -> pd.DataFrame:
    g = E.groupby(by, observed=True)
    out = g.agg(n=("mfe30", "size"), MFE30=("mfe30", "median"), MAE30=("mae30", "median"),
                MFE60=("mfe60", "median"), MAE60=("mae60", "median"), to_close=("to_close", "median"),
                clean=("clean", "mean"), back_inside=("back30", "mean"))
    out["clean"] = (100 * out["clean"]).round(0)
    out["back_inside"] = (100 * out["back_inside"]).round(0)
    return out.round(1)


# ---------------------------------------------------------------- study 1
def study_pdh(name: str, df1: pd.DataFrame) -> pd.DataFrame:
    fav, adv = CLEAN[name]
    rows = []
    for tf in TFS:
        days, G = to_grid(df1, tf)
        F = features(G, days)
        kmax = slot_of(LAST_ENTRY, tf)
        b30, b60, b15 = max(1, 30 // tf), max(1, 60 // tf), max(1, 15 // tf)
        for d in range(1, len(days)):
            if not np.isfinite(F["pH"][d]) or not np.isfinite(F["atr"][d]):
                continue
            for side, lvl in ((1, F["pH"][d]), (-1, F["pL"][d])):
                o = F["dO"][d]
                if side * (o - lvl) > 0:
                    rows.append({"index": name, "tf": tf, "date": days[d], "side": side, "opened_beyond": True})
                    continue
                C = G["C"][d, :kmax + 1]
                hit = np.flatnonzero(side * (C - lvl) > 0)
                if not len(hit):
                    continue
                k = int(hit[0])
                e = G["C"][d, k]
                wick_first = bool(np.any(side * ((G["H"] if side > 0 else G["L"])[d, :k] - lvl) > 0))
                other = F["pL"][d] if side > 0 else F["pH"][d]
                other_broken = bool(np.any(side * (other - G["C"][d, :k]) > 0))
                m15, a15 = after(G, d, k, side, e, b15)
                m30, a30 = after(G, d, k, side, e, b30)
                m60, a60 = after(G, d, k, side, e, b60)
                mC, aC = after(G, d, k, side, e, None)
                nxt = G["C"][d, k + 1:k + 1 + b30]
                rows.append({
                    "index": name, "tf": tf, "date": days[d], "side": side, "opened_beyond": False,
                    "time": slot_time(k, tf), "minute": k * tf, "volx": F["volx"][d, k],
                    "rsi_dir": F["rsi"][d, k] if side > 0 else 100 - F["rsi"][d, k],
                    "vwap_atr": side * (e - F["vwap"][d, k]) / F["atr"][d],
                    "gap_atr": side * (o - F["pC"][d]) / F["atr"][d],
                    "moved_atr": side * (e - o) / F["atr"][d],
                    "beyond_pts": side * (e - lvl), "candle_pts": G["H"][d, k] - G["L"][d, k],
                    "wick_first": wick_first, "other_broken_first": other_broken, "atr": F["atr"][d],
                    "mfe15": m15, "mae15": a15, "mfe30": m30, "mae30": a30, "mfe60": m60, "mae60": a60,
                    "mfe_close": mC, "mae_close": aC, "to_close": side * (F["dC"][d] - e),
                    "back30": bool(np.any(side * (nxt - lvl) <= 0)), "clean": clean(G, d, k, side, e, fav, adv, b60),
                    "close_beyond": bool(side * (F["dC"][d] - lvl) > 0)})
    return pd.DataFrame(rows)


def report_pdh(E: pd.DataFrame):
    for name, X in E.groupby("index"):
        ob = X[X["opened_beyond"]]
        X = X[~X["opened_beyond"]].copy()
        print(f"\n################ STUDY 1: {name} previous-day high / low breaks (last 1 year)")
        days = X[X.tf == 5]["date"].nunique()
        print(f"Opened beyond the level (gap through it): {ob[ob.tf == 5].shape[0]} times. "
              f"Broke it later in the day (5-min close): {X[X.tf == 5].shape[0]} times on {days} days.")
        print("\nBy candle size (side 1 = PDH up, -1 = PDL down). Points: median; clean = % that made the clean move; "
              "back_inside = % that closed back inside the level within 30 min")
        print(summarize(X, ["tf", "side"]).to_string())
        Y = X[X.tf == 5].copy()
        Y["when"] = bucket(Y["minute"], [-1, 45, 135, 255, 400], ["9:15-10:00", "10:00-11:30", "11:30-13:30", "13:30+"])
        Y["volume"] = bucket(Y["volx"], [-1, 1, 1.5, 2.5, 1e9], ["<1x", "1-1.5x", "1.5-2.5x", ">2.5x"])
        Y["rsi"] = bucket(Y["rsi_dir"], [-1, 55, 65, 75, 101], ["<55", "55-65", "65-75", ">75"])
        Y["vs_vwap"] = bucket(Y["vwap_atr"], [-9, 0.1, 0.3, 0.6, 9], ["near/under", "0.1-0.3 ATR", "0.3-0.6 ATR", ">0.6 ATR"])
        Y["gap"] = bucket(Y["gap_atr"], [-9, -0.2, 0.2, 9], ["gap against", "flat", "gap toward"])
        Y["day_moved"] = bucket(Y["moved_atr"], [-9, 0.2, 0.5, 9], ["<0.2 ATR", "0.2-0.5 ATR", ">0.5 ATR"])
        Y["beyond"] = bucket(Y["beyond_pts"] / Y["atr"], [-1, 0.05, 0.15, 9], ["just over", "a little", "far over"])
        for col in ("when", "volume", "rsi", "vs_vwap", "gap", "day_moved", "beyond", "wick_first", "other_broken_first"):
            print(f"\n-- 5-min breaks by {col}")
            print(summarize(Y, ["side", col]).to_string())


# ---------------------------------------------------------------- study 3
def study_candles(name: str, df1: pd.DataFrame) -> pd.DataFrame:
    fav, adv = CLEAN[name]
    rows = []
    for tf in TFS:
        days, G = to_grid(df1, tf)
        F = features(G, days)
        kmax = slot_of(LAST_ENTRY, tf)
        b30, b60 = max(1, 30 // tf), max(1, 60 // tf)
        for ct in CANDLES:
            j = slot_of(ct, tf)
            if (int(ct[:2]) * 60 + int(ct[3:]) - 555) % tf:
                continue
            for d in range(len(days)):
                h, l = G["H"][d, j], G["L"][d, j]
                if not np.isfinite(h):
                    continue
                C = G["C"][d, j + 1:kmax + 1]
                up = np.flatnonzero(C > h)
                dn = np.flatnonzero(C < l)
                fu = up[0] if len(up) else 10**6
                fd = dn[0] if len(dn) else 10**6
                if fu == fd == 10**6:
                    rows.append({"index": name, "tf": tf, "candle": ct, "date": days[d], "side": 0,
                                 "range": h - l, "atr": F["atr"][d]})
                    continue
                side = 1 if fu < fd else -1
                k = j + 1 + min(fu, fd)
                e = G["C"][d, k]
                lvl = h if side > 0 else l
                m30, a30 = after(G, d, k, side, e, b30)
                m60, a60 = after(G, d, k, side, e, b60)
                nxt = G["C"][d, k + 1:k + 1 + b30]
                rows.append({"index": name, "tf": tf, "candle": ct, "date": days[d], "side": side,
                             "range": h - l, "atr": F["atr"][d], "delay": (k - j) * tf, "beyond": side * (e - lvl),
                             "mfe30": m30, "mae30": a30, "mfe60": m60, "mae60": a60,
                             "to_close": side * (F["dC"][d] - e), "back30": bool(np.any(side * (nxt - lvl) <= 0)),
                             "whipsaw": bool(max(fu, fd) < 10**6), "clean": clean(G, d, k, side, e, fav, adv, b60)})
    return pd.DataFrame(rows)


def report_candles(E: pd.DataFrame):
    for name, X in E.groupby("index"):
        print(f"\n################ STUDY 3: {name} same-time candle breaks (last 1 year)")
        g = X.groupby(["tf", "candle"])
        out = pd.DataFrame({
            "days": g.size(), "range": g["range"].median(),
            "up %": g["side"].apply(lambda s: 100 * (s == 1).mean()),
            "down %": g["side"].apply(lambda s: 100 * (s == -1).mean()),
            "none %": g["side"].apply(lambda s: 100 * (s == 0).mean()),
            "delay min": g["delay"].median(),
            "MFE60 p25": g["mfe60"].quantile(.25), "MFE60 p50": g["mfe60"].median(), "MFE60 p75": g["mfe60"].quantile(.75),
            "MAE60 p50": g["mae60"].median(), "MAE60 p75": g["mae60"].quantile(.75),
            "to close": g["to_close"].median(), "clean %": 100 * g["clean"].mean(),
            "back in 30m %": 100 * g["back30"].mean(), "other side too %": 100 * g["whipsaw"].mean()})
        print(out.round(1).to_string())
        Y = X[(X.side != 0)].copy()
        Y["range_vs_atr"] = bucket(Y["range"] / Y["atr"], [-1, 0.1, 0.2, 9], ["small candle", "medium", "big candle"])
        print("\n-- 5-min candles, by the candle's size vs the daily ATR")
        print(Y[Y.tf == 5].groupby(["candle", "range_vs_atr"]).agg(
            n=("mfe60", "size"), MFE60=("mfe60", "median"), MAE60=("mae60", "median"),
            clean=("clean", "mean"), whipsaw=("whipsaw", "mean")).round(2).to_string())


# ---------------------------------------------------------------- study 2
def study_stocks(nifty1: pd.DataFrame):
    import universe as U
    from bigbars_dhan import load_cache
    _, raw = load_cache()
    end = max(v.index.max() for v in raw.values())
    end = end.tz_convert("Asia/Kolkata").tz_localize(None) if end.tzinfo else end
    start = end - pd.Timedelta(days=372)
    syms, grids = [], []
    alldays = None
    for s, df in raw.items():
        df = df.copy()
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
        df = df[df.index >= start - pd.Timedelta(days=40)]  # 20 days back for the volume averages
        if len(df) < 1000:
            continue
        syms.append(s)
        grids.append(df)
        dd = set(df.index.normalize())
        alldays = dd if alldays is None else alldays | dd
    days = sorted(alldays)
    S = {c: [] for c in "OHLCV"}
    for df in grids:
        _, G = to_grid(df, 5, days)
        for c in "OHLCV":
            S[c].append(G[c])
    A = {c: np.stack(S[c]) for c in "OHLCV"}  # [stock, day, slot]
    O, H, L, C, V = A["O"], A["H"], A["L"], A["C"], A["V"]
    ns, nd, nk = C.shape
    first = np.argmax(np.isfinite(O), 2)
    dO = np.take_along_axis(O, first[..., None], 2)[..., 0]
    lastk = nk - 1 - np.argmax(np.isfinite(C[..., ::-1]), 2)
    dC = np.take_along_axis(C, lastk[..., None], 2)[..., 0]
    dH, dL = np.nanmax(H, 2), np.nanmin(L, 2)
    pC = np.concatenate([np.full((ns, 1), np.nan), dC[:, :-1]], 1)
    pH = np.concatenate([np.full((ns, 1), np.nan), dH[:, :-1]], 1)
    pL = np.concatenate([np.full((ns, 1), np.nan), dL[:, :-1]], 1)
    gap = (dO / pC - 1) * 100
    ret = (dC / pC - 1) * 100
    vavg = np.stack([pd.DataFrame(V[i]).rolling(20, min_periods=10).mean().shift(1).to_numpy() for i in range(ns)])
    with np.errstate(invalid="ignore", divide="ignore"):
        volx = V / vavg
        tp = (H + L + C) / 3
        vv = np.where(np.isfinite(V) & np.isfinite(tp), V, 0)
        vwap = np.cumsum(np.nan_to_num(tp) * vv, 2) / np.cumsum(vv, 2)
    # what is left after slot k: highest high / lowest low of the later candles, and the close
    rev = lambda a, f: f.accumulate(a[..., ::-1], axis=2)[..., ::-1]  # noqa: E731
    sufH = np.concatenate([rev(H, np.fmax)[..., 1:], np.full((ns, nd, 1), np.nan)], 2)
    sufL = np.concatenate([rev(L, np.fmin)[..., 1:], np.full((ns, nd, 1), np.nan)], 2)
    keep = np.array([d >= start for d in days])
    sec = np.array([U.FNO_SECTOR_OF.get(s, "Other") for s in syms])
    # day move so far (from previous close) of each stock, its sector (others) and Nifty at each candle
    chg = (C / pC[..., None] - 1) * 100
    sec_chg = np.full_like(chg, np.nan)
    for sname in set(sec):
        idx = np.flatnonzero(sec == sname)
        if len(idx) < 2:
            continue
        tot = np.nansum(chg[idx], 0)
        cnt = np.isfinite(chg[idx]).sum(0)
        for i in idx:
            own = np.nan_to_num(chg[i])
            sec_chg[i] = (tot - own) / np.maximum(cnt - np.isfinite(chg[i]), 1)
    _, NG = to_grid(nifty1, 5, days)
    nC = NG["C"]
    nlast = nk - 1 - np.argmax(np.isfinite(nC[:, ::-1]), 1)
    ndC = nC[np.arange(nd), nlast]
    npC = np.r_[np.nan, ndC[:-1]]
    n_chg = (nC / npC[:, None] - 1) * 100
    n_ret = (ndC / npC - 1) * 100

    k12 = slot_of("12:00", 5)
    orb_h, orb_l = np.nanmax(H[..., :3], 2), np.nanmin(L[..., :3], 2)
    slots = np.arange(nk)[None, None, :]
    below = (C < vwap).astype(float)
    above = (C > vwap).astype(float)
    run_b = np.stack([pd.DataFrame(below[i]).T.rolling(6).sum().shift(1).T.to_numpy() for i in range(ns)])
    run_a = np.stack([pd.DataFrame(above[i]).T.rolling(6).sum().shift(1).T.to_numpy() for i in range(ns)])
    trig = {}
    for side in (1, -1):
        up = side > 0
        trig[("15-min range break", side)] = (C > orb_h[..., None]) if up else (C < orb_l[..., None])
        trig[("15-min range break", side)] &= slots >= 3
        trig[("volume burst 3x", side)] = (volx >= 3) & ((C > O) if up else (C < O)) & (slots >= 1)
        trig[("VWAP reclaim", side)] = ((C > vwap) & (run_b == 6)) if up else ((C < vwap) & (run_a == 6))
        trig[("prev-day high/low break", side)] = ((C > pH[..., None]) & (dO <= pH)[..., None]) if up else \
            ((C < pL[..., None]) & (dO >= pL)[..., None])
        trig[("range break + volume 2x", side)] = trig[("15-min range break", side)] & (volx >= 2)
    trig = {k: v & (slots <= k12) for k, v in trig.items()}

    base_ok = keep[None, :] & np.isfinite(ret) & (np.abs(gap) <= 3)
    # movers: top 5 / bottom 5 by day's return, gaps over 3% left out
    rank_up = np.full(ret.shape, False)
    rank_dn = np.full(ret.shape, False)
    for d in np.flatnonzero(keep):
        r = np.where(base_ok[:, d], ret[:, d], np.nan)
        if np.isfinite(r).sum() < 50:
            continue
        o = np.argsort(np.where(np.isfinite(r), r, -np.inf))[::-1][:5]
        rank_up[o, d] = True
        o = np.argsort(np.where(np.isfinite(r), r, np.inf))[:5]
        rank_dn[o, d] = True

    print("\n################ STUDY 2: F&O stocks, each day's top 5 gainers and losers (gaps over 3% left out)")
    print(f"{len(syms)} stocks, {int(keep.sum())} days ({days[int(np.argmax(keep))]:%d %b %Y} - {days[-1]:%d %b %Y})")
    for side, mv in ((1, rank_up), (-1, rank_dn)):
        word = "GAINERS" if side > 0 else "LOSERS"
        s_i, d_i = np.nonzero(mv)
        print(f"\n=== {word}: {len(s_i)} stock-days. Day move: median {np.median(ret[mv]):+.2f}%, gap median "
              f"{np.median(gap[mv]):+.2f}%")
        ext = (np.nanargmin(np.where(np.isfinite(L[mv]), L[mv], np.inf), 1) if side > 0 else
               np.nanargmax(np.where(np.isfinite(H[mv]), H[mv], -np.inf), 1))
        print("  Day's low (gainers) / high (losers) was made at: " +
              ", ".join(f"{a}: {100 * np.mean(m):.0f}%" for a, m in (
                  ("9:15-9:30", ext < 3), ("9:30-10:00", (ext >= 3) & (ext < 9)), ("10:00-11:00", (ext >= 9) & (ext < 21)),
                  ("11:00-13:00", (ext >= 21) & (ext < 45)), ("after 13:00", ext >= 45))))
        total = dC[mv] - dO[mv]
        for t in ("10:00", "11:00", "12:00", "13:00", "14:00"):
            k = slot_of(t, 5) - 1
            done = (C[mv][:, k] - dO[mv]) / total
            print(f"  share of the open-to-close move done by {t}: median {100 * np.nanmedian(done):.0f}%")
        print(f"  Nifty moved the same way that day: {100 * np.mean(np.sign(n_ret[d_i]) == side):.0f}%  "
              f"(all days: {100 * np.mean(n_ret[keep] * side > 0):.0f}%)")
        k11 = slot_of("11:00", 5) - 1
        sec_at = sec_chg[s_i, d_i, k11] * side
        print(f"  its sector (other stocks) was already {'up' if side > 0 else 'down'} 0.5%+ at 11:00: "
              f"{100 * np.nanmean(sec_at > 0.5):.0f}%")
        rows = []
        for (tname, ts), T in trig.items():
            if ts != side:
                continue
            fired = T.any(2)
            k = np.argmax(T, 2)
            e = np.take_along_axis(C, k[..., None], 2)[..., 0]
            to_close = side * (dC / e - 1) * 100
            mfe = (np.take_along_axis(sufH if side > 0 else sufL, k[..., None], 2)[..., 0] / e - 1) * 100 * side
            mae = (np.take_along_axis(sufL if side > 0 else sufH, k[..., None], 2)[..., 0] / e - 1) * -100 * side
            f_m = fired & mv
            f_all = fired & base_ok
            ctx_sec = np.take_along_axis(sec_chg, k[..., None], 2)[..., 0] * side > 0.3
            ctx_nif = np.take_along_axis(np.broadcast_to(n_chg[None], C.shape), k[..., None], 2)[..., 0] * side > 0.2
            both = f_all & ctx_sec & ctx_nif
            rows.append({
                "trigger (by 12:00)": tname, "fired on movers %": 100 * f_m.sum() / mv.sum(),
                "movers: median time": slot_time(int(np.median(k[f_m])), 5) if f_m.any() else "",
                "movers: move left to close %": np.nanmedian(to_close[f_m]),
                "ALL stocks: fired": int(f_all.sum()),
                "ALL: became top-5 %": 100 * (mv & f_all).sum() / max(1, f_all.sum()),
                "ALL: to close % (avg)": np.nanmean(to_close[f_all]),
                "ALL: closed your way %": 100 * np.nanmean(to_close[f_all] > 0),
                "ALL: MFE % med": np.nanmedian(mfe[f_all]), "ALL: MAE % med": np.nanmedian(mae[f_all]),
                "+sector & Nifty same way: fired": int(both.sum()),
                "+ctx: to close % (avg)": np.nanmean(to_close[both]),
                "+ctx: became top-5 %": 100 * (mv & both).sum() / max(1, both.sum())})
        print(pd.DataFrame(rows).round(2).to_string(index=False))
        print(f"  (a stock-day picked at random became a top-5 {word.lower()[:-1]} {100 * mv.sum() / base_ok.sum():.1f}% "
              f"of the time; costs about 0.06% a round trip)")


def main():
    n1, b1 = load_1m(13), load_1m(25)
    if sys.argv[1:] == ["stocks"]:
        return study_stocks(n1)
    E1 = pd.concat([study_pdh("NIFTY", n1), study_pdh("BANKNIFTY", b1)])
    E1.to_csv(OUT / "intraday_pdh_breaks.csv", index=False)
    report_pdh(E1)
    E3 = pd.concat([study_candles("NIFTY", n1), study_candles("BANKNIFTY", b1)])
    E3.to_csv(OUT / "intraday_candle_breaks.csv", index=False)
    report_candles(E3)
    study_stocks(n1)


if __name__ == "__main__":
    main()
