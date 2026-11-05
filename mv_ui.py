"""Market View visuals: small HTML/SVG pieces (pure functions, no Streamlit) so the page reads at a glance:
index pulse tiles with sparklines and range bars, a mood gauge, signal chips, meters, a sector heatmap and option
chain ranges. Colours come from the app's design tokens (--om-*)."""
from __future__ import annotations

import html
import math

import numpy as np
import pandas as pd

UP, DOWN, NEUTRAL, WARN, ACCENT = "var(--om-up)", "var(--om-down)", "var(--om-neutral)", "var(--om-warn)", "var(--om-accent)"

CSS = """<style>
.mx-sec{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:18px 0 8px}
.mx-sec h4{margin:0;font-size:var(--fs-sm);letter-spacing:.09em;text-transform:uppercase;color:var(--om-muted);font-weight:600}
.mx-sec span{font-size:var(--fs-xs);color:var(--om-faint)}
.mx-pulse{display:grid;grid-template-columns:repeat(5,minmax(170px,1fr));gap:10px}
@media (max-width:900px){.mx-pulse{grid-auto-flow:column;grid-template-columns:none;grid-auto-columns:72%;overflow-x:auto;
  scroll-snap-type:x mandatory;padding-bottom:6px}.mx-pulse>div{scroll-snap-align:start}}
.mx-tile{position:relative;border:1px solid var(--om-border);border-radius:var(--r-md);padding:11px 13px 10px;
  background:linear-gradient(180deg,var(--om-surface),var(--om-sunken));overflow:hidden}
.mx-tile:before{content:"";position:absolute;inset:0 0 auto 0;height:2px;background:var(--c)}
.mx-tile .n{font-size:var(--fs-2xs);letter-spacing:.08em;text-transform:uppercase;color:var(--om-muted);display:flex;justify-content:space-between}
.mx-tile .p{font-family:var(--font-num);font-size:var(--fs-xl);font-weight:600;margin-top:2px;color:var(--om-text)}
.mx-chip{display:inline-block;font-family:var(--font-num);font-size:var(--fs-2xs);font-weight:600;padding:1px 7px;
  border-radius:var(--r-pill);color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent)}
.mx-tag{display:inline-block;font-size:var(--fs-2xs);padding:2px 8px;border-radius:var(--r-pill);margin:6px 4px 0 0;
  border:1px solid color-mix(in srgb,var(--c) 45%,transparent);color:var(--c);white-space:nowrap}
.mx-spark{display:block;width:100%;height:38px;margin:6px 0 2px}
.mx-range{position:relative;height:6px;border-radius:3px;background:var(--om-border-soft);margin:9px 0 3px}
.mx-range i{position:absolute;top:-3px;width:2px;height:12px;background:var(--om-faint);border-radius:1px}
.mx-range b{position:absolute;top:-4px;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:var(--c);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 25%,transparent)}
.mx-range em{position:absolute;top:0;height:6px;border-radius:3px;background:color-mix(in srgb,var(--c) 35%,transparent)}
.mx-rl{display:flex;justify-content:space-between;font-family:var(--font-num);font-size:.62rem;color:var(--om-faint)}
.mx-hero{display:grid;grid-template-columns:260px 1fr;gap:12px;margin-top:12px}
@media (max-width:900px){.mx-hero{grid-template-columns:1fr}}
.mx-gauge{border:1px solid var(--om-border);border-radius:var(--r-lg);padding:12px 14px;text-align:center;
  background:radial-gradient(120% 90% at 50% 100%,color-mix(in srgb,var(--c) 14%,transparent),transparent 70%),var(--om-surface)}
.mx-gauge .l{font-size:var(--fs-lg);font-weight:700;color:var(--c);margin-top:-6px}
.mx-gauge .s{font-size:var(--fs-xs);color:var(--om-muted);margin-top:2px}
.mx-votes{display:flex;height:8px;border-radius:4px;overflow:hidden;margin:10px 4px 4px;background:var(--om-border-soft)}
.mx-votes span{display:block}
.mx-idea{border:1px solid color-mix(in srgb,var(--c) 55%,transparent);border-radius:var(--r-lg);padding:14px 16px;
  background:linear-gradient(135deg,color-mix(in srgb,var(--c) 16%,transparent),transparent 65%),var(--om-surface)}
.mx-idea .k{font-size:var(--fs-2xs);letter-spacing:.1em;text-transform:uppercase;color:var(--om-muted)}
.mx-idea h3{margin:.2rem 0 .5rem;font-size:var(--fs-xl);color:var(--c)}
.mx-sig{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px}
.mx-s{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--om-border);border-left:3px solid var(--c);
  border-radius:var(--r-sm);padding:9px 11px;background:var(--om-surface)}
.mx-s .ic{flex:0 0 30px;height:30px;border-radius:8px;display:grid;place-items:center;font-size:17px;font-weight:700;
  color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent)}
.mx-s .t{font-weight:600;font-size:var(--fs-sm);color:var(--om-text);line-height:1.25}
.mx-s .d{font-size:var(--fs-xs);color:var(--om-muted);margin-top:2px;line-height:1.35}
.mx-s .row{display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}
.mx-mini{font-size:.62rem;padding:1px 7px;border-radius:var(--r-pill);border:1px solid var(--om-border-strong);color:var(--om-text-3)}
.mx-quiet{font-size:var(--fs-xs);color:var(--om-faint);margin-top:6px}
.mx-meters{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:10px}
@media (max-width:640px){.mx-meters{grid-template-columns:1fr 1fr;gap:8px}.mx-m{padding:9px 10px}.mx-m .v{font-size:var(--fs-md)}}
.mx-m{border:1px solid var(--om-border);border-radius:var(--r-md);padding:11px 13px;background:var(--om-surface)}
.mx-m .h{font-size:var(--fs-2xs);letter-spacing:.08em;text-transform:uppercase;color:var(--om-muted)}
.mx-m .v{font-family:var(--font-num);font-size:var(--fs-lg);font-weight:600;color:var(--c);margin:3px 0 7px}
.mx-bar{display:flex;height:9px;border-radius:5px;overflow:hidden;background:var(--om-border-soft)}
.mx-bar span{display:block;height:100%}
.mx-div{position:relative;height:9px;border-radius:5px;background:var(--om-border-soft)}
.mx-div:after{content:"";position:absolute;left:50%;top:-3px;width:1px;height:15px;background:var(--om-faint)}
.mx-div span{position:absolute;top:0;height:9px;border-radius:5px}
.mx-m .f{display:flex;justify-content:space-between;font-size:.62rem;color:var(--om-faint);margin-top:4px}
.mx-heat{display:flex;flex-wrap:wrap;gap:4px}
.mx-heat div{flex-grow:var(--g);flex-basis:110px;min-height:62px;border-radius:8px;padding:7px 9px;color:#fff;
  background:var(--bg);display:flex;flex-direction:column;justify-content:space-between}
.mx-heat b{font-size:var(--fs-xs);font-weight:600;line-height:1.15;text-shadow:0 1px 2px rgba(0,0,0,.35)}
.mx-heat span{font-family:var(--font-num);font-size:var(--fs-sm);font-weight:600;text-shadow:0 1px 2px rgba(0,0,0,.35)}
.mx-heat small{font-size:.6rem;opacity:.85}
.mx-chains{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.mx-ch{border:1px solid var(--om-border);border-radius:var(--r-md);padding:12px 14px;background:var(--om-surface)}
.mx-ch .top{display:flex;justify-content:space-between;align-items:center}
.mx-ch .nm{font-weight:600}
.mx-lad{position:relative;height:34px;margin:14px 6px 2px}
.mx-lad .ln{position:absolute;top:15px;left:0;right:0;height:4px;border-radius:2px;
  background:linear-gradient(90deg,var(--om-up),var(--om-border-soft) 45%,var(--om-border-soft) 55%,var(--om-down))}
.mx-lad .sp{position:absolute;top:8px;width:3px;height:18px;margin-left:-1px;background:var(--om-text);border-radius:2px}
.mx-lad .mp{position:absolute;top:10px;width:9px;height:9px;margin-left:-4px;transform:rotate(45deg);background:var(--om-warn)}
.mx-lad .lb{position:absolute;top:-6px;font-family:var(--font-num);font-size:.62rem;color:var(--om-text-3);transform:translateX(-50%)}
.mx-ch .f{display:flex;justify-content:space-between;font-family:var(--font-num);font-size:.66rem;color:var(--om-faint)}
.mx-kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:10px;margin:4px 0 6px}
.mx-k{border:1px solid var(--om-border);border-radius:var(--r-md);padding:11px 13px;background:linear-gradient(180deg,var(--om-surface),var(--om-sunken))}
.mx-k .h{font-size:var(--fs-2xs);letter-spacing:.08em;text-transform:uppercase;color:var(--om-muted);display:flex;align-items:center;gap:6px}
.mx-k .v{font-family:var(--font-num);font-size:var(--fs-xl);font-weight:600;color:var(--c);margin-top:3px}
.mx-k .s{font-size:var(--fs-xs);color:var(--om-faint);margin-top:1px}
.mx-dot{width:8px;height:8px;border-radius:50%;background:var(--c);box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 25%,transparent)}
.mx-ev{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px}
.mx-e{border:1px solid var(--om-border);border-left:3px solid var(--c);border-radius:var(--r-sm);padding:10px 12px;background:var(--om-surface)}
.mx-e .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.mx-e .nm{font-weight:700;font-size:var(--fs-md)}
.mx-e .px{font-family:var(--font-num);font-size:var(--fs-sm);color:var(--om-text-3)}
.mx-e ul{margin:5px 0 6px;padding-left:16px;font-size:var(--fs-xs);color:var(--om-text-2)}
.mx-e li{margin:1px 0}
.mx-odds{display:flex;align-items:center;gap:8px;font-size:var(--fs-2xs);color:var(--om-muted)}
.mx-odds .b{flex:1;position:relative;height:7px;border-radius:4px;background:var(--om-border-soft)}
.mx-odds .b span{position:absolute;left:0;top:0;height:7px;border-radius:4px;background:var(--c)}
.mx-odds .b i{position:absolute;left:50%;top:-3px;width:1px;height:13px;background:var(--om-faint)}
.mx-feed{border:1px solid var(--om-border);border-radius:var(--r-md);background:var(--om-surface);max-height:420px;overflow:auto}
.mx-f{display:grid;grid-template-columns:48px 92px 1fr auto;gap:8px;align-items:center;padding:6px 12px;
  border-bottom:1px solid var(--om-border-soft);font-size:var(--fs-xs)}
.mx-f:last-child{border-bottom:none}
.mx-f .t{font-family:var(--font-num);color:var(--om-faint)}
.mx-f .s{font-weight:600;color:var(--c)}
.mx-f .w{font-family:var(--font-num);color:var(--om-text-3)}
@media (max-width:640px){.mx-f{grid-template-columns:42px 80px 1fr}.mx-f .w{display:none}}
.mx-legend{font-size:var(--fs-xs);color:var(--om-faint);margin-top:6px}
</style>"""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def tone_color(t) -> str:
    return UP if (t or 0) > 0 else DOWN if (t or 0) < 0 else NEUTRAL


def section(title: str, note: str = "") -> str:
    return f"<div class='mx-sec'><h4>{_e(title)}</h4><span>{_e(note)}</span></div>"


def _num(x, nd=2) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{nd}f}"


def _sgn(x, nd=2) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{nd}f}%"


def sparkline(values, color: str, ref: float | None = None, w: int = 160, h: int = 38) -> str:
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=float)
    if len(v) < 2:
        return f"<svg class='mx-spark' viewBox='0 0 {w} {h}'></svg>"
    lo, hi = float(v.min()), float(v.max())
    if ref is not None and np.isfinite(ref):
        lo, hi = min(lo, ref), max(hi, ref)
    span = hi - lo or 1.0
    xs = np.linspace(1, w - 1, len(v))
    ys = h - 3 - (v - lo) / span * (h - 6)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"1,{h} " + pts + f" {w - 1},{h}"
    ref_line = ""
    if ref is not None and np.isfinite(ref):
        ry = h - 3 - (ref - lo) / span * (h - 6)
        ref_line = (f"<line x1='0' x2='{w}' y1='{ry:.1f}' y2='{ry:.1f}' stroke='var(--om-faint)' stroke-width='1' "
                    "stroke-dasharray='3 3' opacity='.6'/>")
    gid = f"g{abs(hash((pts, color))) % 10**8}"
    return (f"<svg class='mx-spark' viewBox='0 0 {w} {h}' preserveAspectRatio='none'><defs><linearGradient id='{gid}' "
            f"x1='0' x2='0' y1='0' y2='1'><stop offset='0' stop-color='{color}' stop-opacity='.35'/><stop offset='1' "
            f"stop-color='{color}' stop-opacity='0'/></linearGradient></defs>{ref_line}"
            f"<polygon points='{area}' fill='url(#{gid})'/><polyline points='{pts}' fill='none' stroke='{color}' "
            f"stroke-width='1.6' stroke-linejoin='round' vector-effect='non-scaling-stroke'/>"
            f"<circle cx='{xs[-1]:.1f}' cy='{ys[-1]:.1f}' r='2.6' fill='{color}'/></svg>")


def _short_index_tags(read: dict | None) -> list[tuple[str, str]]:
    """2-3 word tags from an index reading (the full sentence stays in the tooltip)."""
    if not read:
        return []
    m, lv, tags = read.get("meaning", ""), read.get("levels") or {}, []
    if m.startswith("Above yesterday's high"):
        tags.append(("Above yday high", UP if "BANK" not in read["title"].upper() else WARN))
    elif m.startswith("Below yesterday's low"):
        tags.append(("Below yday low", DOWN if "BANK" not in read["title"].upper() else WARN))
    else:
        tags.append(("Inside yday range", NEUTRAL))
    if "Buyers in control" in m:
        tags.append(("Above VWAP", UP))
    elif "Sellers in control" in m:
        tags.append(("Below VWAP", DOWN))
    mv = lv.get("move_atr")
    if mv is not None and np.isfinite(mv) and abs(mv) >= 0.6:
        tags.append((f"Trend {mv:+.1f} ATR", UP if mv > 0 else DOWN))
    return tags


def pulse_tile(name: str, snap: dict | None, read: dict | None, bars: pd.DataFrame | None = None,
               invert: bool = False) -> str:
    """Index tile: price, change chip, today's sparkline against yesterday's close, and where price sits in the
    range between yesterday's low / high and today's."""
    if not snap:
        return f"<div class='mx-tile' style='--c:{NEUTRAL}'><div class='n'><span>{_e(name)}</span></div><div class='p'>—</div></div>"
    chg = snap.get("chg")
    good = (chg or 0) * (-1 if invert else 1)
    c = UP if good > 0 else DOWN if good < 0 else NEUTRAL
    closes = snap.get("closes")
    vals = list(closes.to_numpy()) if closes is not None else []
    last = snap.get("last")
    prev = last / (1 + chg / 100) if chg is not None and np.isfinite(chg) else None
    tip = _e((read or {}).get("meaning", "").replace("\n", " "))
    rng = ""
    lv = (read or {}).get("levels") or {}
    pdh, pdl = lv.get("pdh"), lv.get("pdl")
    if vals and pdh is not None and pdl is not None and np.isfinite(pdh) and np.isfinite(pdl):
        tlo, thi = float(np.nanmin(vals)), float(np.nanmax(vals))
        if bars is not None and not bars.empty:
            t = bars[bars.index.normalize() == bars.index.normalize().max()]
            if not t.empty:
                tlo, thi = float(t["Low"].min()), float(t["High"].max())
        lo, hi = min(pdl, tlo), max(pdh, thi)
        sp = hi - lo or 1.0
        pos = lambda x: (x - lo) / sp * 100  # noqa: E731
        rng = (f"<div class='mx-range'><em style='left:{pos(tlo):.1f}%;width:{max(pos(thi) - pos(tlo), 1):.1f}%'></em>"
               f"<i style='left:{pos(pdl):.1f}%' title='Yesterday low {pdl:,.0f}'></i>"
               f"<i style='left:{pos(pdh):.1f}%' title='Yesterday high {pdh:,.0f}'></i>"
               f"<b style='left:{pos(last):.1f}%'></b></div>"
               f"<div class='mx-rl'><span>L {lo:,.0f}</span><span>yday {pdl:,.0f}–{pdh:,.0f}</span><span>H {hi:,.0f}</span></div>")
    tags = "".join(f"<span class='mx-tag' style='--c:{tc}'>{_e(t)}</span>" for t, tc in _short_index_tags(read))
    return (f"<div class='mx-tile' style='--c:{c}' title='{tip}'><div class='n'><span>{_e(name)}</span>"
            f"<span class='mx-chip' style='--c:{c}'>{_sgn(chg)}</span></div>"
            f"<div class='p'>{_num(last)}</div>{sparkline(vals, c, prev)}{rng}<div>{tags}</div></div>")


def pulse(tiles: list[str]) -> str:
    return "<div class='mx-pulse'>" + "".join(tiles) + "</div>"


def gauge(score, label: str, bull: int, bear: int, neutral: int) -> str:
    """Semicircle mood gauge, -100 (bearish) to +100 (bullish), with the readings' votes under it."""
    s = 0.0 if score is None or not np.isfinite(score) else float(max(-100, min(100, score)))
    c = UP if s >= 20 else DOWN if s <= -20 else WARN if abs(s) >= 8 else NEUTRAL
    ang = math.pi * (1 - (s + 100) / 200)
    cx, cy, r = 110, 104, 84
    nx, ny = cx + (r - 14) * math.cos(ang), cy - (r - 14) * math.sin(ang)

    def arc(a0, a1, col):
        x0, y0 = cx + r * math.cos(a0), cy - r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy - r * math.sin(a1)
        return (f"<path d='M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}' stroke='{col}' stroke-width='13' "
                "fill='none' stroke-linecap='butt'/>")
    segs = [(math.pi, math.pi * .8, "var(--om-down)"), (math.pi * .8, math.pi * .6, "color-mix(in srgb,var(--om-down) 45%,var(--om-border))"),
            (math.pi * .6, math.pi * .4, "var(--om-border-strong)"), (math.pi * .4, math.pi * .2, "color-mix(in srgb,var(--om-up) 45%,var(--om-border))"),
            (math.pi * .2, 0, "var(--om-up)")]
    svg = (f"<svg viewBox='0 0 220 120' width='100%' style='max-width:240px'>"
           + "".join(arc(a, b, col) for a, b, col in segs)
           + f"<line x1='{cx}' y1='{cy}' x2='{nx:.1f}' y2='{ny:.1f}' stroke='var(--om-text)' stroke-width='3' stroke-linecap='round'/>"
           f"<circle cx='{cx}' cy='{cy}' r='6' fill='var(--om-text)'/>"
           f"<text x='18' y='118' fill='var(--om-faint)' font-size='10'>Bearish</text>"
           f"<text x='202' y='118' fill='var(--om-faint)' font-size='10' text-anchor='end'>Bullish</text>"
           f"<text x='{cx}' y='72' fill='{c}' font-size='22' font-weight='700' text-anchor='middle' "
           f"font-family='JetBrains Mono,monospace'>{s:+.0f}</text></svg>")
    tot = max(bull + bear + neutral, 1)
    votes = (f"<div class='mx-votes'><span style='width:{bull / tot * 100:.1f}%;background:var(--om-up)'></span>"
             f"<span style='width:{neutral / tot * 100:.1f}%;background:var(--om-border-strong)'></span>"
             f"<span style='width:{bear / tot * 100:.1f}%;background:var(--om-down)'></span></div>")
    return (f"<div class='mx-gauge' style='--c:{c}'>{svg}<div class='l'>{_e(label)}</div>{votes}"
            f"<div class='s'>{bull} bullish · {neutral} neutral · {bear} bearish readings</div></div>")


def idea_panel(idea: dict, when: str, md=lambda s: _e(s)) -> str:
    c = tone_color(idea.get("tone"))
    lines = "".join(f"<div class='mx-s' style='--c:{c};margin-top:6px;border-left-width:3px'><div class='d' "
                    f"style='color:var(--om-text-2);font-size:var(--fs-sm)'>{md(x)}</div></div>" for x in idea["lines"])
    return (f"<div class='mx-idea' style='--c:{c}'><div class='k'>Trade idea · {_e(when)}</div>"
            f"<h3>{_e(idea['headline'])}</h3>{lines}</div>")


STATUS_STYLE = {  # status -> (colour, icon)
    "● SIGNAL": (UP, "●"), "Good odds": (UP, "%"), "Waiting": (WARN, "◔"), "Watch": (ACCENT, "◎"), "Confluence": (ACCENT, "◆"),
    "Done today": (NEUTRAL, "✓"), "None today": (NEUTRAL, "–"), "No data": (NEUTRAL, "?"),
}


def signal_cards(sig: pd.DataFrame, limit: int = 18) -> str:
    """Signals as chips: live ones first; quiet ones ('None today', 'No data') folded into one line."""
    if sig is None or sig.empty:
        return "<div class='mx-quiet'>No signals yet.</div>"
    quiet = sig[sig["Status"].isin(["None today", "No data"])]
    live = sig[~sig.index.isin(quiet.index)]
    cards = []
    for _, r in live.head(limit).iterrows():
        col, icon = STATUS_STYLE.get(r["Status"], (NEUTRAL, "•"))
        txt = f" {r['Signal']} {r.get('Details', '')} "
        side = (DOWN if any(w in txt for w in (" SELL", "PE ", "PE /", "short", " PUT")) else
                UP if any(w in txt for w in (" BUY", "CE ", "CE /", "long", " CALL")) else NEUTRAL)
        if r["Status"] == "● SIGNAL" and side == DOWN:
            col = DOWN
        det = str(r.get("Details", ""))
        cards.append(f"<div class='mx-s' style='--c:{side}' title='{_e(det)}'><div class='ic' style='--c:{col}'>{icon}</div><div>"
                     f"<div class='t'>{_e(r['Signal'])}</div><div class='d'>{_e(det[:110] + ('…' if len(det) > 110 else ''))}</div>"
                     f"<div class='row'><span class='mx-chip' style='--c:{col}'>{_e(r['Status'].replace('● ', ''))}</span>"
                     f"<span class='mx-mini'>{_e(r.get('Evidence', ''))}</span></div></div></div>")
    more = len(live) - limit
    out = "<div class='mx-sig'>" + "".join(cards) + "</div>"
    if more > 0:
        out += f"<div class='mx-quiet'>+{more} more in the full list below.</div>"
    if len(quiet):
        out += "<div class='mx-quiet'>No signal today: " + _e(", ".join(quiet["Signal"].astype(str))) + "</div>"
    return out


def meter_split(title: str, a: float, b: float, a_label: str, b_label: str, value: str, tip: str = "") -> str:
    tot = (a or 0) + (b or 0)
    pa = (a / tot * 100) if tot else 50
    c = UP if pa >= 55 else DOWN if pa <= 45 else NEUTRAL
    return (f"<div class='mx-m' style='--c:{c}' title='{_e(tip)}'><div class='h'>{_e(title)}</div><div class='v'>{_e(value)}</div>"
            f"<div class='mx-bar'><span style='width:{pa:.1f}%;background:var(--om-up)'></span>"
            f"<span style='width:{100 - pa:.1f}%;background:var(--om-down)'></span></div>"
            f"<div class='f'><span>{_e(a_label)}</span><span>{_e(b_label)}</span></div></div>")


def meter_diverging(title: str, x: float, scale: float, value: str, left: str, right: str, tip: str = "") -> str:
    """A bar from the middle: right / green for positive, left / red for negative, length vs `scale`."""
    f = 0.0 if not scale else max(-1.0, min(1.0, x / scale))
    c = UP if f > 0.05 else DOWN if f < -0.05 else NEUTRAL
    w = abs(f) * 50
    left_pos = 50 if f >= 0 else 50 - w
    return (f"<div class='mx-m' style='--c:{c}' title='{_e(tip)}'><div class='h'>{_e(title)}</div><div class='v'>{_e(value)}</div>"
            f"<div class='mx-div'><span style='left:{left_pos:.1f}%;width:{max(w, 1):.1f}%;background:{c}'></span></div>"
            f"<div class='f'><span>{_e(left)}</span><span>{_e(right)}</span></div></div>")


def meter_level(title: str, level, chg, lo: float, hi: float, tip: str = "") -> str:
    """A level on a scale (India VIX): calm on the left, fear on the right."""
    if level is None or not np.isfinite(level):
        return ""
    p = max(0.0, min(1.0, (level - lo) / (hi - lo))) * 100
    c = DOWN if (chg or 0) >= 5 or level >= 20 else UP if (chg or 0) <= -5 else NEUTRAL
    return (f"<div class='mx-m' style='--c:{c}' title='{_e(tip)}'><div class='h'>India VIX (fear)</div>"
            f"<div class='v'>{level:.2f} <span class='mx-chip' style='--c:{c}'>{_sgn(chg, 1)}</span></div>"
            f"<div class='mx-range' style='--c:{c};margin-top:4px;background:linear-gradient(90deg,var(--om-up),var(--om-border-soft),var(--om-down))'>"
            f"<b style='left:{p:.1f}%'></b></div><div class='f'><span>calm {lo:.0f}</span><span>fear {hi:.0f}</span></div></div>")


def meters(parts: list[str]) -> str:
    return "<div class='mx-meters'>" + "".join(p for p in parts if p) + "</div>"


def heatmap(secflow: pd.DataFrame) -> str:
    """Sectors as tiles: size = turnover, colour = net money (green in, red out), strength = net / turnover."""
    if secflow is None or secflow.empty or "Net Flow Cr" not in secflow:
        return ""
    s = secflow.copy()
    s["turn"] = s.get("Inflow Cr", 0) + s.get("Outflow Cr", 0)
    s = s.sort_values("Net Flow Cr", ascending=False)
    mx = max(float((s["Net Flow Cr"].abs() / s["turn"].replace(0, np.nan)).max() or 0), 1e-9)
    tmax = max(float(s["turn"].max() or 0), 1e-9)
    tiles = []
    for _, r in s.iterrows():
        net, turn = float(r["Net Flow Cr"]), float(r["turn"] or 0)
        k = min(abs(net) / turn / mx, 1.0) if turn else 0.0
        base = "38,166,154" if net >= 0 else "239,83,80"
        bg = f"rgba({base},{0.22 + 0.68 * k:.2f})"
        buy = (float(r.get("Inflow Cr", 0)) / turn * 100) if turn else 50
        tiles.append(f"<div style='--g:{max(turn / tmax * 4, 0.6):.2f};--bg:{bg}' title='{_e(r['Sector'])}: in "
                     f"₹{float(r.get('Inflow Cr', 0)):,.0f} Cr, out ₹{float(r.get('Outflow Cr', 0)):,.0f} Cr'>"
                     f"<b>{_e(r['Sector'])}</b><span>₹{net:+,.0f} Cr</span><small>{buy:.0f}% buying</small></div>")
    return "<div class='mx-heat'>" + "".join(tiles) + "</div>"


def chain_tile(read: dict | None, spot: float | None, max_pain: float | None) -> str:
    """Option chain: spot between put-writer support and call-writer resistance, max pain marked, PCR chip."""
    if not read:
        return ""
    lv = read.get("levels") or {}
    sup, res, pcr = lv.get("support"), lv.get("resistance"), lv.get("pcr")
    c = tone_color(read.get("tone"))
    lad = ""
    if sup and res and spot:
        lo, hi = min(sup, spot, res, max_pain or spot), max(sup, spot, res, max_pain or spot)
        pad = (hi - lo) * 0.12 or spot * 0.005
        lo, hi = lo - pad, hi + pad
        pos = lambda x: (x - lo) / (hi - lo) * 100  # noqa: E731
        mp = (f"<div class='mp' style='left:{pos(max_pain):.1f}%' title='Max pain {max_pain:,.0f}'></div>"
              if max_pain else "")
        lad = (f"<div class='mx-lad'><div class='ln'></div>{mp}<div class='sp' style='left:{pos(spot):.1f}%'></div>"
               f"<div class='lb' style='left:{pos(spot):.1f}%'>spot {spot:,.0f}</div></div>"
               f"<div class='f'><span style='color:var(--om-up)'>support {sup:,.0f} ({(spot / sup - 1) * 100:.1f}%↓)</span>"
               f"<span style='color:var(--om-down)'>resistance {res:,.0f} ({(res / spot - 1) * 100:.1f}%↑)</span></div>")
    mood = "Put writers confident" if read.get("tone", 0) > 0 else "Call writers confident" if read.get("tone", 0) < 0 else "Writers balanced"
    return (f"<div class='mx-ch' title='{_e(read.get('meaning', ''))}'><div class='top'><span class='nm'>"
            f"{_e(read['title'].replace(' option chain', ''))}</span><span class='mx-chip' style='--c:{c}'>PCR {_num(pcr)}</span></div>"
            f"{lad}<div class='mx-legend'><span class='mx-tag' style='--c:{c}'>{mood}</span>"
            + (f"<span class='mx-tag' style='--c:{WARN}'>◆ max pain {max_pain:,.0f}</span>" if max_pain else "")
            + "</div></div>")


def chains(tiles: list[str]) -> str:
    return "<div class='mx-chains'>" + "".join(t for t in tiles if t) + "</div>"


def kpi(title: str, value: str, sub: str = "", color: str = NEUTRAL, dot: bool = False) -> str:
    d = f"<span class='mx-dot' style='--c:{color}'></span>" if dot else ""
    return (f"<div class='mx-k' style='--c:{color}'><div class='h'>{d}{_e(title)}</div><div class='v'>{_e(value)}</div>"
            f"<div class='s'>{_e(sub)}</div></div>")


def kpis(parts: list[str]) -> str:
    return "<div class='mx-kpis'>" + "".join(parts) + "</div>"


def odds_bar(o: dict | None) -> str:
    if not o:
        return "<div class='mx-odds'>No past odds yet for this kind of moment.</div>"
    c = UP if o["win"] >= 55 else DOWN if o["win"] < 45 else NEUTRAL
    return (f"<div class='mx-odds' style='--c:{c}' title='Past days, same kind of moment: {o['n']} cases; "
            f"average {o['avg']:+.2f}% to 15:15 after costs; ran another 1 ATR {o['run']:.0f}% of the time'>"
            f"<span>kept going</span><div class='b'><span style='width:{min(o['win'], 100):.0f}%'></span><i></i></div>"
            f"<b style='color:{c}'>{o['win']:.0f}%</b><span>n {o['n']} · {o['avg']:+.2f}%</span></div>")


def event_cards(events: list, limit: int = 12) -> str:
    if not events:
        return "<div class='mx-quiet'>No sudden change right now.</div>"
    out = []
    for r in events[:limit]:
        c = UP if r["side"] > 0 else DOWN if r["side"] < 0 else NEUTRAL
        out.append(f"<div class='mx-e' style='--c:{c}'><div class='top'><span class='nm'>{_e(r['stock'])}</span>"
                   f"<span class='px'>{_num(r['price'])} <span class='mx-chip' style='--c:{c}'>{_sgn(r['chg'])}</span></span></div>"
                   f"<div class='mx-quiet' style='margin:1px 0 0'>{_e(r['sector'])} · {_e(r['time'])} · score {r['score']}</div>"
                   "<ul>" + "".join(f"<li>{_e(t)}</li>" for t in r["events"]) + "</ul>" + odds_bar(r.get("odds")) + "</div>")
    return "<div class='mx-ev'>" + "".join(out) + "</div>"


def feed(items: list, limit: int = 80) -> str:
    if not items:
        return "<div class='mx-quiet'>The feed fills as sudden changes happen in market hours.</div>"
    rows = []
    for e in items[:limit]:
        c = UP if e["side"] > 0 else DOWN if e["side"] < 0 else NEUTRAL
        w = f"{e['win']:.0f}% kept going (n {e['n']})" if e.get("win") is not None else ""
        rows.append(f"<div class='mx-f' style='--c:{c}'><span class='t'>{_e(e['time'])}</span><span class='s'>{_e(e['stock'])}</span>"
                    f"<span>{_e(e['text'])}</span><span class='w'>{_e(w)}</span></div>")
    return "<div class='mx-feed'>" + "".join(rows) + "</div>"


# ---------------------------------------------------------------- sector cards

SECTOR_CSS = """<style>
.sx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:12px}
@media (max-width:640px){.sx-grid{grid-template-columns:1fr}}
.sx-card{border:1px solid var(--om-border);border-radius:var(--r-lg);overflow:hidden;background:var(--om-surface);
  display:flex;flex-direction:column}
.sx-card.sel{border-color:var(--om-accent);box-shadow:0 0 0 1px var(--om-accent)}
.sx-head{padding:12px 14px 10px;background:linear-gradient(135deg,color-mix(in srgb,var(--c) 18%,transparent),transparent 70%);
  border-bottom:1px solid var(--om-border-soft)}
.sx-head .row1{display:flex;justify-content:space-between;align-items:center;gap:8px}
.sx-head .nm{font-family:Sora,Inter,sans-serif;font-weight:700;font-size:var(--fs-lg);color:var(--om-text)}
.sx-head .chg{font-family:var(--font-num);font-weight:700;font-size:var(--fs-lg);color:var(--c)}
.sx-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:9px}
.sx-stats div{background:var(--om-sunken);border:1px solid var(--om-border-soft);border-radius:8px;padding:5px 8px}
.sx-stats small{display:block;font-size:.6rem;letter-spacing:.07em;text-transform:uppercase;color:var(--om-faint)}
.sx-stats b{font-family:var(--font-num);font-size:var(--fs-sm);color:var(--v,var(--om-text))}
.sx-list{max-height:300px;overflow:auto}
.sx-r,.sx-h{display:grid;grid-template-columns:1.5fr 1.15fr .9fr .85fr .6fr .7fr .75fr;gap:6px;align-items:center;
  padding:5px 14px;font-size:var(--fs-xs)}
.sx-h{position:sticky;top:0;background:var(--om-surface-2);color:var(--om-faint);font-size:.62rem;letter-spacing:.06em;
  text-transform:uppercase;z-index:1}
.sx-r{border-bottom:1px solid var(--om-border-soft)}
.sx-r:hover{background:color-mix(in srgb,var(--om-accent) 8%,transparent)}
.sx-r span{font-family:var(--font-num);text-align:right;color:var(--om-text-2)}
.sx-r span:first-child{font-family:Inter,sans-serif;text-align:left;font-weight:600;color:var(--om-text)}
.sx-h span{text-align:right}.sx-h span:first-child{text-align:left}
.sx-pill{display:inline-block;min-width:34px;text-align:center;padding:0 5px;border-radius:5px;
  background:color-mix(in srgb,var(--v) 18%,transparent);color:var(--v)}
.sx-foot{margin-top:auto;padding:9px 14px 11px;border-top:1px solid var(--om-border-soft);background:var(--om-sunken)}
.sx-foot .l1{display:flex;justify-content:space-between;font-size:var(--fs-xs);color:var(--om-text-3);gap:8px;flex-wrap:wrap}
.sx-foot .l1 b{font-family:var(--font-num)}
.sx-flow{display:flex;height:7px;border-radius:4px;overflow:hidden;margin-top:7px;background:var(--om-border-soft)}
@media (max-width:640px){.sx-r,.sx-h{grid-template-columns:1.4fr 1.1fr .9fr .55fr .6fr .7fr;padding:5px 10px}
  .sx-r span:nth-child(3),.sx-h span:nth-child(3){display:none}}
</style>"""


def _cv(x, good=0.0, bad=0.0) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return NEUTRAL
    return UP if x > good else DOWN if x < bad else NEUTRAL


def _n(x, nd=2, sign=False, suf="") -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:+,.{nd}f}{suf}" if sign else f"{x:,.{nd}f}{suf}"


def _rf_color(x) -> str:
    return "var(--om-text-2)" if x is None or not np.isfinite(x) else UP if x >= 70 else WARN if x >= 40 else NEUTRAL


def _act_color(x) -> str:
    return "var(--om-text-2)" if x is None or not np.isfinite(x) else ACCENT if x >= 200 else UP if x >= 130 else NEUTRAL


def sector_card(name: str, g: pd.DataFrame, flow: dict, selected: bool = False) -> str:
    """One sector: header (name, average change, R-factor, smart score, activity), its stocks, then the count of
    stocks up / down and the sector's money in / out / net."""
    avg = float(g["Chg %"].mean()) if len(g) else np.nan
    c = _cv(avg)
    rf = float(g["R-factor"].mean()) if g["R-factor"].notna().any() else np.nan
    sm = float(g["Smart"].mean()) if g["Smart"].notna().any() else np.nan
    ac = float(g["Activity %"].mean()) if g["Activity %"].notna().any() else np.nan
    stats = (f"<div style='--v:{_rf_color(rf)}'><small>R-factor</small><b>{_n(rf, 0)}</b></div>"
             f"<div style='--v:{_cv(sm, 10, -10)}'><small>Smart score</small><b>{_n(sm, 0, True)}</b></div>"
             f"<div style='--v:{_act_color(ac)}'><small>Activity</small><b>{_n(ac, 0, suf='%')}</b></div>"
             f"<div><small>Stocks</small><b>{len(g)}</b></div>")
    rows = []
    for _, r in g.sort_values("Chg %", ascending=False).iterrows():
        cc = _cv(r["Chg %"])
        rows.append(f"<div class='sx-r' title='{_e(r.get('Buildup') or '')}'><span>{_e(r['Stock'])}</span>"
                    f"<span>{_n(r['Price'])}</span><span style='color:{cc}'>{_n(r['Change'], 2, True)}</span>"
                    f"<span style='color:{cc}'>{_n(r['Chg %'], 2, True, '%')}</span>"
                    f"<span style='color:{_rf_color(r['R-factor'])};font-weight:600'>{_n(r['R-factor'], 0)}</span>"
                    f"<span style='color:{_cv(r['Smart'], 10, -10)}'>{_n(r['Smart'], 0, True)}</span>"
                    f"<span style='color:{_act_color(r['Activity %'])}'>{_n(r['Activity %'], 0, suf='%')}</span></div>")
    head = ("<div class='sx-h'><span style='text-align:left'>Stock</span><span>Price</span><span>Chg</span><span>Chg %</span><span>R</span>"
            "<span>Smart</span><span>Activity</span></div>")
    up, dn = int((g["Chg %"] > 0).sum()), int((g["Chg %"] < 0).sum())
    inf, outf = flow.get("Inflow Cr"), flow.get("Outflow Cr")
    net = flow.get("Net Flow Cr")
    bar = ""
    if inf is not None and outf is not None and (inf + outf) > 0:
        p = inf / (inf + outf) * 100
        bar = (f"<div class='sx-flow' title='{p:.0f}% buying'><span style='width:{p:.1f}%;background:var(--om-up)'></span>"
               f"<span style='width:{100 - p:.1f}%;background:var(--om-down)'></span></div>")
    foot = (f"<div class='sx-foot'><div class='l1'><span>{len(g)} stocks · <b style='color:var(--om-up)'>{up} ▲</b> · "
            f"<b style='color:var(--om-down)'>{dn} ▼</b></span><span>in <b style='color:var(--om-up)'>₹{_n(inf, 0)}</b> · "
            f"out <b style='color:var(--om-down)'>₹{_n(outf, 0)}</b> · net <b style='color:{_cv(net)}'>₹{_n(net, 0, True)} Cr</b>"
            f"</span></div>{bar}</div>")
    return (f"<div class='sx-card{' sel' if selected else ''}' style='--c:{c}'><div class='sx-head'><div class='row1'>"
            f"<span class='nm'>{_e(name)}</span><span class='chg'>{_n(avg, 2, True, '%')}</span></div>"
            f"<div class='sx-stats'>{stats}</div></div><div class='sx-list'>{head}{''.join(rows)}</div>{foot}</div>")


def sector_grid(cards: list[str]) -> str:
    return "<div class='sx-grid'>" + "".join(cards) + "</div>"
