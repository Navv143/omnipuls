"""
Nifty Liquidity Sweep backtest - Omnipuls module (Dhan API data).

Same rules as nifty_liquidity_sweep.pine:
  * Levels: previous-day high/low and opening range (9:15-9:30) high/low
  * Sweep: wick 5-60 pts beyond a level, candle closes back inside -> fade it
  * Confirm: "close" (enter on sweep candle close) or "break" (wait up to 3 bars
    for a close beyond the sweep candle's opposite end)
  * Stop: sweep wick +/- 5 pts (skip if risk > 60), target = 2R
  * Entries 9:30-14:30, max 2 trades/day, square-off 15:15

Run:
  python nifty_sweep_backtest.py --years 2               # command line
  streamlit run nifty_sweep_backtest.py                  # as an Omnipuls page
Env: DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
"""

import os
import sys
import time
from dataclasses import dataclass, asdict, replace
from datetime import date, datetime, timedelta, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"
NIFTY_ID = "13"            # NIFTY 50 index on Dhan (IDX_I segment)
CACHE = Path("cache")


# ----------------------------------------------------------------------------
@dataclass
class Params:
    use_day: bool = True
    use_or: bool = True
    or_end: dtime = dtime(9, 30)
    entry_start: dtime = dtime(9, 30)
    entry_end: dtime = dtime(14, 30)
    square_off: dtime = dtime(15, 15)
    confirm: str = "close"          # "close" or "break"
    confirm_bars: int = 3
    min_sweep: float = 5.0
    max_sweep: float = 60.0
    sl_buffer: float = 5.0
    max_risk: float = 60.0
    rr: float = 2.0
    max_trades: int = 2
    slippage: float = 1.0           # points per side
    lot_size: int = 75              # set current Nifty lot size


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

def fetch_nifty_5m(years: float, client_id=None, token=None) -> pd.DataFrame:
    """5-min Nifty candles from Dhan, 90-day chunks, cached to disk."""
    client_id = client_id or os.environ.get("DHAN_CLIENT_ID", "")
    token = token or os.environ.get("DHAN_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN.")
    CACHE.mkdir(exist_ok=True)
    cache_file = CACHE / "nifty_5m.csv"
    cached = pd.read_csv(cache_file, parse_dates=["dt"]) if cache_file.exists() else pd.DataFrame()

    end = date.today()
    start = end - timedelta(days=int(365 * years))
    if not cached.empty:
        have_from, have_to = cached["dt"].min().date(), cached["dt"].max().date()
        if have_from <= start + timedelta(days=5) and have_to >= end - timedelta(days=3):
            return cached[cached["dt"].dt.date >= start].reset_index(drop=True)

    s = requests.Session()
    s.headers.update({"access-token": token, "client-id": client_id,
                      "Content-Type": "application/json", "Accept": "application/json"})
    frames = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=89), end)
        body = {"securityId": NIFTY_ID, "exchangeSegment": "IDX_I", "instrument": "INDEX",
                "interval": "5", "oi": False,
                "fromDate": f"{cur} 09:15:00", "toDate": f"{nxt} 15:30:00"}
        for attempt in range(3):
            r = s.post(INTRADAY_URL, json=body, timeout=60)
            if r.status_code == 429:
                time.sleep(2 + 2 * attempt)
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"Dhan error {r.status_code}: {r.text[:300]}")
        j = r.json()
        if j.get("close"):
            frames.append(pd.DataFrame({
                "dt": pd.to_datetime(j["timestamp"], unit="s", utc=True)
                        .tz_convert("Asia/Kolkata").tz_localize(None),
                "open": j["open"], "high": j["high"], "low": j["low"], "close": j["close"],
            }))
        print(f"  fetched {cur} -> {nxt}")
        cur = nxt + timedelta(days=1)
        time.sleep(0.5)
    df = pd.concat(frames + ([cached] if not cached.empty else []))
    df = df.drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
    df.to_csv(cache_file, index=False)
    return df


def load_csv(path: str) -> pd.DataFrame:
    """Alternative: any 5-min CSV with datetime,open,high,low,close (IST)."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    dtcol = next(c for c in df.columns if c in ("dt", "datetime", "date", "time", "timestamp"))
    df["dt"] = pd.to_datetime(df[dtcol])
    return df[["dt", "open", "high", "low", "close"]].sort_values("dt").reset_index(drop=True)


# ----------------------------------------------------------------------------
# Strategy
# ----------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    df = df.copy()
    df["d"] = df["dt"].dt.date
    df["t"] = df["dt"].dt.time
    days = sorted(df["d"].unique())
    daily = df.groupby("d").agg(high=("high", "max"), low=("low", "min"))
    trades = []

    for di in range(1, len(days)):
        day = days[di]
        prev = daily.loc[days[di - 1]]
        pdh, pdl = prev["high"], prev["low"]
        g = df[df["d"] == day].reset_index(drop=True)
        orb = g[g["t"] < p.or_end]
        orh = orb["high"].max() if len(orb) else np.nan
        orl = orb["low"].min() if len(orb) else np.nan

        used = {"pdh": False, "pdl": False, "orh": False, "orl": False}
        n_trades = 0
        pos = None                      # dict when in a trade
        pend_s = pend_l = None          # pending break-confirm setups

        for i, b in g.iterrows():
            t = b["t"]
            if t < p.or_end:
                continue
            is_exit = t >= p.square_off
            in_window = p.entry_start <= t < p.entry_end

            # ---- manage open position (bars after entry) ----
            if pos is not None and i > pos["i"]:
                exit_px, why = None, None
                if pos["side"] == 1:
                    if b["low"] <= pos["stop"]:
                        exit_px, why = min(b["open"], pos["stop"]), "stop"
                    elif b["high"] >= pos["tgt"]:
                        exit_px, why = max(b["open"], pos["tgt"]), "target"
                else:
                    if b["high"] >= pos["stop"]:
                        exit_px, why = max(b["open"], pos["stop"]), "stop"
                    elif b["low"] <= pos["tgt"]:
                        exit_px, why = min(b["open"], pos["tgt"]), "target"
                if exit_px is None and is_exit:
                    exit_px, why = b["close"], "square-off"
                if exit_px is not None:
                    pts = pos["side"] * (exit_px - pos["entry"]) - 2 * p.slippage
                    trades.append({**pos["info"], "exit_time": b["dt"], "exit": round(exit_px, 2),
                                   "reason": why, "points": round(pts, 2)})
                    pos = None
            if is_exit:
                break

            # ---- sweep detection ----
            bear = bull = False
            if in_window:
                def bear_sw(l): return not np.isnan(l) and l + p.min_sweep <= b["high"] <= l + p.max_sweep and b["close"] < l
                def bull_sw(l): return not np.isnan(l) and l - p.max_sweep <= b["low"] <= l - p.min_sweep and b["close"] > l
                hits = []
                if p.use_day and not used["pdh"] and bear_sw(pdh): bear = True; used["pdh"] = True; hits.append("PDH")
                if p.use_or and not used["orh"] and bear_sw(orh): bear = True; used["orh"] = True; hits.append("ORH")
                if p.use_day and not used["pdl"] and bull_sw(pdl): bull = True; used["pdl"] = True; hits.append("PDL")
                if p.use_or and not used["orl"] and bull_sw(orl): bull = True; used["orl"] = True; hits.append("ORL")
                if bear and bull:
                    bear = bull = False

            go_s = go_l = False
            s_stop = l_stop = np.nan
            level = ",".join(hits) if in_window else ""
            if p.confirm == "close":
                if bear: go_s, s_stop = True, b["high"] + p.sl_buffer
                if bull: go_l, l_stop = True, b["low"] - p.sl_buffer
            else:
                if pend_s:
                    pend_s["stop"] = max(pend_s["stop"], b["high"] + p.sl_buffer)
                    if b["close"] < pend_s["trig"]:
                        go_s, s_stop, level = True, pend_s["stop"], pend_s["lvl"]; pend_s = None
                    elif i - pend_s["i"] >= p.confirm_bars or b["close"] > pend_s["stop"]:
                        pend_s = None
                if pend_l:
                    pend_l["stop"] = min(pend_l["stop"], b["low"] - p.sl_buffer)
                    if b["close"] > pend_l["trig"]:
                        go_l, l_stop, level = True, pend_l["stop"], pend_l["lvl"]; pend_l = None
                    elif i - pend_l["i"] >= p.confirm_bars or b["close"] < pend_l["stop"]:
                        pend_l = None
                if bear: pend_s = {"trig": b["low"], "stop": b["high"] + p.sl_buffer, "i": i, "lvl": level}
                if bull: pend_l = {"trig": b["high"], "stop": b["low"] - p.sl_buffer, "i": i, "lvl": level}

            # ---- entries ----
            can = in_window and pos is None and n_trades < p.max_trades
            for side, go, stop in ((-1, go_s, s_stop), (1, go_l and not go_s, l_stop)):
                if can and go:
                    entry = b["close"]
                    risk = side * (entry - stop)
                    if 0 < risk <= p.max_risk:
                        pos = {"side": side, "entry": entry, "stop": stop,
                               "tgt": entry + side * p.rr * risk, "i": i,
                               "info": {"date": day, "side": "LONG" if side == 1 else "SHORT",
                                        "level": level, "entry_time": b["dt"],
                                        "entry": round(entry, 2), "stop": round(stop, 2),
                                        "risk": round(risk, 2)}}
                        n_trades += 1
                        can = False
        # end of day safety (data gaps)
        if pos is not None:
            last = g.iloc[-1]
            pts = pos["side"] * (last["close"] - pos["entry"]) - 2 * p.slippage
            trades.append({**pos["info"], "exit_time": last["dt"], "exit": round(last["close"], 2),
                           "reason": "eod", "points": round(pts, 2)})
    return pd.DataFrame(trades)


def summary(t: pd.DataFrame, p: Params) -> dict:
    if t.empty:
        return {"trades": 0}
    pts = t["points"]
    w, l = pts[pts > 0], pts[pts <= 0]
    eq = pts.cumsum()
    dd = (eq - eq.cummax()).min()
    return {
        "trades": int(len(t)),
        "win_rate_%": round(100 * len(w) / len(t), 1),
        "net_points": round(float(pts.sum()), 1),
        "net_rupees_1lot": round(float(pts.sum()) * p.lot_size),
        "avg_points": round(float(pts.mean()), 2),
        "avg_win": round(float(w.mean()), 1) if len(w) else 0.0,
        "avg_loss": round(float(l.mean()), 1) if len(l) else 0.0,
        "profit_factor": round(float(w.sum() / -l.sum()), 2) if l.sum() < 0 else float("inf"),
        "max_drawdown_pts": round(float(dd), 1),
        "trading_days": int(t["date"].nunique()),
    }


def breakdowns(t: pd.DataFrame) -> dict:
    if t.empty:
        return {}
    t = t.copy()
    t["year"] = pd.to_datetime(t["date"]).dt.year
    t["win"] = t["points"] > 0
    agg = lambda g: t.groupby(g).agg(trades=("points", "size"), win_rate=("win", "mean"),
                                     net_points=("points", "sum"), avg=("points", "mean")).round(2)
    return {"by_side": agg("side"), "by_level": agg("level"), "by_year": agg("year"),
            "by_exit": agg("reason")}


def compare_variants(df, base: Params) -> pd.DataFrame:
    rows = []
    for confirm in ("close", "break"):
        for rr in (1.5, 2.0, 3.0):
            for levels in (("day", True, False), ("OR", False, True), ("both", True, True)):
                p = replace(base, confirm=confirm, rr=rr, use_day=levels[1], use_or=levels[2])
                s = summary(run_backtest(df, p), p)
                rows.append({"confirm": confirm, "rr": rr, "levels": levels[0], **s})
    return pd.DataFrame(rows).sort_values("profit_factor", ascending=False)


# ----------------------------------------------------------------------------
# Streamlit page (Omnipuls)
# ----------------------------------------------------------------------------

def streamlit_page():
    import streamlit as st
    st.title("Nifty Liquidity Sweep - Backtest")
    c1, c2, c3 = st.columns(3)
    years = c1.slider("Years of data", 0.5, 5.0, 2.0, 0.5)
    confirm = c2.selectbox("Entry confirmation", ["close", "break"])
    rr = c3.slider("Reward : Risk", 1.0, 4.0, 2.0, 0.25)
    c4, c5, c6 = st.columns(3)
    use_day = c4.checkbox("Prev-day high/low", True)
    use_or = c5.checkbox("Opening range", True)
    lot = c6.number_input("Lot size", 1, 500, 75)
    with st.expander("Advanced"):
        a1, a2, a3, a4 = st.columns(4)
        min_sw = a1.number_input("Min sweep pts", 0.0, 50.0, 5.0)
        max_sw = a2.number_input("Max sweep pts", 10.0, 200.0, 60.0)
        max_risk = a3.number_input("Max risk pts", 10.0, 200.0, 60.0)
        max_tr = a4.number_input("Max trades/day", 1, 5, 2)
    if st.button("Run backtest", type="primary"):
        with st.spinner("Loading Nifty 5-min data from Dhan..."):
            df = fetch_nifty_5m(years)
        p = Params(confirm=confirm, rr=rr, use_day=use_day, use_or=use_or, lot_size=int(lot),
                   min_sweep=min_sw, max_sweep=max_sw, max_risk=max_risk, max_trades=int(max_tr))
        t = run_backtest(df, p)
        s = summary(t, p)
        if not s.get("trades"):
            st.warning("No trades with these settings.")
            return
        m = st.columns(5)
        m[0].metric("Trades", s["trades"])
        m[1].metric("Win rate", f'{s["win_rate_%"]}%')
        m[2].metric("Net points", s["net_points"])
        m[3].metric("Profit factor", s["profit_factor"])
        m[4].metric("Max DD (pts)", s["max_drawdown_pts"])
        st.line_chart(t.set_index("exit_time")["points"].cumsum(), height=280)
        b = breakdowns(t)
        cols = st.columns(2)
        cols[0].subheader("Long vs Short"); cols[0].dataframe(b["by_side"])
        cols[1].subheader("By level"); cols[1].dataframe(b["by_level"])
        cols = st.columns(2)
        cols[0].subheader("By year"); cols[0].dataframe(b["by_year"])
        cols[1].subheader("Exit reasons"); cols[1].dataframe(b["by_exit"])
        st.subheader("All trades")
        st.dataframe(t, use_container_width=True)
        st.download_button("Download trades CSV", t.to_csv(index=False), "nifty_sweep_trades.csv")


def cli():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=2)
    ap.add_argument("--csv", help="use a local 5-min CSV instead of Dhan")
    ap.add_argument("--compare", action="store_true", help="test 18 rule variants")
    a = ap.parse_args()
    df = load_csv(a.csv) if a.csv else fetch_nifty_5m(a.years)
    print(f"Data: {df['dt'].min()} -> {df['dt'].max()}  ({len(df)} bars)")
    base = Params()
    if a.compare:
        res = compare_variants(df, base)
        res.to_csv("sweep_variants.csv", index=False)
        print(res.to_string(index=False))
        return
    t = run_backtest(df, base)
    t.to_csv("nifty_sweep_trades.csv", index=False)
    for k, v in summary(t, base).items():
        print(f"{k:>18}: {v}")
    for name, tab in breakdowns(t).items():
        print(f"\n{name}\n{tab.to_string()}")


if __name__ == "__main__":
    try:
        from streamlit.runtime import exists as _st_running
        running = _st_running()
    except Exception:
        running = False
    streamlit_page() if running else cli()
