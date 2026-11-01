"""Trading desk: one market verdict, CE / PE focus lists and an index option plan from everything the app already
measures, plus an optional Claude-written desk note.

Honesty rules baked in: every number shown here is a reading of today's data, not a tested signal. The only setups
with a tested edge are the opening-price ones (gap fade, panic gap-down buy, sector overreaction) and the index
trend-day + rising futures OI rule; the focus lists are confluence of readings (how many agree), shown with their
reasons so the trader decides.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

LABELS = [(55, "Strong bullish"), (20, "Bullish"), (-20, "Neutral"), (-55, "Bearish"), (-101, "Strong bearish")]


def _clip(x, lo=-1.0, hi=1.0):
    return float(np.clip(x, lo, hi)) if pd.notna(x) else np.nan


def regime(buildup_share=None, adv=None, dec=None, buy_share=None, fut_money=None, vix_chg=None,
           nifty_from_open=None, nifty_atr_pct=None) -> dict:
    """Market verdict -100..+100 from up to six readings (missing ones are skipped and their weight shared out)."""
    parts = []
    if buildup_share is not None and pd.notna(buildup_share):
        parts.append(("Nifty option + futures build-up", 0.30, _clip((buildup_share - 50) / 25),
                      f"{buildup_share:.0f}% bullish"))
    if adv is not None and dec is not None and adv + dec > 0:
        parts.append(("F&O breadth", 0.20, _clip((adv - dec) / (adv + dec) / 0.5), f"{adv} up / {dec} down"))
    if buy_share is not None and pd.notna(buy_share):
        parts.append(("Money flow (turnover buying)", 0.15, _clip((buy_share - 50) / 5), f"{buy_share:.1f}% buying"))
    if fut_money is not None and pd.notna(fut_money):
        parts.append(("Fresh futures money", 0.15, _clip(fut_money / 2000), f"₹{fut_money:+,.0f} Cr net"))
    if nifty_from_open is not None and pd.notna(nifty_from_open):
        scale = (nifty_atr_pct or 1.0) * 0.6
        parts.append(("Nifty from its open", 0.15, _clip(nifty_from_open / scale), f"{nifty_from_open:+.2f}%"))
    if vix_chg is not None and pd.notna(vix_chg):
        parts.append(("India VIX (falling = calm)", 0.05, _clip(-vix_chg / 5), f"{vix_chg:+.1f}%"))
    if not parts:
        return {"score": np.nan, "label": "Waiting for data", "parts": []}
    w = sum(p[1] for p in parts)
    score = 100 * sum(p[1] * p[2] for p in parts) / w
    label = next(name for cut, name in LABELS if score >= cut)
    return {"score": round(score), "label": label,
            "parts": [{"reading": n, "value": v, "pull": round(100 * s)} for n, _, s, v in parts]}


BUILD = {"Long buildup": 1.0, "Short covering": 0.5, "Short buildup": -1.0, "Long unwinding": -0.5}


def focus(R: pd.DataFrame, flow: pd.DataFrame, radar: pd.DataFrame, picks: pd.DataFrame, sector_flow: dict,
          n: int = 6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """CE and PE focus lists: stocks where several independent readings point the same way as the price.

    Points (signed: + bullish, - bearish): activity smart score (±1 at 25, ±2 at 40), futures buildup (±1 / ±0.5),
    sector's fresh futures money (±1), the stock's own money flow (±1 when 55%+ / 45%- of turnover is buying),
    momentum-radar TradeFinder fit (±1), yesterday's high / low broken (±1), smart-money pick (±1).
    A stock needs 3+ points the same way as its move today."""
    if R is None or R.empty:
        return pd.DataFrame(), pd.DataFrame()
    d = R[["Stock", "Symbol", "Price", "Chg %", "Smart", "Sector"] +
          [c for c in ("Buildup",) if c in R.columns]].copy()
    if "Buildup" not in d:
        d["Buildup"] = ""
    d["Buildup"] = d["Buildup"].fillna("")
    pts = pd.Series(0.0, index=d.index)
    why = [[] for _ in range(len(d))]

    def add(mask, val, text):
        nonlocal pts
        mask = mask.fillna(False).to_numpy() if hasattr(mask, "fillna") else np.asarray(mask)
        vals = val if hasattr(val, "__len__") else np.full(len(d), val)
        for i in np.where(mask)[0]:
            pts.iloc[i] += vals[i]
            why[i].append(text if isinstance(text, str) else text[i])

    sm = d["Smart"].astype(float)
    add(sm.abs() >= 40, np.sign(sm) * 2, [f"activity {s:+.0f}" for s in sm])
    add((sm.abs() >= 25) & (sm.abs() < 40), np.sign(sm), [f"activity {s:+.0f}" for s in sm])
    b = pd.to_numeric(d["Buildup"].map(BUILD), errors="coerce").fillna(0.0).to_numpy()
    add(pd.Series(b != 0, index=d.index), b, [str(x).lower() for x in d["Buildup"]])
    sec = d["Sector"].map(sector_flow).fillna("")
    sv = np.where(sec == "Bullish", 1, np.where(sec == "Bearish", -1, 0))
    add(pd.Series(sv != 0, index=d.index), sv, [f"{s} money {f.lower()}" for s, f in zip(d["Sector"], sec)])
    if flow is not None and not flow.empty and "Buy share %" in flow:
        bs = d["Stock"].map(flow.set_index("Stock")["Buy share %"])
        fv = np.where(bs >= 55, 1, np.where(bs <= 45, -1, 0))
        add(pd.Series(fv != 0, index=d.index), fv, [f"{x:.0f}% buying" if pd.notna(x) else "" for x in bs])
    if radar is not None and not radar.empty:
        r = radar.set_index("Stock")
        side = d["Stock"].map(r["Side"]).fillna("")
        rs = np.where(side.str.startswith("BUY"), 1, np.where(side.str.startswith("SELL"), -1, 0))
        fit = d["Stock"].map(r["TradeFinder fit"]).fillna("") == "Yes"
        add(fit & (rs != 0), rs, "radar shortlist")
        brk = d["Stock"].map(r["Broke yday high/low"]).fillna("")
        add((brk != "") & (rs != 0), rs, ["broke yday high" if v > 0 else "broke yday low" for v in rs])
    if picks is not None and not picks.empty:
        ps = d["Stock"].map(picks.set_index("Stock")["Side"]).fillna("")
        pv = np.where(ps.str.startswith("BUY"), 1, np.where(ps.str.startswith("SELL"), -1, 0))
        add(pd.Series(pv != 0, index=d.index), pv, "smart-money pick")
    d["Score"] = pts
    d["Why"] = [", ".join(w_ for w_ in ws if w_) for ws in why]
    ce = d[(d["Score"] >= 3) & (d["Chg %"] > 0)].sort_values(["Score", "Chg %"], ascending=False).head(n)
    pe = d[(d["Score"] <= -3) & (d["Chg %"] < 0)].sort_values(["Score", "Chg %"]).head(n)
    return ce.reset_index(drop=True), pe.reset_index(drop=True)


def index_plan(name: str, last: float, step: int, verdict: dict, trend: dict | None, share: float | None) -> dict:
    """What the readings say for buying this index's options. The tested edge is the trend-day alert."""
    atm = round(last / step) * step if last and step else None
    if trend and trend.get("status") == "SIGNAL":
        return {"index": name, "side": trend["side"], "strike": trend["strike"], "tone": 1 if trend["side"] == "CE" else -1,
                "text": f"Trend-day alert fired at {trend['sig_time']}: buy {trend['side']} {trend['strike']:,.0f}, "
                        "-30% stop on the premium, trail. This is the one tested index-option rule."}
    s = verdict.get("score", np.nan)
    bull = pd.notna(s) and s >= 20 and (share is None or pd.isna(share) or share >= 55)
    bear = pd.notna(s) and s <= -20 and (share is None or pd.isna(share) or share <= 45)
    if bull:
        return {"index": name, "side": "CE", "strike": atm, "tone": 1,
                "text": f"Bias up. CE only, on a dip that holds VWAP; ATM {atm:,.0f}. No PE. Wait for the trend-day "
                        "alert for a tested entry."}
    if bear:
        return {"index": name, "side": "PE", "strike": atm, "tone": -1,
                "text": f"Bias down. PE only, on a bounce that fails at VWAP; ATM {atm:,.0f}. No CE. Wait for the "
                        "trend-day alert for a tested entry."}
    return {"index": name, "side": "Wait", "strike": atm, "tone": 0,
            "text": "Mixed readings: no index option trade. Time decay costs about 0.05% of the index an hour."}


def desk_note(verdict: dict, ce: pd.DataFrame, pe: pd.DataFrame, plans: list, top_in: str | None,
              top_out: str | None, openings: list) -> list[str]:
    """A short rule-based note: always available, no API needed."""
    lines = []
    s = verdict.get("score", np.nan)
    if pd.notna(s):
        strongest = max(verdict["parts"], key=lambda p: abs(p["pull"]))
        lines.append(f"**{verdict['label']}** ({s:+.0f}/100). Strongest reading: {strongest['reading'].lower()}, "
                     f"{strongest['value']}.")
    if top_in or top_out:
        lines.append(f"Money is going into **{top_in or '—'}** and out of **{top_out or '—'}**.")
    for p in plans:
        lines.append(f"**{p['index']}:** {p['text']}")
    if len(ce):
        lines.append("CE focus: " + ", ".join(ce["Stock"].head(3)) + ".")
    if len(pe):
        lines.append("PE focus: " + ", ".join(pe["Stock"].head(3)) + ".")
    if openings:
        lines.append("Opening setups live: " + "; ".join(openings) + ".")
    if pd.notna(s) and abs(s) < 20 and not len(ce) and not len(pe):
        lines.append("Nothing lines up yet. The best trade can be no trade.")
    return lines


# ---------------------------------------------------------------- Claude

CLAUDE_MODEL = "claude-opus-5-5"
SYSTEM = (
    "You are the desk analyst for an Indian F&O trader who buys stock and index options (CE/PE). You get a JSON "
    "snapshot of the live market from their screener. Write a short desk note in plain English for someone watching "
    "a running market: (1) the market verdict in one line, (2) index options plan for Nifty and Bank Nifty (CE, PE "
    "or wait, with the condition that would change it), (3) up to 3 CE and 3 PE stocks worth watching, each with "
    "the one or two readings that matter, (4) the main risk right now. Use only the data given; never invent prices "
    "or levels. Say plainly when readings conflict or data is thin. Mention that only the opening-price setups and "
    "the index trend-day + rising futures OI rule have tested edges; everything else is confluence. Under 180 "
    "words, markdown bullets, no preamble. This is information, not investment advice.")


def claude_note(snapshot: dict, api_key: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
    resp = client.beta.messages.create(
        model=CLAUDE_MODEL, max_tokens=4000, system=SYSTEM,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": "Live snapshot:\n" + json.dumps(snapshot, default=str)}])
    if resp.stop_reason == "refusal":
        return "Claude declined this request."
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()
