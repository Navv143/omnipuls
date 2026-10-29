"""Live intraday scanners from the Omnipuls research (Oct 2026), as pure functions on 5-minute bars.

Input everywhere: bars = {symbol: DataFrame} with a naive IST DatetimeIndex (09:15..15:25 5-minute bars) and
columns Open, High, Low, Close, Volume, covering today plus ~20-30 earlier sessions. `nifty` is the same for Nifty 50.
Every scanner returns a DataFrame of today's signals with entry, stop, current price, status and P&L, plus the
research verdict in RESEARCH. Results quoted are after 0.12% costs on shares and 2% of premium on options.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from datetime import time as dtime

IST = timezone(timedelta(hours=5, minutes=30))

import numpy as np
import pandas as pd

# The Nifty 100 stocks the intraday research was run on (5-minute data, Feb 2015 - Apr 2026).
NIFTY100 = ["ABB", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS", "ADANIPOWER", "AMBUJACEM", "APOLLOHOSP",
            "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJAJHLDNG", "BAJFINANCE", "BANKBARODA", "BEL",
            "BHARTIARTL", "BOSCHLTD", "BPCL", "BRITANNIA", "CANBK", "CGPOWER", "CHOLAFIN", "CIPLA", "COALINDIA",
            "CUMMINSIND", "DIVISLAB", "DLF", "DMART", "DRREDDY", "EICHERMOT", "ENRIN", "ETERNAL", "GAIL", "GODREJCP",
            "GRASIM", "HAL", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HINDALCO", "HINDUNILVR", "HINDZINC",
            "HYUNDAI", "ICICIBANK", "INDHOTEL", "INDIGO", "INFY", "IOC", "IRFC", "ITC", "JINDALSTEL", "JIOFIN",
            "JSWSTEEL", "KOTAKBANK", "LODHA", "LTM", "LT", "MARUTI", "MAXHEALTH", "MAZDOCK", "M&M", "MOTHERSON",
            "MUTHOOTFIN", "NESTLEIND", "NTPC", "ONGC", "PFC", "PIDILITIND", "PNB", "POWERGRID", "RECLTD", "RELIANCE",
            "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SOLARINDS", "SUNPHARMA", "TATACAP", "TATACONSUM",
            "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN", "TMCV", "TMPV", "TORNTPHARM", "TRENT", "TVSMOTOR",
            "ULTRACEMCO", "UNIONBANK", "UNITDSPR", "VBL", "VEDL", "WIPRO", "ZYDUSLIFE"]

COST = 0.0012

# verdicts: "best" (use), "ok" (small edge), "weak", "no" (rejected) -----------------------------------------------
RESEARCH = [
    # name, where, verdict, per trade shares, per trade options, years profitable, note
    ("Gap fade (2 biggest 3%+ gaps), entry at the open, 1% stop", "Cash shares, pre-open order", "best",
     "+0.66%", "+9.5% (if bought at the open)", "12/12",
     "Strongest result. Most of the reversal happens in the first 5 minutes, so the entry must be the opening price "
     "(pre-open order 9:00-9:08 for shares). Robust to stop 0.5-3%, top 1-5, gap 2-5%, cost up to 0.30%."),
    ("Gap fade entered at 9:20", "Shares / options", "weak", "+0.33%", "+3.9% (about 0 since 2022)", "11/12",
     "Half the edge is gone by 9:20; roughly zero for options since 2022."),
    ("Panic gap-down buy (Nifty opens -0.5% or worse), entry at the open", "Cash shares, pre-open order", "best",
     "+1.36%", "—", "9/12", "Only ~24 trades a year; big swings year to year."),
    ("Sector overreaction buy, entry at the open", "Cash shares, pre-open order", "ok", "+0.71%", "—", "11/12",
     "Gap-down 2.5%+ and 2.5% worse than its sector."),
    ("Version 3: top-2 movers, 15-min breakout with volume, Nifty check", "Shares", "ok", "+0.16% (+0.23% at 0.05%)",
     "+0.5%", "9/12", "Real but thin; the volume and Nifty filters add nothing; exit at 15:20 matters; weak in 2026."),
    ("Momentum radar: #1 ranked stock at 10:30 (volume vs usual, move vs ATR, move size), 1% stop", "Shares",
     "weak", "+0.17% (top 3: +0.07%, top 10: -0.02%)", "—", "2/2 halves",
     "Dhan 5-minute data, 205 F&O stocks, Nov 2021-Oct 2026: only the single top-ranked stock at 10:30 held up "
     "(t-stat 3.1, +0.10% in 2025-26), and it was 1 of 25 versions tried. Big-money bars (4x volume with the move) "
     "were tested too and add nothing (3+ by 10:30: -0.01%, -0.1% in 2025-26). OI has no history to test, so the radar "
     "logs its 10:30 picks daily to build a track record. Shortlist = TradeFinder pattern from 360 of their verified "
     "trades (broke yesterday's high/low, sector same way, volume 1.5x+ 20-day usual): its top 5 held their stock on "
     "~27% of days."),
    ("Swing calls: 20-day breakout on 2x volume, hold 10 days", "—", "weak", "+1.36%", "+16.5%", "8/12",
     "Random stocks held the same way made +9.6%: mostly bull market and today's-index bias."),
]
VERDICT_LABEL = {"best": "Use", "ok": "Small edge", "weak": "Weak", "no": "Rejected"}


# ---------------------------------------------------------------- preparation

def clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.between_time("09:15", "15:29")
    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c not in df:
            df[c] = 0.0 if c == "Volume" else np.nan
    return df[["Open", "High", "Low", "Close", "Volume"]].astype(float)


_HIST_CACHE: dict = {}  # earlier-session stats don't change during the day: compute once per stock


def _hist_stats(hist: pd.DataFrame):
    g = hist.groupby(hist.index.normalize())
    daily = pd.DataFrame({"open": g["Open"].first(), "high": g["High"].max(), "low": g["Low"].min(),
                          "close": g["Close"].last(), "vol": g["Volume"].sum()})
    pc = daily["close"].shift(1)
    tr = pd.concat([daily["high"] - daily["low"], (daily["high"] - pc).abs(), (daily["low"] - pc).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    # volume by time-of-day slot for earlier sessions (rows = dates, cols = HH:MM)
    slot = hist.index.strftime("%H:%M")
    slot_vol = hist["Volume"].groupby([hist.index.normalize(), slot]).sum().unstack()
    cum_vol = slot_vol.reindex(sorted(slot_vol.columns), axis=1).fillna(0).cumsum(axis=1)
    return daily, atr, slot_vol, cum_vol


class Stock:
    """One symbol: today's bars, earlier sessions, and daily stats known before today."""

    def __init__(self, sym: str, df: pd.DataFrame, session):
        self.sym = sym
        df = clean(df)
        self.ok = not df.empty
        if not self.ok:
            return
        dates = df.index.normalize()
        self.today = df[dates == session]
        self.hist = df[dates < session]
        self.ok = len(self.today) > 0 and self.hist.index.normalize().nunique() >= 5
        if not self.ok:
            return
        key = (sym, session, len(self.hist), self.hist.index[-1])
        hs = _HIST_CACHE.get(key)
        if hs is None:
            hs = _hist_stats(self.hist)
            if len(_HIST_CACHE) > 2000:
                _HIST_CACHE.clear()
            _HIST_CACHE[key] = hs
        self.daily, self.atr, self.slot_vol, self.cum_vol = hs
        daily = self.daily
        self.prev_close = float(daily["close"].iloc[-1])
        self.pdh, self.pdl = float(daily["high"].iloc[-1]), float(daily["low"].iloc[-1])
        self.open = float(self.today["Open"].iloc[0])
        self.ltp = float(self.today["Close"].iloc[-1])
        self.gap = self.open / self.prev_close - 1
        self.atr_pct = self.atr / self.prev_close

    def bars_until(self, t: dtime) -> pd.DataFrame:
        return self.today[self.today.index.time < t]

    def slot_avg(self, hhmm: str, n=10) -> float:
        if hhmm not in self.slot_vol:
            return np.nan
        return float(self.slot_vol[hhmm].tail(n).mean())

    def cum_avg(self, hhmm: str, n=10) -> float:
        if hhmm not in self.cum_vol:
            return np.nan
        return float(self.cum_vol[hhmm].tail(n).mean())


def prepare(bars: dict, session) -> dict:
    out = {}
    for s, df in bars.items():
        st_ = Stock(s, df, session)
        if st_.ok:
            out[s] = st_
    return out


def session_of(nifty: pd.DataFrame):
    n = clean(nifty)
    return n.index.normalize().max() if not n.empty else None


# ---------------------------------------------------------------- trade tracking

def track(stock: Stock, side: int, entry_time, entry: float, stop: float | None, trail: float | None = None,
          exit_at: dtime = dtime(15, 20)) -> dict:
    """Follow a trade on today's bars from entry_time (inclusive) up to now."""
    bars = stock.today[stock.today.index >= entry_time]
    best, status, exit_px, exit_t = entry, "Open", None, None
    for ts, b in bars.iterrows():
        if ts.time() >= exit_at:
            status, exit_px, exit_t = "Closed 15:20", b["Open"], ts
            break
        lvl = stop
        if trail is not None:
            tl = best - side * trail
            lvl = tl if lvl is None else (max(lvl, tl) if side > 0 else min(lvl, tl))
        if lvl is not None and ((side > 0 and b["Low"] <= lvl) or (side < 0 and b["High"] >= lvl)):
            status = "Stopped" if (stop is not None and lvl == stop) else "Trailed out"
            exit_px, exit_t = (min(b["Open"], lvl) if side > 0 else max(b["Open"], lvl)), ts
            break
        best = max(best, b["High"]) if side > 0 else min(best, b["Low"])
    if status == "Open" and len(bars):
        now = datetime.now(IST).replace(tzinfo=None)
        if bars.index[-1].date() < now.date() or now.time() >= exit_at:  # session over; data may stop before 15:20
            status, exit_px, exit_t = "Closed (last bar)", float(bars["Close"].iloc[-1]), bars.index[-1]
    px = exit_px if exit_px is not None else stock.ltp
    return {"Status": status, "Exit/LTP": px, "P&L %": side * (px / entry - 1) * 100,
            "Exit time": exit_t.strftime("%H:%M") if exit_t is not None else ""}


def _row(stock, side, signal_t, entry_t, entry, stop, extra=None, trail=None):
    r = {"Stock": stock.sym, "Side": "BUY / CE" if side > 0 else "SELL / PE", "Signal": signal_t.strftime("%H:%M"),
         "Entry": entry, "Stop": stop}
    if entry_t is None:
        r.update({"Status": "Waiting for next bar", "Exit/LTP": stock.ltp, "P&L %": 0.0, "Exit time": ""})
    else:
        r.update(track(stock, side, entry_t, entry, stop, trail))
    r.update(extra or {})
    return r


def _next_bar(stock, ts):
    nb = stock.today[stock.today.index > ts]
    return (nb.index[0], float(nb["Open"].iloc[0])) if len(nb) else (None, None)


# ---------------------------------------------------------------- 1. gap fade (+ panic, 9:15 candle confirmation)

def gap_fade(S: dict, nifty_gap: float | None, gap_min=0.03, top=2, stop_pct=0.01) -> pd.DataFrame:
    c = sorted([s for s in S.values() if abs(s.gap) >= gap_min and abs(s.gap) < 0.2], key=lambda s: -abs(s.gap))[:top]
    rows = []
    for s in c:
        side = 1 if s.gap < 0 else -1
        t0 = s.today.index[0]
        first = s.today.iloc[0]
        confirm = side * (first["Close"] - first["Open"]) > 0
        r = _row(s, side, t0, t0, s.open, s.open * (1 - side * stop_pct),
                 {"Gap %": s.gap * 100, "9:15 candle reversed": "Yes" if confirm else "No",
                  "Panic day": "Yes" if (nifty_gap is not None and nifty_gap <= -0.005 and side > 0) else ""})
        rows.append(r)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 2. Version 3 opening-range breakout

def version3(S: dict, nifty: Stock | None, top=2, vol_mult=1.5, until=dtime(12, 0), stop_atr=0.5, trail_atr=1.0,
             filters=True) -> tuple[pd.DataFrame, pd.DataFrame]:
    rank = []
    for s in S.values():
        orb = s.bars_until(dtime(9, 30))
        if len(orb) < 3:
            continue
        or_vol = orb["Volume"].sum()
        avg_or = s.cum_avg("09:25", 20)
        rank.append({"s": s, "atr": s.atr_pct, "orr": (orb["High"].max() - orb["Low"].min()) / s.open,
                     "rvol": or_vol / avg_or if avg_or and avg_or > 0 else np.nan, "gap": abs(s.gap),
                     "hi": orb["High"].max(), "lo": orb["Low"].min()})
    r = pd.DataFrame(rank)
    if r.empty:
        return pd.DataFrame(), pd.DataFrame()
    for c in ("atr", "orr", "rvol", "gap"):
        r[c + "_pr"] = r[c].rank(pct=True) * 100
    r["score"] = r[[c + "_pr" for c in ("atr", "orr", "rvol", "gap")]].sum(axis=1)
    r = r.sort_values("score", ascending=False)
    picks = r.head(top)
    n_hi = n_lo = None
    if nifty is not None:
        no = nifty.bars_until(dtime(9, 30))
        if len(no):
            n_hi, n_lo = no["High"].max(), no["Low"].min()
    rows = []
    for p in picks.itertuples():
        s = p.s
        cand = s.today[(s.today.index.time >= dtime(9, 30)) & (s.today.index.time < until)]
        for ts, b in cand.iterrows():
            side = 1 if b["Close"] > p.hi else (-1 if b["Close"] < p.lo else 0)
            if not side:
                continue
            avg = s.slot_avg(ts.strftime("%H:%M"), 10)
            vol_ok = bool(np.isfinite(avg) and avg > 0 and b["Volume"] >= vol_mult * avg)
            nifty_ok = True
            if nifty is not None and n_hi is not None:
                nb = nifty.today[(nifty.today.index.time >= dtime(9, 30)) & (nifty.today.index <= ts)]
                nifty_ok = not ((side > 0 and (nb["Close"] < n_lo).any()) or (side < 0 and (nb["Close"] > n_hi).any()))
            if filters and not (vol_ok and nifty_ok):
                continue
            et, entry = _next_bar(s, ts)
            entry = entry if entry is not None else s.ltp
            a_plus = (side > 0 and s.open <= p.lo * 1.0005) or (side < 0 and s.open >= p.hi * 0.9995)
            rows.append(_row(s, side, ts, et, entry, entry - side * stop_atr * s.atr,
                             {"Score": p.score, "Volume x": b["Volume"] / avg if avg and avg > 0 else np.nan,
                              "Nifty OK": "Yes" if nifty_ok else "No", "A+": "Yes" if a_plus else "",
                              "Gap %": s.gap * 100}, trail=trail_atr * s.atr))
            break
    ranked = pd.DataFrame({"Stock": [x.sym for x in r["s"]], "Score": r["score"].round(0), "ATR %": r["atr"] * 100,
                           "9:15-9:30 range %": r["orr"] * 100, "RVOL": r["rvol"], "Gap %": [x.gap * 100 for x in r["s"]]})
    return pd.DataFrame(rows), ranked.head(10)


# ---------------------------------------------------------------- 3. momentum radar (today's window vs the same window, last X days)

RADAR_CACHE: dict = {}


def _hist_window(s: Stock, hhmm: str, lookback: int, recent: int):
    """Average volume since the open, volume in the last `recent` bars, and range by hhmm on the last sessions."""
    key = (s.sym, len(s.hist), s.hist.index[-1], hhmm, lookback, recent)
    if key in RADAR_CACHE:
        return RADAR_CACHE[key]
    h = s.hist
    t_end = dtime(*map(int, hhmm.split(":")))
    w = h[h.index.time <= t_end]
    g = w.groupby(w.index.normalize())
    rng = ((g["High"].max() - g["Low"].min()) / g["Open"].first()).tail(lookback).mean()
    cols = [c for c in s.slot_vol.columns if c <= hhmm]
    vol = s.slot_vol[cols].fillna(0).sum(axis=1).tail(lookback).mean() if cols else np.nan
    rcols = cols[-recent:]
    rvol = s.slot_vol[rcols].fillna(0).sum(axis=1).tail(lookback).mean() if rcols else np.nan
    slot_avg = s.slot_vol.tail(lookback).mean()
    out = (float(rng), float(vol), float(rvol), slot_avg)
    if len(RADAR_CACHE) > 5000:
        RADAR_CACHE.clear()
    RADAR_CACHE[key] = out
    return out


def _oi_window(o: pd.DataFrame, session, t_last, hhmm: str, lookback: int):
    """OI change from the previous session's close to now, and the usual size of that change by hhmm."""
    if o is None or o.empty:
        return None
    d = o.index.normalize()
    today = o[(d == session) & (o.index <= t_last)]
    before = o[d < session]
    if today.empty or before.empty:
        return None
    prev_close = before["OI"].iloc[-1]
    chg = today["OI"].iloc[-1] / prev_close - 1 if prev_close > 0 else np.nan
    days = before.index.normalize().unique()
    t_end = dtime(*map(int, hhmm.split(":")))
    past = []
    for a, b in zip(days[:-1], days[1:]):
        x = before[(before.index.normalize() == b) & (before.index.time <= t_end)]
        p = before[before.index.normalize() == a]["OI"].iloc[-1]
        if len(x) and p > 0:
            past.append(abs(x["OI"].iloc[-1] / p - 1))
    # rollover weeks (positions moving into these contracts) inflate OI change; leave out days above 3x the median
    med = float(np.median(past)) if past else np.nan
    clean = [x for x in past if x <= 3 * med] if past else []
    usual = float(np.mean(clean[-lookback:])) if clean else np.nan
    bar_chg = today["OI"].diff()
    return chg, usual, bar_chg


def radar(S: dict, oi: dict | None = None, at: dtime | None = None, lookback: int = 20, recent: int = 6,
          min_move: float = 0.01, big_x: float = 4.0, fit_vol: float = 1.5) -> pd.DataFrame:
    """Rank stocks 1%+ from yesterday's close by how unusual today's window is versus the same window on the last
    `lookback` sessions (20, as TradeFinder's R-factor). Score = within-day percentile of volume vs usual + move vs
    ATR + move size (the tested part). Also: yesterday's high (up) / low (down) broken and when, the stock's sector
    move, futures OI and big-money bars. 'TradeFinder fit' = broke yesterday's high/low, sector moving the same way and
    volume 1.5x+ usual: the pattern of 360 verified TradeFinder picks (research/tradefinder_match.py)."""
    import universe as U
    oi = oi or {}
    cut = {s: (st.today if at is None else st.today[st.today.index.time < at]) for s, st in S.items()}
    moves = {s: float(t["Close"].iloc[-1]) / S[s].prev_close - 1 for s, t in cut.items() if not t.empty}
    sec_of = {s: U.FNO_SECTOR_OF.get(s, "Other") for s in moves}
    sec_mv = pd.Series(moves).groupby(pd.Series(sec_of)).mean() if moves else pd.Series(dtype=float)
    sec_n = pd.Series(sec_of).value_counts() if moves else pd.Series(dtype=int)
    rows = []
    for s in S.values():
        t = cut[s.sym]
        if t.empty:
            continue
        last = t.index[-1]
        hhmm = last.strftime("%H:%M")
        px = float(t["Close"].iloc[-1])
        move = px / s.prev_close - 1
        if abs(move) < min_move:
            continue
        side = 1 if move > 0 else -1
        beyond = t["Close"] > s.pdh if side > 0 else t["Close"] < s.pdl
        broke = beyond.idxmax().strftime("%H:%M") if beyond.any() else ""
        first15, later = t[t.index.time < dtime(9, 30)], t[t.index.time >= dtime(9, 30)]
        held = "" if first15.empty or later.empty else \
            ("Yes" if (later["Low"].min() >= first15["Low"].min() if side > 0
                       else later["High"].max() <= first15["High"].max()) else "No")
        sec = sec_of.get(s.sym, "Other")
        smv = float(sec_mv.get(sec, np.nan)) if sec != "Other" and sec_n.get(sec, 0) >= 3 else np.nan
        rng_u, vol_u, rvol_u, slot_avg = _hist_window(s, hhmm, lookback, recent)
        vol_now, rvol_now = t["Volume"].sum(), t["Volume"].tail(recent).sum()
        rng_now = (t["High"].max() - t["Low"].min()) / s.open
        r = {"Stock": s.sym, "Side": "BUY / CE" if side > 0 else "SELL / PE", "Price": px, "Move %": move * 100,
             "From open %": (px / s.open - 1) * 100, "Move / ATR": abs(move) / s.atr_pct if s.atr_pct else np.nan,
             "Volume vs usual": vol_now / vol_u if vol_u > 0 else np.nan,
             "Last 30 min vol vs usual": rvol_now / rvol_u if rvol_u > 0 else np.nan,
             "Range vs usual": rng_now / rng_u if rng_u > 0 else np.nan,
             "Broke yday high/low": broke, "Morning low/high held": held, "Sector": sec, "Sector move %": smv * 100,
             "OI chg %": np.nan, "OI vs usual": np.nan, "Buildup": "", "Big-money bars": 0, "Last big bar": "",
             "As of": hhmm}
        r["TradeFinder fit"] = "Yes" if (broke and np.isfinite(smv) and np.sign(smv) == side
                                         and np.isfinite(r["Volume vs usual"]) and r["Volume vs usual"] >= fit_vol) else ""
        ow = _oi_window(oi.get(s.sym), last.normalize(), last, hhmm, lookback)
        bar_oi = None
        if ow is not None:
            chg, usual, bar_oi = ow
            r["OI chg %"] = chg * 100
            r["OI vs usual"] = abs(chg) / usual if usual and usual > 0 else np.nan
            r["Buildup"] = "" if not chg else ("Long buildup" if chg > 0 else "Short covering") if side > 0 else \
                ("Short buildup" if chg > 0 else "Long unwinding")
        # big-money bars: volume 4x+ the usual for that 5-minute slot, candle in the move's direction, OI added
        big = []
        for ts, b in t.iterrows():
            avg = slot_avg.get(ts.strftime("%H:%M"), np.nan)
            if not (np.isfinite(avg) and avg > 0 and b["Volume"] >= big_x * avg and side * (b["Close"] - b["Open"]) > 0):
                continue
            if bar_oi is not None:
                k = ts.floor("5min")
                if k not in bar_oi.index or not bar_oi.loc[k] > 0:
                    continue
            big.append(ts)
        r["Big-money bars"] = len(big)
        r["Last big bar"] = big[-1].strftime("%H:%M") if big else ""
        rows.append(r)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["Score"] = (df["Volume vs usual"].rank(pct=True) + df["Move / ATR"].rank(pct=True)
                   + df["Move %"].abs().rank(pct=True)) * 100 / 3
    df = df.sort_values("Score", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", np.arange(1, len(df) + 1))
    return df
