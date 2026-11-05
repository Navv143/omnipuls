"""Index Funnel: the Momentum Funnel's simple steps for Nifty 50, Bank Nifty, Fin Nifty, Sensex and Midcap Select
(pure functions, no Streamlit).

Indices have no volume of their own, so their money comes from their stocks (each weighted by its index weight).

Step 1  ATR active    - the index's average 5-minute true range from 9:15 to now vs the same window on the last 20
                        days, and the last 15 minutes vs the same 15 minutes.
Step 2  Range         - high-low from 9:15 to now vs the usual high-low of that window.
Step 3  Index money   - the weighted money flow of its stocks is in the move's direction (buying share > 50% for
                        longs) and still growing (weighted net money beyond its value 15 minutes ago).
Step 4  Breadth       - at least 60% of the index weight is moving the same way from the open.
Step 5  VIX           - India VIX not against (off by default: it did not help on the first test; set vix_max = 3 to
                        require VIX not up more than 3% from its open for longs / not down 3% for shorts).
A signal = the first 5-minute candle of the day (9:30-14:00) where all five pass. Backtest: entry at the next
candle's open, exit at the 15:15 close (optional stop), 0.02% costs (index futures).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
INDEXES = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty", "FINNIFTY": "Fin Nifty", "SENSEX": "Sensex",
           "MIDCPNIFTY": "Midcap Select"}
DEFAULTS = {"day_x": 1.1, "now_x": 1.0, "range_x": 1.1, "breadth": 60.0, "vix_max": 99.0, "lookback": 20, "recent": 3}
# vix_max 99 = the VIX step is off: on the first test (52 days, Yahoo) it did not help; the reading is still shown.
COST = 0.0002
FIRST, LAST, EXIT = 570, 840, 915


def _clean(df):
    if df is None or df.empty:
        return pd.DataFrame()
    d = df[~df.index.duplicated(keep="last")].sort_index()
    m = d.index.hour * 60 + d.index.minute
    return d[(m >= 555) & (m <= 925)]


def index_table(ix: pd.DataFrame, stocks: dict, weights: dict, vix: pd.DataFrame | None, cfg: dict | None = None,
                today_only: bool = False) -> pd.DataFrame:
    """One row per 5-minute candle with every step's reading (all days, or today only)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    d = _clean(ix)
    if d.empty:
        return pd.DataFrame()
    day = d.index.normalize()
    pc = d["Close"].shift(1).where(day == pd.Series(day, index=d.index).shift(1).to_numpy())
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    t = pd.DataFrame({"Open": d["Open"], "High": d["High"], "Low": d["Low"], "Close": d["Close"],
                      "tr": tr.fillna(d["High"] - d["Low"]), "day": day, "slot": d.index.strftime("%H:%M"),
                      "m": d.index.hour * 60 + d.index.minute}, index=d.index)
    g = t.groupby("day")
    t["n"] = g.cumcount() + 1
    t["atr_day"] = g["tr"].cumsum() / t["n"]
    t["atr_now"] = g["tr"].transform(lambda x: x.rolling(cfg["recent"], min_periods=1).mean())
    t["hi"], t["lo"] = g["High"].cummax(), g["Low"].cummin()
    t["rng"] = t["hi"] - t["lo"]
    t["o"] = g["Open"].transform("first")
    # usual values for the same slot on the previous `lookback` days
    for col in ("atr_day", "atr_now", "rng"):
        p = t.pivot_table(index="day", columns="slot", values=col, aggfunc="last")
        u = p.rolling(cfg["lookback"], min_periods=8).mean().shift(1)
        t[col + "_u"] = u.stack().reindex(pd.MultiIndex.from_arrays([t["day"], t["slot"]])).to_numpy()
    t["day_x"], t["now_x"], t["range_x"] = t["atr_day"] / t["atr_day_u"], t["atr_now"] / t["atr_now_u"], t["rng"] / t["rng_u"]
    t["move_pct"] = (t["Close"] / t["o"] - 1) * 100
    t["side"] = np.sign(t["move_pct"]).astype(int)
    # constituents: weighted buying share, weighted net money (cumulative, ₹ Cr) and weighted breadth
    inf_w = out_w = br_up = br_dn = None
    wsum = 0.0
    for s, w in (weights or {}).items():
        b = _clean(stocks.get(s))
        if b.empty or "Volume" not in b:
            continue
        b = b.reindex(t.index)
        bd = pd.Series(b.index.normalize(), index=b.index)
        turn = b["Volume"] * (b["High"] + b["Low"] + b["Close"]) / 3
        rng = (b["High"] - b["Low"])
        press = ((b["Close"] - b["Open"]) / rng.where(rng > 0)).fillna(0)
        i_ = (turn * (1 + press) / 2).fillna(0).groupby(bd).cumsum() * w / 100 / 1e7
        o_ = (turn * (1 - press) / 2).fillna(0).groupby(bd).cumsum() * w / 100 / 1e7
        op = b["Open"].groupby(bd).transform("first")
        mv = np.sign((b["Close"] - op).ffill())
        inf_w = i_ if inf_w is None else inf_w + i_
        out_w = o_ if out_w is None else out_w + o_
        br_up = (mv > 0) * w if br_up is None else br_up + (mv > 0) * w
        br_dn = (mv < 0) * w if br_dn is None else br_dn + (mv < 0) * w
        wsum += w
    if inf_w is not None and wsum > 0:
        t["net"] = inf_w - out_w
        t["buy_share"] = inf_w / (inf_w + out_w).replace(0, np.nan) * 100
        t["net_before"] = t.groupby("day")["net"].shift(cfg["recent"]).fillna(0)
        t["breadth_up"], t["breadth_dn"] = br_up / wsum * 100, br_dn / wsum * 100
    else:
        t["net"] = t["buy_share"] = t["net_before"] = t["breadth_up"] = t["breadth_dn"] = np.nan
    v = _clean(vix)
    if not v.empty:
        vv = v["Close"].reindex(t.index).ffill()
        vo = v["Open"].groupby(v.index.normalize()).transform("first").reindex(t.index).ffill()
        t["vix_chg"] = (vv / vo - 1) * 100
    else:
        t["vix_chg"] = np.nan
    s_ = t["side"]
    t["step1"] = (t["day_x"] >= cfg["day_x"]) & (t["now_x"] >= cfg["now_x"]) & (s_ != 0)
    t["step2"] = t["step1"] & (t["range_x"] >= cfg["range_x"])
    flow_with = np.where(s_ > 0, t["buy_share"] > 50, t["buy_share"] < 50)
    growing = s_ * (t["net"] - t["net_before"]) > 0
    t["step3"] = t["step2"] & flow_with & growing
    t["breadth_with"] = np.where(s_ > 0, t["breadth_up"], t["breadth_dn"])
    t["step4"] = t["step3"] & (t["breadth_with"] >= cfg["breadth"])
    vix_ok = np.where(s_ > 0, t["vix_chg"].fillna(0) <= cfg["vix_max"], t["vix_chg"].fillna(0) >= -cfg["vix_max"])
    t["vix_ok"] = vix_ok
    t["step5"] = t["step4"] & vix_ok
    if today_only:
        t = t[t["day"] == t["day"].max()]
    return t


def signals(t: pd.DataFrame, step: str = "step5", first: int = FIRST, last: int = LAST) -> pd.DataFrame:
    """The first candle of each day where `step` passes, with the trade to 15:15 (entry = next candle's open)."""
    if t.empty:
        return pd.DataFrame()
    t = t.copy()
    t["entry"] = t.groupby("day")["Open"].shift(-1)
    ex = t[t["m"] == EXIT].groupby("day")["Close"].last()
    c = t[t[step] & (t["m"] + 5 >= first) & (t["m"] + 5 <= last) & t["entry"].notna()]
    c = c.groupby("day").head(1).copy()
    c["exit"] = c["day"].map(ex)
    c = c.dropna(subset=["exit"])
    c["ret"] = c["side"] * (c["exit"] / c["entry"] - 1) - COST
    c["time"] = (c["m"] + 5).map(lambda m: f"{m // 60:02d}:{m % 60:02d}")
    return c


def _stats(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) == 0:
        return {"n": 0}
    sd = r.std(ddof=1) if len(r) > 1 else 0
    return {"n": int(len(r)), "ret": round(float(r.mean() * 100), 3), "win": round(float((r > 0).mean() * 100), 1),
            "t": round(float(r.mean() / sd * np.sqrt(len(r))), 2) if sd > 0 else 0.0, "total": round(float(r.sum() * 100), 2)}


def backtest(ix_bars: dict, stocks: dict, weights: dict, vix: pd.DataFrame | None, cfg: dict | None = None) -> dict:
    """Each step's signals per index, all indices, and each step left out (what each step adds)."""
    out = {"run_at": datetime.now(IST).isoformat(timespec="seconds"), "indices": {}, "cfg": {**DEFAULTS, **(cfg or {})}}
    tables = {k: index_table(ix_bars.get(k), stocks, weights.get(k, {}), vix, cfg) for k in INDEXES if ix_bars.get(k) is not None}
    tables = {k: v for k, v in tables.items() if not v.empty}
    allsig = {s: [] for s in ("step1", "step2", "step3", "step4", "step5")}
    for k, t in tables.items():
        res = {}
        days = t.dropna(subset=["day_x_u" if "day_x_u" in t else "atr_day_u"])["day"].nunique()
        for s in allsig:
            sg = signals(t, s)
            allsig[s].append(sg.assign(index=k))
            res[s] = _stats(sg["ret"]) if not sg.empty else {"n": 0}
        sg = signals(t)
        res["days"] = int(days)
        res["recent"] = [{"day": str(r["day"])[:10], "time": r["time"], "side": "LONG" if r["side"] > 0 else "SHORT",
                          "ret": round(float(r["ret"] * 100), 2)} for _, r in sg.tail(10).iterrows()]
        out["indices"][k] = res
    pooled = {s: _stats(pd.concat(v)["ret"]) if v and not pd.concat(v).empty else {"n": 0} for s, v in allsig.items()}
    out["all"] = pooled
    # what each step adds: drop it and compare
    abl = {}
    for drop in ("step1", "step2", "step3", "step4", "vix"):
        rs = []
        for k, t in tables.items():
            t2 = t.copy()
            s_ = t2["side"]
            base = (s_ != 0)
            p1 = (t2["day_x"] >= out["cfg"]["day_x"]) & (t2["now_x"] >= out["cfg"]["now_x"])
            p2 = t2["range_x"] >= out["cfg"]["range_x"]
            p3 = pd.Series(np.where(s_ > 0, t2["buy_share"] > 50, t2["buy_share"] < 50), index=t2.index) & \
                (s_ * (t2["net"] - t2["net_before"]) > 0)
            p4 = t2["breadth_with"] >= out["cfg"]["breadth"]
            p5 = pd.Series(t2["vix_ok"], index=t2.index).astype(bool)
            parts = {"step1": p1, "step2": p2, "step3": p3, "step4": p4, "vix": p5}
            m = base.copy()
            for name, p in parts.items():
                if name != drop:
                    m &= p.fillna(False)
            t2["x"] = m
            rs.append(signals(t2, "x"))
        rs = [r for r in rs if not r.empty]
        abl["without " + drop] = _stats(pd.concat(rs)["ret"]) if rs else {"n": 0}
    out["ablation"] = abl
    return out


def live(ix_bars: dict, stocks: dict, weights: dict, vix: pd.DataFrame | None, cfg: dict | None = None) -> list[dict]:
    """Each index's latest candle with every step, and today's first full signal if there was one."""
    rows = []
    for k, name in INDEXES.items():
        t = index_table(ix_bars.get(k), stocks, weights.get(k, {}), vix, cfg, today_only=True)
        if t.empty:
            continue
        r = t.iloc[-1]
        sg = t[t["step5"] & (t["m"] + 5 >= FIRST) & (t["m"] + 5 <= LAST)]
        first = sg.iloc[0] if len(sg) else None
        plan = None
        if first is not None:
            import funnel as FN
            full = _clean(ix_bars.get(k))
            dd = full.groupby(full.index.normalize()).agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
            pc = dd["c"].shift(1)
            trd = pd.concat([dd["h"] - dd["l"], (dd["h"] - pc).abs(), (dd["l"] - pc).abs()], axis=1).max(axis=1)
            atr14 = float(trd.iloc[-15:-1].mean()) if len(trd) > 5 else np.nan
            upto = t[t.index <= first.name].tail(6)
            plan = FN.trade_plan(int(first["side"]), float(first["Close"]), atr14, float(upto["Low"].min()),
                                 float(upto["High"].max()))
        rows.append({"key": k, "name": name, "price": float(r["Close"]), "move_pct": float(r["move_pct"]),
                     "side": int(r["side"]), "time": f"{(int(r['m']) + 5) // 60:02d}:{(int(r['m']) + 5) % 60:02d}",
                     "day_x": float(r["day_x"]), "now_x": float(r["now_x"]), "range_x": float(r["range_x"]),
                     "buy_share": float(r["buy_share"]) if r["buy_share"] == r["buy_share"] else None,
                     "net": float(r["net"]) if r["net"] == r["net"] else None,
                     "net_before": float(r["net_before"]) if r["net_before"] == r["net_before"] else None,
                     "breadth": float(r["breadth_with"]) if r["breadth_with"] == r["breadth_with"] else None,
                     "vix_chg": float(r["vix_chg"]) if r["vix_chg"] == r["vix_chg"] else None,
                     "steps": [bool(r[f"step{i}"]) for i in (1, 2, 3, 4, 5)],
                     "signal": None if first is None else {"time": f"{(int(first['m']) + 5) // 60:02d}:{(int(first['m']) + 5) % 60:02d}",
                                                           "side": "LONG" if first["side"] > 0 else "SHORT",
                                                           "price": float(first["Close"]), "plan": plan}})
    return rows


def save(res: dict, path):
    path.write_text(json.dumps(res, default=str))


def banknifty_study(ix_bars: dict, stocks: dict, weights: dict, vix: pd.DataFrame | None) -> dict:
    """Bank Nifty variants (the plain funnel is ~zero on Bank Nifty): later start, Nifty 50 money as the leader,
    and the failed break of yesterday's high / low faded (Bank Nifty breaks tend to fail)."""
    bn = index_table(ix_bars.get("BANKNIFTY"), stocks, weights.get("BANKNIFTY", {}), vix)
    nf = index_table(ix_bars.get("NIFTY"), stocks, weights.get("NIFTY", {}), vix)
    if bn.empty or nf.empty:
        return {}
    for c in ("buy_share", "net", "net_before", "side"):
        bn["nif_" + c] = nf[c].reindex(bn.index)
    s1 = (bn["day_x"] >= DEFAULTS["day_x"]) & (bn["now_x"] >= DEFAULTS["now_x"]) & (bn["range_x"] >= DEFAULTS["range_x"]) & (bn["side"] != 0)
    own = pd.Series(np.where(bn["side"] > 0, bn["buy_share"] > 50, bn["buy_share"] < 50), index=bn.index) & \
        (bn["side"] * (bn["net"] - bn["net_before"]) > 0)
    nifm = pd.Series(np.where(bn["side"] > 0, bn["nif_buy_share"] > 50, bn["nif_buy_share"] < 50), index=bn.index) & \
        (bn["side"] * (bn["nif_net"] - bn["nif_net_before"]) > 0) & (bn["nif_side"] == bn["side"])
    br = bn["breadth_with"] >= DEFAULTS["breadth"]
    dl = bn.groupby("day").agg(h=("High", "max"), l=("Low", "min"))
    pdh, pdl = bn["day"].map(dl["h"].shift(1)), bn["day"].map(dl["l"].shift(1))
    hi, lo = bn.groupby("day")["High"].cummax(), bn.groupby("day")["Low"].cummin()
    fb_s, fb_l = (hi > pdh) & (bn["Close"] < pdh), (lo < pdl) & (bn["Close"] > pdl)
    variants = {"funnel (steps 1-4)": (s1 & own & br, None, FIRST), "funnel from 10:00": (s1 & own & br, None, 600),
                "Nifty 50 money as leader": (s1 & nifm, None, FIRST), "funnel + Nifty money": (s1 & own & br & nifm, None, FIRST),
                "failed break of yesterday's high/low, faded": (fb_s | fb_l, np.where(fb_s, -1, np.where(fb_l, 1, 0)), FIRST)}
    out = {}
    for name, (mask, side, first) in variants.items():
        t = bn.copy()
        if side is not None:
            t["side"] = side
        t["x"] = mask.fillna(False) & (t["side"] != 0)
        sg = signals(t, "x", first)
        if sg.empty:
            out[name] = {"n": 0}
            continue
        days = np.sort(sg["day"].unique())
        mid = days[len(days) // 2]
        out[name] = {**_stats(sg["ret"]), "first_half": _stats(sg[sg["day"] < mid]["ret"]).get("ret"),
                     "second_half": _stats(sg[sg["day"] >= mid]["ret"]).get("ret"),
                     "pts": round(float((sg["ret"] * sg["entry"]).mean()), 1)}
    return out


def run_server() -> dict | None:
    """Nightly on the server: the backtest on the Setup Finder's year of Dhan 5-minute candles (indices, their stocks
    and India VIX) -> <data>/bot/index_funnel.json."""
    import bot as B
    import indices as IX
    import paths
    bars = {}
    for f in B.CACHE.glob("*.parquet"):
        bars[f.stem.replace("_and_", "&")] = pd.read_parquet(f)
    ix = {k: bars.get(k) for k in INDEXES if bars.get(k) is not None}
    if not ix:
        return None
    try:
        weights = {k: d.get("w", {}) for k, d in IX.load().items()}
    except Exception:
        weights = {k: IX._norm(v) for k, v in IX.BUILTIN.items()}
    res = backtest(ix, bars, weights, bars.get("INDIAVIX"))
    res["banknifty"] = banknifty_study(ix, bars, weights, bars.get("INDIAVIX"))
    res["source"] = "Dhan 5-minute (Setup Finder cache)"
    try:  # also to Supabase, so the results can be read from outside the server
        import cloudstore
        if not cloudstore.enabled():
            try:
                import streamlit as st
                sb = dict(st.secrets.get("supabase") or {})
                cloudstore.configure(sb.get("url"), sb.get("key"))
            except Exception:
                pass
        cloudstore.upsert_rows("bot_results", [{"run_at": "index_funnel " + res["run_at"],
                                                "result": json.loads(json.dumps(res, default=str))}], "run_at")
        import time as _t
        _t.sleep(3)
    except Exception:
        pass
    out = paths.DATA / "bot"
    out.mkdir(parents=True, exist_ok=True)
    save(res, out / "index_funnel.json")
    return res


if __name__ == "__main__":
    r = run_server()
    print("index funnel:", (r or {}).get("all"))


def day_trend(ix: pd.DataFrame, stocks: dict, weights: dict) -> dict | None:
    """The day measured from YESTERDAY's close (catches gap days the from-open funnel cannot see): change, gap, breadth
    vs yesterday (share of the index weight up / down), and whether the move is a trend day."""
    d = _clean(ix)
    if d.empty:
        return None
    day = d.index.normalize()
    days = sorted(set(day))
    if len(days) < 16:
        return None
    today, prev = d[day == days[-1]], d[day == days[-2]]
    dd = d.groupby(day).agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    pcs = dd["c"].shift(1)
    trd = pd.concat([dd["h"] - dd["l"], (dd["h"] - pcs).abs(), (dd["l"] - pcs).abs()], axis=1).max(axis=1)
    atr14 = float(trd.iloc[-15:-1].mean())
    pc, o, last = float(prev["Close"].iloc[-1]), float(today["Open"].iloc[0]), float(today["Close"].iloc[-1])
    up = dn = wsum = 0.0
    for s, w in (weights or {}).items():
        b = _clean(stocks.get(s))
        if b.empty:
            continue
        bd = b.index.normalize()
        bdays = sorted(set(bd))
        if len(bdays) < 2 or bdays[-1] != days[-1]:
            continue
        bpc = float(b[bd == bdays[-2]]["Close"].iloc[-1])
        ch = float(b["Close"].iloc[-1]) / bpc - 1
        up += w * (ch > 0)
        dn += w * (ch < 0)
        wsum += w
    br_up = up / wsum * 100 if wsum else np.nan
    br_dn = dn / wsum * 100 if wsum else np.nan
    chg_atr = (last - pc) / atr14 if atr14 else np.nan
    side = 1 if last > pc else -1 if last < pc else 0
    breadth = br_up if side > 0 else br_dn
    trend = bool(np.isfinite(chg_atr) and abs(chg_atr) >= 1.0 and breadth == breadth and breadth >= 75)
    return {"price": last, "chg_pct": (last / pc - 1) * 100, "gap_pct": (o / pc - 1) * 100, "from_open_pct": (last / o - 1) * 100,
            "chg_atr": chg_atr, "gap_atr": (o - pc) / atr14 if atr14 else np.nan, "breadth_up": br_up, "breadth_dn": br_dn,
            "side": side, "breadth_with": breadth, "trend_day": trend, "atr14": atr14, "pc": pc, "open": o}


def gap_go(ix: pd.DataFrame, stocks: dict, weights: dict) -> dict | None:
    """Gap & go: on a gap of 0.3+ daily ATR, the first 5-minute close beyond the FIRST HOUR's high (gap up) / low (gap
    down) after 10:15, with 70%+ of the index weight moving the gap's way vs yesterday. Small edge in the 3-year
    hourly test (Bank Nifty +0.05% a trade, both halves positive; Nifty ~0); buying the pullback on gap days lost."""
    dt = day_trend(ix, stocks, weights)
    if not dt or not np.isfinite(dt["gap_atr"]) or abs(dt["gap_atr"]) < 0.3:
        return {"active": False, "day": dt}
    d = _clean(ix)
    today = d[d.index.normalize() == d.index.normalize().max()]
    m = today.index.hour * 60 + today.index.minute
    first = today[m < 615]
    if len(first) < 12:
        return {"active": True, "signal": None, "day": dt, "wait": "first hour not finished"}
    s = 1 if dt["gap_atr"] > 0 else -1
    fh, fl = float(first["High"].max()), float(first["Low"].min())
    later = today[(m >= 615) & (m <= 840)]
    brk = later[(later["Close"] > fh)] if s > 0 else later[(later["Close"] < fl)]
    br = dt["breadth_up"] if s > 0 else dt["breadth_dn"]
    out = {"active": True, "day": dt, "first_high": fh, "first_low": fl, "side": "LONG" if s > 0 else "SHORT",
           "breadth": br, "signal": None}
    if brk.empty or not (br == br and br >= 70):
        out["wait"] = (f"waiting for a close {'above' if s > 0 else 'below'} the first hour's "
                       f"{'high' if s > 0 else 'low'} {fh if s > 0 else fl:,.0f}" + ("" if br == br and br >= 70 else
                                                                                       f" with breadth 70%+ (now {br:.0f}%)"))
        return out
    t0 = brk.index[0]
    px = float(brk["Close"].iloc[0])
    upto = today[today.index <= t0].tail(6)
    import funnel as FN
    plan = FN.trade_plan(s, px, dt["atr14"], float(upto["Low"].min()), float(upto["High"].max()))
    out["signal"] = {"time": (t0 + pd.Timedelta(minutes=5)).strftime("%H:%M"), "side": out["side"], "price": px, "plan": plan}
    return out
