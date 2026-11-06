"""Data engine: the app's heavy work in its own process, shared by every viewer.

The Streamlit app serves every viewer from one Python process, so a 20-second recompute (225 stocks' candles, futures
OI, order book, unusual activity and money flow) froze every screen while it ran, and more viewers made it worse.
This process (started and kept alive by recorder.py, like bots.py) runs the very same loader (scan_service.ScanService
on Dhan, same universe and indices as the app) and the same activity ranking (activity.rank with OI and order-book
snapshots), and writes everything to <data>/engine/state.pkl after each update (atomic replace).

The app (get_scan_service -> EngineService) only reads that file: no Dhan calls and no recompute in the page process.
If the file is missing or older than ENGINE_MAX_AGE seconds (engine down), the app falls back to its own loader.

Usage: python engine.py     (run for ever; REC_ENGINE=0 in the recorder's environment turns it off)
"""
from __future__ import annotations

import os
import pickle
import time
import traceback
from datetime import datetime

import numpy as np

import activity as A
import dhan as D
import indices as IX
import paths
import scan_service as SS
import scanners as SC
import universe as U

OUT = paths.DATA / "engine"
STATE = OUT / "state.pkl"
EVERY = 10          # seconds between checks; a new state is written only when the loader has new data
IST = SS.IST
VERSION = 1


def log(msg: str):
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} engine: {msg}", flush=True)


def universe(cfg: dict) -> tuple[list, dict]:
    """The app's universe: every F&O stock plus every index constituent; indices with their Dhan ids + India VIX."""
    import fno
    lots, src = fno.load()
    if src.startswith("built-in"):
        try:
            d = D.fno_underlyings(cfg)
            if len(d) > 50:
                lots = d
        except Exception:
            pass
    idx = IX.load()
    syms = sorted(set(lots) | {m for d in idx.values() for m in d["w"]})
    return syms, {**{k: d["id"] for k, d in idx.items()}, "INDIAVIX": 21}


def activity(svc) -> tuple | None:
    """activity.rank exactly as the app's _activity_data computes it (with OI and order-book snapshots)."""
    bars, nifty_df = svc.bars()
    if not bars:
        return None
    session = SC.session_of(nifty_df) if nifty_df is not None and not nifty_df.empty else \
        max(df.index.normalize().max() for df in bars.values() if not df.empty)
    R, E, per = A.rank({s: SC.clean(df) for s, df in bars.items()}, session, svc.oi(), svc.snapshots(), U.FNO_SECTOR_OF)
    if not R.empty:
        R["Symbol"] = R["Stock"] + ".NS"
        R["Side"] = np.where(R["Smart"] >= 25, "Bullish", np.where(R["Smart"] <= -25, "Bearish", ""))
    if not E.empty:
        E["Symbol"] = E["Stock"] + ".NS"
        E["Candle"] = np.where(E["Candle"] == "Green", "Bullish", "Bearish")
    return R, E, per, session


_SCANS: dict = {}


def scans(svc) -> dict | None:
    """The scanner results the app's pages show (momentum radar, V3 breakouts, R-factor), exactly as the app computes
    them (_scan_now, smart_money_stocks), recomputed only when the loader has new candles."""
    if _SCANS.get("k") == svc.last_pass:
        return _SCANS.get("v")
    bars, nifty = svc.bars()
    if not bars or nifty is None or nifty.empty:
        return None
    session = SC.session_of(nifty)
    S = SC.prepare(bars, session)
    oi = svc.oi()
    out = {"session": session, "last_pass": svc.last_pass}
    for name, fn in (("radar", lambda: SC.radar(S, oi)),
                     ("v3both", lambda: SC.version3(S, (lambda N: N if N.ok else None)(SC.Stock("NIFTY 50", nifty, session)))),
                     ("rf", lambda: SC.r_factor(S, oi)),
                     ("v3diag", lambda: SC.v3_diagnose(S, (lambda N: N if N.ok else None)(SC.Stock("NIFTY 50", nifty, session))))):
        try:
            out[name] = fn()
        except Exception as e:
            log(f"scan {name}: {e}")
            out[name] = None
    vb = out.pop("v3both", None)               # V3 signals and the 9:30 ranking behind them
    out["v3"], out["v3ranked"] = (vb if vb is not None else (None, None))
    _SCANS.update(k=svc.last_pass, v=out)
    return out


_PLAN: dict = {"gold_t": 0.0, "gold": None}


def plan_parts(svc) -> dict:
    """The heavy parts of the regular setups (app._plan_rows: Desk 'Regular setups' and Market View index plans):
    Bank Nifty failed-break fade, Bank Nifty 5-STAR with the Nifty 100 internals, the trend-day alerts of Nifty and
    Bank Nifty, and Gold Order Flow (PAXG, every 5 minutes)."""
    import fade as FADE
    import five_star as FIVE
    import gold_flow as GF
    import trade_odds as TO
    import trend_alert as TA
    out = {}
    idx, fut = svc.idx_bars(), svc.ifut_bars()
    bn, vix = idx.get("BANKNIFTY"), idx.get("INDIAVIX")
    now = datetime.now(IST).replace(tzinfo=None)
    try:
        out["fade"] = FADE.evaluate(bn, now) if bn is not None and not bn.empty else {"status": "no data"}
    except Exception as e:
        log(f"plan fade: {e}")
    try:
        bars, _ = svc.bars()
        internals = FIVE.market_internals({x: bars[x] for x in SC.NIFTY100 if x in bars})
        out["five"] = FIVE.evaluate(bn, internals) if bn is not None and not bn.empty else {"status": "no data"}
    except Exception as e:
        log(f"plan 5-star: {e}")
    try:
        tr = []
        for k in ("NIFTY", "BANKNIFTY"):
            spot = idx.get(k)
            if spot is not None and not spot.empty:
                tr.append((k, TA.evaluate(k, spot, fut.get(k), vix, None, TA.days_to_expiry(k, spot.index.max()))))
        out["trend"] = tr
    except Exception as e:
        log(f"plan trend: {e}")
    if time.time() - _PLAN["gold_t"] > 300:
        try:
            _PLAN["gold"] = GF.run(GF.to_15m(TO.binance_5m("PAXGUSDT", 60)))
        except Exception as e:
            _PLAN["gold"] = {"error": str(e)[:200]}
        _PLAN["gold_t"] = time.time()
    out["gold"] = _PLAN["gold"]
    return out


def write(svc, act, sc=None, pl=None):
    bars, nifty = svc.bars()
    state = {"version": VERSION, "written": time.time(), "status": svc.status, "error": svc.error,
             "oi_status": svc.oi_status, "tf": svc.tf, "syms": list(svc.syms), "progress": svc.progress(),
             "last_pass": svc.last_pass, "last_snap": svc.last_snap, "freshness": svc.freshness(),
             "bars": bars, "nifty": nifty, "idx": svc.idx_bars(), "ifut": svc.ifut_bars(), "oi": svc.oi(),
             "snaps": svc.snapshots(), "n_snaps": len(svc.snaps), "activity": act, "scans": sc, "plan": pl}
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(f".{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, STATE)


def main():
    cfg = D.load_config()
    while not D.configured(cfg):
        log("waiting for Dhan (no client_id / access_token)")
        time.sleep(60)
        cfg = D.load_config()
    svc = SS.ScanService("dhan", cfg)
    last_key, last_uni, cfg_check = None, 0.0, time.time()
    log("started")
    while True:
        try:
            if time.time() - last_uni > 3600 or not svc.syms:
                syms, ids = universe(cfg)
                svc.set_universe(syms)
                svc.set_indices(ids)
                last_uni = time.time()
            svc.touch()                       # the loader slows down when nobody touches it
            if time.time() - cfg_check > 60:   # pick up a token the recorder renewed
                cfg_check = time.time()
                new = D.load_config()
                if new.get("access_token") != cfg.get("access_token"):
                    cfg = new
                    svc.cfg = cfg
            key = (svc.last_pass, svc.last_snap, svc.progress())
            if key != last_key:
                t0 = time.time()
                act = None
                done, total = svc.progress()
                sc = None
                if done:
                    act = activity(svc)
                    try:
                        sc = scans(svc)
                    except Exception as e:
                        log(f"scans: {e}")
                pl = None
                try:
                    pl = plan_parts(svc)
                except Exception as e:
                    log(f"plan: {e}")
                write(svc, act, sc, pl)
                last_key = key
                log(f"state written ({done}/{total} stocks, {time.time() - t0:.1f}s)")
        except Exception as e:
            log(f"error: {e}\n{traceback.format_exc()[-800:]}")
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
