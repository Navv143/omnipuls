"""Index levels and OI for Nifty / Bank Nifty (pure functions, no Streamlit).

- Pivot points (classic, from yesterday's high / low / close) and the CPR (central pivot range).
- Fixed-range volume profile from the index future's 5-minute volume: POC (most traded price), value area high / low
  (70% of the volume) for yesterday, today and the last 5 sessions.
- OI: the future's OI change today and in the last 15 minutes with the build-up (price up + OI up = long build-up,
  up + OI down = short covering, down + OI up = short build-up, down + OI down = long unwinding); the option chain's
  support (most puts written) and resistance (most calls written), today's biggest put / call writing, PCR, max pain.
- OI step for the index funnel: no OI reading against the move and at least one with it.
- One ladder of every level with the nearest support / resistance and a stop / target suggestion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _clean(df):
    if df is None or df.empty:
        return pd.DataFrame()
    d = df[~df.index.duplicated(keep="last")].sort_index()
    m = d.index.hour * 60 + d.index.minute
    return d[(m >= 555) & (m <= 930)]


def sessions(df) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    d = _clean(df)
    if d.empty:
        return d, d, []
    day = d.index.normalize()
    days = sorted(set(day))
    return d[day == days[-1]], (d[day == days[-2]] if len(days) > 1 else pd.DataFrame()), days

# ---------------------------------------------------------------- pivots


def pivots(prev: pd.DataFrame) -> dict:
    if prev is None or prev.empty:
        return {}
    h, l, c = float(prev["High"].max()), float(prev["Low"].min()), float(prev["Close"].iloc[-1])
    p = (h + l + c) / 3
    bc = (h + l) / 2
    tc = 2 * p - bc
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l), "R3": h + 2 * (p - l),
            "S3": l - 2 * (h - p), "CPR top": max(bc, tc), "CPR bottom": min(bc, tc), "PDH": h, "PDL": l, "PDC": c,
            "cpr_width_pct": abs(tc - bc) / p * 100}

# ---------------------------------------------------------------- volume profile


def volume_profile(bars: pd.DataFrame, bins: int = 48, va: float = 0.70) -> dict:
    """Each candle's volume spread evenly over its high-low range; POC and the value area around it."""
    if bars is None or bars.empty or "Volume" not in bars or bars["Volume"].sum() <= 0:
        return {}
    lo, hi = float(bars["Low"].min()), float(bars["High"].max())
    if hi <= lo:
        return {}
    edges = np.linspace(lo, hi, bins + 1)
    vol = np.zeros(bins)
    for l_, h_, v in zip(bars["Low"].to_numpy(), bars["High"].to_numpy(), bars["Volume"].to_numpy()):
        if not v or not np.isfinite(v):
            continue
        a = max(int(np.searchsorted(edges, l_, side="right")) - 1, 0)
        b = min(int(np.searchsorted(edges, h_, side="left")), bins)
        b = max(b, a + 1)
        vol[a:b] += v / (b - a)
    mid = (edges[:-1] + edges[1:]) / 2
    poc_i = int(vol.argmax())
    tot, inc, lo_i, hi_i = vol.sum(), vol[poc_i], poc_i, poc_i
    while inc < va * tot and (lo_i > 0 or hi_i < bins - 1):
        up = vol[hi_i + 1] if hi_i < bins - 1 else -1
        dn = vol[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1
            inc += vol[hi_i]
        else:
            lo_i -= 1
            inc += vol[lo_i]
    return {"POC": float(mid[poc_i]), "VAH": float(edges[hi_i + 1]), "VAL": float(edges[lo_i]),
            "hist": [(round(float(m), 2), float(v)) for m, v in zip(mid, vol)]}

# ---------------------------------------------------------------- OI


def buildup(price_chg: float, oi_chg: float) -> str:
    if not np.isfinite(price_chg) or not np.isfinite(oi_chg) or oi_chg == 0:
        return ""
    if price_chg >= 0:
        return "Long build-up" if oi_chg > 0 else "Short covering"
    return "Short build-up" if oi_chg > 0 else "Long unwinding"


def futures_oi(fut: pd.DataFrame, recent: int = 3) -> dict:
    """The future's OI today vs yesterday's close and over the last `recent` candles, with the build-ups, and the
    build-up of every candle (for the timeline)."""
    today, prev, _ = sessions(fut)
    if today.empty or "OI" not in today or today["OI"].fillna(0).sum() == 0:
        return {}
    oi = today["OI"].replace(0, np.nan).ffill()
    oi0 = float(prev["OI"].replace(0, np.nan).dropna().iloc[-1]) if not prev.empty and prev["OI"].notna().any() else float(oi.dropna().iloc[0])
    pc = float(prev["Close"].iloc[-1]) if not prev.empty else float(today["Open"].iloc[0])
    last, oi_now = float(today["Close"].iloc[-1]), float(oi.iloc[-1])
    j = max(len(today) - 1 - recent, 0)
    oi_b, px_b = float(oi.iloc[j]), float(today["Close"].iloc[j])
    per = pd.DataFrame({"t": today.index.strftime("%H:%M"), "close": today["Close"].to_numpy(),
                        "oi": oi.to_numpy(), "d_oi": oi.diff().fillna(oi.iloc[0] - oi0).to_numpy(),
                        "d_px": today["Close"].diff().fillna(today["Close"].iloc[0] - pc).to_numpy()})
    per["buildup"] = [buildup(p, o) for p, o in zip(per["d_px"], per["d_oi"])]
    return {"oi": oi_now, "oi_chg_pct": (oi_now / oi0 - 1) * 100 if oi0 else np.nan,
            "price_chg_pct": (last / pc - 1) * 100, "buildup_day": buildup(last - pc, oi_now - oi0),
            "oi_15m_pct": (oi_now / oi_b - 1) * 100 if oi_b else np.nan, "buildup_15m": buildup(last - px_b, oi_now - oi_b),
            "per": per}


def chain_oi(ch: pd.DataFrame, spot: float, max_pain: float | None = None) -> dict:
    """Support / resistance from where options are written, today's biggest writing, PCR."""
    if ch is None or ch.empty or not spot:
        return {}
    c = ch.copy()
    for k in ("CE OI", "PE OI", "CE Chg OI", "PE Chg OI"):
        c[k] = pd.to_numeric(c.get(k), errors="coerce").fillna(0)
    above, below = c[c["Strike"] >= spot], c[c["Strike"] <= spot]
    res = above.nlargest(2, "CE OI")["Strike"].tolist() if not above.empty else []
    sup = below.nlargest(2, "PE OI")["Strike"].tolist() if not below.empty else []
    ce_add = c.loc[c["CE Chg OI"].idxmax()] if c["CE Chg OI"].max() > 0 else None
    pe_add = c.loc[c["PE Chg OI"].idxmax()] if c["PE Chg OI"].max() > 0 else None
    near = c[(c["Strike"] - spot).abs() <= (c["Strike"].diff().median() or 50) * 10]
    ce_chg, pe_chg = float(near["CE Chg OI"].sum()), float(near["PE Chg OI"].sum())
    pcr = float(c["PE OI"].sum() / c["CE OI"].sum()) if c["CE OI"].sum() else np.nan
    writers = 1 if pe_chg > 1.2 * max(ce_chg, 0) and pe_chg > 0 else -1 if ce_chg > 1.2 * max(pe_chg, 0) and ce_chg > 0 else 0
    return {"resistance": res, "support": sup, "pcr": pcr, "max_pain": max_pain,
            "ce_add": float(ce_add["Strike"]) if ce_add is not None else None,
            "pe_add": float(pe_add["Strike"]) if pe_add is not None else None,
            "ce_chg_near": ce_chg, "pe_chg_near": pe_chg, "writers": writers,
            "ce_oi": float(c["CE OI"].sum()), "pe_oi": float(c["PE OI"].sum()),
            "near": near[["Strike", "CE OI", "PE OI", "CE Chg OI", "PE Chg OI"]]}


def oi_step(side: int, fut: dict, chain: dict) -> dict:
    """OI step: futures build-up and option writers. Passes when none is against the move and at least one is with it."""
    if not side:
        return {"pass": False, "with": [], "against": [], "text": "no move yet"}
    with_, against = [], []
    b = fut.get("buildup_day", "")
    if b:
        good = ("Long build-up", "Short covering") if side > 0 else ("Short build-up", "Long unwinding")
        (with_ if b in good else against).append(f"futures {b.lower()} ({fut.get('oi_chg_pct', 0):+.1f}% OI)")
    w = chain.get("writers", 0)
    if w:
        txt = "put writers adding (support)" if w > 0 else "call writers adding (cap)"
        (with_ if w == side else against).append(txt)
    return {"pass": bool(with_) and not against, "with": with_, "against": against,
            "text": "; ".join(with_ + [f"against: {x}" for x in against]) or "OI neutral"}

# ---------------------------------------------------------------- ladder


def ladder(spot: float, piv: dict, vps: dict, chain: dict, side: int = 0, min_gap_pct: float = 0.15) -> dict:
    """Every level in one sorted list, the nearest support / resistance and a stop / target for the side."""
    lv = []
    for k in ("R3", "R2", "R1", "P", "S1", "S2", "S3", "CPR top", "CPR bottom", "PDH", "PDL"):
        if piv.get(k):
            lv.append({"price": piv[k], "name": k if k not in ("PDH", "PDL") else {"PDH": "Yesterday high", "PDL": "Yesterday low"}[k],
                       "kind": "pivot" if k not in ("PDH", "PDL") else "day"})
    for label, vp in vps.items():
        for k in ("POC", "VAH", "VAL"):
            if vp.get(k):
                lv.append({"price": vp[k], "name": f"{k} ({label})", "kind": "volume"})
    for i, s in enumerate(chain.get("support") or []):
        lv.append({"price": s, "name": f"Put OI support{'' if i == 0 else ' 2'}", "kind": "oi"})
    for i, r in enumerate(chain.get("resistance") or []):
        lv.append({"price": r, "name": f"Call OI resistance{'' if i == 0 else ' 2'}", "kind": "oi"})
    if chain.get("max_pain"):
        lv.append({"price": chain["max_pain"], "name": "Max pain", "kind": "oi"})
    lv = sorted([x for x in lv if np.isfinite(x["price"])], key=lambda x: -x["price"])
    gap = spot * min_gap_pct / 100  # a level right at the price is no use as a stop or a target
    above = [x for x in lv if x["price"] > spot + gap]
    below = [x for x in lv if x["price"] < spot - gap]
    res = above[-1] if above else None
    sup = below[0] if below else None
    plan = {}
    if side > 0 and res and sup:
        plan = {"stop": sup["price"], "stop_at": sup["name"], "target": res["price"], "target_at": res["name"],
                "rr": (res["price"] - spot) / (spot - sup["price"]) if spot > sup["price"] else None}
    elif side < 0 and res and sup:
        plan = {"stop": res["price"], "stop_at": res["name"], "target": sup["price"], "target_at": sup["name"],
                "rr": (spot - sup["price"]) / (res["price"] - spot) if res["price"] > spot else None}
    return {"levels": lv, "support": sup, "resistance": res, "plan": plan}


def failed_break(bars: pd.DataFrame) -> dict | None:
    """Today's first failed break of yesterday's high / low: traded beyond it, then a 5-minute close back inside ->
    fade it (Bank Nifty breaks tend to fail). Signals from 9:30."""
    today, prev, _ = sessions(bars)
    if today.empty or prev.empty:
        return None
    pdh, pdl = float(prev["High"].max()), float(prev["Low"].min())
    hi, lo = today["High"].cummax(), today["Low"].cummin()
    m = today.index.hour * 60 + today.index.minute
    s = (hi > pdh) & (today["Close"] < pdh) & (m + 5 >= 570) & (m + 5 <= 840)
    l_ = (lo < pdl) & (today["Close"] > pdl) & (m + 5 >= 570) & (m + 5 <= 840)
    hits = today[s | l_]
    out = {"pdh": pdh, "pdl": pdl, "broke_high": bool((hi > pdh).any()), "broke_low": bool((lo < pdl).any())}
    if hits.empty:
        return {**out, "signal": None}
    t0 = hits.index[0]
    short = bool(s.loc[t0])
    return {**out, "signal": {"side": "SHORT" if short else "LONG", "time": (t0 + pd.Timedelta(minutes=5)).strftime("%H:%M"),
                              "price": float(hits["Close"].iloc[0]), "level": pdh if short else pdl}}
