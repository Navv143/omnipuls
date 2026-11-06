"""Omnipuls bots: five bots that watch the market all day on the server (started and kept alive by recorder.py).

Every 5 minutes in market hours they fetch today's 5-minute candles for every F&O stock, the indices, the index
futures (for OI) and India VIX, and each bot writes its flags:

1. Index bot      - Nifty, Bank Nifty, Fin Nifty, Midcap Select, Sensex: move in ATR, the constituents' money flow,
                    MACD state, futures OI build-up; and today's signal of a passed index rule (Setup Finder).
2. Sector bot     - money flow by sector (₹ crore, buying share), where money rotates from and to, sector vs market.
3. Sector movers  - each sector's top gainers and losers and whether their money flow and volume back the move.
4. F&O unusual    - every F&O stock: unusual volume, range, money flow, open = high / low; and today's first
                    signals of the passed stock rule (Setup Finder).
5. Master bot     - collects the others' flags and checks each idea against the balance: market money, Nifty, the
                    stock's sector, India VIX and the tested rules. It passes an idea only when they agree, and logs
                    every idea (Supabase bot_ideas) with its result at the close, so the bots can be scored later.

After 16:30 (once a day, or when the app asks) it runs the Setup Finder research (bot.py) in its own process.
State for the app: <data>/bots/state.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

import bot as B
import paths

IST = B.IST
OUT = paths.DATA / "bots"
REQUEST = paths.state("bot_request")
EVERY = int(os.environ.get("BOTS_EVERY", 300))
RESEARCH_AFTER = os.environ.get("BOTS_RESEARCH_AFTER", "16:30")
LIVE_DAYS = 45            # history kept for the live readings (20-day usual volume, 14-day ATR)
STATUS: dict = {"started": None, "errors": []}


def log(msg: str):
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} bots: {msg}", flush=True)


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"

# ---------------------------------------------------------------- data


class Market:
    """History (from the Setup Finder cache, or 45 days) plus today's candles, refreshed every cycle."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.syms = B.universe(cfg)
        self.hist: dict = {}
        self.today: dict = {}
        self.fut: dict = {}
        self.weights: dict = {}
        self.odds: dict = {}
        self.oi_avg: dict = {}
        self.feed: list = []
        self.ev_seen: set = set()
        self.trades: list = []
        self.momentum: dict = {}

    def load(self):
        import candles as C
        cut = pd.Timestamp.now() - pd.Timedelta(days=LIVE_DAYS)
        if C.TF == 5:
            stocks, indices = B.load_history(self.cfg, days=LIVE_DAYS if not B.CACHE.exists() else B.HISTORY_DAYS,
                                             symbols=self.syms + [("INDIAVIX", "IDX_I", 21, "INDEX")])
            self.hist = {k: v[v.index >= cut] for k, v in {**stocks, **indices}.items()}
        else:  # the system timeframe (3 minutes): history from the 1-minute cache, resampled
            self.hist = {}
            for i, (sym, seg, sid, ins) in enumerate(self.syms + [("INDIAVIX", "IDX_I", 21, "INDEX")], 1):
                try:
                    h = B.clean(C.history(sym, seg, sid, ins, LIVE_DAYS, self.cfg))
                except Exception as e:
                    log(f"{sym} history: {e}")
                    continue
                if not h.empty:
                    self.hist[sym] = h[h.index.normalize() < pd.Timestamp.now().normalize()]
                if i % 50 == 0:
                    log(f"{C.TF}-minute history: {i} symbols")
        try:
            import indices as IX
            self.weights = {k: d.get("w", {}) for k, d in IX.load().items()}
        except Exception:
            self.weights = {}
        log(f"history: {len(self.hist)} symbols")
        self.odds = load_odds(self.syms)
        self.oi_avg = oi_history()

    def refresh(self):
        import candles as C
        import dhan as D
        for sym, seg, sid, ins in self.syms + [("INDIAVIX", "IDX_I", 21, "INDEX")]:
            try:
                d = B.clean(C.fetch(seg, sid, ins, 1, self.cfg))
            except D.DhanError as e:
                if e.code == "NETWORK":
                    raise
                continue
            d = C.closed(d)                    # closed candles only: nothing signals before the first candle closes
            if not d.empty:
                self.today[sym] = d[d.index.normalize() == d.index.normalize().max()]
        try:
            futs = D.nearest_futures("NSE_FNO", "FUTIDX", list(B.INDEX_IDS), self.cfg)
            for k, f in futs.items():
                d = B.clean(D.intraday("NSE_FNO", f["id"], "FUTIDX", 5, 2, self.cfg))
                if not d.empty:
                    self.fut[k] = d
        except Exception as e:
            log(f"index futures: {e}")

    def bars(self, sym: str) -> pd.DataFrame:
        h, t = self.hist.get(sym, pd.DataFrame()), self.today.get(sym, pd.DataFrame())
        if t.empty:
            return h
        h = h[h.index.normalize() < t.index.normalize().min()] if not h.empty else h
        return pd.concat([h, t])

    def stock_bars(self) -> dict:
        return {s: self.bars(s) for s, seg, _, _ in self.syms if seg != "IDX_I"}


# ---------------------------------------------------------------- odds table, OI from the recorder, sudden changes

ODDS_DAYS = int(os.environ.get("BOTS_ODDS_DAYS", 150))


def load_odds(syms: list, force: bool = False) -> dict:
    """The odds table (bot.odds_table) from the cached 5-minute history; rebuilt once a day."""
    f = OUT / "odds.json"
    try:
        t = json.loads(f.read_text())
        if not force and t.get("built", "")[:10] == datetime.now(IST).strftime("%Y-%m-%d"):
            return t
    except Exception:
        t = {}
    try:
        t0 = time.time()
        cols = ["day", "m", "move", "move_atr", "vol_x", "flow_share", "entry", "exit", "maxhigh", "minlow", "atr"]
        parts = []
        for i, (sym, seg, _, _) in enumerate(syms):
            if seg == "IDX_I":
                continue
            fp = B.CACHE / f"{sym.replace('&', '_and_')}.parquet"
            if not fp.exists():
                continue
            df = pd.read_parquet(fp)
            df = df[df.index >= df.index.max() - pd.Timedelta(days=ODDS_DAYS)]
            c = B.candle_table(sym, df)
            if c.get("n"):
                parts.append({**{k: c[k] for k in cols}, "sym": np.full(c["n"], i, dtype=np.int32)})
        if not parts:
            return t
        T = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        t = B.odds_table(T)
        t["built"] = datetime.now(IST).isoformat(timespec="seconds")
        t["stocks"] = len(parts)
        OUT.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(t))
        log(f"odds table: {t['days']} days, {len(parts)} stocks in {time.time() - t0:.0f}s")
    except Exception as e:
        log(f"odds table: {e}")
    return t


def _quote_files(day: str) -> list:
    d = paths.DATA / "quotes" / "parts" / day
    return sorted(d.glob("*.parquet")) if d.exists() else []


def _fut_oi(df: pd.DataFrame) -> pd.DataFrame:
    """Per future symbol and minute: total OI over the expiries, and the near expiry's book."""
    f = df[df["kind"] == "future"]
    if f.empty:
        return pd.DataFrame()
    return f.groupby(["symbol", "time"]).agg(oi=("oi", "sum"), buy=("buy_qty", "first"), sell=("sell_qty", "first"))


def oi_history(days: int = 20) -> dict:
    """{symbol: usual absolute OI change % in a day} from the recorder's finished quote files."""
    files = sorted((paths.DATA / "quotes").glob("*/*.parquet"))[-days:]
    chg = []
    for fp in files:
        try:
            g = _fut_oi(pd.read_parquet(fp, columns=["time", "kind", "symbol", "oi", "buy_qty", "sell_qty"]))
            if g.empty:
                continue
            g = g.reset_index().sort_values("time").groupby("symbol")["oi"].agg(["first", "last"])
            chg.append(((g["last"] / g["first"].replace(0, np.nan) - 1).abs() * 100).rename(fp.stem))
        except Exception:
            continue
    if not chg:
        return {}
    return pd.concat(chg, axis=1).mean(axis=1).dropna().round(2).to_dict()


def oi_today(day: str) -> pd.DataFrame:
    """Today's futures OI change and order-book pressure per stock, from the recorder's live quote files."""
    files = _quote_files(day)
    if not files:
        return pd.DataFrame()
    try:
        df = pd.concat(pd.read_parquet(f, columns=["time", "kind", "symbol", "oi", "buy_qty", "sell_qty"]) for f in files)
    except Exception:
        return pd.DataFrame()
    g = _fut_oi(df)
    if g.empty:
        return pd.DataFrame()
    g = g.reset_index().sort_values("time")
    a = g.groupby("symbol").agg(oi0=("oi", "first"), oi=("oi", "last"), buy=("buy", "last"), sell=("sell", "last"))
    a["oi_chg"] = (a["oi"] / a["oi0"].replace(0, np.nan) - 1) * 100
    tot = a["buy"] + a["sell"]
    a["book_buy"] = np.where(tot > 0, a["buy"] / tot.replace(0, np.nan) * 100, np.nan)
    return a[["oi_chg", "book_buy"]]


def sudden(bars: pd.DataFrame) -> dict | None:
    """The latest 5-minute candle against the same slot on the last 20 days (volume, size), and the last 15 minutes'
    move."""
    d = B.clean(bars)
    if d.empty:
        return None
    day = d.index.normalize()
    today = d[day == day.max()]
    if today.empty:
        return None
    last = today.iloc[-1]
    slot = d.index[-1].time()
    past = d[(day < day.max()) & (d.index.time == slot)].tail(20)
    if len(past) < 5:
        return None
    v_med = float(past["Volume"].median())
    r_avg = float((past["High"] - past["Low"]).mean())
    c3 = float(today["Close"].iloc[-4]) if len(today) >= 4 else float(today["Open"].iloc[0])
    return {"spike_x": float(last["Volume"]) / v_med if v_med > 0 else np.nan,
            "candle_x": float(last["High"] - last["Low"]) / r_avg if r_avg > 0 else np.nan,
            "jump": float(last["Close"]) - c3, "last_t": d.index[-1].strftime("%H:%M")}


def _f(x, nd=1):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def radar_bot(L: pd.DataFrame, mkt: "Market", oi: pd.DataFrame) -> dict:
    """Every F&O stock with its full readings (each against its own usual), the sudden changes flagged, and the
    odds from past days for its current kind of moment."""
    rows, events = [], []
    for _, r in L.iterrows():
        st_ = r["stock"]
        sd = sudden(mkt.bars(st_)) or {}
        side = 1 if r["move"] > 0 else -1 if r["move"] < 0 else 0
        oc = oi.loc[st_] if (not oi.empty and st_ in oi.index) else None
        oi_chg = float(oc["oi_chg"]) if oc is not None and pd.notna(oc["oi_chg"]) else np.nan
        oi_usual = mkt.oi_avg.get(st_)
        oi_x = abs(oi_chg) / oi_usual if oi_usual and np.isfinite(oi_chg) else np.nan
        jump_atr = sd.get("jump", np.nan) / r["atr"] if r["atr"] else np.nan
        odds = B.odds_lookup(mkt.odds, r["m"], r["vol_x"], r["move_atr"], r["flow_share"], side)
        ev = []
        if sd.get("spike_x", 0) >= 3:
            ev.append(("spike", f"volume spike {sd['spike_x']:.1f}x in the last 5 min"))
        if sd.get("candle_x", 0) >= 2.5:
            ev.append(("candle", f"big candle {sd['candle_x']:.1f}x the usual"))
        if np.isfinite(jump_atr) and abs(jump_atr) >= 0.5:
            ev.append(("jump", f"{jump_atr:+.1f} ATR in 15 min"))
        if r["vol_x"] >= 2:
            ev.append(("vol", f"volume {r['vol_x']:.1f}x usual by this time"))
        if r["range_x"] >= 1.2:
            ev.append(("range", f"range {r['range_x']:.1f}x ATR"))
        if abs(r["move_atr"]) >= 1:
            ev.append(("move", f"{r['move_atr']:+.1f} ATR from the open"))
        if np.isfinite(oi_x) and oi_x >= 2 and abs(oi_chg) >= 3:
            up = r["chg"] > 0
            lab = ("long build-up" if oi_chg > 0 else "short covering") if up else ("short build-up" if oi_chg > 0 else "long unwinding")
            ev.append(("oi", f"OI {oi_chg:+.1f}% ({oi_x:.1f}x usual) {lab}"))
        if (r["o_eq_l"] and side > 0) or (r["o_eq_h"] and side < 0):
            ev.append(("ohl", "opened at the " + ("low" if r["o_eq_l"] else "high")))
        score = (min(sd.get("spike_x", 0) or 0, 10) / 3 + min(r["vol_x"], 6) / 2 + min(r["range_x"], 3)
                 + min(abs(r["move_atr"]), 3) + (min(oi_x, 5) / 2 if np.isfinite(oi_x) else 0))
        row = {"stock": st_, "sector": r["sector"], "price": _f(r["price"], 2), "chg": _f(r["chg"] * 100, 2),
               "move_atr": _f(r["move_atr"], 2), "range_x": _f(r["range_x"], 2), "vol_x": _f(r["vol_x"], 2),
               "spike_x": _f(sd.get("spike_x")), "candle_x": _f(sd.get("candle_x")), "jump_atr": _f(jump_atr, 2),
               "buying": _f(r["flow_share"] * 100, 0), "net_cr": _f(r["net_cr"], 1), "oi_chg": _f(oi_chg, 2),
               "oi_x": _f(oi_x), "book_buy": _f(oc["book_buy"], 0) if oc is not None else None,
               "ohl": "O=L ▲" if r["o_eq_l"] else "O=H ▼" if r["o_eq_h"] else "", "side": side,
               "score": round(score, 1), "events": [t for _, t in ev], "kinds": [k for k, _ in ev],
               "odds": odds, "time": sd.get("last_t", f"{int(r['m']) // 60:02d}:{int(r['m']) % 60:02d}")}
        rows.append(row)
        if ev:
            events.append(row)
    rows.sort(key=lambda x: -x["score"])
    events.sort(key=lambda x: (-len(x["events"]), -x["score"]))
    return {"name": "Radar", "rows": rows, "events": events[:60],
            "odds_info": {"days": mkt.odds.get("days"), "built": mkt.odds.get("built"), "stocks": mkt.odds.get("stocks")}}


def update_feed(mkt: "Market", radar: dict, now: datetime):
    """New sudden changes go to the top of the day's feed (each stock + kind once a day)."""
    for r in radar["events"]:
        for k, t in zip(r["kinds"], r["events"]):
            key = (r["stock"], k)
            if key in mkt.ev_seen:
                continue
            mkt.ev_seen.add(key)
            o = r.get("odds") or {}
            mkt.feed.insert(0, {"time": r["time"], "stock": r["stock"], "kind": k, "text": t, "side": r["side"],
                                "price": r["price"], "chg": r["chg"], "win": o.get("win"), "n": o.get("n"),
                                "avg": o.get("avg")})
    del mkt.feed[300:]

# ---------------------------------------------------------------- the five bots


def _tone_word(t: int) -> str:
    return "bullish" if t > 0 else "bearish" if t < 0 else "neutral"


def latest_rows(T: dict) -> pd.DataFrame:
    """The latest candle of each stock from a today-only table."""
    if not T:
        return pd.DataFrame()
    cols = ["sym", "m", "move", "move_atr", "range_x", "vol_x", "flow_share", "flow_x", "net_cr", "chg", "o_eq_l",
            "o_eq_h", "price", "atr", "sec_flow", "mkt_flow"]
    df = pd.DataFrame({c: T[c] for c in cols})
    df = df.groupby("sym").tail(1).copy()
    df["stock"] = T["names"][df["sym"].to_numpy()]
    df["sector"] = T["sector_of"][df["sym"].to_numpy()]
    return df


def index_bot(mkt: Market, research: dict | None) -> dict:
    flags = []
    for k, name in B.INDEX_NAMES.items():
        bars = mkt.bars(k)
        w = mkt.weights.get(k) or {}
        flow = B.constituent_flow({s: mkt.bars(s) for s in w}, w) if w else pd.DataFrame()
        t = B.candle_table(k, bars, flow, keep_all_days=False) if not bars.empty else {}
        if not t.get("n"):
            continue
        i = -1
        mv, fs = float(t["move_atr"][i]), float(t["flow_share"][i])
        c = B.clean(bars)["Close"]
        m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
        sd = np.sign(m - m.ewm(span=9, adjust=False).mean())
        today = sd[sd.index.normalize() == sd.index.normalize().max()]
        cross = today[(today != today.shift()) & (today != 0)].index
        macd = f"MACD {'up' if sd.iloc[-1] > 0 else 'down'}" + (f" since {cross[-1]:%H:%M}" if len(cross) else "")
        oi_txt, oi_dir = "", 0
        f = mkt.fut.get(k)
        if f is not None and "OI" in f and f["OI"].notna().any():
            fd = f.index.normalize()
            prev = f[fd < fd.max()]
            tod = f[fd == fd.max()]
            if not prev.empty and not tod.empty and prev["OI"].iloc[-1] > 0:
                d_oi = tod["OI"].iloc[-1] / prev["OI"].iloc[-1] - 1
                up = tod["Close"].iloc[-1] >= prev["Close"].iloc[-1]
                label = ("long build-up" if d_oi > 0 else "short covering") if up else \
                        ("short build-up" if d_oi > 0 else "long unwinding")
                oi_dir = (1 if up else -1) if d_oi > 0 else (1 if up else -1) * 0.5
                oi_txt = f"futures {label} (OI {d_oi * 100:+.1f}%)"
        votes = [np.sign(mv) if abs(mv) >= 0.3 else 0, 1 if fs >= 0.55 else -1 if fs <= 0.45 else 0,
                 float(sd.iloc[-1]), np.sign(oi_dir)]
        tone = int(np.sign(sum(votes))) if abs(sum(votes)) >= 2 else 0
        sig = ""
        best = ((research or {}).get("indices", {}).get(k) or {}).get("best")
        if best:
            T1 = {kk: v for kk, v in t.items() if kk != "n"}
            T1["sym"] = np.zeros(t["n"], dtype=np.int32)
            T1["vol_x"] = np.ones(t["n"], dtype=np.float32)
            T1["sec_flow"] = T1["mkt_flow"] = T1["flow_share"]
            side = np.sign(T1["move"]).astype(np.int8)
            sel = B.first_signals(T1, B.rule_mask(T1, best["rule"], side), 99)
            if len(sel):
                j = sel[0]
                sig = f"TESTED SIGNAL {'BUY' if side[j] > 0 else 'SELL'} at {int(T1['m'][j]) // 60:02d}:{int(T1['m'][j]) % 60:02d}"
        flags.append({"name": name, "key": k, "tone": tone, "signal": sig, "value": f"{float(t['price'][i]):,.2f}",
                      "text": f"{mv:+.2f} ATR from open · money {fs * 100:.0f}% buying · {macd}"
                              + (f" · {oi_txt}" if oi_txt else "")})
    return {"name": "Index bot", "flags": flags}


def sector_bot(L: pd.DataFrame) -> dict:
    if L.empty:
        return {"name": "Sector bot", "flags": []}
    g = L.groupby("sector").agg(net_cr=("net_cr", "sum"), buying=("flow_share", "mean"), move=("chg", "mean"),
                                n=("stock", "count")).sort_values("net_cr", ascending=False)
    mkt_move = float(L["chg"].mean())
    flags = []
    for sec, r in g.iterrows():
        if r["n"] < 2:
            continue
        tone = 1 if r["buying"] >= 0.53 and r["net_cr"] > 0 else -1 if r["buying"] <= 0.47 and r["net_cr"] < 0 else 0
        flags.append({"name": sec, "tone": tone, "value": f"₹{r['net_cr']:+,.0f} Cr",
                      "text": f"{r['buying'] * 100:.0f}% buying · avg move {r['move'] * 100:+.2f}% "
                              f"({(r['move'] - mkt_move) * 100:+.2f}% vs market) · {int(r['n'])} stocks"})
    top_in = [f["name"] for f in flags if f["tone"] > 0][:3]
    top_out = [f["name"] for f in flags if f["tone"] < 0][-3:]
    note = (f"Money moving from {', '.join(top_out) or '—'} into {', '.join(top_in) or '—'}.")
    return {"name": "Sector bot", "flags": flags, "note": note}


def movers_bot(L: pd.DataFrame) -> dict:
    flags = []
    if L.empty:
        return {"name": "Sector movers", "flags": flags}
    for sec, g in L.groupby("sector"):
        g = g.sort_values("chg")
        for _, r in pd.concat([g.tail(2), g.head(2)]).drop_duplicates("stock").iterrows():
            side = 1 if r["chg"] > 0 else -1
            backed = (r["flow_share"] >= 0.55 if side > 0 else r["flow_share"] <= 0.45) and r["vol_x"] >= 1.5
            flags.append({"name": r["stock"], "sector": sec, "side": side, "tone": side if backed else 0,
                          "backed": bool(backed), "value": f"{r['chg'] * 100:+.2f}%",
                          "text": f"{sec} · money {r['flow_share'] * 100:.0f}% buying · volume {r['vol_x']:.1f}x usual"
                                  + (" · opened at the low" if r["o_eq_l"] else " · opened at the high" if r["o_eq_h"] else "")
                                  + (" · BACKED by money" if backed else "")})
    flags.sort(key=lambda f: (not f["backed"], -abs(float(f["value"].rstrip("%")))))
    return {"name": "Sector movers", "flags": flags}


def unusual_bot(L: pd.DataFrame, T: dict, research: dict | None) -> dict:
    flags = []
    for _, r in L.iterrows():
        why = []
        if r["vol_x"] >= 2.5:
            why.append(f"volume {r['vol_x']:.1f}x usual")
        if r["range_x"] >= 1.5:
            why.append(f"range {r['range_x']:.1f}x the usual day")
        if abs(r["flow_x"]) >= 0.15:
            why.append(f"net money {r['flow_x'] * 100:+.0f}% of a usual day's turnover")
        if (r["o_eq_l"] and r["move"] > 0) or (r["o_eq_h"] and r["move"] < 0):
            why.append("opened at the " + ("low" if r["o_eq_l"] else "high"))
        if len(why) >= 2 or (why and abs(r["move_atr"]) >= 0.8):
            side = 1 if r["move"] > 0 else -1
            agree = (r["flow_share"] >= 0.55) if side > 0 else (r["flow_share"] <= 0.45)
            flags.append({"name": r["stock"], "sector": r["sector"], "side": side, "tone": side if agree else 0,
                          "value": f"{r['chg'] * 100:+.2f}%", "text": " · ".join(why)})
    flags.sort(key=lambda f: -len(f["text"]))
    signals = []
    best = (research or {}).get("best")
    if best and T:
        signals = B.live_signals(best["rule"], T)
    return {"name": "F&O unusual", "flags": flags[:40], "signals": signals}


def master_bot(L: pd.DataFrame, idx: dict, sec: dict, mov: dict, unu: dict, vix_chg: float | None,
               radar: dict | None = None, funnel_top: list | None = None) -> dict:
    """passed = a tested rule fired AND 3+ of 4 balance checks agree; odds = the radar's past-days odds are good (55%+
    kept going, 40+ cases, 3+ points over the usual) AND 3+ checks agree; watch = 3+ checks only."""
    nifty = next((f for f in idx["flags"] if f.get("key") == "NIFTY"), None)
    sec_tone = {f["name"]: f["tone"] for f in sec["flags"]}
    mkt = float(L["flow_share"].mean()) if not L.empty else 0.5
    cands = {}
    for s in unu.get("signals", []):
        cands[(s["stock"], 1 if s["side"] == "BUY" else -1)] = {"source": "Tested rule (Setup Finder)", "rule": True,
                                                                  "time": s["time"], "price": s["price"], "stop": s["stop"]}
    for f in mov["flags"]:
        if f.get("backed"):
            cands.setdefault((f["name"], f["side"]), {"source": "Sector mover backed by money", "rule": False})
    for f in unu["flags"]:
        if f["tone"] != 0:
            cands.setdefault((f["name"], f["side"]), {"source": "Unusual activity", "rule": False})
    for f in funnel_top or []:  # Momentum Funnel picks (all 5 steps)
        c = cands.setdefault((f["Stock"], int(f["side"])), {"source": "Momentum funnel", "rule": False})
        c["funnel"] = f["score"]
        if c["source"] != "Tested rule (Setup Finder)":
            c["source"] = f"Momentum funnel (score {f['score']:.0f})"
    for r in (radar or {}).get("events", []):
        o = r.get("odds") or {}
        if r["side"] and o.get("n", 0) >= 40 and o.get("win", 0) >= 55 and o.get("edge", 0) >= 3:
            c = cands.setdefault((r["stock"], r["side"]), {"source": "Radar", "rule": False})
            c["odds"] = o
            if c["source"].startswith("Momentum funnel"):
                c["source"] += f" + radar: {', '.join(r['events'][:2])}"
            elif c["source"] != "Tested rule (Setup Finder)":
                c["source"] = f"Radar: {', '.join(r['events'][:2])}"
    rows = L.set_index("stock") if not L.empty else pd.DataFrame()
    ideas = []
    for (stock, side), c in cands.items():
        if stock not in rows.index:
            continue
        r = rows.loc[stock]
        checks = {"market money": bool((mkt >= 0.51) if side > 0 else (mkt <= 0.49)),
                  "Nifty not against": bool(nifty is None or nifty["tone"] != -side),
                  "sector money": bool(sec_tone.get(r["sector"], 0) == side),
                  "VIX calm": bool(vix_chg is None or vix_chg < 5)}
        ok = sum(checks.values())
        status = ("passed" if c["rule"] and ok >= 3 else "odds" if c.get("odds") and ok >= 3 else
                  "watch" if ok >= 3 else None)
        if not status:
            continue
        ideas.append({"stock": stock, "side": "BUY" if side > 0 else "SELL", "status": status, "source": c["source"],
                      "price": c.get("price", round(float(r["price"]), 2)), "stop": c.get("stop"),
                      "time": c.get("time", f"{int(r['m']) // 60:02d}:{int(r['m']) % 60:02d}"),
                      "sector": r["sector"], "checks": checks, "agree": f"{ok}/4",
                      "odds": c.get("odds"),
                      "why": f"{c['source']}; " + ", ".join(k for k, v in checks.items() if v)
                             + (f"; past odds {c['odds']['win']:.0f}% kept going (n {c['odds']['n']})" if c.get("odds") else "")})
    rank = {"passed": 0, "odds": 1, "watch": 2}
    ideas.sort(key=lambda x: (rank[x["status"]], -int(x["agree"][0]), -((x.get("odds") or {}).get("win") or 0)))
    return {"name": "Master bot", "ideas": ideas[:25],
            "note": f"Market money {mkt * 100:.0f}% buying" + (f" · India VIX {vix_chg:+.1f}%" if vix_chg is not None else "")}

# ---------------------------------------------------------------- idea log (Supabase) and scoring at the close


def _cloud():
    import cloudstore
    if not cloudstore.enabled():
        try:
            import streamlit as st
            sb = dict(st.secrets.get("supabase") or {})
            cloudstore.configure(sb.get("url"), sb.get("key"))
        except Exception:
            cloudstore.configure(None, None)
    return cloudstore


def log_ideas(day: str, ideas: list, seen: dict):
    """Logs an idea the first time it shows and again whenever its status changes (watch -> passed). seen keeps the
    first sighting (time and price, for scoring) with the latest status."""
    new = []
    for i in ideas:
        k = (i["stock"], i["side"])
        if k not in seen:
            seen[k] = dict(i)
            new.append(seen[k])
        elif seen[k]["status"] != i["status"]:
            seen[k].update(status=i["status"], checks=i["checks"], why=i["why"])
            new.append(seen[k])
    if not new:
        return
    rows = [{"day": day, "stock": i["stock"], "side": i["side"], "status": i["status"], "first_at": i["time"],
             "price": float(i["price"]), "checks": i["checks"], "reasons": i["why"]} for i in new]
    _cloud().upsert_rows("bot_ideas", rows, "day,stock,side")


def score_ideas(day: str, mkt: Market, seen: dict) -> list:
    """At the close: each idea's result from its first price to 15:20 (no stop), for scoring the bots."""
    out = []
    for (stock, side), i in seen.items():
        b = mkt.today.get(stock)
        if b is None or b.empty:
            continue
        ex = b[b.index.strftime("%H:%M") <= "15:15"]["Close"]
        if ex.empty:
            continue
        s = 1 if side == "BUY" else -1
        res = s * (float(ex.iloc[-1]) / float(i["price"]) - 1) * 100
        out.append({"day": day, "stock": stock, "side": side, "status": i["status"], "first_at": i["time"],
                    "price": float(i["price"]), "checks": i["checks"], "reasons": i["why"],
                    "result_pct": round(res - 0.12, 3)})
    if out:
        _cloud().upsert_rows("bot_ideas", out, "day,stock,side")
    return out


def log_radar(day: str, feed: list, logged: set):
    """Every new radar event with its odds (Supabase radar_events), so the odds can be checked against what happened."""
    new = [e for e in feed if (e["stock"], e["kind"]) not in logged]
    for e in new:
        logged.add((e["stock"], e["kind"]))
    if not new:
        return
    rows = [{"day": day, "stock": e["stock"], "kind": e["kind"], "side": int(e["side"]), "first_at": e["time"],
             "price": e["price"], "text": e["text"], "odds_win": e.get("win"), "odds_n": e.get("n")} for e in new]
    _cloud().upsert_rows("radar_events", rows, "day,stock,kind")


def score_radar(day: str, mkt: Market, feed: list) -> list:
    """At the close: each radar event's result (first price to 15:15, after costs) and how the odds did."""
    out = []
    for e in feed:
        b = mkt.today.get(e["stock"])
        if b is None or b.empty or not e["side"] or not e.get("price"):
            continue
        ex = b[b.index.strftime("%H:%M") <= "15:15"]["Close"]
        if ex.empty:
            continue
        res = e["side"] * (float(ex.iloc[-1]) / float(e["price"]) - 1) * 100 - 0.12
        out.append({"day": day, "stock": e["stock"], "kind": e["kind"], "side": int(e["side"]), "first_at": e["time"],
                    "price": e["price"], "text": e["text"], "odds_win": e.get("win"), "odds_n": e.get("n"),
                    "result_pct": round(res, 3)})
    if out:
        _cloud().upsert_rows("radar_events", out, "day,stock,kind")
        df = pd.DataFrame(out)
        df["band"] = pd.cut(df["odds_win"].fillna(-1), [-2, 0, 50, 55, 60, 101],
                            labels=["no odds", "<50%", "50-55%", "55-60%", "60%+"])
        g = df.groupby("band", observed=True)["result_pct"].agg(n="size", kept=lambda r: float((r > 0).mean() * 100),
                                                                avg="mean").round(2)
        hist = _odds_check()
        hist = [h for h in hist if h.get("day") != day] + [{"day": day, "bands": g.reset_index().to_dict("records")}]
        (OUT / "odds_check.json").write_text(json.dumps(hist[-30:], default=str))
    return out


def _odds_check() -> list:
    try:
        return json.loads((OUT / "odds_check.json").read_text())
    except Exception:
        return []


FUNNEL_COLS = ["Stock", "Sector", "side", "price", "move_pct", "chg_pct", "gap_pct", "day_x", "now_x", "range_x",
               "room_atr", "prev_rng_atr", "net", "net_before", "inflow", "outflow", "sec_net", "sec_net_before",
               "mkt_move", "flow_with", "sec_with", "score", "step1", "step2", "step3", "step4", "step5", "suggest",
               "mkt_prev", "gap_atr", "q_mkt", "q_gap", "q_calm", "quality"]


def funnel_snapshot(mkt: "Market", now: datetime) -> dict:
    """The Momentum Funnel for every F&O stock, stored every cycle (<data>/funnel/<day>/<HHMM>.parquet, and the rows
    that pass step 1 in Supabase funnel_log) so the funnel's rules can be tested on what was known at each moment."""
    import funnel as FN
    import universe as U
    bars = mkt.stock_bars()
    t, _ = FN.build(bars, {s: FN.flow_from_bars(b) for s, b in bars.items()}, U.FNO_SECTOR_OF)
    if t.empty:
        return {}
    snap = t[[c for c in FUNNEL_COLS if c in t]].copy()
    snap.insert(0, "time", t["time"].max())
    d = OUT.parent / "funnel" / now.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    snap.to_parquet(d / f"{now:%H%M}.parquet", index=False)
    rows = [{"day": now.strftime("%Y-%m-%d"), "time": r["time"], "stock": r["Stock"], "side": int(r["side"]),
             "price": float(r["price"]), "day_x": _f(r["day_x"], 3), "now_x": _f(r["now_x"], 3), "range_x": _f(r["range_x"], 3),
             "sec_net": _f(r["sec_net"], 2), "net": _f(r["net"], 2), "net_before": _f(r["net_before"], 2),
             "mkt_move": _f(r["mkt_move"], 3), "room_atr": _f(r["room_atr"], 2), "prev_rng_atr": _f(r["prev_rng_atr"], 2),
             "score": _f(r["score"], 0), "step": sum(int(r[f"step{i}"]) for i in (1, 2, 3, 4, 5)),
             "suggest": bool(r["suggest"]), "quality": int(r.get("quality", 0) or 0), "q_mkt": bool(r.get("q_mkt", False)),
             "q_gap": bool(r.get("q_gap", False)), "q_calm": bool(r.get("q_calm", False)),
             "gap_atr": _f(r.get("gap_atr"), 3), "mkt_prev": _f(r.get("mkt_prev"), 3)} for _, r in snap[snap["step1"]].iterrows()]
    try:
        if rows:
            _cloud().upsert_rows("funnel_log", rows, "day,time,stock")
    except Exception as e:
        log(f"funnel_log: {e}")
    p5 = t[t["step5"] & t["entry"].notna()]
    plans = [{"symbol": r["Stock"], "side": int(r["side"]), "time": r["time"], "entry": float(r["entry"]),
              "sl": float(r["sl"]), "tp1": float(r["tp1"]), "tp2": float(r["tp2"]), "risk_pct": float(r["risk_pct"]),
              "score": _f(r["score"], 0), "note": r.get("quality_note") or None} for _, r in p5.iterrows()]
    return {"plans": plans, "time": snap["time"].iloc[0], "stocks": int(len(snap)),
            "steps": [int(snap[f"step{i}"].sum()) for i in (1, 2, 3, 4, 5)], "suggest": int(snap["suggest"].sum()),
            "top": t[t["suggest"]].sort_values("score", ascending=False).head(10)[
                ["Stock", "Sector", "side", "price", "move_pct", "time", "day_x", "now_x", "range_x", "score", "sec_net", "net",
                 "net_before", "why", "quality", "q_mkt", "q_gap", "q_calm"]].to_dict("records")}


def _latest_chain(index: str, day: str) -> tuple[float, pd.DataFrame]:
    """The recorder's latest option-chain snapshot (nearest expiry) for an index, in the app's column names."""
    d = OUT.parent / "option_chain" / "parts" / day
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
        c = c[c["expiry"] == c["expiry"].min()]
        ren = {"strike": "Strike", "ce_oi": "CE OI", "pe_oi": "PE OI", "ce_chg_oi": "CE Chg OI", "pe_chg_oi": "PE Chg OI"}
        return float(c["spot"].iloc[0]), c.rename(columns=ren)
    return 0.0, pd.DataFrame()


def index_snapshot(mkt: "Market", now: datetime) -> list:
    """Every 5 minutes: each index's funnel steps, index money, futures OI and option OI, to Supabase index_log, so
    the OI step (and Bank Nifty variants) can be tested later on what was known at each moment."""
    import index_funnel as IF
    import index_levels as LV
    stocks = mkt.stock_bars()
    vix = mkt.bars("INDIAVIX")
    day = now.strftime("%Y-%m-%d")
    rows = []
    for k in IF.INDEXES:
        t = IF.index_table(mkt.bars(k), stocks, mkt.weights.get(k, {}), vix, today_only=True)
        if t.empty:
            continue
        r = t.iloc[-1]
        side = int(r["side"])
        fo = LV.futures_oi(mkt.fut.get(k)) if mkt.fut.get(k) is not None else {}
        spot, ch = _latest_chain(k, day) if k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX") else (0.0, pd.DataFrame())
        co = LV.chain_oi(ch, spot or float(r["Close"])) if not ch.empty else {}
        oi = LV.oi_step(side, fo, co)
        rows.append({"day": day, "time": f"{(int(r['m']) + 5) // 60:02d}:{(int(r['m']) + 5) % 60:02d}", "index": k,
                     "price": float(r["Close"]), "move_pct": _f(r["move_pct"], 3), "side": side,
                     "day_x": _f(r["day_x"], 3), "now_x": _f(r["now_x"], 3), "range_x": _f(r["range_x"], 3),
                     "net": _f(r["net"], 2), "net_before": _f(r["net_before"], 2), "buy_share": _f(r["buy_share"], 1),
                     "breadth": _f(r["breadth_with"], 1), "vix_chg": _f(r["vix_chg"], 2),
                     "fut_oi": _f(fo.get("oi"), 0), "fut_oi_chg": _f(fo.get("oi_chg_pct"), 3),
                     "fut_buildup": fo.get("buildup_day") or None, "fut_buildup_15m": fo.get("buildup_15m") or None,
                     "ce_oi": _f(co.get("ce_oi"), 0), "pe_oi": _f(co.get("pe_oi"), 0),
                     "ce_chg_near": _f(co.get("ce_chg_near"), 0), "pe_chg_near": _f(co.get("pe_chg_near"), 0),
                     "pcr": _f(co.get("pcr"), 3), "support": (co.get("support") or [None])[0],
                     "resistance": (co.get("resistance") or [None])[0], "writers": co.get("writers"),
                     "step": sum(int(bool(r[f"step{i}"])) for i in (1, 2, 3, 4)), "oi_pass": bool(oi["pass"])})
    try:
        if rows:
            _cloud().upsert_rows("index_log", rows, "day,time,index")
    except Exception as e:
        log(f"index_log: {e}")
    return rows


def collect_signals(mkt: "Market", fun: dict) -> list:
    """Every live signal with its plan: funnel stocks (all 5 steps), index funnel, Bank Nifty failed-break fade."""
    import index_funnel as IF
    import index_levels as LV
    out = [{**p, "source": "Momentum funnel"} for p in (fun or {}).get("plans", [])]
    try:
        ix = {k: mkt.bars(k) for k in IF.INDEXES}
        for r in IF.live(ix, mkt.stock_bars(), mkt.weights, mkt.bars("INDIAVIX")):
            g = r.get("signal") or {}
            p = g.get("plan")
            if p:
                out.append({"source": "Index funnel", "symbol": r["key"], "side": 1 if g["side"] == "LONG" else -1,
                            "time": g["time"], **{k: p[k] for k in ("entry", "sl", "tp1", "tp2", "risk_pct")}, "score": None})
        for k, nm in IF.INDEXES.items():  # index momentum bot: every confirmed burst (Bank Nifty: faded)
            mo = IF.momentum_now(mkt.bars(k), mkt.stock_bars(), mkt.weights.get(k, {}), nm, mode=IF.MOM_MODE.get(k),
                                 fut=mkt.fut.get(k)) or {}
            mkt.momentum[k] = {kk: v for kk, v in mo.items()}
            for g in mo.get("signals", []):
                p = g["plan"]
                o = g.get("oi") or {}
                out.append({"source": "Index momentum bot" + (" (early)" if g.get("stage") == "EARLY" else ""),
                            "symbol": f"{k} {g['time']}", "side": 1 if g["side"] == "LONG" else -1,
                            "time": g["time"], **{kk: p[kk] for kk in ("entry", "sl", "tp1", "tp2", "risk_pct")}, "score": None,
                            "note": (f"OI {'confirms' if o.get('oi_ok') else 'does not confirm'}: 15 min {o.get('oi_15m') or '-'}, "
                                     f"day {o.get('oi_day') or '-'} ({o.get('oi_chg_pct')}%)") if o else "OI n/a"})
        for k in ("NIFTY", "BANKNIFTY"):
            gg = IF.gap_go(mkt.bars(k), mkt.stock_bars(), mkt.weights.get(k, {})) or {}
            g = gg.get("signal") or {}
            if g.get("plan"):
                p = g["plan"]
                out.append({"source": "Gap & go", "symbol": k, "side": 1 if g["side"] == "LONG" else -1, "time": g["time"],
                            **{kk: p[kk] for kk in ("entry", "sl", "tp1", "tp2", "risk_pct")}, "score": None})
        fb = LV.failed_break(mkt.bars("BANKNIFTY")) or {}
        g = fb.get("signal") or {}
        if g.get("plan"):
            p = g["plan"]
            out.append({"source": "Bank Nifty failed-break fade", "symbol": "BANKNIFTY", "side": 1 if g["side"] == "LONG" else -1,
                        "time": g["time"], **{k: p[k] for k in ("entry", "sl", "tp1", "tp2", "risk_pct")}, "score": None})
    except Exception as e:
        log(f"index signals: {e}")
    return out


def _trade_file(day: str):
    d = OUT / "trades"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{day}.json"


def track_trades(mkt: "Market", day: str, signals: list, final: bool = False):
    """New signals join the day's record (each source + symbol once); every trade's result so far (or final at the
    close) from the candles after its signal; saved locally and to Supabase trade_signals."""
    import funnel as FN
    seen = {(t["source"], t["symbol"]) for t in mkt.trades}
    new = [dict(s_, day=day, status="open") for s_ in signals if (s_["source"], s_["symbol"]) not in seen]
    mkt.trades.extend(new)
    changed = list(new)
    for t in mkt.trades:
        if t.get("status") == "closed":
            continue
        b = mkt.bars(t["symbol"].split(" ")[0])
        if b is None or b.empty:
            continue
        b = b[b.index.normalize() == b.index.normalize().max()]
        after = b[b.index.strftime("%H:%M") >= t["time"]]
        res = FN.simulate(t["side"], t["entry"], t["sl"], t["tp1"], t["tp2"], after)
        if not res:
            continue
        mg = FN.manage(t["side"], t["entry"], t["sl"], t["tp1"], t["tp2"], after)  # live state + managed exits
        live = {"ltp": mg.get("ltp"), "r_now": mg.get("r_now"), "best_r": mg.get("best_r"), "worst_r": mg.get("worst_r"),
                "advice": mg.get("advice"), "stop_now": mg.get("stop_now"), "as_of": mg.get("as_of"),
                "m_exit": (f"{mg['exit_how']} {mg['exit_at']}" if mg.get("closed") else None),
                "m_r": mg.get("exit_r"), "m_pct": mg.get("exit_pct")} if mg else {}
        done = final or res["outcome"] in ("stop", "TP2", "TP1 then stop at entry")
        upd = {**res, **live, "status": "closed" if done else "open", "last": float(b["Close"].iloc[-1])}
        if any(t.get(k) != v for k, v in upd.items()):
            t.update(upd)
            changed.append(t)
    _trade_file(day).write_text(json.dumps(mkt.trades, default=str))
    if changed:
        rows = [{"day": day, "time": t["time"], "source": t["source"], "symbol": t["symbol"], "side": int(t["side"]),
                 "entry": t["entry"], "sl": t["sl"], "tp1": t["tp1"], "tp2": t["tp2"], "risk_pct": t["risk_pct"],
                 "score": t.get("score"), "note": t.get("note"), "status": t.get("status"), "outcome": t.get("outcome"), "r": t.get("r"),
                 "pct": t.get("pct"), "ltp": t.get("ltp"), "r_now": t.get("r_now"), "best_r": t.get("best_r"),
                 "worst_r": t.get("worst_r"), "advice": t.get("advice"), "m_exit": t.get("m_exit"), "m_r": t.get("m_r"),
                 "m_pct": t.get("m_pct")} for t in {id(x): x for x in changed}.values()]
        try:
            _cloud().upsert_rows("trade_signals", rows, "day,source,symbol")
        except Exception as e:
            log(f"trade_signals: {e}")


# ---------------------------------------------------------------- closing picks (buy near the close, sell next day)

CLOSE_DIR = paths.DATA / "closing"
CLOSE_FROM, CLOSE_AT = "14:45", "15:15"   # live preview from 14:45; the picks are fixed with the data up to 15:15


def _close_file(day: str):
    CLOSE_DIR.mkdir(parents=True, exist_ok=True)
    return CLOSE_DIR / f"{day}.json"


def oi_last(day: str, mins: int = 30, cut: str = CLOSE_AT) -> dict:
    """{symbol: futures OI change % over the last `mins` minutes before `cut`, the price change of the future and
    the build-up} from the recorder's live quote files."""
    import index_levels as LV
    files = _quote_files(day)
    if not files:
        return {}
    try:
        df = pd.concat(pd.read_parquet(f, columns=["time", "kind", "symbol", "oi", "ltp"]) for f in files[-12:])
    except Exception:
        try:
            df = pd.concat(pd.read_parquet(f, columns=["time", "kind", "symbol", "oi"]) for f in files[-12:])
        except Exception:
            return {}
    f = df[df["kind"] == "future"].copy()
    if f.empty:
        return {}
    f["time"] = pd.to_datetime(f["time"])
    f = f[f["time"].dt.strftime("%H:%M") <= cut]
    agg = {"oi": ("oi", "sum")} | ({"px": ("ltp", "first")} if "ltp" in f else {})
    g = f.groupby(["symbol", "time"]).agg(**agg).reset_index().sort_values("time")
    out = {}
    for sym, x in g.groupby("symbol"):
        end = x["time"].iloc[-1]
        then = x[x["time"] <= end - pd.Timedelta(minutes=mins)]
        if then.empty or not then["oi"].iloc[-1]:
            continue
        d_oi = float(x["oi"].iloc[-1] - then["oi"].iloc[-1])
        d_px = float(x["px"].iloc[-1] - then["px"].iloc[-1]) if "px" in x else float("nan")
        out[sym] = {"oi_30_pct": round(d_oi / float(then["oi"].iloc[-1]) * 100, 2), "buildup_30": LV.buildup(d_px, d_oi)}
    return out


def chain_writing(index: str, day: str, mins: int = 30, cut: str = CLOSE_AT, strikes: int = 6) -> dict:
    """Option OI added in the last `mins` minutes near the money (nearest expiry, ±`strikes` strikes): calls written
    (ce) and puts written (pe), from the recorder's option-chain parts."""
    d = OUT.parent / "option_chain" / "parts" / day
    files = sorted(d.glob("*.parquet")) if d.exists() else []
    if not files:
        return {}
    try:
        c = pd.concat(pd.read_parquet(f) for f in files[-16:])
    except Exception:
        return {}
    c = c[c["index"] == index]
    if c.empty:
        return {}
    c["time"] = pd.to_datetime(c["time"])
    c = c[(c["time"].dt.strftime("%H:%M") <= cut) & (c["expiry"] == c["expiry"].min())]
    if c.empty:
        return {}
    end = c["time"].max()
    then_t = c[c["time"] <= end - pd.Timedelta(minutes=mins)]["time"]
    if then_t.empty:
        return {}
    a, b = c[c["time"] == end], c[c["time"] == then_t.max()]
    spot = float(a["spot"].iloc[0])
    ks = sorted(a["strike"].unique(), key=lambda k: abs(k - spot))[: 2 * strikes + 1]
    a, b = a[a["strike"].isin(ks)].set_index("strike"), b[b["strike"].isin(ks)].set_index("strike")
    ce = float((a["ce_oi"] - b["ce_oi"].reindex(a.index)).fillna(0).sum())
    pe = float((a["pe_oi"] - b["pe_oi"].reindex(a.index)).fillna(0).sum())
    big = lambda col: int((a[col] - b[col].reindex(a.index)).fillna(0).idxmax()) if len(a) else None
    return {"ce": ce, "pe": pe, "from": then_t.max().strftime("%H:%M"), "to": end.strftime("%H:%M"),
            "ce_top": big("ce_oi"), "pe_top": big("pe_oi"), "spot": spot}


def closing_read(mkt: "Market", now: datetime) -> dict:
    """The closing read: index picks (tested: close near the day's high) and stock picks (untested) with what the last
    15-30 minutes added: money, close location, volume, sector money, futures OI and option writing."""
    import closing as CL
    import index_funnel as IF
    import universe as U
    day = now.strftime("%Y-%m-%d")
    cut = min(now.strftime("%H:%M"), CLOSE_AT)
    stocks = mkt.stock_bars()
    idx = []
    for k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"):
        if k not in IF.INDEXES:
            continue
        try:
            w30 = chain_writing(k, day, cut=cut)
            r = CL.index_pick(IF.INDEXES[k], mkt.bars(k), stocks, mkt.weights.get(k, {}), mkt.fut.get(k), w30, cut)
        except Exception as e:
            log(f"closing {k}: {e}")
            r = None
        if r:
            r["key"] = k
            r["tested"] = bool(r["tested"] and k in ("NIFTY", "BANKNIFTY"))  # the 10-year test covers these two
            if k not in ("NIFTY", "BANKNIFTY") and r["side"]:
                r["verdict"] = "WATCH (close near the high, not tested on this index)"
            idx.append(r)
    oi30 = oi_last(day, cut=cut)
    sp = CL.stock_picks(stocks, U.FNO_SECTOR_OF, cut)
    picks = []
    for _, r in sp.iterrows():
        o = oi30.get(r["symbol"], {})
        d = {k: (None if isinstance(v, float) and not np.isfinite(v) else (round(v, 3) if isinstance(v, float) else v))
             for k, v in r.to_dict().items()}
        d["side"] = int(d["side"])
        d.update(o)
        if o.get("buildup_30"):
            d["why"] += f" · futures OI {o['oi_30_pct']:+.1f}% in 30 min ({o['buildup_30'].lower()})"
        picks.append(d)
    return {"day": day, "time": cut, "final": now.strftime("%H:%M") >= CLOSE_AT, "indices": idx, "stocks": picks}


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def record_closing(read: dict):
    """Stores the 15:15 picks once (<data>/closing/<day>.json and Supabase closing_picks), to be scored next day."""
    f = _close_file(read["day"])
    if f.exists():
        return
    read = _clean(read)
    f.write_text(json.dumps(read, default=str))
    rows = []
    for r in read["indices"]:
        rows.append({"day": read["day"], "time": r["time"], "kind": "index", "symbol": r["key"], "side": int(r["side"]),
                     "price": float(r["price"]), "score": None, "tested": bool(r["tested"]), "verdict": r["verdict"],
                     "reasons": ", ".join(r.get("confirmations") or []) or None,
                     "readings": {k: r.get(k) for k in ("clv", "ret_day", "ret_atr", "net_30", "breadth", "breadth_chg_30",
                                                         "oi_30_pct", "buildup_30", "writers_30")}})
    for r in read["stocks"]:
        rows.append({"day": read["day"], "time": r["time"], "kind": "stock", "symbol": r["symbol"], "side": int(r["side"]),
                     "price": float(r["price"]), "score": r.get("score"), "tested": False,
                     "verdict": "BUY (untested)" if r["side"] > 0 else "SELL (untested)", "reasons": r.get("why"),
                     "readings": {k: r.get(k) for k in ("sector", "clv", "ret_day", "ret_30", "net_30", "net_15", "flow_30",
                                                         "vol_30_x", "sec_net_30", "oi_30_pct", "buildup_30")}})
    try:
        if rows:
            _cloud().upsert_rows("closing_picks", _clean(rows), "day,kind,symbol")
    except Exception as e:
        log(f"closing_picks: {e}")
    log(f"closing picks recorded: {len(read['indices'])} indices, {len(read['stocks'])} stocks")


def score_closing(mkt: "Market", today: str, final: bool = False):
    """Every recorded day before today whose picks are not scored: the next trading day's open (gap) and close,
    after costs (0.02% index futures, 0.12% stocks). At the open only the gap is filled; the close at 15:35."""
    import closing as CL
    files = sorted(CLOSE_DIR.glob("*.json")) if CLOSE_DIR.exists() else []
    for f in files[-10:]:
        if f.stem >= today:
            continue
        try:
            rec = json.loads(f.read_text())
        except Exception:
            continue
        if rec.get("scored") == "close":
            continue
        rows, changed = [], False
        for kind, lst, key in (("index", rec.get("indices", []), "key"), ("stock", rec.get("stocks", []), "symbol")):
            cost = 0.02 if kind == "index" else 0.12
            for r in lst:
                b = mkt.bars(r[key])
                if b is None or b.empty:
                    continue
                nxt_day = sorted(d for d in set(b.index.normalize()) if d.strftime("%Y-%m-%d") > rec["day"])
                if not nxt_day:
                    continue
                nx = b[b.index.normalize() == nxt_day[0]]
                side = int(r.get("side") or 0) or 1   # a NO TRADE index read is scored as a long, to compare with the picks
                res = CL.score_next_day(float(r["price"]), side, nx)
                if not res:
                    continue
                res = {k: round(v, 3) for k, v in res.items()}
                res["open_pct"] = round(res["open_pct"] - cost, 3)
                res["close_pct"] = round(res["close_pct"] - cost, 3)
                res["next_day"] = nxt_day[0].strftime("%Y-%m-%d")
                if any(r.get(k) != v for k, v in res.items()):
                    r.update(res)
                    changed = True
                rows.append({"day": rec["day"], "kind": kind, "symbol": r[key], **res})
        if not rows:
            continue
        nxt_done = all(x["next_day"] < today for x in rows) or final
        rec["scored"] = "close" if nxt_done else "open"
        f.write_text(json.dumps(rec, default=str))
        if changed:
            try:
                _cloud().upsert_rows("closing_picks", _clean(rows), "day,kind,symbol")
            except Exception as e:
                log(f"closing_picks score: {e}")


# ---------------------------------------------------------------- Auto Trader (paper account, autotrader.py)

AUTO_DIR = paths.DATA / "autotrader"


def _auto_account() -> dict:
    import autotrader as AT
    try:
        return json.loads((AUTO_DIR / "account.json").read_text())
    except Exception:
        return {"start": AT.RULES["capital"], "equity": AT.RULES["capital"], "history": [], "rules": AT.RULES}


def auto_step(mkt: "Market", now: datetime, scanned: int, final: bool = False) -> dict:
    """The six agents on today's signal records: new signals decided once (filter, analyst, risk, paper order),
    positions marked to the managed results; <data>/autotrader/<day>.json and Supabase auto_trades."""
    import autotrader as AT
    AUTO_DIR.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y-%m-%d")
    f = AUTO_DIR / f"{day}.json"
    acc = _auto_account()
    try:
        book = json.loads(f.read_text())
    except Exception:
        prior = [h for h in acc.get("history", []) if h["day"] < day]
        book = {"day": day, "equity_start": prior[-1]["equity"] if prior else acc.get("start", AT.RULES["capital"]),
                "decisions": {}}
    book = AT.step(book, mkt.trades, float(book["equity_start"]), now.strftime("%H:%M"), scanned)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(book), default=str))
    os.replace(tmp, f)
    if final and book.get("decisions"):   # market holidays (no signal at all) don't enter the history
        acc = AT.close_day(acc, day, book)
        acc["rules"] = AT.RULES
        (AUTO_DIR / "account.json").write_text(json.dumps(_clean(acc), default=str))
    rows = []
    for d in book["decisions"].values():
        m, p = d.get("mark") or {}, d.get("pos") or {}
        rows.append({"day": day, "time": d.get("time"), "source": d["source"], "symbol": d["symbol"], "side": d["side"],
                     "decision": "TRADE" if d.get("ok") else "REJECTED", "stage": d.get("stage"), "reason": d.get("why"),
                     "qty": p.get("qty"), "entry": d.get("entry"), "sl": d.get("sl"), "tp1": d.get("tp1"), "tp2": d.get("tp2"),
                     "value": p.get("value"), "risk": p.get("risk"), "r": m.get("r"), "pnl": m.get("pnl"),
                     "status": ("closed" if m.get("closed") else "open") if p else None, "exit": m.get("exit")})
    try:
        if rows:
            _cloud().upsert_rows("auto_trades", _clean(rows), "day,source,symbol")
    except Exception as e:
        log(f"auto_trades: {e}")
    return {k: book.get(k) for k in ("funnel", "pnl", "equity", "equity_start", "updated")}


# ---------------------------------------------------------------- Bank Nifty EBP 1h, held overnight (paper, bn_ebp.py)

BN_EBP_FILE = OUT / "bn_ebp.json"


def bn_ebp_step(mkt: "Market", now: datetime) -> dict:
    """Bank Nifty 1h Engulfing Bar Play (paper): finished hourly candles from the 5-min bars; trades whose signal came
    after the paper start are kept with their state (waiting / open / closed) in <data>/bots/bn_ebp.json and every
    change goes to Supabase crypto_paper (setup = name + signal time)."""
    import bn_ebp as BE
    try:
        st = json.loads(BN_EBP_FILE.read_text())
    except Exception:
        st = {"since": now.strftime("%Y-%m-%d %H:%M"), "trades": []}
    h1 = BE.hourly(mkt.bars("BANKNIFTY"))
    if h1.empty:
        return st
    nowl = pd.Timestamp(now.replace(tzinfo=None))
    end = h1.index + pd.Timedelta(minutes=60)
    end = end.where(h1.index.strftime("%H:%M") != "15:15", h1.index + pd.Timedelta(minutes=15))
    h1 = h1[end <= nowl]                                   # finished hours only
    tr = BE.trades(h1, since=pd.Timestamp(st["since"]))
    old = {t_["signal_at"]: t_ for t_ in st.get("trades", [])}
    rows, new = [], []
    for t_ in tr:
        t_ = {k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in t_.items()}
        new.append(t_)
        if old.get(t_["signal_at"]) != t_ and t_.get("entry") is not None:
            sig = pd.Timestamp(t_["signal_at"])
            rows.append({"day": sig.strftime("%Y-%m-%d"), "setup": f"{BE.NAME} {sig:%H:%M}", "symbol": "BANKNIFTY",
                         "side": int(t_["side"]), "signal_at": sig.strftime("%H:%M"), "entry_at": str(t_.get("entry_at", ""))[5:16],
                         "entry_at_ist": str(t_.get("entry_at", ""))[5:16], "entry": t_["entry"], "sl": t_["sl"], "tp": t_["tp"],
                         "stop_pct": round(abs(t_["entry"] - t_["sl"]) / t_["entry"] * 100, 3), "result": t_["status"],
                         "exit_at": (str(t_["exit_at"])[5:16] if t_.get("exit_at") else None), "exit_px": t_.get("exit_px"),
                         "r": t_["r"], "pct": round(t_["pts"] / t_["entry"] * 100, 3)})
            if t_["signal_at"] not in old:
                log(f"BN EBP paper trade: {'BUY' if t_['side'] > 0 else 'SELL'} {t_['entry']} stop {t_['sl']} target {t_['tp']}")
    # closed trades that fell out of the 45-day window are kept from the file
    keep = [t_ for k_, t_ in old.items() if k_ not in {x_["signal_at"] for x_ in new}]
    st["trades"] = sorted(keep + new, key=lambda z: z["signal_at"])
    st["updated"] = now.strftime("%Y-%m-%d %H:%M")
    st["last_hour"] = str(h1.index[-1]) if len(h1) else None
    tmp = BN_EBP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(st), default=str))
    os.replace(tmp, BN_EBP_FILE)
    try:
        if rows:
            _cloud().upsert_rows("crypto_paper", _clean(rows), "day,setup")
    except Exception as e:
        log(f"bn ebp: {e}")
    return st


# ---------------------------------------------------------------- Breakout V3 and the V3 early pick (paper record)

V3_FILE = OUT / "v3_record.json"


def v3_step(mkt: "Market", now: datetime):
    """V3 (top 2 with the volume and Nifty filters, as on the Scanners page) and the V3 early pick, recorded with their
    result (stop 0.5 ATR, trail 1 ATR, exit 15:20): <data>/bots/v3_record.json and Supabase crypto_paper."""
    import scanners as SC
    if now.strftime("%H:%M") < "09:31":
        return
    nb = mkt.bars("NIFTY")
    session = SC.session_of(nb)
    if session is None or session.strftime("%Y-%m-%d") != now.strftime("%Y-%m-%d"):
        return
    S = SC.prepare(mkt.stock_bars(), session)
    if len(S) < 50:
        return
    N = SC.Stock("NIFTY 50", nb, session)
    v3, _ = SC.version3(S, N if N.ok else None)
    _, early = SC.v3_diagnose(S, N if N.ok else None)
    picks = [("V3 (top 2, filters)", r) for r in (v3.to_dict("records") if v3 is not None and not v3.empty else [])]
    if early:
        picks.append(("V3 early pick", early))
    day = now.strftime("%Y-%m-%d")
    try:
        rec = json.loads(V3_FILE.read_text())
    except Exception:
        rec = []
    have = {(x["day"], x["setup"]): x for x in rec}
    rows = []
    for setup, r in picks:
        side = 1 if str(r["Side"]).startswith("BUY") else -1
        entry, stop = float(r["Entry"]), float(r["Stop"])
        stop_pct = abs(entry - stop) / entry * 100 if entry else None
        pct = float(r["P&L %"]) - (0.12 if str(r["Status"]).startswith(("Closed", "Stopped", "Trailed")) else 0)
        row = {"day": day, "setup": f"{setup} {r['Stock']}", "symbol": r["Stock"], "side": side, "signal_at": r["Signal"],
               "entry_at": r["Signal"], "entry_at_ist": r["Signal"], "entry": round(entry, 2), "sl": round(stop, 2), "tp": None,
               "stop_pct": round(stop_pct, 3) if stop_pct else None, "result": r["Status"],
               "exit_at": r.get("Exit time") or None, "exit_px": round(float(r["Exit/LTP"]), 2),
               "r": round(pct / stop_pct, 2) if stop_pct else None, "pct": round(pct, 3)}
        if have.get((day, row["setup"])) != row:
            if (day, row["setup"]) not in have:
                log(f"{setup}: {r['Stock']} {r['Side']} {entry} stop {stop}")
            have[(day, row["setup"])] = row
            rows.append(row)
    if rows:
        V3_FILE.write_text(json.dumps(list(have.values()), default=str))
        try:
            _cloud().upsert_rows("crypto_paper", _clean(rows), "day,setup")
        except Exception as e:
            log(f"v3 record: {e}")


MOM_FILE = OUT / "momentum_record.json"


def momentum_step(mkt: "Market", now: datetime):
    """Grinder 10:30 and Ignition big mover paper trades (momentum_paper.py), with the result 60 / 120 minutes after
    entry: <data>/bots/momentum_record.json and Supabase crypto_paper."""
    import momentum_paper as MP
    import scanners as SC
    if now.strftime("%H:%M") < "09:36":
        return
    nb = mkt.bars("NIFTY")
    session = SC.session_of(nb)
    if session is None or session.strftime("%Y-%m-%d") != now.strftime("%Y-%m-%d"):
        return
    S = SC.prepare(mkt.stock_bars(), session)
    if len(S) < 50:
        return
    N = SC.Stock("NIFTY 50", nb, session)
    try:
        rec = json.loads(MOM_FILE.read_text())
    except Exception:
        rec = []
    have = {(x["day"], x["setup"]): x for x in rec}
    new = []
    for row in MP.rows(S, N if N.ok else None, now):
        old = have.get((row["day"], row["setup"]))
        if old is not None and old.get("result") != "open":
            continue                                   # finished trades stay as recorded
        if old != row:
            if old is None:
                log(f"{row['setup']}: {'BUY' if row['side'] > 0 else 'SELL'} {row['entry']} stop {row['sl']} target {row['tp']}")
            have[(row["day"], row["setup"])] = row
            new.append(row)
    if new:
        tmp = MOM_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(have.values()), default=str))
        os.replace(tmp, MOM_FILE)
        try:
            _cloud().upsert_rows("crypto_paper", _clean(new), "day,setup")
        except Exception as e:
            log(f"momentum record: {e}")


def plan_for(mkt: "Market", stock: str, side: int) -> dict | None:
    """Entry / stop / targets for a stock idea, the same plan as the Momentum Funnel (funnel.trade_plan)."""
    import funnel as FN
    if not side:
        return None
    a = FN.atr_step(mkt.bars(stock))
    if not a:
        return None
    return FN.trade_plan(int(side), float(a["price"]), a.get("atr14"), a.get("swing_low"), a.get("swing_high"))

# ---------------------------------------------------------------- loop


def cycle(mkt: Market) -> dict:
    import universe as U
    research = B.latest()
    T = B.build_table(mkt.stock_bars(), U.FNO_SECTOR_OF, keep_all_days=False)
    L = latest_rows(T)
    vix = mkt.bars("INDIAVIX")
    vix_chg = None
    if not vix.empty:
        dd = vix.index.normalize()
        if (dd < dd.max()).any():
            vix_chg = float(vix["Close"].iloc[-1] / vix[dd < dd.max()]["Close"].iloc[-1] - 1) * 100
    now = datetime.now(IST)
    idx, sec = index_bot(mkt, research), sector_bot(L)
    mov, unu = movers_bot(L), unusual_bot(L, T, research)
    oi = oi_today(now.strftime("%Y-%m-%d"))
    radar = radar_bot(L, mkt, oi) if not L.empty else {"name": "Radar", "rows": [], "events": []}
    update_feed(mkt, radar, now)
    try:
        fun = funnel_snapshot(mkt, now)
    except Exception as e:
        fun = {"error": str(e)[:200]}
    master = master_bot(L, idx, sec, mov, unu, vix_chg, radar, fun.get("top"))
    try:
        ixs = index_snapshot(mkt, now)
    except Exception as e:
        ixs = [{"error": str(e)[:200]}]
    # every master idea and radar event gets a plan; master ideas are recorded and scored like the other signals
    idea_sigs = []
    for i in master.get("ideas", []):
        sd = 1 if i["side"] == "BUY" else -1
        p = plan_for(mkt, i["stock"], sd)
        i["plan"] = p
        if p:
            idea_sigs.append({"source": f"Master bot ({i['status']})", "symbol": i["stock"], "side": sd,
                              "time": now.strftime("%H:%M"), **{k: p[k] for k in ("entry", "sl", "tp1", "tp2", "risk_pct")},
                              "score": None})
    for r in radar.get("events", [])[:20]:
        r["plan"] = plan_for(mkt, r["stock"], r["side"])
    try:
        track_trades(mkt, now.strftime("%Y-%m-%d"), collect_signals(mkt, fun) + idea_sigs)
    except Exception as e:
        log(f"trades: {e}")
    auto = None
    try:
        auto = auto_step(mkt, now, int(len(L)) + 5)
    except Exception as e:
        log(f"auto trader: {e}")
    try:
        bn_ebp_step(mkt, now)
    except Exception as e:
        log(f"bn ebp: {e}")
    try:
        v3_step(mkt, now)
    except Exception as e:
        log(f"v3: {e}")
    try:
        momentum_step(mkt, now)
    except Exception as e:
        log(f"momentum paper: {e}")
    try:
        import ironfly as IFY
        fly = IFY.step(now)
        if fly:
            _cloud().upsert_rows("crypto_paper", _clean([IFY.paper_row(fly)]), "day,setup")
    except Exception as e:
        log(f"iron fly: {e}")
    closing = None
    if now.strftime("%H:%M") >= CLOSE_FROM:
        try:
            closing = closing_read(mkt, now)
            if closing["final"]:
                record_closing(closing)
        except Exception as e:
            log(f"closing: {e}")
    last_bar = max((b.index.max() for b in mkt.today.values() if b is not None and not b.empty), default=None)
    health = {"stocks_live": int(len(L)), "last_candle": str(last_bar)[11:16] if last_bar is not None else None,
              "oi_from_recorder": int(len(oi)), "odds_days": mkt.odds.get("days"), "odds_built": mkt.odds.get("built"),
              "research_run": (research or {}).get("run_at"), "errors": STATUS["errors"][-3:]}
    return {"updated": now.isoformat(timespec="seconds"), "health": health, "feed": mkt.feed[:120],
            "bots": {"index": idx, "sector": sec, "movers": mov, "unusual": unu, "radar": radar, "master": master},
            "odds_check": _odds_check(), "funnel": {k: v for k, v in fun.items() if k != "plans"}, "indices": ixs,
            "trades": mkt.trades, "momentum": mkt.momentum, "closing": closing, "auto": auto}


def save(state: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    os.replace(tmp, OUT / "state.json")


def research_due(now: datetime) -> bool:
    if market_open(now):
        return False
    if REQUEST.exists():
        return True
    last = (B.latest() or {}).get("run_at", "")[:10]
    return now.strftime("%H:%M") >= RESEARCH_AFTER and last != now.strftime("%Y-%m-%d")


def run_research():
    REQUEST.unlink(missing_ok=True)
    log("Setup Finder research: starting")
    r = subprocess.run([sys.executable, str(paths.HERE / "bot.py")], cwd=str(paths.HERE), timeout=4 * 3600)
    log(f"Setup Finder research: finished (exit {r.returncode})")
    try:  # then the momentum study on the same cached year of candles
        m = subprocess.run([sys.executable, str(paths.HERE / "momentum_study.py")], cwd=str(paths.HERE), timeout=3 * 3600)
        log(f"momentum study: finished (exit {m.returncode})")
        x = subprocess.run([sys.executable, str(paths.HERE / "index_funnel.py")], cwd=str(paths.HERE), timeout=3600)
        log(f"index funnel backtest: finished (exit {x.returncode})")
        nz = subprocess.run([sys.executable, str(paths.HERE / "noise_research.py")], cwd=str(paths.HERE), timeout=3600)
        log(f"noise band research: finished (exit {nz.returncode})")
        cs = subprocess.run([sys.executable, str(paths.HERE / "candle_study.py")], cwd=str(paths.HERE), timeout=3 * 3600)
        log(f"candle study (6 months, 3 / 5 / 15 min): finished (exit {cs.returncode})")
    except Exception as e:
        log(f"momentum study: {e}")
    if r.returncode != 0 and not (B.BOT_DIR / "latest.json").exists():
        B.BOT_DIR.mkdir(parents=True, exist_ok=True)
        (B.BOT_DIR / "latest.json").write_text(json.dumps({"run_at": datetime.now(IST).isoformat(timespec="seconds"),
                                                           "error": "research run failed"}))


def main():
    import dhan as D
    STATUS["started"] = datetime.now(IST).isoformat(timespec="seconds")
    cfg = D.load_config()
    while not D.configured(cfg):
        log("waiting for Dhan (no client_id / access_token)")
        time.sleep(60)
        cfg = D.load_config()
    mkt = Market(cfg)
    mkt.load()
    day, seen, scored, last, logged, opened = None, {}, False, 0.0, set(), False
    last_slot = None
    while True:
        now = datetime.now(IST)
        try:
            if now.strftime("%Y-%m-%d") != day:
                day, seen, scored, logged, opened = now.strftime("%Y-%m-%d"), {}, False, set(), False
                mkt.today, mkt.feed, mkt.ev_seen = {}, [], set()
                try:  # a restart in the day keeps the day's trades
                    mkt.trades = json.loads(_trade_file(day).read_text())
                except Exception:
                    mkt.trades = []
                if mkt.hist:
                    mkt.load()   # yesterday joins the history
            import candles as C
            mins = (now.hour * 60 + now.minute) - (9 * 60 + 15)
            slot = mins // C.TF                          # run right after each candle closes (+10 s for Dhan to settle)
            due = slot != last_slot and (mins % C.TF) * 60 + now.second >= 10
            if market_open(now) and (due or time.time() - last >= EVERY):
                last, last_slot = time.time(), slot
                mkt.cfg = D.load_config()   # the token the app or recorder renewed
                mkt.refresh()
                state = cycle(mkt)
                save(state)
                log_ideas(day, state["bots"]["master"]["ideas"], seen)
                log_radar(day, mkt.feed, logged)
                if now.strftime("%H:%M") >= "09:20" and not opened:
                    opened = True
                    try:
                        score_closing(mkt, day)
                    except Exception as e:
                        log(f"closing score: {e}")
            if not market_open(now) and now.weekday() < 5 and now.strftime("%H:%M") >= "15:35" and not scored:
                scored = True
                if seen:
                    log(f"scored {len(score_ideas(day, mkt, seen))} ideas")
                if mkt.feed:
                    log(f"scored {len(score_radar(day, mkt, mkt.feed))} radar events")
                if mkt.trades:
                    track_trades(mkt, day, [], final=True)
                    log(f"closed {len(mkt.trades)} signals")
                try:
                    a_ = auto_step(mkt, now, 0, final=True)
                    log(f"auto trader day closed: P&L {a_.get('pnl')}")
                except Exception as e:
                    log(f"auto trader close: {e}")
                try:
                    score_closing(mkt, (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), final=True)
                except Exception as e:
                    log(f"closing score: {e}")
            if research_due(now):
                run_research()
                mkt.odds = load_odds(mkt.syms, force=True)   # tonight's history joins the odds
        except Exception as e:
            STATUS["errors"] = (STATUS["errors"] + [f"{now:%d %b %H:%M} {e}"[:200]])[-10:]
            log(f"error: {e}")
            time.sleep(30)
        time.sleep(5)


if __name__ == "__main__":
    main()
