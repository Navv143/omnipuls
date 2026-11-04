"""Omnipuls market data recorder: keeps our own history so every idea can be backtested later on real data.

Runs on its own, with no web page (Docker service `recorder`, or `python recorder.py`). Uses the same Dhan login as
the app (dhan_config.json in the state folder, see paths.py): a token the app renews is picked up here, and a token
made here is picked up by the app, so the two never keep replacing each other's.

What it records, into OMNIPULS_DATA (default <state>/market_data), as Parquet files (open with pandas.read_parquet):

1. candles_1m/<YYYY-MM>/<YYYY-MM-DD>.parquet, once a day after the close (and for any missed day in the last
   BACKFILL_DAYS on start): 1-minute candles of
   - the indices (Nifty 50, Bank Nifty, Fin Nifty, Midcap Select, Sensex, India VIX),
   - every F&O stock (cash market),
   - every stock and index future, near and next month, with open interest,
   - Nifty and Bank Nifty options, 2 nearest expiries, 15 strikes each side of the close, with open interest.
2. option_chain/<YYYY-MM>/<YYYY-MM-DD>.parquet, every CHAIN_EVERY seconds in market hours: the option chains of
   Nifty, Bank Nifty, Fin Nifty, Midcap Select and Sensex (2 nearest expiries, CHAIN_STRIKES each side): LTP, bid,
   ask and their quantities, OI and previous OI, volume, IV, delta, gamma, theta, vega, with the spot.
3. quotes/<YYYY-MM>/<YYYY-MM-DD>.parquet, every QUOTE_EVERY seconds in market hours: a full quote of every
   instrument in (1) except options: LTP, volume, OI, total buy / sell quantity, best bid / ask and quantity,
   average price - the order-book pressure that no history download gives.

Live snapshots are written every FLUSH_EVERY seconds as part files and joined into one file per day after the close.
status.json in the data folder says what was recorded last and any error.

Usage: python recorder.py              run for ever (the Docker service)
       python recorder.py --backfill 30 fetch 1-minute candles for the last 30 days, then stop
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timedelta

import pandas as pd

import dhan as D
import paths

IST = D.IST
DATA = paths.DATA
CHAIN_EVERY = int(os.environ.get("REC_CHAIN_EVERY", 60))
QUOTE_EVERY = int(os.environ.get("REC_QUOTE_EVERY", 60))
FLUSH_EVERY = int(os.environ.get("REC_FLUSH_EVERY", 300))
BACKFILL_DAYS = int(os.environ.get("REC_BACKFILL_DAYS", 5))
CHAIN_STRIKES = int(os.environ.get("REC_CHAIN_STRIKES", 25))
OPT_STRIKES = int(os.environ.get("REC_OPT_STRIKES", 15))
CANDLES_AFTER = os.environ.get("REC_CANDLES_AFTER", "15:45")  # IST; Dhan's day of 1-min bars is complete by then
INDICES = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "MIDCPNIFTY": 442, "SENSEX": 51, "INDIAVIX": 21}
CHAIN_INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
OPT_UNDERLYINGS = ["NIFTY", "BANKNIFTY"]
TOKEN_CODES = ("DH-901", "401", "807", "808", "809")
STATUS: dict = {"started": None, "candles": {}, "chain": {}, "quotes": {}, "errors": []}


def log(msg: str):
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def _error(where: str, e: Exception):
    msg = f"{datetime.now(IST):%d %b %H:%M} {where}: {getattr(e, 'friendly', None) or e}"[:300]
    STATUS["errors"] = (STATUS["errors"] + [msg])[-20:]
    log("ERROR " + msg)


def _save_status():
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = DATA / "status.json.tmp"
        tmp.write_text(json.dumps(STATUS, indent=2, default=str))
        os.replace(tmp, DATA / "status.json")
    except Exception:
        pass

# ---------------------------------------------------------------- Dhan login shared with the app


class Dhan:
    """Dhan calls with the token from dhan_config.json; on a rejected token: use a newer saved one if there is one,
    otherwise make a new one (PIN + TOTP in Secrets/environment), at most every 2 minutes."""

    def __init__(self):
        self.cfg = D.load_config()
        self.made = 0.0

    def renew(self, rejected: str):
        fresh = D.load_config()
        if fresh.get("access_token") and fresh["access_token"] != rejected:
            self.cfg = fresh  # the app (or a person in Dhan Connect) already renewed it
            return
        if D.can_auto_token(fresh) and time.time() - self.made > 120:
            self.made = time.time()
            D.generate_token(fresh)  # saves to dhan_config.json for the app too
            self.cfg = fresh
            log("made a new Dhan token")
            return
        raise D.DhanError("TOKEN", "Dhan token expired. Paste a new one in Dhan Connect, or put pin and "
                                   "totp_secret in Secrets so tokens are made automatically.")

    def __call__(self, fn, *args, **kw):
        try:
            return fn(*args, cfg=self.cfg, **kw)
        except D.DhanError as e:
            if e.code not in TOKEN_CODES:
                raise
            self.renew(str(self.cfg.get("access_token")))
            return fn(*args, cfg=self.cfg, **kw)

# ---------------------------------------------------------------- what to record


def universe(dh: Dhan) -> dict:
    """Instruments to record: {"index": [...], "equity": [...], "future": [...]}; each item a dict with
    segment, security_id, instrument (Dhan chart type), symbol, expiry."""
    out = {"index": [{"segment": "IDX_I", "security_id": sid, "instrument": "INDEX", "symbol": name, "expiry": None}
                     for name, sid in INDICES.items()], "equity": [], "future": []}
    stocks = dh(D.fno_underlyings)
    eq = dh(D.equity_ids)
    for s in sorted(stocks):
        if s in eq:
            out["equity"].append({"segment": "NSE_EQ", "security_id": eq[s], "instrument": "EQUITY", "symbol": s,
                                  "expiry": None})
    for ins in ("FUTIDX", "FUTSTK"):
        for u, lst in dh(D.live_futures, "NSE_FNO", ins, n=2).items():
            for c in lst:
                out["future"].append({"segment": "NSE_FNO", "security_id": c["id"], "instrument": ins, "symbol": u,
                                      "expiry": str(c["expiry"])})
    return out


def option_contracts(dh: Dhan, closes: dict) -> list[dict]:
    """Nifty / Bank Nifty options, 2 nearest expiries, OPT_STRIKES strikes each side of the day's close."""
    df = D.instruments("NSE_FNO", dh.cfg)
    if "INSTRUMENT" not in df.columns or "STRIKE_PRICE" not in df.columns:
        return []
    df = df[df["INSTRUMENT"] == "OPTIDX"].copy()
    df["_u"], df["_e"] = D._underlying(df).str.upper(), D._expiry(df)
    df["_k"] = pd.to_numeric(df["STRIKE_PRICE"], errors="coerce")
    today = datetime.now(IST).date()
    out = []
    for u in OPT_UNDERLYINGS:
        spot = closes.get(u)
        sub = df[(df["_u"] == u) & df["_e"].notna() & (df["_e"] >= today) & df["_k"].notna()]
        if sub.empty or not spot:
            continue
        for exp in sorted(sub["_e"].unique())[:2]:
            e = sub[sub["_e"] == exp]
            strikes = sorted(e["_k"].unique(), key=lambda k: abs(k - spot))[:2 * OPT_STRIKES + 1]
            for _, r in e[e["_k"].isin(strikes)].iterrows():
                out.append({"segment": "NSE_FNO", "security_id": int(float(r["SECURITY_ID"])), "instrument": "OPTIDX",
                            "symbol": u, "expiry": str(exp), "strike": float(r["_k"]),
                            "opt_type": str(r.get("OPTION_TYPE", ""))[:2]})
    return out

# ---------------------------------------------------------------- 1. one-minute candles, once a day


def _day_bars(dh: Dhan, item: dict, day: date) -> pd.DataFrame:
    body = {"securityId": str(item["security_id"]), "exchangeSegment": item["segment"],
            "instrument": item["instrument"], "interval": "1", "oi": item["instrument"].startswith(("FUT", "OPT")),
            "fromDate": f"{day:%Y-%m-%d} 09:00:00", "toDate": f"{day:%Y-%m-%d} 15:59:59"}
    df = D._bars(dh(D.call, "POST", "/charts/intraday", "data", body), intraday=True)
    if df.empty:
        return df
    df = df[df.index.date == day]
    df.index = df.index.tz_localize(None)
    return df


def _candle_file(day: date):
    return DATA / "candles_1m" / f"{day:%Y-%m}" / f"{day:%Y-%m-%d}.parquet"


def record_candles(dh: Dhan, day: date, uni: dict | None = None) -> str:
    """All 1-minute candles of `day` into one file. Returns 'saved', 'holiday' or 'exists'."""
    f = _candle_file(day)
    if f.exists() or f.with_suffix(".holiday").exists():
        return "exists"
    uni = uni or universe(dh)
    frames, closes = [], {}
    t0 = time.time()

    def grab(items, kind):
        n = 0
        for it in items:
            try:
                df = _day_bars(dh, it, day)
            except D.DhanError as e:
                if e.code in ("NETWORK",):
                    raise
                continue  # one instrument with no data must not stop the day
            if df.empty:
                continue
            n += 1
            if kind == "index":
                closes[it["symbol"]] = float(df["Close"].iloc[-1])
            frames.append(df.reset_index(names="time").assign(
                kind=kind, segment=it["segment"], security_id=it["security_id"], symbol=it["symbol"],
                expiry=it.get("expiry"), strike=it.get("strike"), opt_type=it.get("opt_type")))
        return n

    if not grab(uni["index"], "index"):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.with_suffix(".holiday").write_text("no index candles from Dhan: holiday or no data")
        return "holiday"
    counts = {"index": len(closes), "equity": grab(uni["equity"], "equity"), "future": grab(uni["future"], "future")}
    if day == datetime.now(IST).date():  # option contracts can only be listed while they are live
        try:
            counts["option"] = grab(option_contracts(dh, closes), "option")
        except Exception as e:
            _error("option contracts", e)
    out = pd.concat(frames, ignore_index=True)
    cols = ["time", "kind", "symbol", "segment", "security_id", "expiry", "strike", "opt_type",
            "Open", "High", "Low", "Close", "Volume", "OI"]
    out = out.reindex(columns=cols).rename(columns=str.lower)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    out.to_parquet(tmp, index=False)
    os.replace(tmp, f)
    STATUS["candles"] = {"day": str(day), "rows": len(out), "instruments": counts, "seconds": round(time.time() - t0)}
    log(f"candles {day}: {len(out):,} rows {counts} in {time.time() - t0:.0f}s")
    return "saved"


def trading_days_back(n: int) -> list[date]:
    """The last n weekdays before today (holidays are found and skipped by record_candles)."""
    d, out = datetime.now(IST).date(), []
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return sorted(out)


def backfill(dh: Dhan, days: int):
    uni = None
    for d in trading_days_back(days):
        if _candle_file(d).exists() or _candle_file(d).with_suffix(".holiday").exists():
            continue
        try:
            uni = uni or universe(dh)
            record_candles(dh, d, uni)
        except Exception as e:
            _error(f"candles {d}", e)
        _save_status()

# ---------------------------------------------------------------- 2-3. live snapshots in market hours


class Snapshots:
    def __init__(self, kind: str):
        self.kind, self.rows, self.last_flush = kind, [], time.time()

    def part_dir(self, day: date):
        return DATA / self.kind / "parts" / f"{day:%Y-%m-%d}"

    def flush(self, force=False):
        if not self.rows or (not force and time.time() - self.last_flush < FLUSH_EVERY):
            return
        rows, self.rows, self.last_flush = self.rows, [], time.time()
        df = pd.DataFrame(rows)
        day = pd.Timestamp(df["time"].iloc[0]).date()
        d = self.part_dir(day)
        d.mkdir(parents=True, exist_ok=True)
        df.to_parquet(d / f"{datetime.now(IST):%H%M%S}.parquet", index=False)

    def compact(self, day: date):
        """Join a finished day's part files into <kind>/<YYYY-MM>/<YYYY-MM-DD>.parquet."""
        d = self.part_dir(day)
        parts = sorted(d.glob("*.parquet")) if d.exists() else []
        if not parts:
            return
        f = DATA / self.kind / f"{day:%Y-%m}" / f"{day:%Y-%m-%d}.parquet"
        f.parent.mkdir(parents=True, exist_ok=True)
        frames = [pd.read_parquet(p) for p in parts]
        if f.exists():
            frames.insert(0, pd.read_parquet(f))
        pd.concat(frames, ignore_index=True).to_parquet(f.with_suffix(".tmp"), index=False)
        os.replace(f.with_suffix(".tmp"), f)
        for p in parts:
            p.unlink()
        d.rmdir()
        log(f"{self.kind} {day}: joined {len(parts)} parts")


def chain_rows(dh: Dhan, exps: dict, now: datetime) -> list[dict]:
    rows = []
    for name in CHAIN_INDICES:
        sid = INDICES[name]
        try:
            if name not in exps:
                exps[name] = dh(D.expiries, sid, "IDX_I")
            live = [e for e in exps[name] if str(e) >= now.strftime("%Y-%m-%d")][:2]
        except Exception as e:
            _error(f"expiries {name}", e)
            continue
        for exp in live:
            try:
                spot, ch = dh(D.option_chain, sid, "IDX_I", exp)
            except Exception as e:  # one index failing must not stop the others
                _error(f"chain {name} {exp}", e)
                continue
            if ch.empty:
                continue
            ch = ch.assign(_d=(ch["Strike"] - spot).abs()).nsmallest(2 * CHAIN_STRIKES + 1, "_d").drop(columns="_d")
            ch.columns = [str(c).lower().replace(" ", "_") for c in ch.columns]
            for r in ch.to_dict("records"):
                rows.append({"time": now.replace(tzinfo=None, second=0, microsecond=0), "index": name,
                             "expiry": str(exp), "spot": spot, **r})
    return rows


def quote_rows(dh: Dhan, items: list[dict], now: datetime) -> list[dict]:
    q = dh(D.quotes, [(it["segment"], it["security_id"]) for it in items])
    rows = []
    t = now.replace(tzinfo=None, second=0, microsecond=0)
    for it in items:
        x = q.get((it["segment"], int(it["security_id"])))
        if not x:
            continue
        depth = x.get("depth") or {}
        b0 = (depth.get("buy") or [{}])[0] or {}
        s0 = (depth.get("sell") or [{}])[0] or {}
        ohlc = x.get("ohlc") or {}
        rows.append({"time": t, "kind": it["kind"], "symbol": it["symbol"], "segment": it["segment"],
                     "security_id": it["security_id"], "expiry": it.get("expiry"),
                     "ltp": x.get("last_price"), "avg_price": x.get("average_price"), "volume": x.get("volume"),
                     "oi": x.get("oi"), "buy_qty": x.get("buy_quantity"), "sell_qty": x.get("sell_quantity"),
                     "bid": b0.get("price"), "bid_qty": b0.get("quantity"), "ask": s0.get("price"),
                     "ask_qty": s0.get("quantity"), "open": ohlc.get("open"), "high": ohlc.get("high"),
                     "low": ohlc.get("low"), "prev_close": ohlc.get("close"), "net_change": x.get("net_change"),
                     "last_trade": str(x.get("last_trade_time") or "")})
    return rows

# ---------------------------------------------------------------- main loop


def _git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(paths.HERE), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return ""


BOT_AFTER = os.environ.get("REC_BOT_AFTER", "16:30")
BOT_REQUEST = paths.state("bot_request")


def bot_due(now: datetime) -> bool:
    """The Setup Finder runs once a day after BOT_AFTER (any day, so weekends catch up), or when the app asks, never
    in market hours."""
    if market_open(now) or os.environ.get("REC_BOT", "1") != "1":
        return False
    if BOT_REQUEST.exists():
        return True
    last = ""
    try:
        last = json.loads((DATA / "bot" / "latest.json").read_text()).get("run_at", "")[:10]
    except Exception:
        pass
    return now.strftime("%H:%M") >= BOT_AFTER and last != now.strftime("%Y-%m-%d")


def run_bot():
    """bot.py in its own process (memory is freed when it ends; a crash can't stop the recorder)."""
    BOT_REQUEST.unlink(missing_ok=True)
    log("Setup Finder: starting")
    try:
        r = subprocess.run([sys.executable, str(paths.HERE / "bot.py")], cwd=str(paths.HERE), timeout=4 * 3600)
        STATUS["bot"] = {"time": datetime.now(IST), "exit": r.returncode}
    except Exception as e:
        _error("Setup Finder", e)
    (DATA / "bot").mkdir(parents=True, exist_ok=True)
    marker = DATA / "bot" / "latest.json"
    if not marker.exists():  # failed before writing results: don't retry in a tight loop today
        marker.write_text(json.dumps({"run_at": datetime.now(IST).isoformat(timespec="seconds"), "error": "run failed",
                                      "top": []}))


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"


def run():
    STATUS["started"] = datetime.now(IST)
    DATA.mkdir(parents=True, exist_ok=True)
    log(f"recorder started, data in {DATA}")
    dh = Dhan()
    if not D.configured(dh.cfg):
        log("Dhan is not connected (no client_id / access_token): waiting for Dhan Connect or Secrets")
    head = _git_head()
    restart_on_update = os.environ.get("REC_RESTART_ON_UPDATE") == "1"
    chain, quotes = Snapshots("option_chain"), Snapshots("quotes")
    uni, uni_day, exps, holiday = None, None, {}, None
    last_chain = last_quote = last_backfill_try = last_head_check = 0.0
    while True:
        now = datetime.now(IST)
        today = now.date()
        try:
            if not D.configured(dh.cfg):
                dh.cfg = D.load_config()
                time.sleep(30)
                continue
            if uni_day != today:
                uni, uni_day, exps, holiday = universe(dh), today, {}, None
                log(f"universe: {len(uni['equity'])} stocks, {len(uni['future'])} futures, {len(uni['index'])} indices")
            quiet = not ("09:00" <= now.strftime("%H:%M") <= "15:40") or now.weekday() >= 5
            if quiet and time.time() - last_backfill_try > 3600:  # missed days, outside market hours only
                last_backfill_try = time.time()
                backfill(dh, BACKFILL_DAYS)
            if market_open(now) and holiday is not True:
                if holiday is None and now.strftime("%H:%M") >= "09:20":  # is NSE trading today? (a quote from today)
                    q = dh(D.quotes, [("IDX_I", INDICES["NIFTY"])]).get(("IDX_I", INDICES["NIFTY"]))
                    holiday = D.trade_date(q) != today if q else None
                    if holiday:
                        log("no trades today on NSE: holiday, live snapshots skipped")
                if holiday is False or holiday is None:
                    if time.time() - last_quote >= QUOTE_EVERY:
                        last_quote = time.time()
                        items = ([{**i, "kind": "index"} for i in uni["index"]] +
                                 [{**i, "kind": "equity"} for i in uni["equity"]] +
                                 [{**i, "kind": "future"} for i in uni["future"]])
                        try:
                            rows = quote_rows(dh, items, now)
                            quotes.rows += rows
                            STATUS["quotes"] = {"time": now, "rows": len(rows)}
                        except Exception as e:
                            _error("quotes", e)
                    if time.time() - last_chain >= CHAIN_EVERY:
                        last_chain = time.time()
                        rows = chain_rows(dh, exps, now)
                        chain.rows += rows
                        STATUS["chain"] = {"time": now, "rows": len(rows)}
            chain.flush()
            quotes.flush()
            if now.strftime("%H:%M") >= "15:35" or now.weekday() >= 5:
                chain.flush(force=True)
                quotes.flush(force=True)
                for s in (chain, quotes):
                    for d in sorted(p.name for p in (DATA / s.kind / "parts").glob("*") if p.is_dir()):
                        s.compact(date.fromisoformat(d))
            if now.weekday() < 5 and now.strftime("%H:%M") >= CANDLES_AFTER and not _candle_file(today).exists() \
                    and not _candle_file(today).with_suffix(".holiday").exists():
                record_candles(dh, today, uni)
            if bot_due(now):
                run_bot()
        except Exception as e:
            _error("loop", e)
            if os.environ.get("REC_DEBUG"):
                traceback.print_exc()
            time.sleep(20)
        _save_status()
        if restart_on_update and time.time() - last_head_check > 60:
            last_head_check = time.time()
            if head and _git_head() not in ("", head):
                chain.flush(force=True)
                quotes.flush(force=True)
                log("new code pulled: restarting")
                sys.exit(0)  # Docker restarts the service with the new code
        time.sleep(1 if market_open(now) else 20)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill", type=int, help="fetch 1-minute candles for the last N weekdays, then stop")
    a = ap.parse_args()
    if a.backfill:
        backfill(Dhan(), a.backfill)
        _save_status()
    else:
        run()
