"""Back-test of the Research Bot's plans: replay research_bot.analyze() on past candles and record what each plan did.

For every stock and day, at each decision time (10:00 and 12:00 IST by default), the bot sees only what it would have
seen then: daily candles up to yesterday and the intraday candles up to that time. When its bias is Bullish or Bearish,
the plan on the bias side is followed on the candles that came next:
- entry: "at market" plans (entry = the price then) fill at the next candle's open; "breakout" plans wait for a candle
  close beyond the entry level until 14:30 and fill at the next open (no fill = no trade)
- then stop first, target 1 (the plan's first target), otherwise out at 15:20; cost 0.12% a round trip
Results by side, trend, entry type, bias score and reward:risk, both halves of the period, so the app can show
"plans like this one hit target 1 first in X% of N past cases".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import research_bot as RB

COST = 0.12
TIMES = ("10:00", "12:00")


def _daily_from(intra: pd.DataFrame) -> pd.DataFrame:
    g = intra.groupby(intra.index.normalize())
    return pd.DataFrame({"Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(),
                         "Close": g["Close"].last(), "Volume": g["Volume"].sum()})


def _follow(bars: pd.DataFrame, side: int, entry: float, stop: float, t1: float, at_market: bool) -> dict | None:
    hm = bars.index.strftime("%H:%M")
    i0 = None
    if at_market:
        i0 = 0 if len(bars) else None
    else:
        for i in range(len(bars) - 1):
            if hm[i] > "14:30":
                break
            c = bars["Close"].iloc[i]
            if (side > 0 and c > entry) or (side < 0 and c < entry):
                i0 = i + 1
                break
    if i0 is None or i0 >= len(bars) or hm[i0] >= "15:20":
        return None
    e = float(bars["Open"].iloc[i0])
    if side * (e - stop) <= 0:                      # opened beyond the stop: skip
        return None
    risk = abs(e - stop)
    res, x, t_exit = "time", None, None
    for j in range(i0, len(bars)):
        if hm[j] >= "15:20":
            x, t_exit = float(bars["Open"].iloc[j]), hm[j]
            break
        lo, hi = bars["Low"].iloc[j], bars["High"].iloc[j]
        if (side > 0 and lo <= stop) or (side < 0 and hi >= stop):
            res, x, t_exit = "stop", stop, hm[j]
            break
        if (side > 0 and hi >= t1) or (side < 0 and lo <= t1):
            res, x, t_exit = "target 1", t1, hm[j]
            break
    if x is None:
        x, t_exit = float(bars["Close"].iloc[-1]), hm[-1]
    pct = side * (x / e - 1) * 100 - COST
    return {"result": res, "entry_px": e, "exit_px": x, "exit_at": t_exit, "pct": pct,
            "r": side * (x - e) / risk if risk else np.nan}


def replay(sym: str, intra: pd.DataFrame, daily: pd.DataFrame | None = None, times=TIMES, min_days: int = 30) -> list[dict]:
    """All plan trades of one stock. intra: 3- or 5-minute candles (naive IST); daily: optional longer daily history
    (else built from the intraday candles)."""
    intra = intra.dropna(subset=["Close"]).sort_index()
    if daily is None:
        daily = _daily_from(intra)
    days = sorted(set(intra.index.normalize()))
    out = []
    for d in days:
        dh = daily[daily.index < d]
        if len(dh) < min_days:
            continue
        today = intra[intra.index.normalize() == d]
        recent = intra[(intra.index >= d - pd.Timedelta(days=7)) & (intra.index < d)]
        for t in times:
            cut = d + pd.Timedelta(hours=int(t[:2]), minutes=int(t[3:]))
            seen = pd.concat([recent, today[today.index < cut]])
            after = today[today.index >= cut]
            if len(seen) < 10 or after.empty:
                continue
            try:
                r = RB.analyze(dh, seen)
            except Exception:
                continue
            if r["bias"] == "Neutral":
                continue
            side = 1 if r["bias"] == "Bullish" else -1
            for kind, p in (("intraday", r.get("intraday_plan")),
                            ("swing", next(x for x in r["plans"] if (x["side"] == "BUY") == (side > 0)))):
                if not p:
                    continue
                at_mkt = abs(p["entry"] / r["price"] - 1) < 0.0005
                f = _follow(after, side, p["entry"], p["stop"], p["t1"], at_mkt)
                if f is None:
                    continue
                out.append({"stock": sym, "day": d, "time": t, "plan": kind, "side": "BUY" if side > 0 else "SELL",
                            "bias_score": r["score"], "trend": r["trend"],
                            "entry_type": "at market" if at_mkt else "breakout",
                            "rr_plan": p["rr1"], "risk_pct": p["risk_pct"], **f})
    return out


def summarize(t: pd.DataFrame) -> dict:
    """{plan kind: stats} for the intraday and the swing plan."""
    if t.empty:
        return {}
    if "plan" not in t:
        return {"swing": _summ(t)}
    return {k: _summ(z) for k, z in t.groupby("plan")}


def _summ(t: pd.DataFrame) -> dict:
    """Hit rates and average result by the plan's features, both halves of the period."""
    if t.empty:
        return {"n": 0}
    t = t.copy()
    t["hit"] = (t["result"] == "target 1").astype(float)
    t["rr_bucket"] = pd.cut(t["rr_plan"], [0, 1, 1.5, 2, 3, 99], labels=["<1", "1-1.5", "1.5-2", "2-3", "3+"]).astype(str)
    t["score_bucket"] = t["bias_score"].abs().clip(upper=6).astype(int).astype(str)
    mid = t["day"].sort_values().iloc[len(t) // 2]

    def agg(z):
        return {"n": int(len(z)), "hit_t1_pct": round(z["hit"].mean() * 100, 1),
                "stop_pct": round((z["result"] == "stop").mean() * 100, 1),
                "avg_pct": round(z["pct"].mean(), 3), "avg_r": round(z["r"].mean(), 2),
                "h1_avg_pct": round(z.loc[z["day"] < mid, "pct"].mean(), 3) if (z["day"] < mid).any() else None,
                "h2_avg_pct": round(z.loc[z["day"] >= mid, "pct"].mean(), 3) if (z["day"] >= mid).any() else None}
    out = {"all": agg(t), "from": str(t["day"].min().date()), "to": str(t["day"].max().date()),
           "stocks": int(t["stock"].nunique())}
    for col in ("side", "trend", "entry_type", "rr_bucket", "score_bucket", "time"):
        out[col] = {str(k): agg(z) for k, z in t.groupby(col) if len(z) >= 20}
    combo = t.groupby(["side", "entry_type", "trend"])
    out["combo"] = {" | ".join(map(str, k)): agg(z) for k, z in combo if len(z) >= 20}
    return out


def match(stats: dict, side: str, entry_type: str, trend: str, kind: str = "swing") -> dict | None:
    """The past record of plans like this one (same kind, side, entry type and trend), else by entry type."""
    stats = (stats or {}).get(kind) or {}
    if not stats:
        return None
    k = f"{side} | {entry_type} | {trend}"
    if k in (stats.get("combo") or {}):
        return {"key": k, **stats["combo"][k]}
    by = stats.get("entry_type", {}).get(entry_type)
    return {"key": f"{entry_type} plans", **by} if by else None


def main():
    """Nightly on the server: every F&O stock's cached 1-minute candles (<bot>/cache_m1, ~6 months, filled by
    candle_study.py) -> 5-minute candles -> replay -> <data>/bot/research_bot_bt.json and Supabase bot_results
    ("research_bot_bt ...")."""
    import json
    import sys
    import time
    from datetime import datetime, timedelta, timezone

    import bot as B
    import candles as C
    import universe as U
    t0 = time.time()
    cache = B.BOT_DIR / "cache_m1"
    rows = []
    syms = sorted(U.FNO_SECTOR_OF)
    for i, s in enumerate(syms):
        f = cache / f"{s.replace('&', '_and_')}.parquet"
        if not f.exists():
            continue
        try:
            m1 = C.naive(pd.read_parquet(f)).astype("float64")
            rows += replay(s, C.resample(m1, 5))
        except Exception as e:
            print(f"{s}: {e}", file=sys.stderr)
        if i % 25 == 0:
            print(f"research bot back-test: {i}/{len(syms)} stocks, {len(rows)} trades, {time.time() - t0:.0f}s", flush=True)
    t = pd.DataFrame(rows)
    res = {"run_at": datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec="seconds"),
           "trades": int(len(t)), "secs": round(time.time() - t0), "stats": summarize(t)}
    out = B.BOT_DIR / "research_bot_bt.json"
    out.write_text(json.dumps(res, default=str))
    try:
        import cloudstore
        cloudstore.upsert_rows("bot_results", [{"run_at": "research_bot_bt " + res["run_at"],
                                                "result": json.loads(json.dumps(res, default=str))}], "run_at")
    except Exception as e:
        print(f"save: {e}", file=sys.stderr)
    print(f"research bot back-test: {len(t)} trades in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
