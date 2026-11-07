"""Index Desk: seven bots, layer by layer, for short intraday trades in the five Indian indices (Nifty 50, Bank Nifty,
Fin Nifty, Sensex, Midcap Select) on 3-minute candles. Pure functions, no Streamlit.

1. PULSE  trend      - EMA 9 / 21 on 3-min, EMA 20 on 15-min, VWAP (index futures volume; time-weighted when there is
                       no futures volume). Vote: price above / below all three.
2. DRIVE  momentum   - RSI(14), MACD(12, 26, 9) histogram side and slope, and whether the index is active (ATR today vs
                       its usual, from the index funnel). A dead market votes 0; RSI beyond 75 / 25 = stretched.
3. PRISM  patterns   - micro patterns on the latest 3-min candles: 15-min opening range break, inside-bar break, NR7
                       break, engulfing, hammer / shooting star at an OI level, three strong candles, higher highs /
                       lower lows, VWAP reclaim / loss, failed break of yesterday's high / low. A FRESH pattern (last two
                       candles) is the entry trigger.
4. VAULT  OI         - option chain: support = biggest put OI below, resistance = biggest call OI above, today's writing
                       near the money (put writers = support building, call writers = cap), PCR; index futures OI
                       build-up (day and last 15 min). Vote: writers + futures, none against.
5. RIVER  flow       - the index's stocks, weighted: net money (and is it still growing), buying share, breadth (% of
                       weight up / down from the open), and the top-5 heavyweights' contribution.
6. SHIELD risk       - entry at the next candle's open; stop beyond the last 5-candle swing (0.8-2.0 x 3-min ATR);
                       TP1 = 1R (book half, stop to cost), TP2 = the next OI wall (1.5-3R); trail: after TP1 the stop
                       follows the low (long) / high (short) of the last two closed candles, never loosened; time stop:
                       out if not +0.5R within 10 candles (30 min); all out at 15:15. Checks: 9:30-14:30 only, room to
                       the OI wall >= 1R, R/R to TP2 >= 1.5, max 2 trades per index a day, 1 open per group
                       (Nifty / Sensex, Bank Nifty / Fin Nifty, Midcap), market not wild (ATR <= 2.5x usual).
7. ORACLE final call - TRADE when PRISM has a fresh trigger, at least 4 of the 5 readers (PULSE, DRIVE, PRISM, VAULT,
                       RIVER) agree, neither VAULT nor RIVER is against, and SHIELD passes. WAIT when 3 agree or one is
                       against; NO TRADE otherwise.

Analysis rules, not back-tested: every TRADE is paper-tracked with the exact exit rules (bots.py index_desk_step).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

INDEXES = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty", "FINNIFTY": "Fin Nifty", "SENSEX": "Sensex",
           "MIDCPNIFTY": "Midcap Select"}
GROUP = {"NIFTY": "Nifty/Sensex", "SENSEX": "Nifty/Sensex", "BANKNIFTY": "Banks", "FINNIFTY": "Banks",
         "MIDCPNIFTY": "Midcap"}
BOTS = {
    "PULSE": ("Trend", "EMA 9/21 (3-min), EMA 20 (15-min), VWAP."),
    "DRIVE": ("Momentum", "RSI, MACD histogram, is the index active."),
    "PRISM": ("Micro patterns", "Opening range, inside bar, NR7, engulfing, pin bars, swings, VWAP, failed breaks."),
    "VAULT": ("OI & option chain", "Support / resistance from OI, writers, PCR, futures build-up."),
    "RIVER": ("Flow & breadth", "Weighted net money of its stocks, buying share, breadth, heavyweights."),
    "SHIELD": ("Risk", "Entry, stop, TP1 / TP2, trail, time stop, room to the OI wall. Can reject."),
    "ORACLE": ("Final call", "4 of 5 agree, OI and flow not against, risk passed: TRADE."),
}
TRAIL_RULE = ("TP1 at 1R: book half, stop to cost. Then trail the stop to the low (long) / high (short) of the last two "
              "closed 3-min candles, never loosened; TP2 at the OI wall; out if not +0.5R in 30 min; all out 15:15.")


def _today(d: pd.DataFrame) -> pd.DataFrame:
    return d[d.index.normalize() == d.index.normalize().max()] if len(d) else d


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    ch = s.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(d, n=14):
    pc = d["Close"].shift()
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def vwap(ix: pd.DataFrame, fut: pd.DataFrame | None) -> tuple[float, str, float | None]:
    """(VWAP in index points, source, futures premium). Futures VWAP shifted by today's premium to index terms."""
    t = _today(ix)
    if fut is not None and len(fut) and "Volume" in fut:
        f = _today(fut)
        if len(f) and f["Volume"].fillna(0).sum() > 0 and f.index.normalize().max() == t.index.normalize().max():
            tp = (f["High"] + f["Low"] + f["Close"]) / 3
            fv = float((tp * f["Volume"]).sum() / f["Volume"].sum())
            prem = float(f["Close"].iloc[-1] - t["Close"].iloc[-1])
            return fv - prem, "futures volume", prem
    tp = (t["High"] + t["Low"] + t["Close"]) / 3
    return float(tp.mean()), "time-weighted (no futures volume)", None

# ---------------------------------------------------------------- 1. PULSE


def pulse(ix: pd.DataFrame, vw: float) -> dict:
    c = ix["Close"]
    e9, e21 = float(ema(c, 9).iloc[-1]), float(ema(c, 21).iloc[-1])
    c15 = c.resample("15min", offset="15min").last().dropna()
    e20_15 = float(ema(c15.iloc[:-1] if len(c15) > 21 else c15, 20).iloc[-1])
    px = float(c.iloc[-1])
    up = px > e9 > e21 and px > vw and px > e20_15
    dn = px < e9 < e21 and px < vw and px < e20_15
    vote = 1 if up else -1 if dn else 0
    above = sum([px > e9, px > e21, px > vw, px > e20_15])
    return {"vote": vote, "ema9": e9, "ema21": e21, "ema20_15m": e20_15, "vwap": vw,
            "text": f"price above {above}/4 (EMA9, EMA21, VWAP, 15-min EMA20)" + (" · aligned up" if up else " · aligned down" if dn else " · mixed")}

# ---------------------------------------------------------------- 2. DRIVE


def drive(ix: pd.DataFrame, row: pd.Series | None) -> dict:
    c = ix["Close"]
    r = float(rsi(c).iloc[-1])
    m = ema(c, 12) - ema(c, 26)
    h = m - ema(m, 9)
    h0, h1 = float(h.iloc[-1]), float(h.iloc[-2])
    macd = 1 if h0 > 0 and h0 >= h1 else -1 if h0 < 0 and h0 <= h1 else 0
    rs = 1 if r >= 55 else -1 if r <= 45 else 0
    day_x = float(row["day_x"]) if row is not None and pd.notna(row.get("day_x")) else np.nan
    active = not np.isfinite(day_x) or day_x >= 0.8
    vote = rs if rs == macd and active else 0
    cross = "MACD crossed up" if h0 > 0 >= h1 else "MACD crossed down" if h0 < 0 <= h1 else ""
    return {"vote": vote, "rsi": r, "macd_hist": h0, "macd_state": macd, "day_x": day_x, "active": active,
            "stretched": r >= 75 or r <= 25,
            "text": f"RSI {r:.0f} · MACD hist {'+' if h0 > 0 else '−'}{' rising' if h0 > h1 else ' falling'}"
                    + (f" · {cross}" if cross else "") + (f" · ATR {day_x:.1f}x usual" if np.isfinite(day_x) else "")
                    + ("" if active else " · quiet market")}

# ---------------------------------------------------------------- 3. PRISM


def prism(ix: pd.DataFrame, vw: float, levels: dict) -> dict:
    t = _today(ix)
    prev = ix[ix.index.normalize() < t.index.normalize().max()]
    pats = []
    if len(t) < 3:
        return {"vote": 0, "trigger": 0, "patterns": [], "text": "too early"}
    o, h, l, c = (t[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    n = len(t)
    rng = h - l
    body = np.abs(c - o)

    def add(name, side, fresh):
        pats.append({"name": name, "side": int(side), "fresh": bool(fresh)})

    if n > 6:   # 15-min opening range = first 5 three-minute candles
        orh, orl = h[:5].max(), l[:5].min()
        for i in range(5, n):
            if c[i] > orh or c[i] < orl:
                add("15-min opening range break" + (" up" if c[i] > orh else " down"), 1 if c[i] > orh else -1, i >= n - 2)
                break
    if n >= 3 and h[-2] <= h[-3] and l[-2] >= l[-3]:
        if c[-1] > h[-2]:
            add("inside-bar break up", 1, True)
        elif c[-1] < l[-2]:
            add("inside-bar break down", -1, True)
    if n >= 8 and rng[-2] == rng[-8:-1].min():
        if c[-1] > h[-2]:
            add("NR7 break up", 1, True)
        elif c[-1] < l[-2]:
            add("NR7 break down", -1, True)
    if c[-1] > o[-1] and c[-2] < o[-2] and c[-1] >= o[-2] and o[-1] <= c[-2] and body[-1] > body[-2]:
        add("bullish engulfing", 1, True)
    if c[-1] < o[-1] and c[-2] > o[-2] and c[-1] <= o[-2] and o[-1] >= c[-2] and body[-1] > body[-2]:
        add("bearish engulfing", -1, True)
    lw, uw = np.minimum(o[-1], c[-1]) - l[-1], h[-1] - np.maximum(o[-1], c[-1])
    a3 = float(atr(ix).iloc[-1]) if len(ix) > 20 else float(rng.mean())
    sup, res = levels.get("support"), levels.get("resistance")
    if rng[-1] > 0 and lw >= 2 * max(body[-1], rng[-1] * 0.1) and c[-1] >= l[-1] + 0.6 * rng[-1]:
        near = sup is not None and abs(l[-1] - sup) <= 1.5 * a3
        add("hammer" + (" at OI support" if near else ""), 1, True)
    if rng[-1] > 0 and uw >= 2 * max(body[-1], rng[-1] * 0.1) and c[-1] <= l[-1] + 0.4 * rng[-1]:
        near = res is not None and abs(h[-1] - res) <= 1.5 * a3
        add("shooting star" + (" at OI resistance" if near else ""), -1, True)
    if n >= 3 and all(c[-k] > o[-k] and body[-k] >= 0.6 * rng[-k] for k in (1, 2, 3)):
        add("three strong green candles", 1, True)
    if n >= 3 and all(c[-k] < o[-k] and body[-k] >= 0.6 * rng[-k] for k in (1, 2, 3)):
        add("three strong red candles", -1, True)
    if n >= 12:   # swing structure from 3-candle pivots
        ph = [h[i] for i in range(1, n - 1) if h[i] >= h[i - 1] and h[i] >= h[i + 1]]
        pl = [l[i] for i in range(1, n - 1) if l[i] <= l[i - 1] and l[i] <= l[i + 1]]
        if len(ph) >= 2 and len(pl) >= 2:
            if ph[-1] > ph[-2] and pl[-1] > pl[-2]:
                add("higher highs and higher lows", 1, False)
            elif ph[-1] < ph[-2] and pl[-1] < pl[-2]:
                add("lower highs and lower lows", -1, False)
    if c[-2] < vw < c[-1]:
        add("VWAP reclaimed", 1, True)
    elif c[-2] > vw > c[-1]:
        add("VWAP lost", -1, True)
    if len(prev):
        pd_ = prev[prev.index.normalize() == prev.index.normalize().max()]
        pdh, pdl = float(pd_["High"].max()), float(pd_["Low"].min())
        if h[:-1].max() > pdh and c[-2] > pdh >= c[-1]:
            add("failed break of yesterday's high", -1, True)
        elif l[:-1].min() < pdl and c[-2] < pdl <= c[-1]:
            add("failed break of yesterday's low", 1, True)
    s = sum(p["side"] for p in pats)
    fresh = [p for p in pats if p["fresh"]]
    fs = sum(p["side"] for p in fresh)
    return {"vote": int(np.sign(s)), "trigger": int(np.sign(fs)) if fresh else 0, "patterns": pats,
            "text": ", ".join(p["name"] + (" (now)" if p["fresh"] else "") for p in pats) or "no pattern"}

# ---------------------------------------------------------------- 4. VAULT


def vault(spot: float, chain: dict, fut: dict) -> dict:
    sup = (chain.get("support") or [None])[0]
    res = (chain.get("resistance") or [None])[0]
    w = chain.get("writers", 0)
    b, b15 = fut.get("buildup_day", ""), fut.get("buildup_15m", "")
    fb = 1 if b in ("Long build-up", "Short covering") else -1 if b in ("Short build-up", "Long unwinding") else 0
    f15 = 1 if b15 in ("Long build-up", "Short covering") else -1 if b15 in ("Short build-up", "Long unwinding") else 0
    votes = [x for x in (w, fb) if x]
    vote = int(np.sign(sum(votes))) if votes and not (1 in votes and -1 in votes) else 0
    pcr = chain.get("pcr")
    parts = []
    if sup:
        parts.append(f"support {sup:g} (put OI)")
    if res:
        parts.append(f"resistance {res:g} (call OI)")
    if w:
        parts.append("put writers adding" if w > 0 else "call writers adding")
    if b:
        parts.append(f"futures {b.lower()}" + (f", last 15 min {b15.lower()}" if b15 else ""))
    if pcr is not None and np.isfinite(pcr):
        parts.append(f"PCR {pcr:.2f}")
    return {"vote": vote, "support": sup, "resistance": res, "writers": w, "fut_buildup": b, "fut_15m": b15, "fut_15m_vote": f15,
            "pcr": pcr, "ce_add": chain.get("ce_add"), "pe_add": chain.get("pe_add"),
            "ce_chg_near": chain.get("ce_chg_near"), "pe_chg_near": chain.get("pe_chg_near"),
            "has_chain": bool(chain), "has_fut": bool(fut), "text": " · ".join(parts) or "no OI data"}

# ---------------------------------------------------------------- 5. RIVER


def river(row: pd.Series | None, stocks: dict, weights: dict) -> dict:
    if row is None or pd.isna(row.get("buy_share")):
        return {"vote": 0, "text": "no constituent data", "heavy": []}
    net, nb, bs = float(row["net"]), float(row["net_before"]), float(row["buy_share"])
    bu, bd = float(row["breadth_up"]), float(row["breadth_dn"])
    up = bs > 52 and net > nb and bu >= 55
    dn = bs < 48 and net < nb and bd >= 55
    heavy = []
    for s, w in sorted((weights or {}).items(), key=lambda kv: -kv[1])[:5]:
        b = stocks.get(s)
        if b is None or b.empty:
            continue
        t = _today(b)
        if t.empty:
            continue
        mv = (float(t["Close"].iloc[-1]) / float(t["Open"].iloc[0]) - 1) * 100
        heavy.append({"stock": s, "weight": round(float(w), 1), "move": round(mv, 2), "contrib": round(mv * w / 100, 3)})
    hc = sum(x["contrib"] for x in heavy)
    return {"vote": 1 if up else -1 if dn else 0, "net_cr": net, "net_15m_ago": nb, "buy_share": bs, "breadth_up": bu,
            "breadth_dn": bd, "heavy": heavy, "heavy_contrib": hc,
            "text": f"net ₹{net:+,.0f} Cr ({'growing' if net > nb else 'shrinking'}) · buying {bs:.0f}% · breadth "
                    f"{bu:.0f}% up / {bd:.0f}% down · top-5 heavyweights {hc:+.2f}% of the index"}

# ---------------------------------------------------------------- 6. SHIELD


def shield(ix: pd.DataFrame, side: int, va: dict, dr: dict, now_hm: str, trades_today: int, group_busy: bool,
           index_busy: bool) -> dict:
    t = _today(ix)
    a3 = float(atr(ix).iloc[-1])
    px = float(t["Close"].iloc[-1])
    last5 = t.tail(5)
    if side > 0:
        stop = float(np.clip(last5["Low"].min() - 0.1 * a3, px - 2.0 * a3, px - 0.8 * a3))
        wall = va.get("resistance") if va.get("resistance") and va["resistance"] > px else None
    else:
        stop = float(np.clip(last5["High"].max() + 0.1 * a3, px + 0.8 * a3, px + 2.0 * a3))
        wall = va.get("support") if va.get("support") and va["support"] < px else None
    risk = abs(px - stop)
    tp1 = px + side * risk
    room = abs(wall - px) / risk if wall and risk else np.inf
    tp2 = px + side * float(np.clip(room - 0.2 if np.isfinite(room) else 2.5, 1.5, 3.0)) * risk
    rr2 = abs(tp2 - px) / risk if risk else 0
    day_x = dr.get("day_x", np.nan)
    checks = [
        ("Time window", "09:30" <= now_hm <= "14:30", f"{now_hm} (entries 9:30-14:30)"),
        ("Room to OI wall", room >= 1.0, (f"{room:.1f}R to the {'call' if side > 0 else 'put'} wall at {wall:g}" if wall else "no wall in the way")),
        ("Reward / risk", rr2 >= 1.5, f"TP2 {rr2:.1f}R"),
        ("Trades today", trades_today < 2, f"{trades_today} on this index (max 2)"),
        ("One per group", not group_busy and not index_busy, "open trade on this index / its group" if (group_busy or index_busy) else "free"),
        ("Volatility", not (np.isfinite(day_x) and day_x > 2.5), f"ATR {day_x:.1f}x usual" if np.isfinite(day_x) else "n/a"),
    ]
    return {"side": int(side), "entry": px, "stop": stop, "tp1": tp1, "tp2": tp2, "risk_pts": risk, "atr3": a3,
            "rr": round(float(rr2), 2), "wall": wall, "trail": TRAIL_RULE,
            "checks": [{"name": n, "pass": bool(p), "text": tx} for n, p, tx in checks], "pass": all(p for _, p, _ in checks)}

# ---------------------------------------------------------------- 7. ORACLE


def oracle(pu, dr, pr, va, rv, sh) -> dict:
    side = pr["trigger"]
    votes = {"PULSE": pu["vote"], "DRIVE": dr["vote"], "PRISM": pr["vote"], "VAULT": va["vote"], "RIVER": rv["vote"]}
    if not side:
        lean = int(np.sign(sum(votes.values())))
        return {"call": "NO TRADE", "side": lean, "why": "No fresh micro-pattern trigger on the last candles.",
                "votes": votes, "agree": sum(1 for v in votes.values() if v == lean and lean), "against": 0}
    agree = sum(1 for v in votes.values() if v == side)
    against = [k for k, v in votes.items() if v == -side]
    key_against = [k for k in against if k in ("VAULT", "RIVER")]
    if dr.get("stretched") and dr["rsi"] * side > (75 if side > 0 else -25):
        against.append("DRIVE (RSI stretched)")
    if sh and not sh["pass"]:
        failed = ", ".join(c["name"].lower() for c in sh["checks"] if not c["pass"])
        return {"call": "REJECT", "side": side, "why": f"SHIELD rejected: {failed}.", "votes": votes, "agree": agree,
                "against": len(against)}
    if agree >= 4 and not key_against and not any("stretched" in a for a in against):
        return {"call": "TRADE", "side": side, "why": f"{agree}/5 agree, OI and flow not against, risk passed.",
                "votes": votes, "agree": agree, "against": len(against)}
    if agree >= 3:
        return {"call": "WAIT", "side": side, "why": (f"{', '.join(against)} against" if against else f"only {agree}/5 agree")
                + ": wait for confirmation.", "votes": votes, "agree": agree, "against": len(against)}
    return {"call": "NO TRADE", "side": side, "why": f"Only {agree}/5 agree with the {'long' if side > 0 else 'short'} trigger.",
            "votes": votes, "agree": agree, "against": len(against)}

# ---------------------------------------------------------------- one index, all layers


def read_index(key: str, ix: pd.DataFrame, fut: pd.DataFrame | None, chain: dict, fut_oi: dict, row: pd.Series | None,
               stocks: dict, weights: dict, now_hm: str, trades_today: int = 0, group_busy: bool = False,
               index_busy: bool = False) -> dict | None:
    if ix is None or len(_today(ix)) < 3 or len(ix) < 60:
        return None
    vw, vsrc, prem = vwap(ix, fut)
    pu = pulse(ix, vw)
    dr = drive(ix, row)
    va = vault(float(ix["Close"].iloc[-1]), chain, fut_oi)
    pr = prism(ix, vw, va)
    rv = river(row, stocks, weights)
    side = pr["trigger"] or int(np.sign(pu["vote"] + dr["vote"] + rv["vote"]))
    sh = shield(ix, side, va, dr, now_hm, trades_today, group_busy, index_busy) if pr["trigger"] else None
    orc = oracle(pu, dr, pr, va, rv, sh)
    t = _today(ix)
    o = float(t["Open"].iloc[0])
    return {"index": key, "name": INDEXES.get(key, key), "price": float(t["Close"].iloc[-1]), "move_pct": (float(t["Close"].iloc[-1]) / o - 1) * 100,
            "as_of": str(t.index[-1])[11:16], "vwap_source": vsrc, "fut_premium": prem,
            "pulse": pu, "drive": dr, "prism": pr, "vault": va, "river": rv, "shield": sh, "oracle": orc,
            "spark": [round(float(x), 2) for x in t["Close"].tail(60)]}

# ---------------------------------------------------------------- paper trade management


def manage(tr: dict, bars: pd.DataFrame) -> dict:
    """Walk an open trade through the closed 3-min candles after its entry with the exit rules. bars: today's index
    candles. Mutates and returns tr (status open / closed, legs, R)."""
    if tr.get("status") == "closed":
        return tr
    t = bars[bars.index > pd.Timestamp(tr["signal_ts"])]
    if t.empty:
        return tr
    if tr.get("entry") is None:
        tr["entry"] = float(t["Open"].iloc[0])
        tr["entry_at"] = str(t.index[0])[11:16]
        shift = tr["entry"] - tr["plan_entry"]
        for k in ("stop", "tp1", "tp2"):
            tr[k] = tr[k] + shift
        tr["risk_pts"] = abs(tr["entry"] - tr["stop"])
        tr["status"] = "open"
    s, e, R = tr["side"], tr["entry"], tr["risk_pts"]
    stop, half = tr.get("cur_stop", tr["stop"]), tr.get("half_done", False)
    best = tr.get("best", e)
    rows = t[t.index >= pd.Timestamp(t.index[0])]
    after = rows[rows.index > pd.Timestamp(tr.get("last_ts", "1970-01-01"))] if tr.get("last_ts") else rows
    for i, (ts, b) in enumerate(after.iterrows()):
        hm = ts.strftime("%H:%M")
        o_, h_, l_, c_ = float(b["Open"]), float(b["High"]), float(b["Low"]), float(b["Close"])
        k = int(((rows.index <= ts).sum()))           # candles since entry, including this one
        if hm >= "15:15":
            return _close(tr, o_, hm, "15:15 exit", half)
        if (s > 0 and l_ <= stop) or (s < 0 and h_ >= stop):
            x = min(o_, stop) if s > 0 else max(o_, stop)
            return _close(tr, x, hm, "trailed stop" if half else "stop", half)
        if not half and ((s > 0 and h_ >= tr["tp1"]) or (s < 0 and l_ <= tr["tp1"])):
            half = True
            tr["half_done"], tr["half_px"], tr["half_at"] = True, tr["tp1"], hm
            stop = max(stop, e) if s > 0 else min(stop, e)
        if half and ((s > 0 and h_ >= tr["tp2"]) or (s < 0 and l_ <= tr["tp2"])):
            return _close(tr, tr["tp2"], hm, "TP2", half)
        best = max(best, h_) if s > 0 else min(best, l_)
        if not half and k >= 10 and s * (best - e) < 0.5 * R:
            return _close(tr, c_, hm, "time stop (no +0.5R in 30 min)", half)
        if half:     # trail: low / high of the last two closed candles, never loosened
            j = rows.index.get_loc(ts)
            w = rows.iloc[max(0, j - 1): j + 1]
            ts_ = float(w["Low"].min()) if s > 0 else float(w["High"].max())
            stop = max(stop, ts_) if s > 0 else min(stop, ts_)
        tr["last_ts"] = str(ts)
    tr["cur_stop"], tr["best"] = stop, best
    tr["now_r"] = round(s * (float(rows["Close"].iloc[-1]) - e) / R, 2) if R else None
    return tr


def _close(tr, x, hm, why, half):
    s, e, R = tr["side"], tr["entry"], tr["risk_pts"]
    leg2 = s * (x - e)
    pts = 0.5 * s * (tr["half_px"] - e) + 0.5 * leg2 if half else leg2
    tr.update(status="closed", exit_px=float(x), exit_at=hm, result=why, points=round(float(pts), 2),
              r=round(float(pts / R), 2) if R else None, pct=round(float(pts / e * 100), 3))
    return tr
