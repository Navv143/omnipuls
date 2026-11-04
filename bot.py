"""Setup Finder: our research bot. Runs on the server outside market hours (recorder.py starts it) and looks for
intraday setups that combine money flow with volume, ATR / range, sector and market agreement - and keeps only the
ones that still work on days they were not tuned on.

1. Data: 5-minute candles for the Nifty 100 stocks and the Nifty index from Dhan (a year, cached on the server and
   topped up each night).
2. Events: for every stock, day and decision time (10:00, 10:30, 11:00, 12:00) the readings so far today:
   money-flow buying share and net flow vs the usual day's turnover, volume vs the usual volume by that time, range
   so far vs the average day's range, move from the open in ATR, gap, open = high / low, and the sector's and the
   market's buying share at the same moment. Outcome: entry at the next candle's open, exit at 15:20, or a stop of
   0.5 / 1 ATR.
3. Search: ~5,000 rule combinations (long and short together), after 0.12% round-trip costs. Each is scored on the
   first 60% of days; the best are judged ONLY on the last 40% (never seen while choosing) and on their neighbours
   (one setting changed), so a lucky setting does not pass.
4. Nifty: MACD crosses on 5-minute Nifty, with and without the Nifty 100 money flow agreeing, same split.
5. Results: <data>/bot/latest.json (the app's Setup Finder page and Market View) and the Supabase table bot_results.

Usage: python bot.py            (run once now; needs Dhan in dhan_config.json / Secrets)
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
TIMES = ("10:00", "10:30", "11:00", "12:00")
EXIT = "15:15"            # the 15:15 candle's close (15:20) is the exit
COST = 0.0012             # stocks: 0.12% round trip (same as the research)
INDEX_COST = 0.0002       # Nifty futures: about 5 points on 24,000 incl. slippage
TRAIN = 0.6
HISTORY_DAYS = int(os.environ.get("BOT_HISTORY_DAYS", 365))
STATUS: dict = {}


def log(msg: str):
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} bot: {msg}", flush=True)

# ---------------------------------------------------------------- data


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    d.index = idx
    d = d[~d.index.duplicated(keep="last")].sort_index().between_time("09:15", "15:25")
    return d[["Open", "High", "Low", "Close", "Volume"]].astype(float)


def load_history(cfg: dict | None = None, days: int = HISTORY_DAYS) -> tuple[dict, pd.DataFrame]:
    """{stock: 5-min bars}, nifty bars. Cached per symbol; each run fetches only the last 10 days again."""
    import dhan as D
    import scanners as SC
    CACHE.mkdir(parents=True, exist_ok=True)
    cfg = cfg or D.load_config()
    eq = D.equity_ids(cfg)
    wanted = [("NIFTY", "IDX_I", 13, "INDEX")] + [(s, "NSE_EQ", eq[s], "EQUITY") for s in SC.NIFTY100 if s in eq]
    out = {}
    for i, (sym, seg, sid, ins) in enumerate(wanted, 1):
        f = CACHE / f"{sym.replace('&', '_and_')}.parquet"
        old = pd.read_parquet(f) if f.exists() else pd.DataFrame()
        span = 10 if not old.empty and (pd.Timestamp.now() - old.index.max()).days < 9 else days
        try:
            new = _clean(D.intraday(seg, sid, ins, 5, span, cfg))
        except Exception as e:
            log(f"{sym}: {getattr(e, 'friendly', e)}")
            new = pd.DataFrame()
        df = pd.concat([old, new]) if not old.empty else new
        if df.empty:
            continue
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[df.index >= df.index.max() - pd.Timedelta(days=days + 5)]
        df.to_parquet(f)
        out[sym] = df
        if i % 20 == 0:
            log(f"history {i}/{len(wanted)}")
    return {k: v for k, v in out.items() if k != "NIFTY"}, out.get("NIFTY", pd.DataFrame())

# ---------------------------------------------------------------- features and outcomes


_HHMM = np.array([f"{m // 60:02d}:{m % 60:02d}" for m in range(1440)], dtype=object)


def _hhmm(idx) -> np.ndarray:
    idx = pd.DatetimeIndex(idx)
    return _HHMM[np.asarray(idx.hour) * 60 + np.asarray(idx.minute)]


def _prev(t: str) -> str:
    h, m = map(int, t.split(":"))
    m -= 5
    return f"{h - (m < 0):02d}:{m % 60:02d}"


def stock_events(sym: str, df: pd.DataFrame, times=TIMES) -> pd.DataFrame:
    """One row per (day, decision time): the readings from the open to that time, and what happened after."""
    d = _clean(df)
    if len(d) < 75 * 25:
        return pd.DataFrame()
    O, H, L, C, V = (d[c].to_numpy() for c in ("Open", "High", "Low", "Close", "Volume"))
    day = d.index.normalize()
    slot = _hhmm(d.index)
    rng = H - L
    prevc = np.r_[np.nan, C[:-1]]
    press = np.where(rng > 0, (C - O) / np.where(rng > 0, rng, 1), np.sign(np.nan_to_num(C - prevc)))
    turn = V * (H + L + C) / 3
    frame = pd.DataFrame({"day": day, "slot": slot, "O": O, "H": H, "L": L, "C": C, "V": V, "turn": turn,
                          "inf": turn * (1 + press) / 2, "outf": turn * (1 - press) / 2}, index=d.index)
    g = frame.groupby("day", sort=True)
    frame["cumv"] = g["V"].cumsum()
    frame["cumin"] = g["inf"].cumsum()
    frame["cumout"] = g["outf"].cumsum()
    frame["hi"] = g["H"].cummax()
    frame["lo"] = g["L"].cummin()
    frame["dopen"] = g["O"].transform("first")
    daily = g.agg(o=("O", "first"), h=("H", "max"), l=("L", "min"), c=("C", "last"), turn=("turn", "sum"))
    pc = daily["c"].shift(1)
    tr = pd.concat([daily["h"] - daily["l"], (daily["h"] - pc).abs(), (daily["l"] - pc).abs()], axis=1).max(axis=1)
    daily["atr"] = tr.rolling(14).mean().shift(1)
    daily["avg_rng"] = (daily["h"] - daily["l"]).rolling(14).mean().shift(1)
    daily["avg_turn"] = daily["turn"].rolling(20).mean().shift(1)
    daily["prev_c"] = pc
    # usual cumulative volume by time of day: same slot, last 20 days
    cv = frame.pivot_table(index="day", columns="slot", values="cumv", aggfunc="last")
    usual_cv = cv.rolling(20, min_periods=10).mean().shift(1)
    # path after entry: lowest low / highest high from each candle to the exit candle (same day)
    upto = frame["slot"] <= EXIT
    lo_x = frame["L"].where(upto)
    hi_x = frame["H"].where(upto)
    frame["minlow_after"] = lo_x[::-1].groupby(frame["day"][::-1]).cummin()[::-1]
    frame["maxhigh_after"] = hi_x[::-1].groupby(frame["day"][::-1]).cummax()[::-1]
    exit_px = frame[frame["slot"] == EXIT].set_index("day")["C"]
    rows = []
    for t in times:
        dec = frame[frame["slot"] == _prev(t)]                      # last completed candle at time t
        ent = frame[frame["slot"] == t].set_index("day")             # the next candle: entry at its open
        if dec.empty or ent.empty:
            continue
        dd = dec.set_index("day")
        common = dd.index.intersection(ent.index).intersection(exit_px.index).intersection(daily.dropna().index)
        if not len(common):
            continue
        dd, en, dl = dd.loc[common], ent.loc[common], daily.loc[common]
        ucv = usual_cv[_prev(t)].reindex(common) if _prev(t) in usual_cv else pd.Series(np.nan, index=common)
        r = pd.DataFrame(index=common)
        r["sym"], r["t"] = sym, t
        r["move"] = dd["C"] / dd["dopen"] - 1
        r["move_atr"] = (dd["C"] - dd["dopen"]) / dl["atr"]
        r["range_x"] = (dd["hi"] - dd["lo"]) / dl["avg_rng"]
        r["vol_x"] = dd["cumv"] / ucv
        tot = dd["cumin"] + dd["cumout"]
        r["flow_share"] = np.where(tot > 0, dd["cumin"] / tot, 0.5)
        r["flow_x"] = (dd["cumin"] - dd["cumout"]) / dl["avg_turn"]
        r["gap"] = dl["o"] / dl["prev_c"] - 1
        tol = dl["o"] * 0.0005
        r["o_eq_l"] = (dl["o"] - dd["lo"]).abs() <= tol   # opened at the low so far
        r["o_eq_h"] = (dd["hi"] - dl["o"]).abs() <= tol
        r["entry"] = en["O"]
        r["exit"] = exit_px.loc[common]
        r["atr"] = dl["atr"]
        r["minlow"] = en["minlow_after"]
        r["maxhigh"] = en["maxhigh_after"]
        rows.append(r.reset_index(names="day"))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def build_events(bars: dict, sectors: dict | None = None) -> pd.DataFrame:
    ev = [stock_events(s, df) for s, df in bars.items()]
    ev = pd.concat([e for e in ev if not e.empty], ignore_index=True) if any(not e.empty for e in ev) else pd.DataFrame()
    if ev.empty:
        return ev
    ev = ev.replace([np.inf, -np.inf], np.nan).dropna(subset=["move_atr", "range_x", "vol_x", "atr", "entry", "exit"])
    ev = ev.reset_index(drop=True)  # row labels must equal row positions (picks are used both ways)
    ev["sector"] = ev["sym"].map(sectors or {}).fillna("Other")
    ev["mkt_flow"] = ev.groupby(["day", "t"])["flow_share"].transform("mean")
    ev["sec_flow"] = ev.groupby(["day", "t", "sector"])["flow_share"].transform("mean")
    return ev


def returns(ev: pd.DataFrame, side: np.ndarray, k: float) -> np.ndarray:
    """Net return of each event for side (+1 long, -1 short) with a stop of k ATR, exit at 15:20."""
    e, x, a = ev["entry"].to_numpy(), ev["exit"].to_numpy(), ev["atr"].to_numpy()
    stop_hit = np.where(side > 0, e - ev["minlow"].to_numpy() >= k * a, ev["maxhigh"].to_numpy() - e >= k * a)
    r = np.where(stop_hit, -k * a / e, side * (x - e) / e)
    return r - COST

# ---------------------------------------------------------------- search


GRID = {"t": list(TIMES), "move_atr": [0.3, 0.5, 0.8], "flow": [0.0, 0.55, 0.6, 0.65], "vol_x": [1.0, 1.5, 2.0],
        "range": ["any", "room", "wide"], "sector": [False, True], "market": [False, True], "stop": [0.5, 1.0],
        "top": [1, 3]}
FLOW_STEPS = GRID["flow"]


def _mask(ev: pd.DataFrame, c: dict, side: np.ndarray) -> np.ndarray:
    m = (ev["t"].to_numpy() == c["t"]) & (np.abs(ev["move_atr"].to_numpy()) >= c["move_atr"])
    m &= ev["vol_x"].to_numpy() >= c["vol_x"]
    if c["flow"] > 0:
        fs = ev["flow_share"].to_numpy()
        m &= np.where(side > 0, fs >= c["flow"], fs <= 1 - c["flow"])
    if c["range"] == "room":      # still has room: range so far under 1.2x the usual day
        m &= ev["range_x"].to_numpy() <= 1.2
    elif c["range"] == "wide":    # already a wide day: range at least 0.8x the usual
        m &= ev["range_x"].to_numpy() >= 0.8
    if c["sector"]:
        sf = ev["sec_flow"].to_numpy()
        m &= np.where(side > 0, sf >= 0.52, sf <= 0.48)
    if c["market"]:
        mf = ev["mkt_flow"].to_numpy()
        m &= np.where(side > 0, mf >= 0.51, mf <= 0.49)
    return m


def _pick_top(ev: pd.DataFrame, m: np.ndarray, top: int) -> np.ndarray:
    """Within each day, keep the `top` events with the biggest |net flow vs usual turnover|."""
    idx = np.flatnonzero(m)
    if not len(idx):
        return idx
    sub = ev.iloc[idx]
    order = sub.assign(_k=-sub["flow_x"].abs()).sort_values(["day", "_k"])
    keep = order.groupby("day").head(top).index
    return np.asarray(keep)


def _stats(r: np.ndarray, days: np.ndarray) -> dict:
    n = len(r)
    if n == 0:
        return {"n": 0}
    mean, sd = float(r.mean()), float(r.std(ddof=1)) if n > 1 else 0.0
    wins, losses = r[r > 0].sum(), -r[r <= 0].sum()
    yrs = max((pd.Timestamp(days.max()) - pd.Timestamp(days.min())).days / 365.25, 0.1)
    return {"n": n, "per_trade_pct": round(mean * 100, 3), "win_pct": round(float((r > 0).mean()) * 100, 1),
            "t": round(mean / sd * np.sqrt(n), 2) if sd > 0 else 0.0,
            "profit_factor": round(float(wins / losses), 2) if losses > 0 else None,
            "per_year": round(n / yrs), "total_pct": round(float(r.sum()) * 100, 1)}


def evaluate(ev: pd.DataFrame, c: dict, days_split) -> tuple[dict, dict]:
    side = np.sign(ev["move"].to_numpy())
    pick = _pick_top(ev, _mask(ev, c, side) & (side != 0), c["top"])
    if not len(pick):
        return {"n": 0}, {"n": 0}
    r = returns(ev.iloc[pick], side[pick], c["stop"])
    dsel = ev["day"].to_numpy()[pick]
    tr = dsel < days_split
    return _stats(r[tr], dsel[tr]), _stats(r[~tr], dsel[~tr])


def describe(c: dict) -> str:
    parts = [f"at {c['t']}, stocks {c['move_atr']}+ ATR from the open"]
    if c["flow"] > 0:
        parts.append(f"with {c['flow'] * 100:.0f}%+ of turnover buying (short: selling)")
    if c["vol_x"] > 1.0:
        parts.append(f"volume {c['vol_x']}x+ the usual by this time")
    parts.append({"any": "", "room": "range still under 1.2x the usual day", "wide": "range already 0.8x+ the usual day"}
                 [c["range"]])
    if c["sector"]:
        parts.append("sector money flowing the same way")
    if c["market"]:
        parts.append("market money flowing the same way")
    parts.append(f"top {c['top']} a day by money flow; trade with the move, stop {c['stop']} ATR, exit 15:20")
    return "; ".join(p for p in parts if p)


def search(ev: pd.DataFrame, min_train_trades: int = 60, keep: int = 12) -> dict:
    days = np.sort(ev["day"].unique())
    split = days[int(len(days) * TRAIN)]
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
    log(f"searching {len(combos)} rules on {len(ev):,} events, {len(days)} days (train to {pd.Timestamp(split):%d %b %Y})")
    scored = []
    t0 = time.time()
    for c in combos:
        tr, _ = evaluate(ev, c, split)
        if tr.get("n", 0) >= min_train_trades:
            scored.append((tr["t"], c, tr))
    scored.sort(key=lambda x: -x[0])
    seen, results = set(), []
    for _, c, tr in scored:
        sig = (c["t"], c["move_atr"], c["flow"] > 0, c["vol_x"])   # don't report near-copies of the same rule
        if sig in seen:
            continue
        seen.add(sig)
        _, te = evaluate(ev, c, split)
        nb = neighbours(ev, c, split)
        results.append({"rule": c, "text": describe(c), "train": tr, "test": te, "neighbours_positive_pct": nb})
        if len(results) >= keep:
            break
    base = {"rule": "every stock 0.5+ ATR from the open at 10:30, with the move, stop 1 ATR, exit 15:20"}
    b_tr, b_te = evaluate(ev, {"t": "10:30", "move_atr": 0.5, "flow": 0.0, "vol_x": 1.0, "range": "any",
                               "sector": False, "market": False, "stop": 1.0, "top": 99}, split)
    base.update(train=b_tr, test=b_te)
    log(f"search done in {time.time() - t0:.0f}s, {len(scored)} rules had enough trades")
    return {"split": str(pd.Timestamp(split).date()), "days": len(days), "events": int(len(ev)),
            "rules_tried": len(combos), "top": results, "baseline": base}


def neighbours(ev: pd.DataFrame, c: dict, split) -> float:
    """Share of rules one setting away that are also profitable on the training days (robustness)."""
    pos = tot = 0
    for k, vals in GRID.items():
        if k in ("t",):
            continue
        for v in vals:
            if v == c[k]:
                continue
            tr, _ = evaluate(ev, {**c, k: v}, split)
            if tr.get("n", 0) >= 30:
                tot += 1
                pos += tr["per_trade_pct"] > 0
    return round(100 * pos / tot, 0) if tot else 0.0


def verdict(r: dict) -> str:
    te, tr = r["test"], r["train"]
    if te.get("n", 0) >= 40 and te["per_trade_pct"] >= 0.05 and te["t"] >= 2 and r["neighbours_positive_pct"] >= 60:
        return "pass"
    if te.get("n", 0) >= 20 and te.get("per_trade_pct", -1) > 0:
        return "watch"
    return "fail"

# ---------------------------------------------------------------- Nifty: MACD crosses with and without money flow


def nifty_macd(nifty: pd.DataFrame, bars: dict) -> dict:
    n = _clean(nifty)
    if n.empty:
        return {}
    flows = []
    for s, df in bars.items():
        d = _clean(df)
        if d.empty:
            continue
        rng = (d["High"] - d["Low"]).to_numpy()
        press = np.where(rng > 0, (d["Close"] - d["Open"]).to_numpy() / np.where(rng > 0, rng, 1), 0.0)
        flows.append(pd.Series(d["Volume"].to_numpy() * d["Close"].to_numpy() * press, index=d.index))
    if not flows:
        return {}
    flow = pd.concat(flows, axis=1).sum(axis=1).reindex(n.index).fillna(0)
    e1, e2 = n["Close"].ewm(span=12, adjust=False).mean(), n["Close"].ewm(span=26, adjust=False).mean()
    m = e1 - e2
    sig = m.ewm(span=9, adjust=False).mean()
    side = np.sign(m - sig)
    f30 = flow.rolling(6).sum()
    day = n.index.normalize()
    slot = _hhmm(n.index)
    rows = []
    idx = np.flatnonzero((side != side.shift()) & (side != 0))
    for i in idx:
        if i + 1 >= len(n) or not ("09:30" <= slot[i] <= "14:30") or day[i + 1] != day[i]:
            continue
        s_ = int(side.iloc[i])
        j = i + 1
        e = float(n["Open"].iloc[j])
        k = j
        while k + 1 < len(n) and day[k + 1] == day[i] and slot[k] < EXIT and side.iloc[k] == s_:
            k += 1
        x = float(n["Close"].iloc[k])
        rows.append({"day": day[i], "side": s_, "ret": s_ * (x - e) / e - INDEX_COST,
                     "backed": bool(np.sign(f30.iloc[i]) == s_)})
    if not rows:
        return {}
    t = pd.DataFrame(rows)
    days = np.sort(t["day"].unique())
    split = days[int(len(days) * TRAIN)]
    out = {}
    for name, sub in (("all_crosses", t), ("flow_backed", t[t["backed"]]), ("flow_against", t[~t["backed"]])):
        tr, te = sub[sub["day"] < split], sub[sub["day"] >= split]
        out[name] = {"train": _stats(tr["ret"].to_numpy(), tr["day"].to_numpy()),
                     "test": _stats(te["ret"].to_numpy(), te["day"].to_numpy())}
    return out

# ---------------------------------------------------------------- live matches for the app


def live_matches(rule: dict, bars: dict, sectors: dict | None = None, now_hhmm: str | None = None) -> pd.DataFrame:
    """Stocks matching a found rule today (at its decision time, once it has passed)."""
    now_hhmm = now_hhmm or datetime.now(IST).strftime("%H:%M")
    if now_hhmm < rule["t"]:
        return pd.DataFrame()
    ev = []
    for s, df in bars.items():
        e = stock_events(s, df, times=(rule["t"],))
        if not e.empty:
            ev.append(e[e["day"] == e["day"].max()])
    if not ev:
        return pd.DataFrame()
    ev = pd.concat(ev, ignore_index=True)
    ev = ev[ev["day"] == ev["day"].max()].replace([np.inf, -np.inf], np.nan).reset_index(drop=True)
    ev["sector"] = ev["sym"].map(sectors or {}).fillna("Other")
    ev["mkt_flow"] = ev["flow_share"].mean()
    ev["sec_flow"] = ev.groupby("sector")["flow_share"].transform("mean")
    side = np.sign(ev["move"].to_numpy())
    pick = _pick_top(ev, _mask(ev, rule, side) & (side != 0), rule["top"])
    out = ev.iloc[pick].copy() if len(pick) else pd.DataFrame()
    if out.empty:
        return out
    s = np.sign(out["move"])
    out["Side"] = np.where(s > 0, "BUY", "SELL")
    out["Stop"] = out["entry"] - s * rule["stop"] * out["atr"]
    return out.rename(columns={"sym": "Stock", "entry": "Entry"})[["Stock", "Side", "Entry", "Stop", "flow_share",
                                                                    "vol_x", "move_atr"]]

# ---------------------------------------------------------------- run


def run(cfg: dict | None = None, bars: dict | None = None, nifty: pd.DataFrame | None = None) -> dict:
    import universe as U
    t0 = time.time()
    BOT_DIR.mkdir(parents=True, exist_ok=True)
    if bars is None:
        bars, nifty = load_history(cfg)
    log(f"{len(bars)} stocks loaded")
    ev = build_events(bars, U.FNO_SECTOR_OF)
    if ev.empty:
        raise RuntimeError("no events: not enough history yet")
    res = search(ev)
    for r in res["top"]:
        r["verdict"] = verdict(r)
    res["nifty_macd"] = nifty_macd(nifty if nifty is not None else pd.DataFrame(), bars)
    res["run_at"] = datetime.now(IST).isoformat(timespec="seconds")
    res["seconds"] = round(time.time() - t0)
    res["best"] = next((r for r in res["top"] if r["verdict"] == "pass"), None)
    tmp = BOT_DIR / "latest.json.tmp"
    tmp.write_text(json.dumps(res, indent=2, default=str))
    os.replace(tmp, BOT_DIR / "latest.json")
    try:
        import cloudstore
        cloudstore.configure(None, None) if not cloudstore.enabled() else None
        cloudstore.upsert_rows("bot_results", [{"run_at": res["run_at"], "result": json.loads(json.dumps(res, default=str))}],
                               "run_at")
    except Exception as e:
        log(f"Supabase: {e}")
    log(f"done in {res['seconds']}s: {sum(r['verdict'] == 'pass' for r in res['top'])} passed, "
        f"{sum(r['verdict'] == 'watch' for r in res['top'])} to watch")
    return res


def latest() -> dict | None:
    try:
        return json.loads((BOT_DIR / "latest.json").read_text())
    except Exception:
        return None


if __name__ == "__main__":
    run()
