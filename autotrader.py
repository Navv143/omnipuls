"""Auto Trader (paper): six agents that turn the bots' signals into sized paper trades with fixed risk rules.

1. Scanner   - what the bots scanned this cycle (F&O stocks + indices) and the signals they produced
2. Filter    - drops signals from untested sources, outside 9:20-15:00, with a stop too tight / too wide, or on a
               symbol that already has an open position
3. Analyst   - checks the plan (entry / stop / targets in the right order, reward:risk) and notes OI / evidence
4. Risk      - sizes each trade to RISK_PCT of the account (stop distance), caps the position value, refuses new trades
               when MAX_OPEN are open or the day's loss reaches MAX_DAY_LOSS_PCT
5. Executor  - opens the paper position at the signal's entry and closes it with the managed exits (target 1 → half
               and stop to entry, trail, momentum slowing before target 1, target 2, stop, 15:15)
6. Reporter  - the account: equity, today's P&L, wins / losses, the equity curve over the days

Pure functions; bots.py calls step() every 5 minutes with the day's signal records (which already carry the live
and managed results) and close_day() at 15:35. No real orders.
"""
from __future__ import annotations

import math

RULES = {
    "capital": 100000.0,        # starting paper capital (₹)
    "risk_pct": 1.0,            # risk per trade, % of equity (distance entry → stop × quantity)
    "max_day_loss_pct": 3.0,    # no new trades once today's P&L (closed + open) is this far down
    "max_open": 5,              # positions open at the same time
    "start": "09:20", "last_entry": "15:00",
    "min_stop_pct": 0.15, "max_stop_pct": 2.5,   # stop distance as % of price
    "max_position_x": 3.0,      # position value at most 3x equity (intraday margin)
    "cost_stock_pct": 0.12, "cost_index_pct": 0.02,   # round trip, % of position value
}

# sources the Filter lets through (tested or small-edge setups); everything else is logged as rejected
# Only tested setups (setup_registry: "account": True). The old engines (index funnel, index momentum bot, momentum
# funnel, master bot, gap & go) lost on paper (index funnel -0.36R, momentum funnel -0.26R, 5-6 Nov) and never passed a
# backtest: they are logged as "untested source" and not traded.
import setup_registry as _REG
TRADE_SOURCES = _REG.account_setups()
INDEXES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")

AGENTS = [("Scanner", "scans every F&O stock and index every 5 minutes"),
          ("Filter", "only tested setups, 9:20-15:00, sane stop, one open position per symbol"),
          ("Analyst", "checks entry / stop / targets and reward:risk"),
          ("Risk manager", "1% risk a trade · max 5 open · stop at -3% a day"),
          ("Executor", "paper orders, managed exits (half at T1, trail, 15:15)"),
          ("Reporter", "equity, P&L, wins / losses, equity curve")]


def _key(s: dict) -> str:
    return f"{s['source']}|{s['symbol']}"


def _base(sym: str) -> str:
    return str(sym).split(" ")[0]


def _r_of(t: dict) -> float | None:
    """The trade's result in R: managed exit when closed, R now while open."""
    if t.get("m_r") is not None:
        return float(t["m_r"])
    if t.get("status") == "closed" and t.get("r") is not None:   # stopped / target hit before the managed exit ran
        return float(t["r"])
    if t.get("r_now") is not None:
        return float(t["r_now"])
    return None


def pnl_of(pos: dict, rec: dict | None) -> dict:
    """Paper P&L of a position from its signal record (live R or managed exit R)."""
    r = _r_of(rec or {})
    risk_unit = abs(pos["entry"] - pos["sl"])
    gross = (r or 0.0) * risk_unit * pos["qty"]
    cost = pos["value"] * pos["cost_pct"] / 100
    closed = bool(rec and (rec.get("m_exit") or rec.get("status") == "closed"))
    return {"r": r, "gross": round(gross, 2), "cost": round(cost, 2), "pnl": round(gross - cost, 2), "closed": closed,
            "ltp": (rec or {}).get("ltp"), "advice": (rec or {}).get("advice"), "exit": (rec or {}).get("m_exit"),
            "stop_now": (rec or {}).get("stop_now")}


def step(book: dict, records: list, equity_start: float, now_hhmm: str, scanned: int, rules: dict = RULES) -> dict:
    """One cycle: every new signal record goes through Filter → Analyst → Risk → Executor (decision fixed once made);
    open positions are marked to their records. `book` = {"decisions": {key: {...}}, "funnel": {...}}."""
    dec = book.setdefault("decisions", {})
    recs = {_key(r): r for r in records}
    # today's P&L so far (closed + open) for the day-loss rule
    def day_pnl():
        return sum(pnl_of(d["pos"], recs.get(k))["pnl"] for k, d in dec.items() if d.get("pos"))
    for r in sorted(records, key=lambda x: x.get("time", "")):
        k = _key(r)
        if k in dec:
            continue
        d = {"time": r.get("time"), "decided_at": now_hhmm, "source": r["source"], "symbol": r["symbol"],
             "side": int(r["side"]), "entry": r.get("entry"), "sl": r.get("sl"), "tp1": r.get("tp1"), "tp2": r.get("tp2"),
             "note": r.get("note"), "stage": "Filter", "ok": False}
        dec[k] = d
        # --- Filter
        if not str(r["source"]).startswith(TRADE_SOURCES):
            d["why"] = "untested source (watch only)"
            continue
        if not (rules["start"] <= str(r.get("time", "")) <= rules["last_entry"]):
            d["why"] = f"outside {rules['start']}-{rules['last_entry']}"
            continue
        if None in (r.get("entry"), r.get("sl"), r.get("tp1"), r.get("tp2")):
            d["why"] = "no plan"
            continue
        e, sl, t1, t2, sd = float(r["entry"]), float(r["sl"]), float(r["tp1"]), float(r["tp2"]), int(r["side"])
        stop_pct = abs(e - sl) / e * 100
        if not (rules["min_stop_pct"] <= stop_pct <= rules["max_stop_pct"]):
            d["why"] = f"stop {stop_pct:.2f}% away (allowed {rules['min_stop_pct']}-{rules['max_stop_pct']}%)"
            continue
        if any(x.get("pos") and _base(x["symbol"]) == _base(r["symbol"])
               and not pnl_of(x["pos"], recs.get(kk))["closed"] for kk, x in dec.items()):
            d["why"] = f"a {_base(r['symbol'])} position is already open"
            continue
        # --- Analyst
        d["stage"] = "Analyst"
        if not (sd * (t1 - e) > 0 and sd * (t2 - t1) > 0 and sd * (e - sl) > 0):
            d["why"] = "plan levels out of order"
            continue
        rr = abs(t2 - e) / abs(e - sl)
        d["rr"] = round(rr, 2)
        if rr < 1.5:
            d["why"] = f"reward:risk {rr:.1f} < 1.5"
            continue
        # --- Risk manager
        d["stage"] = "Risk manager"
        n_open = sum(1 for kk, x in dec.items() if x.get("pos") and not pnl_of(x["pos"], recs.get(kk))["closed"])
        if n_open >= rules["max_open"]:
            d["why"] = f"{n_open} positions open (max {rules['max_open']})"
            continue
        dp = day_pnl()
        if dp <= -equity_start * rules["max_day_loss_pct"] / 100:
            d["why"] = f"day loss limit hit (₹{dp:,.0f})"
            continue
        risk_amt = equity_start * rules["risk_pct"] / 100
        qty = math.floor(risk_amt / abs(e - sl))
        cap_qty = math.floor(equity_start * rules["max_position_x"] / e)
        qty = min(qty, cap_qty)
        if qty < 1:
            d["why"] = "position too small for the price"
            continue
        # --- Executor
        d["stage"] = "Executor"
        idx = _base(r["symbol"]) in INDEXES
        d["pos"] = {"qty": qty, "entry": e, "sl": sl, "value": round(qty * e, 2), "risk": round(qty * abs(e - sl), 2),
                    "cost_pct": rules["cost_index_pct"] if idx else rules["cost_stock_pct"]}
        d["ok"] = True
        d["why"] = (f"{'BUY' if sd > 0 else 'SELL'} {qty} @ {e:,.2f} · risk ₹{d['pos']['risk']:,.0f} "
                    f"({d['pos']['risk'] / equity_start * 100:.1f}%) · R:R {rr:.1f}")
    # mark to market
    for k, d in dec.items():
        if d.get("pos"):
            d["mark"] = pnl_of(d["pos"], recs.get(k))
    taken = [d for d in dec.values() if d.get("pos")]
    closed = [d for d in taken if d["mark"]["closed"]]
    pnl = sum(d["mark"]["pnl"] for d in taken)
    book["funnel"] = {"scanned": scanned, "signals": len(dec),
                      "filtered": sum(1 for d in dec.values() if d["stage"] != "Filter" or d["ok"]),
                      "analysed": sum(1 for d in dec.values() if d["stage"] in ("Risk manager", "Executor")),
                      "executed": len(taken), "open": len(taken) - len(closed), "closed": len(closed),
                      "wins": sum(1 for d in closed if d["mark"]["pnl"] > 0),
                      "losses": sum(1 for d in closed if d["mark"]["pnl"] <= 0)}
    book["pnl"] = round(pnl, 2)
    book["equity_start"] = equity_start
    book["equity"] = round(equity_start + pnl, 2)
    book["updated"] = now_hhmm
    return book


def close_day(account: dict, day: str, book: dict) -> dict:
    """Adds the finished day to the account history (once per day)."""
    hist = [h for h in account.get("history", []) if h["day"] != day]
    f = book.get("funnel") or {}
    hist.append({"day": day, "pnl": book.get("pnl", 0.0), "equity": book.get("equity", account.get("equity", RULES["capital"])),
                 "trades": f.get("executed", 0), "wins": f.get("wins", 0), "losses": f.get("losses", 0),
                 "signals": f.get("signals", 0)})
    hist.sort(key=lambda h: h["day"])
    account["history"] = hist
    account["equity"] = hist[-1]["equity"]
    return account
