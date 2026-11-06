"""Super Bot: six bots in a row on every F&O stock, every closed candle (3 minutes).

  1 SCANNER     every stock -> three tables: UP momentum, DOWN momentum, RANGED
  2 EXPANSION   on those tables: range vs ATR, volume vs usual by this time, last candles' volume / range
  3 MONEY       the stock's money flow (day and last 30 min) and its sector's money, same way as the move
  4 OI & ACTIVITY  futures OI change (fresh positions), unusual candles today with / against the move, smart score
  5 CHART       yesterday's high/low break, first 15-min and first-hour range break, acceleration, VWAP, RSI, room
                to the next support / resistance
  6 DECISION    TRADE or REJECT, with every reason: with the market only (longs while Nifty is up, shorts while down),
                at most 3 trades a day and 1 per sector (best scores first); entry = next candle's open, stop = last
                swing (0.3-1.0 ATR), target = next swing level (at least 1.5R, else 2R), profit lock after +1R, 15:20

Each stage returns a table with every stock it looked at, PASS / REJECT and the reason, so any rule can be reviewed and
changed later (all thresholds are in RULES). Recorded by bots.superbot_step: the latest table of each stage
(Supabase superbot_stage) and every arrival at the decision stage (superbot_trades): trades, rejects, and repeats while
the stock is already in a trade.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

RULES = {
    # 1 scanner
    "trend_move_pct": 0.5,          # |change from yesterday's close| to call it momentum
    # 2 expansion (pass when at least `exp_need` of the four hold)
    "atr_used": 0.6, "vol_x": 1.5, "last3_vol_x": 1.5, "move_atr": 0.5, "exp_need": 2,
    # 3 money
    "money_window_min": 30,
    # 4 OI & activity
    "oi_fresh_pct": 2.0, "smart_against": -10,
    # 5 chart (pass when price is on the right side of VWAP and at least `chart_need` of the 7 checks hold)
    "rsi_long": (55, 80), "rsi_short": (20, 45), "room_atr": 0.5, "chart_need": 4,
    # 6 decision
    "first_entry": "09:30", "last_entry": "14:30", "max_trades": 3, "max_per_sector": 1, "stop_atr": (0.3, 1.0),
    "min_rr": 1.5,
    # with the market: longs only while Nifty is up on the day, shorts only while it is down (research/superbot_strict.py,
    # 40 days: 3 a day + this rule = 61% wins, +0.29% a trade, t 2.24, both halves positive; without it -0.02%)
    "with_market": True,
}
STAGES = {1: "Scanner", 2: "Expansion", 3: "Money", 4: "OI & activity", 5: "Chart", 6: "Decision"}


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _rsi(c: pd.Series, n: int = 14) -> float:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    r = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return float(r.iloc[-1]) if len(r) else np.nan


def _swings(h: pd.Series, l: pd.Series, k: int = 3) -> tuple[list, list]:
    """Pivot highs and lows (k candles each side)."""
    H, L = h.to_numpy(), l.to_numpy()
    hi, lo = [], []
    for i in range(k, len(H) - k):
        if H[i] == H[i - k:i + k + 1].max():
            hi.append(float(H[i]))
        if L[i] == L[i - k:i + k + 1].min():
            lo.append(float(L[i]))
    return hi, lo


def run(S: dict, per: dict, events: pd.DataFrame, oi: pd.DataFrame, sector_of: dict, now: datetime,
        open_trades: set | None = None, trades_today: int = 0, nifty_chg: float | None = None,
        taken_sectors: dict | None = None) -> dict:
    """S: scanners.prepare() stocks; per: activity.rank() per-stock candle tables; events: activity unusual candles;
    oi: bots.oi_today() (index = stock, oi_chg %). Returns {stage number: DataFrame} with a 'pass' and 'reason' column,
    and 'decisions' (stage 6 rows)."""
    R = RULES
    open_trades = open_trades or set()
    hm = now.strftime("%H:%M")
    out = {i: [] for i in range(1, 7)}
    # sector money (day and window) from every stock's candles
    sec_day, sec_win = {}, {}
    for sym, c in per.items():
        if c is None or c.empty or "Net Flow Cr" not in c:
            continue
        sec = sector_of.get(sym, "Other")
        sec_day[sec] = sec_day.get(sec, 0.0) + float(c["Net Flow Cr"].sum())
        cut = c.index[-1] - pd.Timedelta(minutes=R["money_window_min"])
        sec_win[sec] = sec_win.get(sec, 0.0) + float(c.loc[c.index > cut, "Net Flow Cr"].sum())
    ev = events if events is not None else pd.DataFrame()

    for sym, s in S.items():
        t = s.today
        if t is None or len(t) < 2 or not s.prev_close:
            continue
        px = float(t["Close"].iloc[-1])
        chg = (px / s.prev_close - 1) * 100
        tp = (t["High"] + t["Low"] + t["Close"]) / 3
        vwap = float((tp * t["Volume"]).sum() / max(t["Volume"].sum(), 1e-9))
        allc = pd.concat([s.hist["Close"].tail(60), t["Close"]]) if getattr(s, "hist", None) is not None and len(s.hist) else t["Close"]
        e9, e21 = float(_ema(allc, 9).iloc[-1]), float(_ema(allc, 21).iloc[-1])
        A = float(s.atr) if s.atr else np.nan
        dhi, dlo = float(t["High"].max()), float(t["Low"].min())
        base = {"stock": sym, "sector": sector_of.get(sym, "Other"), "price": round(px, 2), "chg_pct": round(chg, 2),
                "time": hm}
        # ---- 1 scanner
        if chg >= R["trend_move_pct"] and px > vwap and e9 > e21:
            side, table = 1, "UP"
        elif chg <= -R["trend_move_pct"] and px < vwap and e9 < e21:
            side, table = -1, "DOWN"
        else:
            side, table = 0, "RANGED"
        r1 = {**base, "table": table, "vwap": round(vwap, 2), "ema9_vs_21": "up" if e9 > e21 else "down",
              "from_open_pct": round((px / float(t["Open"].iloc[0]) - 1) * 100, 2), "pass": True,
              "reason": {"UP": "momentum up: above VWAP, EMA9 > EMA21", "DOWN": "momentum down: below VWAP, EMA9 < EMA21",
                         "RANGED": "no clear momentum"}[table]}
        out[1].append(r1)
        # ---- 2 expansion
        c = per.get(sym)
        last = c.iloc[-1] if c is not None and len(c) else None
        atr_used = (dhi - dlo) / A if A and A > 0 else np.nan
        vol_x = float(last["Vol x (time)"]) if last is not None and pd.notna(last.get("Vol x (time)")) else np.nan
        l3v = float(c["Candle Vol x"].tail(3).mean()) if c is not None and "Candle Vol x" in c else np.nan
        l3r = float(c["Candle Range x"].tail(3).mean()) if c is not None and "Candle Range x" in c else np.nan
        move_atr = abs(px - s.prev_close) / A if A and A > 0 else np.nan
        checks = {"range vs ATR": atr_used >= R["atr_used"], "volume vs usual": vol_x >= R["vol_x"],
                  "last 3 candles volume": l3v >= R["last3_vol_x"], "move vs ATR": move_atr >= R["move_atr"]}
        nok = sum(bool(v) for v in checks.values())
        if side == 0:
            coiled = (atr_used <= 0.5) and (vol_x >= 2)
            p2, why = False, ("coiled: small range on heavy volume, watch for a break" if coiled else "ranged: no trade")
        else:
            p2 = nok >= R["exp_need"]
            why = (f"{nok}/4 expansion checks: " + ", ".join(k for k, v in checks.items() if v)) if p2 else \
                f"only {nok}/4 expansion checks"
        r2 = {**base, "side": table, "atr_used_x": round(atr_used, 2) if np.isfinite(atr_used) else None,
              "vol_x": round(vol_x, 2) if np.isfinite(vol_x) else None, "last3_vol_x": round(l3v, 2) if np.isfinite(l3v) else None,
              "last3_range_x": round(l3r, 2) if np.isfinite(l3r) else None,
              "move_atr": round(move_atr, 2) if np.isfinite(move_atr) else None, "checks": nok, "pass": bool(p2), "reason": why}
        out[2].append(r2)
        if not p2:
            continue
        # ---- 3 money
        day_net = float(c["Net Flow Cr"].sum()) if c is not None and "Net Flow Cr" in c else np.nan
        cut = c.index[-1] - pd.Timedelta(minutes=R["money_window_min"]) if c is not None else None
        win_net = float(c.loc[c.index > cut, "Net Flow Cr"].sum()) if cut is not None else np.nan
        sd_, sw_ = sec_day.get(base["sector"], 0.0), sec_win.get(base["sector"], 0.0)
        ok_stock = side * day_net > 0 and side * win_net >= 0
        ok_sec = side * sd_ >= 0 or side * sw_ > 0
        p3 = bool(ok_stock and ok_sec)
        why = ("stock and sector money agree" if p3 else
               ("stock money against the move" if not ok_stock else "sector money against the move"))
        r3 = {**base, "side": table, "stock_money_day_cr": round(day_net, 1), "stock_money_30m_cr": round(win_net, 1),
              "sector_money_day_cr": round(sd_, 1), "sector_money_30m_cr": round(sw_, 1), "pass": p3, "reason": why}
        out[3].append(r3)
        if not p3:
            continue
        # ---- 4 OI & unusual activity
        oc = float(oi["oi_chg"].get(sym)) if oi is not None and not oi.empty and sym in oi.index and pd.notna(oi["oi_chg"].get(sym)) else np.nan
        e_s = ev[ev["Stock"] == sym] if not ev.empty else ev
        green = e_s["Candle"].isin(["Green", "Bullish"]) if not e_s.empty else pd.Series(dtype=bool)
        u_with = int((green if side > 0 else ~green).sum()) if not e_s.empty else 0
        u_against = int(len(e_s) - u_with) if not e_s.empty else 0
        smart = float(last["Smart"]) if last is not None and pd.notna(last.get("Smart")) else 0.0
        fresh = np.isfinite(oc) and oc >= R["oi_fresh_pct"]
        build = ("" if not np.isfinite(oc) else ("Long buildup" if oc > 0 else "Short covering") if side > 0 else
                 ("Short buildup" if oc > 0 else "Long unwinding"))
        p4 = bool((fresh or u_with >= 1) and side * smart >= R["smart_against"] and u_with >= u_against)
        why = ", ".join(x for x in (f"fresh OI {oc:+.1f}% ({build})" if fresh else "",
                                    f"{u_with} unusual candle(s) with the move" if u_with else "",
                                    f"{u_against} against" if u_against else "", f"smart {smart:+.0f}") if x)
        if not p4:
            why = "no fresh OI and no unusual candle with the move" if not (fresh or u_with) else \
                ("smart score against" if side * smart < R["smart_against"] else "more unusual candles against") + \
                f" ({why})"
        r4 = {**base, "side": table, "oi_chg_pct": round(oc, 2) if np.isfinite(oc) else None, "buildup": build,
              "unusual_with": u_with, "unusual_against": u_against, "unusual_today": int(len(e_s)), "smart": smart,
              "pass": p4, "reason": why}
        out[4].append(r4)
        if not p4:
            continue
        # ---- 5 chart
        hmt = t.index.strftime("%H:%M")
        f15, f60 = t[hmt < "09:30"], t[hmt < "10:15"]
        cl = t["Close"]
        k = {}
        k["yday high/low break"] = bool(px > s.pdh) if side > 0 else bool(px < s.pdl)
        k["first 15-min range break"] = bool(len(f15) and (px > f15["High"].max() if side > 0 else px < f15["Low"].min()))
        k["first-hour range break"] = bool(hm >= "10:15" and len(f60) and (px > f60["High"].max() if side > 0 else px < f60["Low"].min()))
        ret = cl.pct_change().dropna()
        k["acceleration"] = bool(len(ret) >= 9 and side * ret.tail(3).mean() > max(side * ret.iloc[-9:-3].mean(), 0))
        k["VWAP side"] = bool(side * (px - vwap) > 0)
        rsi = _rsi(allc)
        lo_, hi_ = R["rsi_long"] if side > 0 else R["rsi_short"]
        k["RSI zone"] = bool(np.isfinite(rsi) and lo_ <= rsi <= hi_)
        hist3 = pd.concat([s.hist.tail(3 * 125), t]) if getattr(s, "hist", None) is not None and len(s.hist) else t
        sh, sl = _swings(hist3["High"], hist3["Low"])
        res_ = min([x for x in sh if x > px], default=np.nan) if side > 0 else max([x for x in sl if x < px], default=np.nan)
        room = abs(res_ - px) / A if np.isfinite(res_) and A else np.inf
        k["room to next level"] = bool(room >= R["room_atr"])
        nk = sum(k.values())
        p5 = bool(k["VWAP side"] and nk >= R["chart_need"])
        why = f"{nk}/7: " + ", ".join(n for n, v in k.items() if v) if p5 else \
            ("wrong side of VWAP" if not k["VWAP side"] else f"only {nk}/7 chart checks")
        r5 = {**base, "side": table, "chart_checks": nk, "rsi": round(rsi, 1) if np.isfinite(rsi) else None,
              "next_level": round(res_, 2) if np.isfinite(res_) else None,
              "room_atr": round(room, 2) if np.isfinite(room) else None,
              **{n: v for n, v in k.items()}, "pass": p5, "reason": why}
        out[5].append(r5)
        if not p5:
            continue
        # ---- 6 decision
        recent = t.tail(6)
        swing = float(recent["Low"].min()) if side > 0 else float(recent["High"].max())
        lo_a, hi_a = R["stop_atr"]
        risk = min(max(abs(px - swing), lo_a * A), hi_a * A) if A else abs(px - swing)
        stop = px - side * risk
        tgt_lvl = res_ if np.isfinite(res_) and abs(res_ - px) >= R["min_rr"] * risk else np.nan
        target = tgt_lvl if np.isfinite(tgt_lvl) else px + side * 2 * risk
        rr = abs(target - px) / risk if risk else np.nan
        score = nok + nk + (1 if fresh else 0) + min(u_with, 2) + (1 if side * smart >= 25 else 0)
        reasons = [r2["reason"], r3["reason"], r4["reason"], r5["reason"]]
        against = R.get("with_market") and nifty_chg is not None and np.isfinite(nifty_chg) and \
            ((side > 0 and nifty_chg < 0) or (side < 0 and nifty_chg > 0))
        if sym in open_trades:
            decision, why = "REPEAT", "already in a trade on this stock"
        elif against:
            decision, why = "REJECT", f"against the market (Nifty {nifty_chg:+.2f}%): longs only when Nifty is up, shorts when down"
        elif hm < R["first_entry"]:
            decision, why = "REJECT", f"before {R['first_entry']}"
        elif hm > R["last_entry"]:
            decision, why = "REJECT", f"after {R['last_entry']}: too late for a new trade"
        elif not np.isfinite(rr) or rr < R["min_rr"]:
            decision, why = "REJECT", f"reward/risk {rr:.1f} below {R['min_rr']}"
        else:
            decision, why = "TRADE", f"all stages passed, score {score}"   # the day's limit is applied below
        out[6].append({**base, "side": table, "decision": decision, "reason": why, "score": score,
                       "entry_plan": round(px, 2), "stop": round(stop, 2), "target": round(target, 2),
                       "risk_pct": round(risk / px * 100, 2), "rr": round(rr, 2) if np.isfinite(rr) else None,
                       "stages": " | ".join(reasons), "pass": decision == "TRADE"})
    # the day's trade limit (best scores first) and one trade per sector a day
    left = R["max_trades"] - trades_today
    secs = dict(taken_sectors or {})
    for r in sorted([x for x in out[6] if x["decision"] == "TRADE"], key=lambda x: -x["score"]):
        if secs.get(r["sector"], 0) >= R.get("max_per_sector", 99):
            r["decision"], r["reason"], r["pass"] = "REJECT", f"already a trade in {r['sector']} today (1 per sector)", False
        elif left > 0:
            left -= 1
            secs[r["sector"]] = secs.get(r["sector"], 0) + 1
        else:
            r["decision"], r["reason"], r["pass"] = "REJECT", f"day's limit of {R['max_trades']} trades reached " \
                f"(score {r['score']}, lower than the trades taken)", False
    return {i: pd.DataFrame(v) for i, v in out.items()}
