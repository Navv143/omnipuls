"""What makes an F&O stock trend intraday? A study on 5-minute candles of every F&O stock.

For each stock and day it measures what was known at a decision time (9:30, 9:45, 10:15): the gap, yesterday's range
and close, ATR contraction, distance to the 20-day high / low, the move and range so far, volume so far vs the usual
for that window, the first 15 minutes' range vs usual, money-flow share, relative strength vs Nifty, the sector's and
the market's direction, open = high / low. Then it asks two questions:

t-stats are counted over days, not trades: trades on one day move together with the market.

1. Big-move odds: which readings come before a trend day (open to 15:15 close at least 1.5 ATR)? Lift = how many
   times more often a trend day follows that reading than on an average day.
2. Tradable edge: entering in the direction of the move at the next candle and holding to 15:15 (0.12% costs), which
   readings and combinations made money on the first 60% of days AND on the last 40% (unseen)?

Data: the Setup Finder's cache (a year of Dhan 5-minute candles) on the server, else Yahoo (about 60 days).
Output: <data>/bot/momentum.json (and Supabase bot_results). Run: python momentum_study.py [--yahoo]
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
COST = 0.0012
TRAIN = 0.6
CHECKS = {"09:30": 570, "09:45": 585, "10:15": 615}
EXIT = 915  # the 15:15 candle's close


def log(m):
    print(f"{datetime.now(IST):%H:%M:%S} momentum: {m}", flush=True)

# ---------------------------------------------------------------- data


def load_yahoo(symbols: list[str], sleep: float = 0.25) -> dict:
    import requests
    out, s = {}, requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    for i, sym in enumerate(symbols):
        y = sym if sym.startswith("^") else sym + ".NS"
        try:
            j = s.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{y}", params={"range": "60d", "interval": "5m"},
                      timeout=20).json()["chart"]["result"][0]
            q = j["indicators"]["quote"][0]
            df = pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"], "Close": q["close"],
                               "Volume": q["volume"]}, index=pd.to_datetime(j["timestamp"], unit="s", utc=True))
            df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
            df = df.dropna(subset=["Close"])
            if len(df) > 500:
                out[sym] = df
        except Exception:
            pass
        if i % 40 == 0:
            log(f"yahoo {i}/{len(symbols)}")
        time.sleep(sleep)
    return out


def load_cache() -> dict:
    import bot as B
    out = {}
    for f in sorted(B.CACHE.glob("*.parquet")):
        out[f.stem.replace("_and_", "&")] = pd.read_parquet(f)
    return out

# ---------------------------------------------------------------- features per stock-day


def stock_days(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    d = df[(df.index.hour * 60 + df.index.minute >= 555) & (df.index.hour * 60 + df.index.minute <= 925)].copy()
    if d.empty:
        return pd.DataFrame()
    d["day"] = d.index.normalize()
    d["m"] = d.index.hour * 60 + d.index.minute
    g = d.groupby("day")
    daily = g.agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"), v=("Volume", "sum"))
    if len(daily) < 25:
        return pd.DataFrame()
    pc = daily["c"].shift(1)
    tr = pd.concat([daily["h"] - daily["l"], (daily["h"] - pc).abs(), (daily["l"] - pc).abs()], axis=1).max(axis=1)
    daily["atr"] = tr.rolling(14).mean().shift(1)
    daily["atr5"] = tr.rolling(5).mean().shift(1)
    daily["atr20"] = tr.rolling(20).mean().shift(1)
    daily["pc"] = pc
    daily["prev_rng_atr"] = ((daily["h"] - daily["l"]) / daily["atr"].shift(-1)).shift(1)  # yesterday's range vs ATR
    daily["prev_clv"] = ((daily["c"] - daily["l"]) / (daily["h"] - daily["l"]).replace(0, np.nan)).shift(1)
    daily["prev_chg"] = (daily["c"] / daily["c"].shift(1) - 1).shift(1) * 100
    daily["hi20"] = daily["h"].rolling(20).max().shift(1)
    daily["lo20"] = daily["l"].rolling(20).min().shift(1)
    # the close used for exits and the outcome
    ex = d[d["m"] == EXIT].groupby("day")["Close"].last()  # only finished sessions (today's open one is left out)
    daily["exit"] = ex
    rows = []
    cum = d.assign(cv=g["Volume"].cumsum(), hi=g["High"].cummax(), lo=g["Low"].cummin(),
                   rng=d["High"] - d["Low"])
    rngc = (cum["High"] - cum["Low"]).replace(0, np.nan)
    press = ((cum["Close"] - cum["Open"]) / rngc).fillna(0)
    turn = cum["Volume"] * cum["Close"]
    cum["inf"] = (turn * (1 + press) / 2).groupby(cum["day"]).cumsum()
    cum["tot"] = turn.groupby(cum["day"]).cumsum()
    first15 = d[d["m"] < 570].groupby("day").agg(fr=("High", "max"), fl=("Low", "min"), fv=("Volume", "sum"))
    first15["frng"] = first15["fr"] - first15["fl"]
    first15["frng_avg"] = first15["frng"].rolling(20, min_periods=10).mean().shift(1)
    for name, m in CHECKS.items():
        at = cum[cum["m"] == m - 5].set_index("day")  # the candle that closes at the decision time
        nxt = d[d["m"] == m].set_index("day")["Open"]  # entry: the next candle's open
        win_v = d[d["m"] < m].groupby("day")["Volume"].sum()
        usual_v = win_v.rolling(20, min_periods=10).mean().shift(1)
        x = daily.join(at[["Close", "hi", "lo", "inf", "tot"]], how="inner").join(nxt.rename("entry"))
        x = x.join(first15[["frng", "frng_avg"]]).join((win_v / usual_v).rename("vol_x"))
        x["sym"], x["check"] = sym, name
        rows.append(x)
    t = pd.concat(rows)
    a = t["atr"]
    t["gap_pct"] = (t["o"] / t["pc"] - 1) * 100
    t["gap_atr"] = (t["o"] - t["pc"]) / a
    t["move_atr"] = (t["Close"] - t["o"]) / a
    t["move_pct"] = (t["Close"] / t["o"] - 1) * 100
    t["chg_pct"] = (t["Close"] / t["pc"] - 1) * 100
    t["range_atr"] = (t["hi"] - t["lo"]) / a
    t["atr_contract"] = t["atr5"] / t["atr20"]
    t["to_hi20_atr"] = (t["hi20"] - t["Close"]) / a
    t["to_lo20_atr"] = (t["Close"] - t["lo20"]) / a
    t["or_x"] = t["frng"] / t["frng_avg"]
    t["flow"] = t["inf"] / t["tot"].replace(0, np.nan)
    t["o_eq_l"] = (t["lo"] >= t["o"] * 0.9995)
    t["o_eq_h"] = (t["hi"] <= t["o"] * 1.0005)
    t["atr_pct"] = a / t["pc"] * 100
    # outcomes
    t["trend_day"] = ((t["exit"] - t["o"]).abs() / a >= 1.5)
    side = np.sign(t["move_atr"])
    t["side"] = side
    t["ret"] = side * (t["exit"] / t["entry"] - 1) - COST
    t["more_atr"] = side * (t["exit"] - t["Close"]) / a
    keep = ["sym", "check", "gap_pct", "gap_atr", "prev_rng_atr", "prev_clv", "prev_chg", "atr_contract", "to_hi20_atr",
            "to_lo20_atr", "move_atr", "move_pct", "chg_pct", "range_atr", "vol_x", "or_x", "flow", "o_eq_l", "o_eq_h",
            "atr_pct", "trend_day", "side", "ret", "more_atr"]
    t = t.reset_index().rename(columns={"index": "day"})[["day"] + keep]
    return t.replace([np.inf, -np.inf], np.nan).dropna(subset=["move_atr", "ret", "vol_x", "range_atr"])


def build(bars: dict, nifty: pd.DataFrame | None, sectors: dict) -> pd.DataFrame:
    parts = []
    for i, (s, df) in enumerate(bars.items()):
        if s.startswith("^") or s in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "INDIAVIX"):
            continue
        try:
            x = stock_days(s, df)
            if not x.empty:
                parts.append(x)
        except Exception as e:
            log(f"{s}: {e}")
    T = pd.concat(parts, ignore_index=True)
    T["sector"] = T["sym"].map(sectors).fillna("Other")
    # market and sector direction at the same moment (from all stocks), and relative strength vs the market
    grp = T.groupby(["day", "check"])["move_pct"]
    T["mkt_move"] = grp.transform("mean")
    T["mkt_flow"] = T.groupby(["day", "check"])["flow"].transform("mean")
    T["sec_move"] = T.groupby(["day", "check", "sector"])["move_pct"].transform("mean")
    T["rel_mkt"] = T["side"] * (T["move_pct"] - T["mkt_move"])
    T["mkt_with"] = np.sign(T["mkt_move"]) == T["side"]
    T["sec_with"] = np.sign(T["sec_move"]) == T["side"]
    T["flow_with"] = np.where(T["side"] > 0, T["flow"], 1 - T["flow"])
    T["gap_with"] = np.sign(T["gap_pct"]) == T["side"]
    T["clv_with"] = np.where(T["side"] > 0, T["prev_clv"], 1 - T["prev_clv"])
    T["room_atr"] = np.where(T["side"] > 0, T["to_hi20_atr"], T["to_lo20_atr"])  # distance to the 20-day extreme
    T["abs_move_atr"] = T["move_atr"].abs()
    T["abs_gap_atr"] = T["gap_atr"].abs()
    T["ohl_with"] = np.where(T["side"] > 0, T["o_eq_l"], T["o_eq_h"])
    return T

# ---------------------------------------------------------------- analysis

FEATURES = {  # name: description
    "abs_move_atr": "move from the open so far, in ATR",
    "range_atr": "range so far, in ATR",
    "vol_x": "volume so far vs usual for this window",
    "or_x": "first 15 minutes' range vs usual",
    "flow_with": "money-flow share in the move's direction",
    "rel_mkt": "move vs the market's average move (%)",
    "abs_gap_atr": "opening gap, in ATR",
    "prev_rng_atr": "yesterday's range vs ATR (low = quiet day)",
    "clv_with": "yesterday's close location, in the move's direction",
    "atr_contract": "ATR 5 / ATR 20 (low = volatility squeeze)",
    "room_atr": "distance to the 20-day high/low in the move's direction (ATR)",
    "atr_pct": "ATR as % of price",
}
FLAGS = {"mkt_with": "market moving the same way", "sec_with": "sector moving the same way",
         "gap_with": "gapped the same way", "ohl_with": "open = low (long) / open = high (short)"}


def _t(r: np.ndarray) -> float:
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else 0.0


def _day_t(r: np.ndarray, day: np.ndarray) -> tuple[float, int]:
    """t-stat over days (each day's average trade counts once: trades on one day move together)."""
    if len(r) < 3:
        return 0.0, 0
    s = pd.Series(r).groupby(day).mean().to_numpy()
    return _t(s), len(s)


def _stats(sub: pd.DataFrame) -> dict:
    r = sub["ret"].to_numpy()
    dt, nd = _day_t(r, sub["day"].to_numpy())
    return {"n": int(len(r)), "days": nd, "ret": round(float(r.mean() * 100), 3) if len(r) else None,
            "win": round(float((r > 0).mean() * 100), 1) if len(r) else None, "t": round(dt, 2),
            "trend": round(float(sub["trend_day"].mean() * 100), 1) if len(r) else None,
            "more": round(float(sub["more_atr"].mean()), 3) if len(r) else None}


def buckets(T: pd.DataFrame, split) -> list[dict]:
    out = []
    base = T["trend_day"].mean()
    for f, desc in FEATURES.items():
        x = T[f]
        try:
            q = pd.qcut(x, 5, duplicates="drop")
        except Exception:
            continue
        for b, sub in T.groupby(q, observed=True):
            tr, te = sub[sub["day"] < split], sub[sub["day"] >= split]
            out.append({"feature": f, "desc": desc, "bucket": f"{b.left:.2f} to {b.right:.2f}",
                        "lift": round(float(sub["trend_day"].mean() / base), 2) if base else None,
                        "all": _stats(sub), "tune": _stats(tr), "unseen": _stats(te)})
    for f, desc in FLAGS.items():
        for v in (True, False):
            sub = T[T[f] == v]
            tr, te = sub[sub["day"] < split], sub[sub["day"] >= split]
            out.append({"feature": f, "desc": desc, "bucket": "yes" if v else "no",
                        "lift": round(float(sub["trend_day"].mean() / base), 2) if base else None,
                        "all": _stats(sub), "tune": _stats(tr), "unseen": _stats(te)})
    return out


def combos(T: pd.DataFrame, split, min_n: int = 60, keep: int = 20) -> tuple[list, int]:
    """Rules of 1-3 conditions (thresholds at the 60th / 80th percentile, or a flag), judged on unseen days."""
    conds = []
    for f in FEATURES:
        for qv in (0.2, 0.4, 0.6, 0.8):
            v = float(T[f].quantile(qv))
            conds.append((f"{f} >= {v:.2f}", T[f].to_numpy() >= v))
            if qv <= 0.4:
                conds.append((f"{f} <= {v:.2f}", T[f].to_numpy() <= v))
    for f in FLAGS:
        conds.append((f"{f}", T[f].to_numpy().astype(bool)))
    tr = (T["day"] < split).to_numpy()
    r = T["ret"].to_numpy()
    dcode = pd.factorize(T["day"])[0]
    tested, res = 0, []
    single = sorted(conds, key=lambda c: -_t(r[c[1] & tr]) if (c[1] & tr).sum() >= min_n else 0)
    strong = single[:20]
    for k in (1, 2, 3):
        pool = conds if k < 3 else strong
        for cs in itertools.combinations(pool, k):
            if len({c[0].split()[0] for c in cs}) < k:
                continue
            m = np.logical_and.reduce([c[1] for c in cs])
            a, b = r[m & tr], r[m & ~tr]
            tested += 1
            if len(a) < min_n or len(b) < min_n // 2:
                continue
            ta, na = _day_t(a, dcode[m & tr])
            if a.mean() <= 0 or ta < 1.5:
                continue
            tb, nb = _day_t(b, dcode[m & ~tr])
            res.append({"rule": " AND ".join(c[0] for c in cs),
                        "tune": {"n": len(a), "days": na, "ret": round(a.mean() * 100, 3), "t": round(ta, 2)},
                        "unseen": {"n": len(b), "days": nb, "ret": round(b.mean() * 100, 3), "t": round(tb, 2),
                                   "win": round((b > 0).mean() * 100, 1)}})
    res.sort(key=lambda x: -x["tune"]["t"])
    top = res[:200]
    for x in top:
        u = x["unseen"]
        # pass: +0.05%+ a trade after costs on unseen days, t 2+ counted over DAYS (not trades), 40+ trades, 20+ days
        x["verdict"] = ("pass" if u["ret"] >= 0.05 and u["t"] >= 2 and u["n"] >= 40 and u["days"] >= 20 else
                        "watch" if u["ret"] > 0 else "fail")
    top.sort(key=lambda x: (x["verdict"] != "pass", -x["unseen"]["t"]))
    return top[:keep], tested


def study(T: pd.DataFrame) -> dict:
    days = np.sort(T["day"].unique())
    split = days[int(len(days) * TRAIN)]
    out = {"run_at": datetime.now(IST).isoformat(timespec="seconds"), "stock_days": int(T.groupby(["day", "sym"]).ngroups),
           "stocks": int(T["sym"].nunique()), "days": int(len(days)), "first_day": str(days[0])[:10],
           "last_day": str(days[-1])[:10], "split": str(split)[:10], "checks": {}}
    for chk, sub in T.groupby("check"):
        sub = sub[sub["side"] != 0]
        top, tested = combos(sub, split)
        out["checks"][chk] = {"base": _stats(sub), "base_trend_pct": round(float(sub["trend_day"].mean() * 100), 1),
                              "buckets": buckets(sub, split), "rules": top, "rules_tested": tested,
                              "rules_pass": sum(1 for x in top if x["verdict"] == "pass")}
        log(f"{chk}: {len(sub):,} stock-days, base trend days {out['checks'][chk]['base_trend_pct']}%, "
            f"{tested:,} rules, {out['checks'][chk]['rules_pass']} pass")
    return out


def main(use_yahoo: bool = False):
    import paths
    import universe as U
    t0 = time.time()
    bars = {} if use_yahoo else load_cache()
    src = "Dhan 5-minute (Setup Finder cache)"
    if len(bars) < 50:
        bars, src = load_yahoo(sorted(U.FNO_SECTOR_OF)), "Yahoo 5-minute (about 60 days)"
    log(f"{len(bars)} symbols from {src}")
    T = build(bars, None, U.FNO_SECTOR_OF)
    res = study(T)
    res["source"], res["seconds"] = src, round(time.time() - t0)
    out = paths.DATA / "bot"
    out.mkdir(parents=True, exist_ok=True)
    (out / "momentum.json").write_text(json.dumps(res, default=str))
    try:
        import cloudstore
        if not cloudstore.enabled():
            try:
                import streamlit as st
                sb = dict(st.secrets.get("supabase") or {})
                cloudstore.configure(sb.get("url"), sb.get("key"))
            except Exception:
                pass
        cloudstore.upsert_rows("bot_results", [{"run_at": "momentum " + res["run_at"], "result": json.loads(json.dumps(res, default=str))}], "run_at")
        time.sleep(3)
    except Exception as e:
        log(f"Supabase: {e}")
    log(f"done in {res['seconds']}s")
    return res, T


if __name__ == "__main__":
    main("--yahoo" in sys.argv)
