"""Setup Finder: the research engine behind our bots. Runs on the server outside market hours (bots.py starts it).

It tests intraday rules on ALL F&O stocks and the indices, and keeps only rules that still make money on days they
were never tuned on.

1. Data: 5-minute candles for every F&O stock and Nifty, Bank Nifty, Fin Nifty, Midcap Select and Sensex from Dhan
   (a year, cached on the server, topped up each night).
2. Readings at EVERY candle from 9:30 (no fixed time): from the open to that candle - money-flow buying share and net
   flow vs the usual day's turnover, volume vs the usual volume by that time, range so far vs the usual day, move
   from the open in ATR, gap, open = high / low, and the sector's and the market's buying share at that moment.
3. Signal = the FIRST candle of the day where a rule's conditions are all true; entry at the next candle's open, exit
   15:20 or a stop of 0.5 / 1 ATR. "Top N a day" = the first N signals of the day in time order (no look-ahead).
4. Search: ~3,500 stock rules (long and short together) after 0.12% costs; per index, rules on the index move and its
   constituents' money flow, and MACD crosses with / without that flow. Tuned on the first 60% of days, judged
   ONLY on the last 40% and on neighbouring settings (one value changed), so a lucky setting does not pass.
5. Results: <data>/bot/latest.json (app and bots) and the Supabase table bot_results.
"""
from __future__ import annotations

import itertools
import json
import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import paths

IST = timezone(timedelta(hours=5, minutes=30))
BOT_DIR = paths.DATA / "bot"
CACHE = BOT_DIR / "cache"
FIRST, LAST, EXIT = 9 * 60 + 30, 14 * 60 + 30, 15 * 60 + 15   # signals 9:30-14:30, exit = the 15:15 candle's close
COST = 0.0012             # stocks: 0.12% round trip (same as the research)
INDEX_COST = 0.0002       # index futures: about 5 points on 24,000 including slippage
TRAIN = 0.6
HISTORY_DAYS = int(os.environ.get("BOT_HISTORY_DAYS", 365))
INDEX_IDS = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "MIDCPNIFTY": 442, "SENSEX": 51}
INDEX_NAMES = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty", "FINNIFTY": "Fin Nifty", "MIDCPNIFTY": "Midcap Select",
               "SENSEX": "Sensex"}


def log(msg: str):
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} bot: {msg}", flush=True)

# ---------------------------------------------------------------- data


def clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    d.index = idx
    d = d[~d.index.duplicated(keep="last")].sort_index().between_time("09:15", "15:25")
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume", "OI") if c in d]
    out = d[cols].astype(float)
    if "Volume" not in out:
        out["Volume"] = 0.0
    return out


def universe(cfg: dict) -> list[tuple[str, str, int, str]]:
    """(symbol, segment, security id, chart instrument) for every F&O stock and the indices."""
    import dhan as D
    eq = D.equity_ids(cfg)
    stocks = sorted(s for s in D.fno_underlyings(cfg) if s in eq)
    return ([(k, "IDX_I", v, "INDEX") for k, v in INDEX_IDS.items()] +
            [(s, "NSE_EQ", eq[s], "EQUITY") for s in stocks])


def load_history(cfg: dict | None = None, days: int = HISTORY_DAYS, symbols=None) -> tuple[dict, dict]:
    """({stock: 5-min bars}, {index: 5-min bars}). Cached per symbol; later runs fetch only the last 10 days."""
    import dhan as D
    CACHE.mkdir(parents=True, exist_ok=True)
    cfg = cfg or D.load_config()
    wanted = symbols or universe(cfg)
    stocks, indices = {}, {}
    for i, (sym, seg, sid, ins) in enumerate(wanted, 1):
        f = CACHE / f"{sym.replace('&', '_and_')}.parquet"
        old = pd.read_parquet(f) if f.exists() else pd.DataFrame()
        span = 10 if not old.empty and (pd.Timestamp.now() - old.index.max()).days < 9 else days
        try:
            new = clean(D.intraday(seg, sid, ins, 5, span, cfg))
        except Exception as e:
            log(f"{sym}: {getattr(e, 'friendly', e)}")
            new = pd.DataFrame()
        df = pd.concat([old, new]) if not old.empty and not new.empty else (new if old.empty else old)
        if df.empty:
            continue
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[df.index >= df.index.max() - pd.Timedelta(days=days + 5)]
        df.to_parquet(f)
        (indices if seg == "IDX_I" else stocks)[sym] = df
        if i % 25 == 0:
            log(f"history {i}/{len(wanted)}")
    return stocks, indices

# ---------------------------------------------------------------- readings at every candle


def candle_table(sym: str, df: pd.DataFrame, flow: pd.DataFrame | None = None, keep_all_days: bool = True) -> dict:
    """Numpy columns, one row per candle in the signal window, with the readings so far today and the outcome of
    entering at the next candle. `flow` (index only): per-candle inflow / outflow of its constituents."""
    d = clean(df)
    if len(d) < 75 * 22:
        return {}
    O, H, L, C, V = (d[c].to_numpy() for c in ("Open", "High", "Low", "Close", "Volume"))
    day = d.index.normalize()
    mins = np.asarray(d.index.hour) * 60 + np.asarray(d.index.minute)
    if flow is not None and not flow.empty:
        f = flow.reindex(d.index).fillna(0.0)
        inf, outf = f["inflow"].to_numpy(), f["outflow"].to_numpy()
        turn = inf + outf
    else:
        rng = H - L
        prevc = np.r_[np.nan, C[:-1]]
        press = np.where(rng > 0, (C - O) / np.where(rng > 0, rng, 1), np.sign(np.nan_to_num(C - prevc)))
        turn = V * (H + L + C) / 3
        inf, outf = turn * (1 + press) / 2, turn * (1 - press) / 2
    fr = pd.DataFrame({"day": day, "m": mins, "O": O, "H": H, "L": L, "C": C, "V": V, "turn": turn, "inf": inf,
                       "outf": outf}, index=d.index)
    g = fr.groupby("day", sort=True)
    cumv, cumin, cumout = g["V"].cumsum(), g["inf"].cumsum(), g["outf"].cumsum()
    hi, lo, dopen = g["H"].cummax(), g["L"].cummin(), g["O"].transform("first")
    daily = g.agg(o=("O", "first"), h=("H", "max"), l=("L", "min"), c=("C", "last"), turn=("turn", "sum"))
    pc = daily["c"].shift(1)
    tr = pd.concat([daily["h"] - daily["l"], (daily["h"] - pc).abs(), (daily["l"] - pc).abs()], axis=1).max(axis=1)
    dl = pd.DataFrame({"atr": tr.rolling(14).mean().shift(1), "avg_rng": (daily["h"] - daily["l"]).rolling(14)
                       .mean().shift(1), "avg_turn": daily["turn"].rolling(20).mean().shift(1),
                       "gap": daily["o"] / pc - 1, "o": daily["o"]}).reindex(day)
    cv = fr.assign(cumv=cumv.values).pivot_table(index="day", columns="m", values="cumv", aggfunc="last")
    ucv = cv.rolling(20, min_periods=10).mean().shift(1).stack().rename("ucv")
    usual = pd.Series(ucv.reindex(pd.MultiIndex.from_arrays([day, mins])).to_numpy(), index=d.index)
    # outcome of entering at the NEXT candle: its open, then the lowest low / highest high until the exit candle
    upto = mins <= EXIT
    lo_x = pd.Series(np.where(upto, L, np.nan), index=d.index)
    hi_x = pd.Series(np.where(upto, H, np.nan), index=d.index)
    rev_day = pd.Series(day, index=d.index)[::-1]
    minlow = lo_x[::-1].groupby(rev_day).cummin()[::-1]
    maxhigh = hi_x[::-1].groupby(rev_day).cummax()[::-1]
    nxt = lambda s: s.groupby(day).shift(-1)  # noqa: E731
    exit_px = pd.Series(np.where(mins == EXIT, C, np.nan), index=d.index).groupby(day).transform("max")
    tot = (cumin + cumout).to_numpy()
    out = {
        "day": (day.to_numpy().astype("datetime64[D]").astype(np.int64)), "m": mins.astype(np.int16),
        "move": (C / dopen.to_numpy() - 1), "move_atr": (C - dopen.to_numpy()) / dl["atr"].to_numpy(),
        "range_x": (hi - lo).to_numpy() / dl["avg_rng"].to_numpy(), "vol_x": cumv.to_numpy() / usual.to_numpy(),
        "flow_share": np.where(tot > 0, cumin.to_numpy() / np.where(tot > 0, tot, 1), 0.5),
        "flow_x": (cumin - cumout).to_numpy() / dl["avg_turn"].to_numpy(), "gap": dl["gap"].to_numpy(),
        "o_eq_l": np.abs(dl["o"].to_numpy() - lo.to_numpy()) <= dl["o"].to_numpy() * 0.0005,
        "o_eq_h": np.abs(hi.to_numpy() - dl["o"].to_numpy()) <= dl["o"].to_numpy() * 0.0005,
        "entry": nxt(fr["O"]).to_numpy(), "minlow": nxt(minlow).to_numpy(), "maxhigh": nxt(maxhigh).to_numpy(),
        "exit": exit_px.to_numpy(), "atr": dl["atr"].to_numpy(), "price": C,
        "net_cr": (cumin - cumout).to_numpy() / 1e7, "chg": C / pc.reindex(day).to_numpy() - 1,  # change vs yesterday's close
    }
    keep = (mins >= FIRST) & (mins <= LAST)
    if not keep_all_days:  # live: today only, the whole session (the bots watch to the close)
        keep = (mins >= 560) & (mins <= 930) & (out["day"] == out["day"].max())
    need = ["move_atr", "range_x", "atr", "entry", "exit"] if keep_all_days else ["move_atr", "range_x", "atr"]
    for k in need:
        keep &= np.isfinite(out[k].astype(float))
    res = {k: (v[keep].astype(np.float32) if v.dtype.kind == "f" else v[keep]) for k, v in out.items()}
    res["n"] = int(keep.sum())
    return res


def build_table(bars: dict, sectors: dict | None = None, keep_all_days: bool = True) -> dict:
    """All stocks' candle tables in one, sorted by (day, minute, stock), with the market's and sector's buying share
    at each candle."""
    parts, names = [], []
    for s, df in bars.items():
        t = candle_table(s, df, keep_all_days=keep_all_days)
        if t.get("n"):
            t["sym"] = np.full(t["n"], len(names), dtype=np.int32)
            names.append(s)
            parts.append(t)
    if not parts:
        return {}
    keys = [k for k in parts[0] if k != "n"]
    T = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    order = np.lexsort((T["sym"], T["m"], T["day"]))
    T = {k: v[order] for k, v in T.items()}
    T["vol_x"] = np.nan_to_num(T["vol_x"], nan=1.0, posinf=1.0)
    T["flow_x"] = np.nan_to_num(T["flow_x"], nan=0.0, posinf=0.0, neginf=0.0)
    gid = np.unique(T["day"].astype(np.int64) * 2000 + T["m"], return_inverse=True)[1]
    cnt = np.bincount(gid)
    T["mkt_flow"] = (np.bincount(gid, T["flow_share"]) / cnt)[gid].astype(np.float32)
    sec_names = sorted(set((sectors or {}).values()) | {"Other"})
    sec_of = np.array([sec_names.index((sectors or {}).get(n, "Other")) for n in names], dtype=np.int32)
    sid = gid * len(sec_names) + sec_of[T["sym"]]
    u, inv = np.unique(sid, return_inverse=True)
    T["sec_flow"] = (np.bincount(inv, T["flow_share"]) / np.bincount(inv))[inv].astype(np.float32)
    T["names"] = np.array(names, dtype=object)
    T["sector_of"] = np.array([(sectors or {}).get(n, "Other") for n in names], dtype=object)
    return T

# ---------------------------------------------------------------- rules


GRID = {"move_atr": [0.3, 0.5, 0.8], "flow": [0.0, 0.55, 0.6, 0.65], "vol_x": [1.0, 1.5, 2.0],
        "range": ["any", "room", "wide"], "sector": [False, True], "market": [False, True], "stop": [0.5, 1.0],
        "top": [1, 3], "until": ["11:30", "14:30"]}


def _hm(s: str) -> int:
    h, m = map(int, s.split(":"))
    return h * 60 + m


def rule_mask(T: dict, c: dict, side: np.ndarray) -> np.ndarray:
    m = (T["m"] <= _hm(c.get("until", "14:30"))) & (np.abs(T["move_atr"]) >= c["move_atr"]) & (side != 0)
    if c.get("vol_x", 1.0) > 1.0:
        m &= T["vol_x"] >= c["vol_x"]
    if c.get("flow", 0) > 0:
        m &= np.where(side > 0, T["flow_share"] >= c["flow"], T["flow_share"] <= 1 - c["flow"])
    if c.get("range") == "room":      # still has room: range so far under 1.2x the usual day
        m &= T["range_x"] <= 1.2
    elif c.get("range") == "wide":    # already a wide day
        m &= T["range_x"] >= 0.8
    if c.get("sector"):
        m &= np.where(side > 0, T["sec_flow"] >= 0.52, T["sec_flow"] <= 0.48)
    if c.get("market"):
        m &= np.where(side > 0, T["mkt_flow"] >= 0.51, T["mkt_flow"] <= 0.49)
    return m


def first_signals(T: dict, m: np.ndarray, top: int) -> np.ndarray:
    """Rows where the rule fires for the first time that day for that stock; then the first `top` of each day in time
    order (rows are sorted by day, minute, stock, so array order is time order)."""
    idx = np.flatnonzero(m)
    if not len(idx):
        return idx
    key = T["sym"][idx].astype(np.int64) * 100000 + (T["day"][idx] - T["day"].min())
    _, first = np.unique(key, return_index=True)
    sel = np.sort(idx[first])
    if top < 99:
        days = T["day"][sel]
        start = np.r_[0, np.flatnonzero(np.diff(days)) + 1]
        rank = np.arange(len(sel)) - np.repeat(start, np.diff(np.r_[start, len(sel)]))
        sel = sel[rank < top]
    return sel


def trade_returns(T: dict, sel: np.ndarray, side: np.ndarray, k: float, cost: float) -> np.ndarray:
    e, x, a = T["entry"][sel].astype(float), T["exit"][sel].astype(float), T["atr"][sel].astype(float)
    s = side[sel]
    hit = np.where(s > 0, e - T["minlow"][sel] >= k * a, T["maxhigh"][sel] - e >= k * a)
    return np.where(hit, -k * a / e, s * (x - e) / e) - cost


def stats(r: np.ndarray, days: np.ndarray) -> dict:
    n = len(r)
    if n == 0:
        return {"n": 0}
    mean, sd = float(r.mean()), float(r.std(ddof=1)) if n > 1 else 0.0
    wins, losses = r[r > 0].sum(), -r[r <= 0].sum()
    yrs = max((int(days.max()) - int(days.min())) / 365.25, 0.1)
    return {"n": n, "per_trade_pct": round(mean * 100, 3), "win_pct": round(float((r > 0).mean()) * 100, 1),
            "t": round(mean / sd * np.sqrt(n), 2) if sd > 0 else 0.0,
            "profit_factor": round(float(wins / losses), 2) if losses > 0 else None,
            "per_year": round(n / yrs), "total_pct": round(float(r.sum()) * 100, 1)}


def evaluate(T: dict, c: dict, split: int, cost: float = COST) -> tuple[dict, dict]:
    side = np.sign(T["move"]).astype(np.int8)
    sel = first_signals(T, rule_mask(T, c, side), c.get("top", 99))
    if not len(sel):
        return {"n": 0}, {"n": 0}
    r = trade_returns(T, sel, side, c["stop"], cost)
    d = T["day"][sel]
    tr = d < split
    return stats(r[tr], d[tr]), stats(r[~tr], d[~tr])


def describe(c: dict, what: str = "stocks") -> str:
    parts = [f"{what} {c['move_atr']}+ ATR from the open, any time 9:30-{c.get('until', '14:30')}"]
    if c.get("flow", 0) > 0:
        parts.append(f"{c['flow'] * 100:.0f}%+ of turnover buying (short: selling)")
    if c.get("vol_x", 1.0) > 1.0:
        parts.append(f"volume {c['vol_x']}x+ the usual by that time")
    parts.append({"any": "", "room": "range still under 1.2x the usual day", "wide": "range already 0.8x+ the usual day",
                  None: ""}[c.get("range")])
    if c.get("sector"):
        parts.append("sector money the same way")
    if c.get("market"):
        parts.append("market money the same way")
    if c.get("top", 99) < 99:
        parts.append(f"first {c['top']} signal{'s' if c['top'] > 1 else ''} of the day")
    parts.append(f"trade with the move from the next candle, stop {c['stop']} ATR, exit 15:20")
    return "; ".join(p for p in parts if p)


def neighbours(T: dict, c: dict, split: int, grid: dict, cost: float) -> float:
    pos = tot = 0
    for k, vals in grid.items():
        for v in vals:
            if v == c.get(k):
                continue
            tr, _ = evaluate(T, {**c, k: v}, split, cost)
            if tr.get("n", 0) >= 30:
                tot += 1
                pos += tr["per_trade_pct"] > 0
    return round(100 * pos / tot, 0) if tot else 0.0


def verdict(r: dict) -> str:
    te = r["test"]
    if te.get("n", 0) >= 40 and te["per_trade_pct"] >= 0.05 and te["t"] >= 2 and r["neighbours_positive_pct"] >= 60:
        return "pass"
    if te.get("n", 0) >= 20 and te.get("per_trade_pct", -1) > 0:
        return "watch"
    return "fail"


def search(T: dict, grid: dict = GRID, cost: float = COST, what: str = "stocks", min_train: int = 60,
           keep: int = 12) -> dict:
    days = np.unique(T["day"])
    split = int(days[int(len(days) * TRAIN)])
    combos = [dict(zip(grid, v)) for v in itertools.product(*grid.values())]
    log(f"{what}: {len(combos)} rules on {len(T['day']):,} candles, {len(days)} days")
    t0, scored = time.time(), []
    for c in combos:
        tr, _ = evaluate(T, c, split, cost)
        if tr.get("n", 0) >= min_train:
            scored.append((tr["t"], c, tr))
    scored.sort(key=lambda x: -x[0])
    seen, results = set(), []
    for _, c, tr in scored:
        sig = (c["move_atr"], c.get("flow", 0) > 0, c.get("vol_x", 1.0), c.get("until"))
        if sig in seen:
            continue
        seen.add(sig)
        _, te = evaluate(T, c, split, cost)
        r = {"rule": c, "text": describe(c, what), "train": tr, "test": te,
             "neighbours_positive_pct": neighbours(T, c, split, grid, cost)}
        r["verdict"] = verdict(r)
        results.append(r)
        if len(results) >= keep:
            break
    log(f"{what}: done in {time.time() - t0:.0f}s")
    return {"split": str(np.datetime64(split, "D")), "days": int(len(days)), "candles": int(len(T["day"])),
            "rules_tried": len(combos), "top": results,
            "best": next((r for r in results if r["verdict"] == "pass"), None)}

# ---------------------------------------------------------------- indices


def constituent_flow(bars: dict, weights: dict) -> pd.DataFrame:
    """Per 5-minute candle: weighted inflow / outflow of an index's stocks (weights in %)."""
    parts = []
    for s, w in (weights or {}).items():
        d = clean(bars.get(s))
        if d.empty:
            continue
        rng = (d["High"] - d["Low"]).to_numpy()
        press = np.where(rng > 0, (d["Close"] - d["Open"]).to_numpy() / np.where(rng > 0, rng, 1), 0.0)
        turn = d["Volume"].to_numpy() * d["Close"].to_numpy() * w / 100
        parts.append(pd.DataFrame({"inflow": turn * (1 + press) / 2, "outflow": turn * (1 - press) / 2}, index=d.index))
    return pd.concat(parts).groupby(level=0).sum().sort_index() if parts else pd.DataFrame()


INDEX_GRID = {"move_atr": [0.3, 0.5, 0.8], "flow": [0.0, 0.55, 0.6], "range": ["any", "room"], "stop": [0.5, 1.0],
              "until": ["11:30", "14:30"]}


def index_research(indices: dict, stocks: dict, weights: dict) -> dict:
    out = {}
    for k, df in indices.items():
        w = (weights or {}).get(k) or {s: 1.0 for s in stocks}      # no weights: the whole F&O market
        t = candle_table(k, df, constituent_flow(stocks, w))
        if not t.get("n"):
            continue
        T = {kk: v for kk, v in t.items() if kk != "n"}
        T["sym"] = np.zeros(t["n"], dtype=np.int32)
        T["vol_x"] = np.full(t["n"], 1.0, dtype=np.float32)
        T["sec_flow"] = T["mkt_flow"] = T["flow_share"]
        res = search(T, INDEX_GRID, INDEX_COST, INDEX_NAMES.get(k, k), min_train=30, keep=5)
        res["macd"] = macd_test(df, constituent_flow(stocks, w))
        out[k] = res
    return out


def macd_test(index_bars: pd.DataFrame, flow: pd.DataFrame) -> dict:
    n = clean(index_bars)
    if n.empty or flow is None or flow.empty:
        return {}
    net = (flow["inflow"] - flow["outflow"]).reindex(n.index).fillna(0)
    m = n["Close"].ewm(span=12, adjust=False).mean() - n["Close"].ewm(span=26, adjust=False).mean()
    side = np.sign(m - m.ewm(span=9, adjust=False).mean())
    f30 = net.rolling(6).sum()
    day = n.index.normalize()
    mins = np.asarray(n.index.hour) * 60 + np.asarray(n.index.minute)
    rows = []
    for i in np.flatnonzero((side != side.shift()) & (side != 0)):
        if i + 1 >= len(n) or not (FIRST <= mins[i] <= LAST) or day[i + 1] != day[i]:
            continue
        s_ = int(side.iloc[i])
        e, k = float(n["Open"].iloc[i + 1]), i + 1
        while k + 1 < len(n) and day[k + 1] == day[i] and mins[k] < EXIT and side.iloc[k] == s_:
            k += 1
        rows.append({"day": int(np.datetime64(day[i].date(), "D").astype(np.int64)),
                     "ret": s_ * (float(n["Close"].iloc[k]) - e) / e - INDEX_COST, "backed": bool(np.sign(f30.iloc[i]) == s_)})
    if not rows:
        return {}
    t = pd.DataFrame(rows)
    split = np.sort(t["day"].unique())[int(t["day"].nunique() * TRAIN)]
    res = {}
    for name, sub in (("all_crosses", t), ("flow_backed", t[t["backed"]]), ("flow_against", t[~t["backed"]])):
        a, b = sub[sub["day"] < split], sub[sub["day"] >= split]
        res[name] = {"train": stats(a["ret"].to_numpy(), a["day"].to_numpy()),
                     "test": stats(b["ret"].to_numpy(), b["day"].to_numpy())}
    return res


# ---------------------------------------------------------------- odds: what happened after similar moments

ODDS_BINS = {"vol": [0, 1.5, 2.5, 4, np.inf], "mv": [0, 0.3, 0.6, 1.0, np.inf]}
ODDS_TIMES = [630, 720, 871]          # up to 10:30, up to 12:00, up to 14:30 (minutes)


def _odds_keys(m, vol_x, move_atr, flow_share, side) -> pd.DataFrame:
    agree = np.where(side > 0, flow_share >= 0.55, flow_share <= 0.45)
    return pd.DataFrame({
        "side": side.astype(np.int8),
        "tb": np.searchsorted(ODDS_TIMES, m, side="left").clip(0, 2).astype(np.int8),
        "vol": (np.digitize(np.nan_to_num(vol_x, nan=1.0), ODDS_BINS["vol"][1:-1])).astype(np.int8),
        "mv": (np.digitize(np.abs(np.nan_to_num(move_atr)), ODDS_BINS["mv"][1:-1])).astype(np.int8),
        "fl": agree.astype(np.int8)})


def odds_table(T: dict, cost: float = COST) -> dict:
    """For every kind of moment (side, time of day, volume vs usual, move from open in ATR, money flow agreeing),
    what happened next on past days: share that kept going to 15:15, average result after costs, share that ran
    another 1 ATR. Each stock-day counts once per kind (its first such candle)."""
    if not T:
        return {}
    side = np.sign(T["move"]).astype(np.int8)
    k = _odds_keys(T["m"], T["vol_x"], T["move_atr"], T["flow_share"], side)
    ok = (side != 0) & np.isfinite(T["entry"]) & np.isfinite(T["exit"]) & (T["atr"] > 0)
    k["sym"], k["day"] = T["sym"], T["day"]
    s = side.astype(float)
    ret = s * (T["exit"] / T["entry"] - 1) - cost
    fav = np.where(side > 0, T["maxhigh"] - T["entry"], T["entry"] - T["minlow"]) / T["atr"]
    k["ret"], k["run"] = ret, fav >= 1.0
    k = k[ok].drop_duplicates(["sym", "day", "side", "tb", "vol", "mv", "fl"])
    out = {"days": int(len(np.unique(T["day"]))), "levels": {}}
    for name, cols in (("full", ["side", "tb", "vol", "mv", "fl"]), ("no_time", ["side", "vol", "mv", "fl"]),
                       ("coarse", ["side", "vol", "mv"])):
        g = k.groupby(cols).agg(n=("ret", "size"), win=("ret", lambda r: float((r > 0).mean())),
                                avg=("ret", "mean"), run=("run", "mean"))
        out["levels"][name] = {"|".join(map(str, i if isinstance(i, tuple) else (i,))):
                               [int(r.n), round(r.win * 100, 1), round(r.avg * 100, 3), round(r.run * 100, 1)]
                               for i, r in g.iterrows()}
    base = k.groupby("side")["ret"].agg(lambda r: float((r > 0).mean()))
    out["base_win"] = {str(int(i)): round(v * 100, 1) for i, v in base.items()}
    return out


def odds_lookup(table: dict, m: float, vol_x: float, move_atr: float, flow_share: float, side: int,
                min_n: int = 40) -> dict | None:
    """The odds for one moment now: the most specific level with enough past cases."""
    if not table or not side:
        return None
    k = _odds_keys(np.array([m]), np.array([vol_x]), np.array([move_atr]), np.array([flow_share]),
                   np.array([side])).iloc[0]
    keys = {"full": [k.side, k.tb, k.vol, k.mv, k.fl], "no_time": [k.side, k.vol, k.mv, k.fl],
            "coarse": [k.side, k.vol, k.mv]}
    for level in ("full", "no_time", "coarse"):
        v = table["levels"].get(level, {}).get("|".join(str(int(x)) for x in keys[level]))
        if v and v[0] >= min_n:
            return {"n": int(v[0]), "win": float(v[1]), "avg": float(v[2]), "run": float(v[3]), "level": level,
                    "edge": round(float(v[1]) - float(table.get("base_win", {}).get(str(int(side)), 50.0)), 1)}
    return None

# ---------------------------------------------------------------- live: today's first signals of a passed rule


def live_signals(rule: dict, T_today: dict) -> list[dict]:
    """First signals today of a passed stock rule, from a today-only table (build_table(..., keep_all_days=False))."""
    if not T_today:
        return []
    side = np.sign(T_today["move"]).astype(np.int8)
    sel = first_signals(T_today, rule_mask(T_today, rule, side), rule.get("top", 99))
    out = []
    for i in sel:
        s = int(side[i])
        px, a = float(T_today["price"][i]), float(T_today["atr"][i])
        m = int(T_today["m"][i])
        out.append({"stock": str(T_today["names"][T_today["sym"][i]]), "side": "BUY" if s > 0 else "SELL",
                    "time": f"{m // 60:02d}:{m % 60:02d}", "price": round(px, 2), "stop": round(px - s * rule["stop"] * a, 2),
                    "flow_share": round(float(T_today["flow_share"][i]) * 100, 1),
                    "vol_x": round(float(T_today["vol_x"][i]), 2), "move_atr": round(float(T_today["move_atr"][i]), 2)})
    return out

# ---------------------------------------------------------------- run


def run(cfg: dict | None = None, stocks: dict | None = None, indices: dict | None = None,
        weights: dict | None = None) -> dict:
    import universe as U
    t0 = time.time()
    BOT_DIR.mkdir(parents=True, exist_ok=True)
    if stocks is None:
        stocks, indices = load_history(cfg)
    if weights is None:
        try:
            import indices as IX
            weights = {k: d.get("w", {}) for k, d in IX.load().items()}
        except Exception:
            weights = {}
    log(f"{len(stocks)} F&O stocks, {len(indices or {})} indices loaded")
    T = build_table(stocks, U.FNO_SECTOR_OF)
    if not T:
        raise RuntimeError("not enough history yet")
    res = {"stocks": search(T)}
    res["indices"] = index_research(indices or {}, stocks, weights)
    res["run_at"] = datetime.now(IST).isoformat(timespec="seconds")
    res["seconds"] = round(time.time() - t0)
    res["best"] = res["stocks"]["best"]
    tmp = BOT_DIR / "latest.json.tmp"
    tmp.write_text(json.dumps(res, indent=2, default=str))
    os.replace(tmp, BOT_DIR / "latest.json")
    try:
        import cloudstore
        if not cloudstore.enabled():
            try:
                import streamlit as st
                sb = dict(st.secrets.get("supabase") or {})
                cloudstore.configure(sb.get("url"), sb.get("key"))
            except Exception:
                cloudstore.configure(None, None)
        cloudstore.upsert_rows("bot_results", [{"run_at": res["run_at"], "result": json.loads(json.dumps(res, default=str))}],
                               "run_at")
        time.sleep(3)  # the upload runs in the background: give it a moment before the process ends
    except Exception as e:
        log(f"Supabase: {e}")
    n_pass = sum(r["verdict"] == "pass" for r in res["stocks"]["top"])
    n_ix = sum(1 for v in res["indices"].values() if v.get("best"))
    log(f"done in {res['seconds']}s: {n_pass} stock rule(s) passed, {n_ix} index rule(s) passed")
    return res


def latest() -> dict | None:
    try:
        return json.loads((BOT_DIR / "latest.json").read_text())
    except Exception:
        return None


if __name__ == "__main__":
    run()
