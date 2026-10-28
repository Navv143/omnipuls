"""Omnipuls logo concepts: marks, wordmark (text converted to paths), lockups, app icons."""
import io
import math
from pathlib import Path

import cairosvg
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
FONT = Path(__file__).parent / "Sora.ttf"

# ---------------------------------------------------------------- wordmark as outlines


def _instance(wght):
    f = TTFont(FONT)
    return instantiateVariableFont(f, {"wght": wght})


FONTS = {600: _instance(600), 250: _instance(250)}


def text_path(text: str, wght: int, size: float, x: float, baseline: float, tracking: float = 0.0):
    """SVG path data for text, plus advance width."""
    f = FONTS[wght]
    upm = f["head"].unitsPerEm
    cmap = f.getBestCmap()
    gs = f.getGlyphSet()
    scale = size / upm
    d, pen_x = [], x
    for ch in text:
        g = cmap[ord(ch)]
        sp = SVGPathPen(gs)
        tp = TransformPen(sp, (scale, 0, 0, -scale, pen_x, baseline))
        gs[g].draw(tp)
        d.append(sp.getCommands())
        pen_x += gs[g].width * scale + tracking
    return " ".join(d), pen_x - x - tracking


def wordmark(x, baseline, size, omni_fill, puls_fill):
    d1, w1 = text_path("omni", 600, size, x, baseline, tracking=size * 0.005)
    d2, w2 = text_path("puls", 250, size, x + w1 + size * 0.03, baseline, tracking=size * 0.02)
    svg = f'<path d="{d1}" fill="{omni_fill}"/><path d="{d2}" fill="{puls_fill}"/>'
    return svg, w1 + size * 0.03 + w2

# ---------------------------------------------------------------- marks (viewBox 0 0 100 100)


def polar(cx, cy, r, deg):  # 0 deg = 12 o'clock, clockwise
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def mark_momentum(gid="m1"):
    """Concept 1: an 'O' built from vertical data bars, broken at the top right where a line chart breaks out."""
    cx, cy, ro, ri = 47, 55, 33, 20
    bars = []
    w, step = 5.0, 7.4
    xs = [cx - ro + w / 2 + 0.3 + i * step for i in range(10)]
    for i, x in enumerate(xs):
        dx = abs(x - cx)
        if dx >= ro:
            continue
        yo = math.sqrt(ro ** 2 - dx ** 2)
        yi = math.sqrt(ri ** 2 - dx ** 2) if dx < ri else 0.0
        lift = 1.6 * i  # bars step upward left to right: momentum
        segs = [(cy + yi, cy + yo)]  # lower arc
        if not (x > cx - 2):  # upper arc only on the left half: the O is broken at the top right
            segs.append((cy - yo, cy - yi))
        for y0, y1 in segs:
            if y1 - y0 < 0.5:
                y0, y1 = cy - yo, cy + yo
            top = y0 - (lift if y0 > cy else 0)
            bars.append(f'<rect x="{x - w / 2:.2f}" y="{top:.2f}" width="{w}" height="{y1 - top:.2f}" rx="1.2"/>')
    pts = [(cx - 6, cy + 4), (cx + 4, cy - 6), (cx + 11, cy - 1), (cx + 22, cy - 20), (cx + 28, cy - 15), (cx + 42, cy - 40)]
    path = "M" + " L".join(f"{a:.2f},{b:.2f}" for a, b in pts)
    hx, hy = pts[-1]
    head = f'<path d="M{hx - 10:.2f},{hy - 0.2:.2f} L{hx:.2f},{hy:.2f} L{hx + 0.6:.2f},{hy + 10:.2f}"/>'
    defs = (f'<linearGradient id="{gid}" x1="0" y1="1" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#2F5BD3"/><stop offset=".5" stop-color="#1D9BF0"/>'
            f'<stop offset="1" stop-color="#2EE6F6"/></linearGradient>')
    body = (f'<g fill="url(#{gid})">{"".join(bars)}</g>'
            f'<g stroke="url(#{gid})" stroke-width="5.2" stroke-linecap="round" stroke-linejoin="round" fill="none">'
            f'<path d="{path}"/>{head}</g>')
    return defs, body


def mark_convergence(gid="m2"):
    """Concept 2: chamfered geometric 'O' ribbon; the interior negative space forms a 'P'."""
    def octo(x0, y0, x1, y1, ch):
        return (f"M{x0 + ch},{y0} L{x1 - ch},{y0} L{x1},{y0 + ch} L{x1},{y1 - ch} L{x1 - ch},{y1} "
                f"L{x0 + ch},{y1} L{x0},{y1 - ch} L{x0},{y0 + ch} Z")
    outer = octo(12, 12, 88, 88, 17)
    inner = octo(25, 25, 75, 75, 11)
    # Solid block in the lower right (leaves the P's stem on the left) and the bowl's counter as a floating node.
    block = "M41,55 L75,55 L75,64 L64,75 L41,75 Z"
    node = "M49,34 L60,34 L64,38 L64,46 L49,46 Z"
    defs = (f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="#3BF0A0"/><stop offset="1" stop-color="#0F9F67"/></linearGradient>')
    body = (f'<path d="{outer} {inner}" fill="url(#{gid})" fill-rule="evenodd"/>'
            f'<path d="{block} {node}" fill="url(#{gid})"/>')
    return defs, body


def mark_beacon(gid="m3"):
    """Concept 3: a solid core with radiating rings that thin and break as they travel outward."""
    cx, cy = 50, 50
    rings = []
    spec = [(17, 6.0, 0, 360), (29, 4.2, 20, 330), (40, 2.6, 40, 300)]
    for r, w, a0, a1 in spec:
        if a1 - a0 >= 360:
            rings.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke-width="{w}"/>')
            continue
        x0, y0 = polar(cx, cy, r, a0)
        x1, y1 = polar(cx, cy, r, a1)
        large = 1 if a1 - a0 > 180 else 0
        rings.append(f'<path d="M{x0:.2f},{y0:.2f} A{r},{r} 0 {large} 1 {x1:.2f},{y1:.2f}" fill="none" '
                     f'stroke-width="{w}" stroke-linecap="round"/>')
    nodes = "".join(f'<circle cx="{polar(cx, cy, 40, a)[0]:.2f}" cy="{polar(cx, cy, 40, a)[1]:.2f}" r="{rr}"/>'
                    for a, rr in ((318, 3.2), (334, 2.4), (348, 1.6)))
    defs = (f'<linearGradient id="{gid}" x1="0" y1="1" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#FF1F4B"/><stop offset="1" stop-color="#FFB02E"/></linearGradient>')
    body = (f'<circle cx="{cx}" cy="{cy}" r="7.5" fill="url(#{gid})"/>'
            f'<g stroke="url(#{gid})">{"".join(rings)}</g><g fill="url(#{gid})">{nodes}</g>')
    return defs, body


CONCEPTS = {
    "momentum": {"title": "Aligned Momentum", "mark": mark_momentum, "tile": "#0B1526", "omni": "#EAF2FF",
                 "puls": "#2EE6F6"},
    "convergence": {"title": "Quantum Convergence", "mark": mark_convergence, "tile": "#16191D", "omni": "#EEF1F3",
                    "puls": "#3BF0A0"},
    "beacon": {"title": "Order Book Beacon", "mark": mark_beacon, "tile": "#140C10", "omni": "#FFF1EC",
               "puls": "#FF8A3D"},
}

# ---------------------------------------------------------------- assemblies


def svg_mark(key, size=512, tile=False, pad=0.0):
    defs, body = CONCEPTS[key]["mark"](f"g_{key}")
    bg = (f'<rect width="100" height="100" rx="22" fill="{CONCEPTS[key]["tile"]}"/>' if tile else "")
    s = 1 - 2 * pad
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 100 100">'
            f'<defs>{defs}</defs>{bg}<g transform="translate({pad * 100} {pad * 100}) scale({s})">{body}</g></svg>')


def svg_lockup(key, height=120, omni=None, puls=None):
    cfg = CONCEPTS[key]
    defs, body = cfg["mark"](f"l_{key}")
    size = 64
    wm, w = wordmark(78, 45, 40, omni or cfg["omni"], puls or cfg["puls"])
    total_w = 78 + w + 6
    return (f'<svg xmlns="http://www.w3.org/2000/svg" height="{height}" width="{height * total_w / 64:.0f}" '
            f'viewBox="0 0 {total_w:.1f} 64"><defs>{defs}</defs>'
            f'<g transform="translate(0 0) scale(0.64)">{body}</g>{wm}</svg>')


def png(svg: str, path: Path, w=None, h=None):
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(path), output_width=w, output_height=h)


if __name__ == "__main__":
    for k in CONCEPTS:
        (OUT / f"{k}_mark.svg").write_text(svg_mark(k))
        (OUT / f"{k}_icon.svg").write_text(svg_mark(k, tile=True, pad=0.1))
        (OUT / f"{k}_lockup_dark.svg").write_text(svg_lockup(k))
        (OUT / f"{k}_lockup_light.svg").write_text(svg_lockup(k, omni="#0B1526"))
        png(svg_mark(k, tile=True, pad=0.1), OUT / f"{k}_icon_512.png", 512, 512)
        png(svg_lockup(k), OUT / f"{k}_lockup.png", h=160)
    print("ok")
