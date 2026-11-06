"""Colour every table by what its data means (the app-wide theme for st.dataframe).

- money / move columns (P&L %, Chg %, R, Net flow ...): green when positive, red when negative
- side columns (BUY / SELL, Bullish / Bearish): green / red
- status columns (stop, target, hold, exit, open ...): red / green / blue / amber by meaning
- gap groups: the desk's gap-group colours (0-0.5% cyan, 0.5-1% blue, 1-3% amber, >3% pink)
- the name column (Stock / Symbol / Setup / Index / Sector) bold

install(st) wraps st.dataframe once; tables already passed as a pandas Styler, or very large ones, are left alone.
"""
from __future__ import annotations

import re

import pandas as pd

UP, DOWN, BLUE, AMBER, CYAN, PINK, VIOLET = "#22C55E", "#F43F5E", "#3B82F6", "#F59E0B", "#22D3EE", "#EC4899", "#A78BFA"
_W = "font-weight:600"
MAX_ROWS = 1500
ZEBRA = "background-color: rgba(148,170,210,0.10)"

_SIGNED = re.compile(r"(%|p&l|chg|change|net|flow|money|smart|^r$|^r |\br$| r$|best r|worst r|from open|move|pnl|profit|"
                     r"gain|return|edge|avg r)", re.I)
_NOT_SIGNED = re.compile(r"(atr|range|vol|stop|turnover|risk|win|odds|inflow|outflow|pcr|weight|share|buying|selling|"
                         r"rate|prob|hit|coverage|loaded|iv\b|spread|lot|qty|price|entry|exit|ltp|^now$|level|strike)", re.I)
_SIDE = re.compile(r"^(side|direction|bias|trend|signal|call|view|flow|money favours|sentiment|buildup|smart side)$", re.I)
_STATUS = re.compile(r"(status|result|outcome|decision|pass|hour-1 call|now vs range|where|verdict|advice|action|state)", re.I)
_NAME = ("Stock", "Symbol", "Setup", "Index", "Sector", "Name", "Instrument", "Contract")
_GAP = {"0-0.5%": CYAN, "0.5-1%": BLUE, "1-3%": AMBER, ">3%": PINK}

_RED_WORDS = ("stop", "exit", "below", "loss", "sell", "bear", "short", "reject", "fail", "avoid", "down", "out", "trap")
_GREEN_WORDS = ("trade", "✓", "signal", "target", "hold", "above", "win", "buy", "bull", "long", "traded", "core", "up", "in ", "profit", "trail")
_BLUE_WORDS = ("done", "squared", "open", "inside", "live", "testing", "running")
_AMBER_WORDS = ("repeat", "wait", "time", "closed", "mixed", "neutral", "watch", "pending")


def _num_css(v) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x != x or x == 0:
        return ""
    return f"color:{UP};{_W}" if x > 0 else f"color:{DOWN};{_W}"


def _side_css(v) -> str:
    s = str(v).strip().upper()
    if not s or s in ("—", "-", "NONE", "NAN"):
        return ""
    if s.startswith(("BUY", "LONG", "BULL", "UP", "YES", "CE")) or "BULLISH" in s:
        return f"color:{UP};{_W}"
    if s.startswith(("SELL", "SHORT", "BEAR", "DOWN", "NO", "PE")) or "BEARISH" in s:
        return f"color:{DOWN};{_W}"
    return ""


def _status_css(v) -> str:
    s = str(v).strip().lower()
    if not s or s in ("—", "-", "nan", "none"):
        return ""
    for words, c in ((_RED_WORDS, DOWN), (_GREEN_WORDS, UP), (_BLUE_WORDS, BLUE), (_AMBER_WORDS, AMBER)):
        if any(s.startswith(w) or f" {w}" in f" {s}" for w in words):
            return f"color:{c};{_W}"
    return ""


def _signstr_css(v) -> str:
    """Text like '+0.87%' or '-328 pts': green / red by its sign."""
    t = str(v).strip()
    if t[:1] == "+":
        return f"color:{UP};{_W}"
    if t[:1] in ("-", "−"):
        return f"color:{DOWN};{_W}"
    return ""


def _gap_css(v) -> str:
    c = _GAP.get(str(v))
    return f"color:{c};{_W}" if c else ""


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    x = float(v)
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x):,}" if abs(x) >= 10000 else f"{int(x)}"
    return f"{x:,.2f}" if abs(x) >= 0.01 else f"{x:.3g}"


def style(df: pd.DataFrame, formatted=()):
    """A pandas Styler with the theme colours, or the frame unchanged when nothing applies. Float columns without a
    column_config format (`formatted`) get a plain 2-decimal format, so the Styler doesn't show 6 decimals."""
    if not isinstance(df, pd.DataFrame) or df.empty or len(df) > MAX_ROWS or not df.columns.is_unique \
            or not df.index.is_unique:
        return df
    sty = df.style
    for c in df.columns:
        name = str(c)
        col = df[c]
        if name in _NAME:
            sty = sty.map(lambda v: _W, subset=[c])
        elif name.lower() == "gap group":
            sty = sty.map(_gap_css, subset=[c])
        elif pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_bool_dtype(col):
            if _SIGNED.search(name) and not _NOT_SIGNED.search(name):
                sty = sty.map(_num_css, subset=[c])
        elif col.dtype == object or pd.api.types.is_string_dtype(col):
            if _SIDE.match(name):
                sty = sty.map(_side_css, subset=[c])
            elif _SIGNED.search(name) and not _NOT_SIGNED.search(name):
                sty = sty.map(_signstr_css, subset=[c])
            elif _STATUS.search(name):
                sty = sty.map(_status_css, subset=[c])
    # alternate rows shaded, so long tables read like a professional grid
    def _zebra(d):
        css = pd.DataFrame("", index=d.index, columns=d.columns)
        css.iloc[1::2, :] = ZEBRA
        return css
    sty = sty.apply(_zebra, axis=None)
    floats = [c for c in df.columns if pd.api.types.is_float_dtype(df[c]) and str(c) not in formatted]
    if floats:
        sty = sty.format(_fmt, subset=floats)
    return sty


def install(st) -> None:
    if getattr(st.dataframe, "_themed", False):
        return
    raw = st.dataframe

    def dataframe(data=None, *args, **kwargs):
        try:
            cc = kwargs.get("column_config") or {}
            themed = style(data, tuple(str(k) for k in cc))
        except Exception:
            themed = data
        if themed is data:
            return raw(data, *args, **kwargs)
        try:
            return raw(themed, *args, **kwargs)
        except Exception:                      # never let the colours break a table
            return raw(data, *args, **kwargs)

    dataframe._themed = True
    st.dataframe = dataframe
