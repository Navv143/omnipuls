"""Paper weekly Nifty iron fly on REAL recorded option prices (research/option_edge_study.py: the option sellers' edge).

Each week, on the first market cycle from 09:30 with no open trade and the nearest expiry still ahead (so: the day
after an expiry): sell the ATM call and put, buy a call and a put about 2 weekly standard deviations away (2 x spot x
ATM IV x sqrt(days to expiry / 365)), from the recorder's latest Nifty option chain. Sells fill at the bid, buys at
the ask (LTP when missing). Marked every cycle at what it would cost to close (shorts bought back at the ask, wings sold
at the bid). Closed on expiry day from 15:15. Risk is capped: max loss = wing width - credit.
Costs per lot (approx.): Rs 20 x 8 orders + 0.15% of the premium turnover (STT on sold premium, exchange, GST).
State: <data>/bots/ironfly.json; also Supabase crypto_paper (setup "Nifty iron fly <expiry>").
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime

import pandas as pd

import paths

FILE = paths.DATA / "bots" / "ironfly.json"
WING_SD = 2.0
ENTRY_FROM, CLOSE_FROM = "09:30", "15:15"


def _chain(now: datetime, index: str = "NIFTY") -> pd.DataFrame | None:
    d = paths.DATA / "option_chain" / "parts" / now.strftime("%Y-%m-%d")
    files = sorted(d.glob("*.parquet")) if d.exists() else []
    for f in reversed(files[-3:]):
        try:
            c = pd.read_parquet(f)
        except Exception:
            continue
        c = c[c["index"] == index]
        if c.empty:
            continue
        c = c[c["time"] == c["time"].max()]
        age = now.replace(tzinfo=None) - pd.Timestamp(c["time"].iloc[0]).to_pydatetime()
        if age.total_seconds() > 600:
            return None
        return c
    return None


def _px(row: pd.Series, side: str, how: str) -> float | None:
    """side 'ce'/'pe'; how 'bid'/'ask'; falls back to the LTP."""
    for k in (f"{side}_{how}", f"{side}_ltp"):
        v = row.get(k)
        if v is not None and pd.notna(v) and float(v) > 0:
            return float(v)
    return None


def _lot() -> int | None:
    try:
        import dhan as D
        return (D.nearest_futures("NSE_FNO", "FUTIDX", ["NIFTY"]).get("NIFTY") or {}).get("lot")
    except Exception:
        return None


def _load() -> list[dict]:
    try:
        return json.loads(FILE.read_text())
    except Exception:
        return []


def _save(rows: list[dict]):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, default=str))
    os.replace(tmp, FILE)


def step(now: datetime) -> dict | None:
    hm = now.strftime("%H:%M")
    if hm < ENTRY_FROM:
        return None
    rows = _load()
    open_ = next((r for r in rows if r.get("status") == "open"), None)
    c = _chain(now)
    if c is None:
        return open_
    today = now.strftime("%Y-%m-%d")
    if open_ is None:
        exp = sorted(e for e in c["expiry"].astype(str).unique() if e > today)
        if not exp or hm > "14:30":
            return None
        ch = c[c["expiry"].astype(str) == exp[0]].sort_values("strike")
        spot = float(ch["spot"].iloc[0])
        atm = ch.iloc[(ch["strike"] - spot).abs().argsort().iloc[0]]
        iv = pd.to_numeric(pd.Series([atm.get("ce_iv"), atm.get("pe_iv")]), errors="coerce").mean()
        dte = max((pd.Timestamp(exp[0]) + pd.Timedelta(hours=15, minutes=30) - pd.Timestamp(now.replace(tzinfo=None))).total_seconds()
                  / 86400, 0.5)
        if not (iv and iv > 0):
            return None
        w = WING_SD * spot * iv / 100 * math.sqrt(dte / 365)
        k = float(atm["strike"])
        up = ch.iloc[(ch["strike"] - (k + w)).abs().argsort().iloc[0]]
        dn = ch.iloc[(ch["strike"] - (k - w)).abs().argsort().iloc[0]]
        legs = {"short_ce": _px(atm, "ce", "bid"), "short_pe": _px(atm, "pe", "bid"),
                "long_ce": _px(up, "ce", "ask"), "long_pe": _px(dn, "pe", "ask")}
        if any(v is None for v in legs.values()) or float(up["strike"]) <= k or float(dn["strike"]) >= k:
            return None
        credit = legs["short_ce"] + legs["short_pe"] - legs["long_ce"] - legs["long_pe"]
        width = max(float(up["strike"]) - k, k - float(dn["strike"]))
        open_ = {"setup": f"Nifty iron fly {exp[0]}", "expiry": exp[0], "opened": now.strftime("%Y-%m-%d %H:%M"),
                 "spot": round(spot, 2), "atm": k, "wing_ce": float(up["strike"]), "wing_pe": float(dn["strike"]),
                 "iv": round(float(iv), 2), "entry": {k_: round(v, 2) for k_, v in legs.items()}, "credit": round(credit, 2),
                 "max_loss": round(width - credit, 2), "lot": _lot(), "status": "open", "marks": []}
        rows.append(open_)
    ch = c[c["expiry"].astype(str) == open_["expiry"]]
    if ch.empty:
        return open_
    by_k = ch.set_index("strike")
    try:
        cost = (_px(by_k.loc[open_["atm"]], "ce", "ask") + _px(by_k.loc[open_["atm"]], "pe", "ask")
                - _px(by_k.loc[open_["wing_ce"]], "ce", "bid") - _px(by_k.loc[open_["wing_pe"]], "pe", "bid"))
    except Exception:
        return open_
    pnl = open_["credit"] - cost
    turnover = sum(open_["entry"].values()) + abs(cost)
    lot = open_.get("lot") or 0
    cost_pts = (160 / lot if lot else 0) + 0.0015 * turnover
    open_.update({"spot_now": round(float(ch["spot"].iloc[0]), 2), "close_cost": round(cost, 2), "pnl_pts": round(pnl, 2),
                  "pnl_after_costs_pts": round(pnl - cost_pts, 2), "marked": now.strftime("%Y-%m-%d %H:%M"),
                  "pnl_rs_per_lot": round((pnl - cost_pts) * lot) if lot else None})
    if not open_["marks"] or open_["marks"][-1][0][:10] != today:
        open_["marks"].append([now.strftime("%Y-%m-%d %H:%M"), open_["pnl_pts"]])
    else:
        open_["marks"][-1] = [now.strftime("%Y-%m-%d %H:%M"), open_["pnl_pts"]]
    if today >= open_["expiry"] and hm >= CLOSE_FROM:
        open_["status"] = "closed"
        open_["closed"] = now.strftime("%Y-%m-%d %H:%M")
    _save(rows)
    return open_


def load() -> list[dict]:
    return _load()


def paper_row(t: dict) -> dict:
    """The trade as a crypto_paper row (entry = credit in points, pct = P&L after costs as % of spot, R vs max loss)."""
    return {"day": t["opened"][:10], "setup": t["setup"], "symbol": "NIFTY", "side": -1, "signal_at": t["opened"][11:],
            "entry_at": t["opened"][11:], "entry_at_ist": t["opened"][11:], "entry": t["credit"], "sl": None, "tp": None,
            "stop_pct": None, "result": "time" if t["status"] == "closed" else "open", "exit_at": t.get("closed"),
            "exit_px": t.get("close_cost"),
            "r": round(t.get("pnl_after_costs_pts", 0) / t["max_loss"], 3) if t.get("max_loss", 0) > 0 else None,
            "pct": round(t.get("pnl_after_costs_pts", 0) / t["spot"] * 100, 4)}


if __name__ == "__main__":
    print(json.dumps(_load()[-3:], indent=1, default=str))
