"""Background loader for the Scanners page: keeps 5-minute bars for the whole F&O list ready.

- Earlier sessions: fetched once a day per stock and saved to scan_cache/<date>/ so restarts are instant.
- Today: during market hours a background thread re-fetches today's bars for every stock in a loop (Dhan allows
  about 5 data requests a second, so a full pass over ~210 stocks takes about 50 seconds). The page never waits:
  it shows whatever is ready and says how fresh it is.
- Yahoo (no Dhan): one batch download for all stocks every few minutes.
"""
from __future__ import annotations

import pickle
import threading
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import pandas as pd

import dhan as D

IST = timezone(timedelta(hours=5, minutes=30))
CACHE = Path(__file__).with_name("scan_cache")
NIFTY = "__NIFTY__"
VERSION = 2  # bump when ScanService changes, so a running app replaces its old loader
INSTANCES: list = []


def _naive(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    df.index = idx
    return df[~df.index.duplicated(keep="last")].sort_index()


def combine_oi(frames: list) -> pd.DataFrame:
    """Sum the OI of several futures contracts on the 5-minute grid (each contract carried forward within the day)."""
    cols = []
    for i, df in enumerate(frames):
        if df is None or df.empty or "OI" not in df:
            continue
        s = df["OI"].copy()
        s.index = s.index.floor("5min")
        cols.append(s.groupby(level=0).last().rename(i))
    if not cols:
        return pd.DataFrame()
    m = pd.concat(cols, axis=1).sort_index()
    m = m.groupby(m.index.normalize()).ffill().fillna(0)
    m = m[(m.index.time >= dtime(9, 15)) & (m.index.time <= dtime(15, 30))]
    return pd.DataFrame({"OI": m.sum(axis=1)})


def market_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    return now.weekday() < 5 and dtime(9, 14) <= now.time() <= dtime(15, 35)


class ScanService:
    def __init__(self, source: str, cfg: dict | None = None):
        self.source, self.cfg = source, cfg
        self.syms: list[str] = []
        self.hist: dict[str, pd.DataFrame] = {}
        self.today: dict[str, pd.DataFrame] = {}
        self.today_at: dict[str, float] = {}
        self.last_pass = 0.0
        self.pass_secs = 0.0
        self.status = "starting"
        self.error = ""
        self.touched = time.time()
        self._lock = threading.Lock()
        self._stop = False
        self._ids: dict = {}
        self._day = None
        self._eod_done = False
        # futures open interest (Dhan only): near + next month summed per 5-minute bar, so rollover doesn't break it
        self.oi_raw: dict[str, dict[int, pd.DataFrame]] = {}
        self.oi_hist: dict[str, pd.DataFrame] = {}
        self.oi_status = "off" if source != "dhan" else "starting"
        self._fut: dict = {}
        self._oi_day = None
        self.thread = threading.Thread(target=self._run, name="scan-service", daemon=True)
        self.thread.start()
        if source == "dhan":
            self.oi_thread = threading.Thread(target=self._run_oi, name="scan-oi", daemon=True)
            self.oi_thread.start()

    # ---------------------------------------------------------------- public

    def set_universe(self, syms):
        syms = list(dict.fromkeys(syms))
        with self._lock:
            if syms != self.syms:
                self.syms = syms

    def touch(self):
        self.touched = time.time()

    def stop(self):
        self._stop = True

    def progress(self) -> tuple[int, int]:
        with self._lock:
            want = list(self.syms)
        return sum(1 for s in want if s in self.hist), len(want)

    def bars(self) -> tuple[dict, pd.DataFrame | None]:
        """{sym: bars (history + today)}, nifty bars. Only stocks already loaded."""
        with self._lock:
            want = list(self.syms)
        out = {}
        for s in want + [NIFTY]:
            h = self.hist.get(s)
            if h is None or h.empty:
                continue
            t = self.today.get(s)
            df = h if t is None or t.empty else pd.concat([h, t])
            out[s] = df[~df.index.duplicated(keep="last")]
        return out, out.pop(NIFTY, None)

    def oi(self) -> dict:
        """{sym: DataFrame with column OI (near + next futures summed) on the 5-minute grid}. Only loaded stocks."""
        with self._lock:
            raw = {s: dict(v) for s, v in self.oi_raw.items()}
        return {s: combine_oi(list(v.values())) for s, v in raw.items() if v}

    def freshness(self) -> float | None:
        """Seconds since the oldest 'today' update among loaded stocks (None outside market hours)."""
        if not self.today_at:
            return None
        return time.time() - min(self.today_at.values())

    # ---------------------------------------------------------------- internals

    def _fetch(self, sym: str, days: int) -> pd.DataFrame:
        if sym == NIFTY:
            return _naive(D.intraday("IDX_I", 13, "INDEX", 5, days, self.cfg))
        sid = self._ids.get(sym.upper())
        if sid is None:
            return pd.DataFrame()
        return _naive(D.intraday("NSE_EQ", sid, "EQUITY", 5, days, self.cfg))

    def _cache_dir(self, day) -> Path:
        d = CACHE / f"{self.source}_{day:%Y%m%d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _new_day(self, day):
        """Drop yesterday's state and old cache folders."""
        self._day = day
        self._eod_done = False
        with self._lock:
            self.hist, self.today, self.today_at = {}, {}, {}
        try:
            for p in CACHE.glob(f"{self.source}_*"):
                if p.name != f"{self.source}_{day:%Y%m%d}":
                    for f in p.glob("*"):
                        f.unlink(missing_ok=True)
                    p.rmdir()
        except Exception:
            pass

    def _split(self, sym, df, day):
        if df.empty:
            return
        d = df.index.normalize()
        hist, today = df[d < pd.Timestamp(day)], df[d >= pd.Timestamp(day)]
        with self._lock:
            self.hist[sym] = hist
            if not today.empty:
                self.today[sym] = today
                self.today_at[sym] = time.time()
        return hist

    def _load_history(self, day) -> bool:
        """Fill history for every wanted symbol (disk cache first). Returns True when all are done."""
        cdir = self._cache_dir(day)
        with self._lock:
            want = [NIFTY] + [s for s in self.syms]
        missing = [s for s in want if s not in self.hist]
        for s in missing:
            if self._stop:
                return False
            f = cdir / f"{s.replace('&', '_and_')}.pkl"
            if f.exists():
                try:
                    with self._lock:
                        self.hist[s] = pickle.loads(f.read_bytes())
                    tf = cdir / f"today_{f.name}"
                    if tf.exists():
                        with self._lock:
                            self.today[s] = pickle.loads(tf.read_bytes())
                            self.today_at[s] = tf.stat().st_mtime
                    continue
                except Exception:
                    pass
            if self.source != "dhan":
                continue
            try:
                hist = self._split(s, self._fetch(s, 40), day)
                if hist is not None:
                    f.write_bytes(pickle.dumps(hist))
                    now = datetime.now(IST)
                    if s in self.today and now.weekday() < 5 and now.time() > dtime(15, 35):
                        (cdir / f"today_{f.name}").write_bytes(pickle.dumps(self.today[s]))
                elif s != NIFTY:
                    with self._lock:
                        self.hist[s] = pd.DataFrame()  # no data for this symbol; don't retry all day
            except Exception as e:
                self.error = f"{s}: {e}"
            self.status = f"loading history {sum(1 for x in want if x in self.hist)}/{len(want)}"
        return all(s in self.hist for s in want)

    def _yahoo_pass(self, day):
        import yfinance as yf
        with self._lock:
            want = list(self.syms)
        tick = {f"{s}.NS": s for s in want}
        tick["^NSEI"] = NIFTY
        raw = yf.download(list(tick), period="40d", interval="5m", group_by="ticker", threads=True,
                          progress=False, auto_adjust=False)
        for t, s in tick.items():
            try:
                df = _naive(raw[t].dropna(how="all"))
                self._split(s, df, day)
            except Exception:
                pass
        self.last_pass = time.time()

    def _fetch_fut(self, cid: int, days: int) -> pd.DataFrame:
        df = _naive(D.intraday("NSE_FNO", cid, "FUTSTK", 5, days, self.cfg))
        return df[["OI"]] if "OI" in df else pd.DataFrame()

    def _run_oi(self):
        npass = 0
        while not self._stop:
            try:
                now = datetime.now(IST)
                day = now.date()
                if day != self._oi_day:
                    self._oi_day = day
                    with self._lock:
                        self.oi_raw, self.oi_hist = {}, {}
                    self.oi_status = "loading futures list"
                    self._fut = D.live_futures("NSE_FNO", "FUTSTK", n=2, cfg=self.cfg)
                with self._lock:
                    want = [s for s in self.syms if s.upper() in self._fut]
                cdir = self._cache_dir(day)
                missing = [s for s in want if s not in self.oi_hist]
                for i, s in enumerate(missing, 1):  # history: once a day, cached on disk
                    if self._stop:
                        return
                    hist = {}
                    for c in self._fut[s.upper()]:
                        f = cdir / f"fut_{c['id']}.pkl"
                        try:
                            df = pickle.loads(f.read_bytes()) if f.exists() else None
                        except Exception:
                            df = None
                        if df is None:
                            try:
                                df = self._fetch_fut(c["id"], 40)
                            except Exception as e:
                                self.error = f"{s} futures: {e}"
                                df = pd.DataFrame()
                            if not df.empty:
                                df = df[df.index.normalize() < pd.Timestamp(day)]
                            f.write_bytes(pickle.dumps(df))
                        hist[c["id"]] = df
                    with self._lock:
                        self.oi_hist[s] = pd.DataFrame()  # marker: history done
                        self.oi_raw[s] = hist
                    self.oi_status = f"loading futures OI {i}/{len(missing)}"
                active = time.time() - self.touched < 15 * 60
                if market_hours(now) and active and want:
                    for s in want:  # today: near month every pass, next month every 3rd pass
                        if self._stop:
                            return
                        for k, c in enumerate(self._fut[s.upper()]):
                            if k > 0 and npass % 3:
                                continue
                            try:
                                t = self._fetch_fut(c["id"], 1)
                            except Exception as e:
                                self.error = f"{s} futures: {e}"
                                continue
                            if t.empty:
                                continue
                            with self._lock:
                                old = self.oi_raw.get(s, {}).get(c["id"], pd.DataFrame())
                                old = old[old.index.normalize() < pd.Timestamp(day)] if not old.empty else old
                                self.oi_raw.setdefault(s, {})[c["id"]] = pd.concat([old, t[t.index.normalize() >= pd.Timestamp(day)]])
                    npass += 1
                    self.oi_status = "ready"
                    time.sleep(20)
                else:
                    if not missing:
                        self.oi_status = "ready"
                    time.sleep(15)
            except Exception as e:
                self.error = str(e)[:200]
                self.oi_status = "error, retrying"
                time.sleep(20)

    def _run(self):
        while not self._stop:
            try:
                now = datetime.now(IST)
                day = now.date()
                if day != self._day:
                    self._new_day(day)
                if self.source == "dhan" and not self._ids:
                    self.status = "loading Dhan instrument list"
                    self._ids = D.equity_ids(self.cfg)
                if self.source != "dhan":
                    if time.time() - self.last_pass > (180 if market_hours(now) else 1800) or \
                            any(s not in self.hist for s in self.syms):
                        self.status = "downloading from Yahoo"
                        self._yahoo_pass(day)
                    self.status = "ready"
                    time.sleep(5)
                    continue
                if not self._load_history(day):
                    continue
                active = time.time() - self.touched < 15 * 60
                after_close = now.weekday() < 5 and now.time() > dtime(15, 35)
                if (market_hours(now) and active) or (after_close and not self._eod_done):
                    t0 = time.time()
                    cdir = self._cache_dir(day)
                    with self._lock:
                        want = [NIFTY] + list(self.syms)
                    for i, s in enumerate(want, 1):
                        if self._stop or s not in self.hist or (s != NIFTY and self.hist[s].empty):
                            continue
                        if after_close and s in self.today and self.today_at.get(s, 0) > \
                                datetime.combine(day, dtime(15, 35), IST).timestamp():
                            continue  # already have the full session
                        try:
                            self._split(s, self._fetch(s, 1), day)
                            if after_close and s in self.today:
                                (cdir / f"today_{s.replace('&', '_and_')}.pkl").write_bytes(pickle.dumps(self.today[s]))
                        except Exception as e:
                            self.error = f"{s}: {e}"
                        self.status = f"updating today's bars {i}/{len(want)}"
                    self.last_pass, self.pass_secs = time.time(), time.time() - t0
                    self._eod_done = self._eod_done or after_close
                    self.status = "ready"
                    time.sleep(10)
                else:
                    self.status = "ready"
                    time.sleep(15)
            except Exception as e:
                self.error = str(e)[:200]
                self.status = "error, retrying"
                time.sleep(20)
