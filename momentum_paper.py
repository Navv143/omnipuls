"""Paper setups from the grinders / momentum-ignition studies (research/grinders_study.py, research/grinder_exits.py,
research/ignition_study.py). Both are recorded with their result, plus the result 60 and 120 minutes after entry, so
the live record can show whether the move comes fast (momentum) or slowly (grind).

- "Grinder 10:30": flat open (|gap| <= 0.3 ATR); at 10:30 already >= 0.4 ATR from yesterday's close, >= 0.8% ahead of
  Nifty since the open, on the right side of VWAP on >= 80% of candles, pullback <= 20% of the move, its sector moving
  the same way. Entry at the 10:30 candle's open, stop at the day's opposite extreme, target 1.5 ATR, exit 15:20.
  Up to 10 a day, highest volume first. Tested (45 days, in-sample): +0.18% a trade, halves +0.14 / +0.20; slow - only
  14% reach +0.5 ATR within 2 hours.
- "Aligned 10:00" (research/divergence_study.py): at 10:00 the stock, its sector (the other stocks of the sector) and
  Nifty (vs yesterday's close) all point the same way, the stock already >= 0.5 ATR from yesterday's close on >= 2x its
  usual volume for the time. Entry at the 10:00 candle's open, stop 0.75 ATR, target 1.5 ATR, exit 15:20; up to 10 a
  day, biggest move first. Tested (32 days): +0.16% a trade, halves +0.15 / +0.17, 55% win.
- "Nifty midday fade" (research/nifty_leaders_study.py): Nifty closes a 5-min candle > 0.1% above its last hour's high
  between 11:00 and 14:00 (first time that day); short Nifty at the next open, exit after 60 minutes. Only 11 cases so
  far (Nifty fell back in 9): recorded to build the sample.
- "Ignition big mover": a stock already >= 1.5 ATR from yesterday's close whose first volume-burst candle of the day
  (>= 1.5x usual volume for the time, range >= 0.15 ATR, close in the outer 30%) breaks the day's high (low), 09:30-13:55.
  Entry at the next candle's open, stop 0.4 ATR, target 1.5 ATR, exit 15:20. Tested: +0.13% a trade (172 trades,
  halves +0.12 / +0.14); 24% reach +0.5 ATR within an hour.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

COST = 0.12
EXIT_AT = "15:20"
GRINDER = "Grinder 10:30"
IGNITION = "Ignition big mover"
ALIGNED = "Aligned 10:00"
FADE = "Nifty midday fade"
TESTED = {GRINDER: ("+0.18% a trade", "56%"), IGNITION: ("+0.13% a trade", "40%"), ALIGNED: ("+0.16% a trade", "55%"),
          FADE: ("+0.09% a trade (11 days)", "82%")}


def _hm(idx) -> np.ndarray:
    return np.asarray(idx.strftime("%H:%M"))


def track(today: pd.DataFrame, entry_ts, side: int, entry: float, sl: float, tp: float, now: datetime) -> dict:
    """Follow the trade from the entry candle (inclusive): stop first, then target, exit at the 15:20 candle's open."""
    bars = today[today.index >= entry_ts]
    hm = _hm(bars.index)
    status, px, t_exit, path = "open", None, None, []
    for (ts, b), h in zip(bars.iterrows(), hm):
        if h >= EXIT_AT:
            status, px, t_exit = "time", float(b["Open"]), ts
            break
        if (side > 0 and b["Low"] <= sl) or (side < 0 and b["High"] >= sl):
            status, px, t_exit = "stop", float(min(b["Open"], sl) if side > 0 else max(b["Open"], sl)), ts
            break
        if (side > 0 and b["High"] >= tp) or (side < 0 and b["Low"] <= tp):
            status, px, t_exit = "target", float(max(b["Open"], tp) if side > 0 else min(b["Open"], tp)), ts
            break
        path.append((ts + timedelta(minutes=5), float(b["Close"])))
    if status == "open" and len(bars) and (bars.index[-1].date() < now.date() or now.strftime("%H:%M") >= EXIT_AT):
        status, px, t_exit = "time", float(bars["Close"].iloc[-1]), bars.index[-1]
    last = px if px is not None else (float(bars["Close"].iloc[-1]) if len(bars) else entry)
    pct = side * (last / entry - 1) * 100 - (COST if status != "open" else 0)

    def at(mins: int):
        cut = pd.Timestamp(entry_ts) + timedelta(minutes=mins)
        if t_exit is not None and t_exit < cut:
            return round(pct, 3)                     # already out: the trade's result
        if pd.Timestamp(now.replace(tzinfo=None)) < cut and status == "open":
            return None                              # not there yet
        c = [p for t, p in path if t <= cut]
        return round(side * (c[-1] / entry - 1) * 100 - COST, 3) if c else None

    return {"result": status, "exit_at": t_exit.strftime("%H:%M") if t_exit is not None else None,
            "exit_px": round(last, 2), "pct": round(pct, 3), "pct_60": at(60), "pct_120": at(120)}


def grinder_picks(S: dict, nifty, T: str = "10:30", top: int = 10) -> list[dict]:
    if nifty is None or not getattr(nifty, "ok", False):
        return []
    nt = nifty.today
    na = nt[_hm(nt.index) < T]
    if not len(na) or not (_hm(nt.index) >= T).any():
        return []
    n_ret = (na["Close"].iloc[-1] / nt["Open"].iloc[0] - 1) * 100
    cand = []
    for sym, s in S.items():
        A, P, O = s.atr, s.prev_close, s.open
        if not A or A <= 0 or abs((O - P) / A) > 0.3:
            continue
        hm = _hm(s.today.index)
        a, post = s.today[hm < T], s.today[hm >= T]
        if len(a) < 3 or post.empty:
            continue
        c = float(a["Close"].iloc[-1])
        mv = (c - P) / A
        sd = 1 if mv >= 0 else -1
        tp_ = (a["High"] + a["Low"] + a["Close"]) / 3
        vw = (tp_ * a["Volume"]).cumsum() / a["Volume"].replace(0, np.nan).cumsum()
        ext = a["High"].max() if sd > 0 else a["Low"].min()
        usual = s.cum_avg(hm[hm < T][-1], n=20)
        cand.append({"sym": sym, "sector": _sector(sym), "mv": mv, "sd": sd,
                     "rel": sd * ((c / O - 1) * 100 - n_ret), "hold": float(((a["Close"] - vw) * sd > 0).mean()),
                     "pull": abs(ext - c) / max(abs(ext - O), 1e-9),
                     "rvol": float(a["Volume"].sum() / usual) if usual and usual > 0 else 0.0,
                     "stock": s, "entry_ts": post.index[0], "entry": float(post["Open"].iloc[0]),
                     "opp": float(a["Low"].min() if sd > 0 else a["High"].max())})
    if not cand:
        return []
    df = pd.DataFrame(cand)
    df["sec"] = df.groupby("sector")["mv"].transform("mean") * df["sd"]
    ok = df[(df["mv"] * df["sd"] >= 0.4) & (df["rel"] >= 0.8) & (df["hold"] >= 0.8) & (df["pull"] <= 0.2) & (df["sec"] > 0)]
    out = []
    for r in ok.sort_values("rvol", ascending=False).head(top).itertuples(index=False):
        A = r.stock.atr
        out.append({"setup": GRINDER, "sym": r.sym, "side": int(r.sd), "signal_at": T, "entry_ts": r.entry_ts,
                    "entry": r.entry, "sl": r.opp, "tp": r.entry + r.sd * 1.5 * A, "stock": r.stock,
                    "why": f"{r.mv * r.sd:.2f} ATR, {r.rel:+.2f}% vs Nifty, VWAP {r.hold * 100:.0f}%, vol {r.rvol:.1f}x"})
    return out


def ignition_picks(S: dict) -> list[dict]:
    out = []
    for sym, s in S.items():
        A, P = s.atr, s.prev_close
        if not A or A <= 0:
            continue
        d = s.today
        if len(d) < 4:
            continue
        hm = _hm(d.index)
        hod, lod = d["High"].cummax().shift(), d["Low"].cummin().shift()
        rng = d["High"] - d["Low"]
        clv = (d["Close"] - d["Low"]) / rng.replace(0, np.nan)
        usual = np.array([s.slot_avg(h, n=20) for h in hm], dtype=float)
        vx = d["Volume"].to_numpy() / np.where(usual > 0, usual, np.nan)
        base = (hm >= "09:30") & (hm <= "13:55") & (vx >= 1.5) & (rng.to_numpy() >= 0.15 * A)
        for side, m in ((1, (d["Close"] > hod) & (clv >= 0.7)), (-1, (d["Close"] < lod) & (clv <= 0.3))):
            idx = np.flatnonzero(base & m.to_numpy())
            if not len(idx) or idx[0] + 1 >= len(d):
                continue
            i = idx[0]                                   # the first ignition of the day on this side
            if side * (d["Close"].iloc[i] - P) / A < 1.5:
                continue                                 # only for stocks already 1.5 ATR on the move
            e = float(d["Open"].iloc[i + 1])
            out.append({"setup": IGNITION, "sym": sym, "side": side, "signal_at": hm[i], "entry_ts": d.index[i + 1],
                        "entry": e, "sl": e - side * 0.4 * A, "tp": e + side * 1.5 * A, "stock": s,
                        "why": f"{side * (d['Close'].iloc[i] - P) / A:.2f} ATR on the day, volume {vx[i]:.1f}x"})
    return out


def _sector(sym: str) -> str:
    try:
        import universe as U
        return U.FNO_SECTOR_OF.get(sym, "Other")
    except Exception:
        return "Other"


def aligned_picks(S: dict, nifty, T: str = "10:00", top: int = 10) -> list[dict]:
    if nifty is None or not getattr(nifty, "ok", False):
        return []
    na = nifty.today[_hm(nifty.today.index) < T]
    if not len(na) or not (_hm(nifty.today.index) >= T).any():
        return []
    n_dir = 1 if na["Close"].iloc[-1] >= nifty.prev_close else -1
    cand = []
    for sym, s in S.items():
        A, P = s.atr, s.prev_close
        if not A or A <= 0:
            continue
        hm = _hm(s.today.index)
        a, post = s.today[hm < T], s.today[hm >= T]
        if not len(a) or post.empty:
            continue
        usual = s.cum_avg(hm[hm < T][-1], n=20)
        cand.append({"sym": sym, "sector": _sector(sym), "mv": (float(a["Close"].iloc[-1]) - P) / A,
                     "rvol": float(a["Volume"].sum() / usual) if usual and usual > 0 else 0.0, "stock": s,
                     "entry_ts": post.index[0], "entry": float(post["Open"].iloc[0])})
    if not cand:
        return []
    df = pd.DataFrame(cand)
    g = df.groupby("sector")["mv"]
    df["sec_ex"] = (g.transform("sum") - df["mv"]) / (g.transform("size") - 1).replace(0, np.nan)
    df["sd"] = np.where(df["mv"] >= 0, 1, -1)
    ok = df[(df["mv"].abs() >= 0.5) & (df["sd"] == n_dir) & (np.sign(df["sec_ex"]) == n_dir) & (df["rvol"] >= 2)]
    out = []
    for r in ok.reindex(ok["mv"].abs().sort_values(ascending=False).index).head(top).itertuples(index=False):
        A = r.stock.atr
        out.append({"setup": ALIGNED, "sym": r.sym, "side": int(r.sd), "signal_at": T, "entry_ts": r.entry_ts,
                    "entry": r.entry, "sl": r.entry - r.sd * 0.75 * A, "tp": r.entry + r.sd * 1.5 * A, "stock": r.stock,
                    "why": f"{abs(r.mv):.2f} ATR, sector {r.sec_ex * r.sd:+.2f} ATR, vol {r.rvol:.1f}x, with Nifty"})
    return out


def nifty_fade(nifty, now: datetime, look: int = 12, min_brk: float = 0.1) -> dict | None:
    """Short Nifty after its first midday (11:00-14:00) close > min_brk % above the last hour's high; exit 60 min later."""
    if nifty is None or not getattr(nifty, "ok", False):
        return None
    g = nifty.today
    hm = _hm(g.index)
    hi = g["High"].rolling(look).max().shift()
    brk = (g["Close"] - hi) / g["Close"] * 100
    m = np.flatnonzero(((brk > min_brk) & (hm >= "11:00") & (hm <= "14:00")).to_numpy())
    if not len(m) or m[0] + 1 >= len(g):
        return None
    i = m[0]
    e, ets = float(g["Open"].iloc[i + 1]), g.index[i + 1]
    end = ets + timedelta(minutes=60)
    post = g[(g.index >= ets) & (g.index < end)]
    done = (g.index >= end).any() or now.strftime("%H:%M") >= EXIT_AT
    last = float(g[g.index >= end]["Open"].iloc[0]) if (g.index >= end).any() else float(post["Close"].iloc[-1])
    pct = -(last / e - 1) * 100 - (0.03 if done else 0)
    return {"day": now.strftime("%Y-%m-%d"), "setup": f"{FADE} NIFTY", "symbol": "NIFTY", "side": -1, "signal_at": hm[i],
            "entry_at": ets.strftime("%H:%M"), "entry_at_ist": ets.strftime("%H:%M"), "entry": round(e, 2), "sl": None,
            "tp": None, "stop_pct": None, "r": None, "result": "time" if done else "open",
            "exit_at": end.strftime("%H:%M") if done else None, "exit_px": round(last, 2), "pct": round(pct, 3),
            "pct_60": round(pct, 3) if done else None, "pct_120": None}


def rows(S: dict, nifty, now: datetime) -> list[dict]:
    day = now.strftime("%Y-%m-%d")
    picks = ignition_picks(S)
    if now.strftime("%H:%M") >= "10:00":
        picks += aligned_picks(S, nifty)
    if now.strftime("%H:%M") >= "10:30":
        picks += grinder_picks(S, nifty)
    out = []
    for p in picks:
        res = track(p["stock"].today, p["entry_ts"], p["side"], p["entry"], p["sl"], p["tp"], now)
        stop_pct = abs(p["entry"] - p["sl"]) / p["entry"] * 100
        et = pd.Timestamp(p["entry_ts"]).strftime("%H:%M")
        out.append({"day": day, "setup": f"{p['setup']} {p['sym']}", "symbol": p["sym"], "side": p["side"],
                    "signal_at": p["signal_at"], "entry_at": et, "entry_at_ist": et, "entry": round(p["entry"], 2),
                    "sl": round(p["sl"], 2), "tp": round(p["tp"], 2), "stop_pct": round(stop_pct, 3),
                    "r": round(res["pct"] / stop_pct, 2) if stop_pct else None, **res})
    f = nifty_fade(nifty, now)
    if f:
        out.append(f)
    return out
