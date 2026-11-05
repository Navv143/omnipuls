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

    def load(self):
        stocks, indices = B.load_history(self.cfg, days=LIVE_DAYS if not B.CACHE.exists() else B.HISTORY_DAYS,
                                         symbols=self.syms + [("INDIAVIX", "IDX_I", 21, "INDEX")])
        cut = pd.Timestamp.now() - pd.Timedelta(days=LIVE_DAYS)
        self.hist = {k: v[v.index >= cut] for k, v in {**stocks, **indices}.items()}
        try:
            import indices as IX
            self.weights = {k: d.get("w", {}) for k, d in IX.load().items()}
        except Exception:
            self.weights = {}
        log(f"history: {len(self.hist)} symbols")
        self.odds = load_odds(self.syms)
        self.oi_avg = oi_history()

    def refresh(self):
        import dhan as D
        for sym, seg, sid, ins in self.syms + [("INDIAVIX", "IDX_I", 21, "INDEX")]:
            try:
                d = B.clean(D.intraday(seg, sid, ins, 5, 1, self.cfg))
            except D.DhanError as e:
                if e.code == "NETWORK":
                    raise
                continue
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
               radar: dict | None = None) -> dict:
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
    for r in (radar or {}).get("events", []):
        o = r.get("odds") or {}
        if r["side"] and o.get("n", 0) >= 40 and o.get("win", 0) >= 55 and o.get("edge", 0) >= 3:
            c = cands.setdefault((r["stock"], r["side"]), {"source": "Radar", "rule": False})
            c["odds"] = o
            if c["source"] != "Tested rule (Setup Finder)":
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
    master = master_bot(L, idx, sec, mov, unu, vix_chg, radar)
    last_bar = max((b.index.max() for b in mkt.today.values() if b is not None and not b.empty), default=None)
    health = {"stocks_live": int(len(L)), "last_candle": str(last_bar)[11:16] if last_bar is not None else None,
              "oi_from_recorder": int(len(oi)), "odds_days": mkt.odds.get("days"), "odds_built": mkt.odds.get("built"),
              "research_run": (research or {}).get("run_at"), "errors": STATUS["errors"][-3:]}
    return {"updated": now.isoformat(timespec="seconds"), "health": health, "feed": mkt.feed[:120],
            "bots": {"index": idx, "sector": sec, "movers": mov, "unusual": unu, "radar": radar, "master": master},
            "odds_check": _odds_check()}


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
    day, seen, scored, last, logged = None, {}, False, 0.0, set()
    while True:
        now = datetime.now(IST)
        try:
            if now.strftime("%Y-%m-%d") != day:
                day, seen, scored, logged = now.strftime("%Y-%m-%d"), {}, False, set()
                mkt.today, mkt.feed, mkt.ev_seen = {}, [], set()
                if mkt.hist:
                    mkt.load()   # yesterday joins the history
            if market_open(now) and time.time() - last >= EVERY:
                last = time.time()
                mkt.cfg = D.load_config()   # the token the app or recorder renewed
                mkt.refresh()
                state = cycle(mkt)
                save(state)
                log_ideas(day, state["bots"]["master"]["ideas"], seen)
                log_radar(day, mkt.feed, logged)
            if not market_open(now) and now.weekday() < 5 and now.strftime("%H:%M") >= "15:35" and not scored:
                scored = True
                if seen:
                    log(f"scored {len(score_ideas(day, mkt, seen))} ideas")
                if mkt.feed:
                    log(f"scored {len(score_radar(day, mkt, mkt.feed))} radar events")
            if research_due(now):
                run_research()
                mkt.odds = load_odds(mkt.syms, force=True)   # tonight's history joins the odds
        except Exception as e:
            STATUS["errors"] = (STATUS["errors"] + [f"{now:%d %b %H:%M} {e}"[:200]])[-10:]
            log(f"error: {e}")
            time.sleep(30)
        time.sleep(15)


if __name__ == "__main__":
    main()
