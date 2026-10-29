"""Omnipuls: live dashboard, NSE indices and sectors, F&O stocks, crypto,
forex, INR currency pairs and commodities, with screener and charts.

Run:  python app.py   (installs anything missing, then opens the app)
Data: Yahoo Finance via yfinance, F&O list and lot sizes from NSE.
"""
import sys

import bootstrap

if "streamlit" not in sys.modules:  # started with `python app.py` or the desktop shortcut
    bootstrap.ensure()
    if "--install-only" in sys.argv:
        bootstrap.make_shortcut()
    else:
        bootstrap.launch(__file__)
    sys.exit()
bootstrap.ensure()  # started with `streamlit run`: still fill any gaps

import json
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

import auth
import dhan as D
import feed as F
import fno
import streamlit.components.v1 as components
import indicators as ind
import scan_service as SS
import scanners as SC
import setups as SU
import universe as U

IST = timezone(timedelta(hours=5, minutes=30))
UP, DOWN, GOLD = "#26A69A", "#EF5350", "#E8B33A"
DATA_FILE = Path(__file__).with_name("watchlist.json")  # replaced per user after sign-in

ASSETS = Path(__file__).resolve().parent / "assets"
st.set_page_config(page_title="Omnipuls", page_icon=str(ASSETS / "omnipuls_icon.png"), layout="wide")
st.logo(str(ASSETS / "omnipuls_logo.png"), icon_image=str(ASSETS / "omnipuls_mark.png"), size="large")

st.markdown(
    """
<style>
  .block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
  [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums; font-size: 1.35rem;}
  [data-testid="stMetricLabel"] p {font-size: .76rem; letter-spacing: .05em; text-transform: uppercase; opacity: .78;}
  .status-row {display:flex; flex-wrap:wrap; gap:.45rem; margin:.1rem 0 .8rem;}
  .pill {padding:.16rem .6rem; border-radius:999px; font-size:.76rem; border:1px solid rgba(128,128,128,.35);}
  .pill.open {color:#26A69A; border-color:#26A69A;}
  .pill.closed {color:#EF5350; border-color:#EF5350;}
  .pill.pre {color:#E8B33A; border-color:#E8B33A;}
  .big-price {font-size:2.1rem; font-weight:700; font-variant-numeric: tabular-nums; line-height:1.1;}
  .chg-up {color:#26A69A; font-weight:600;} .chg-down {color:#EF5350; font-weight:600;}
  .muted {opacity:.65; font-size:.85rem;}
  .tape {overflow:hidden; white-space:nowrap; border-block:1px solid rgba(128,128,128,.25);
         padding:.45rem 0; margin-bottom:1rem; mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);}
  .tape-track {display:inline-block; animation: tape 45s linear infinite; font-variant-numeric: tabular-nums;}
  .tape:hover .tape-track {animation-play-state: paused;}
  .tape-item {display:inline-block; margin-right:2.2rem; font-size:.92rem;}
  .tape-item b {margin-right:.4rem;}
  @keyframes tape {from {transform: translateX(0);} to {transform: translateX(-50%);}}
  @media (prefers-reduced-motion: reduce) {.tape-track {animation: none;}}
  .live-dot {display:inline-block; width:.5rem; height:.5rem; border-radius:50%; background:#26A69A;
             margin-right:.35rem; animation: pulse 1.6s ease-in-out infinite;}
  @keyframes pulse {50% {opacity:.25;}}
  .bbar {display:flex; height:8px; border-radius:4px; overflow:hidden; margin-top:.55rem; background:rgba(128,128,128,.2);}
  .bbar span {display:block; height:100%;}
  .bbar.big {height:12px; margin:.2rem 0 .4rem;}
  .cell {padding-top:.45rem; font-variant-numeric: tabular-nums;}
  .hdr {font-size:.72rem; letter-spacing:.05em; text-transform:uppercase; opacity:.6;}
  /* ---------- phones and small tablets ---------- */
  @media (max-width: 640px) {
    .block-container {padding: .8rem .7rem 3rem !important;}
    h1 {font-size: 1.55rem !important;} h2 {font-size: 1.25rem !important;} h3 {font-size: 1.08rem !important;}
    [data-testid="stMetricValue"] {font-size: 1.1rem;}
    .big-price {font-size: 1.7rem;}
    .status-row {gap:.3rem;} .pill {font-size:.68rem; padding:.12rem .5rem;}
    /* metric cards: two per row instead of one long column */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stMetric"]) {
      flex-wrap: wrap !important; gap: .5rem !important; }
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stMetric"]) > [data-testid="stColumn"] {
      flex: 1 1 calc(50% - .5rem) !important; min-width: calc(50% - .5rem) !important; width: auto !important; }
    /* row lists keep their columns and scroll sideways as one block */
    [class*="st-key-rows_"] {overflow-x: auto; -webkit-overflow-scrolling: touch;}
    [class*="st-key-rows_"] [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: .35rem !important;}
    [class*="st-key-rows_"] [data-testid="stColumn"] {min-width: 0 !important;}
    [class*="st-key-rows_wide"] [data-testid="stHorizontalBlock"] {min-width: 760px;}
    [class*="st-key-rows_"] .cell, [class*="st-key-rows_"] p, [class*="st-key-rows_"] button {font-size: .82rem !important;}
  }
  /* ---------- sign-in screen ---------- */
  .signin-note {opacity:.7; font-size:.85rem;}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- device and sign-in


def _is_mobile() -> bool:
    try:
        ua = (st.context.headers.get("User-Agent") or "").lower()
    except Exception:
        return False
    return any(k in ua for k in ("iphone", "android", "mobile", "ipod")) and "ipad" not in ua


MOBILE = _is_mobile() or os.environ.get("OMNIPULS_MOBILE") == "1"  # env var: preview the phone layout


def _is_public() -> bool:
    """True when served from a public host (e.g. Streamlit Community Cloud) rather than this PC or home Wi-Fi."""
    forced = os.environ.get("OMNIPULS_PUBLIC")
    if forced in ("0", "1"):
        return forced == "1"
    if Path("/mount/src").exists():  # Streamlit Community Cloud
        return True
    try:
        host = (st.context.headers.get("Host") or "").split(":")[0].strip("[]").lower()
    except Exception:
        return False
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return True  # a domain name


PUBLIC = _is_public()
SECRETS_HELP = "Streamlit Cloud → your app → ⋮ → Settings → Secrets"


def lan_url() -> str | None:
    """Address other devices on the same Wi-Fi can use to open the app."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        if ip.startswith("127."):
            return None
        return f"http://{ip}:{st.get_option('server.port')}"
    except Exception:
        return None


def login_screen():
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']{display:none}</style>",
                unsafe_allow_html=True)
    if MOBILE:
        mid = st.container()
    else:
        _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.write("")
        st.image(str(ASSETS / "omnipuls_logo.png"), width=250)
        if not auth.has_users() and PUBLIC:
            st.subheader("Set up the admin account")
            st.markdown("This copy of Omnipuls is on a public server, so accounts can't be created from this "
                        f"screen. Add your admin account to the app's Secrets (**{SECRETS_HELP}**), save, and "
                        "reload this page:")
            st.code('[users.navneet]\nname = "Navneet"\nrole = "admin"\npassword = "choose-a-strong-password"',
                    language="toml")
            st.markdown('<div class="signin-note">Secrets are private to your Streamlit account and are never '
                        'stored in GitHub. Change the user ID, name and password to your own.</div>',
                        unsafe_allow_html=True)
        elif not auth.has_users():
            st.subheader("Create your admin account")
            st.markdown('<div class="signin-note">This is the first start. The admin can add other users, '
                        'connect Dhan and see the portfolio.</div>', unsafe_allow_html=True)
            with st.form("setup_form"):
                name = st.text_input("Your name", key="su_name")
                uid = st.text_input("User ID", key="su_uid", placeholder="e.g. navneet")
                pw = st.text_input("Password", type="password", key="su_pw",
                                   help="At least 8 characters, mixing letters with numbers or symbols.")
                pw2 = st.text_input("Confirm password", type="password", key="su_pw2")
                ok = st.form_submit_button("Create account and sign in", type="primary", width="stretch")
            if ok:
                if pw != pw2:
                    st.error("The two passwords don't match.")
                else:
                    err = auth.create(uid, pw, "admin", name)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.user = auth.verify(uid, pw)
                        st.rerun()
        else:
            st.subheader("Sign in")
            with st.form("login_form"):
                uid = st.text_input("User ID", key="li_uid", autocomplete="username")
                pw = st.text_input("Password", type="password", key="li_pw", autocomplete="current-password")
                ok = st.form_submit_button("Sign in", type="primary", width="stretch")
            if ok:
                wait = auth.locked_for(uid)
                user = None if wait else auth.verify(uid, pw)
                if user:
                    st.session_state.user = user
                    st.rerun()
                wait = auth.locked_for(uid)
                st.error(f"Too many wrong passwords. Try again in {wait // 60 + 1} min." if wait
                         else "Wrong user ID or password.")
            st.markdown('<div class="signin-note">Forgot your password? Ask the admin to reset it under '
                        '<b>Account</b>. The admin can reset their own by running <code>reset_password.py</code> '
                        'on the computer that runs Omnipuls.</div>', unsafe_allow_html=True)


if "user" not in st.session_state or not auth.load().get(st.session_state.user.get("id", "")):
    st.session_state.pop("user", None)
    login_screen()
    st.stop()
USER = st.session_state.user
IS_ADMIN = USER.get("role") == "admin"
_BOOT = st.empty()  # shown only while the app starts up (Dhan check, instrument lists), cleared before the page
if not st.session_state.get("_booted"):
    _BOOT.info("Starting Omnipuls: checking Dhan and loading instrument lists. The first start on a computer can "
               "take 1-2 minutes; after that pages open in seconds. If this stays for more than 3 minutes, look at "
               "the black command window for an error.", icon=":material/hourglass_top:")


# ---------------------------------------------------------------- layouts (Account > Appearance)

LAYOUTS = {
    "Clean Corporate": {
        "about": "Near-black sidebar with a thin divider; frameless tables with a slate header and subtle dark stripes.",
        "page": "#0B1220", "sb": "#070D18", "sb_edge": "1px solid #22314A", "sb_active": "rgba(56,189,248,.14)",
        "sb_bar": "transparent", "accent": "#3B82F6",
        "t_border": "none", "t_radius": "0px", "t_line": "#22314A", "h_bg": "#1E293B", "h_fg": "#E6EDF7",
        "h_case": "none", "h_weight": "600", "h_rule": "none", "even": "#0F1828", "odd": "#131D2F", "hover": "#1A2740",
        "card": "#131D2F", "card_line": "#22314A",
    },
    "Modern Minimalist": {
        "about": "Charcoal sidebar with an electric-blue edge; framed, rounded tables with uppercase headers and soft stripes.",
        "page": "#0F172A", "sb": "#0B1220", "sb_edge": "4px solid #3B82F6", "sb_active": "rgba(59,130,246,.18)",
        "sb_bar": "transparent", "accent": "#3B82F6",
        "t_border": "1px solid #334155", "t_radius": "12px", "t_line": "transparent", "h_bg": "#0F172A",
        "h_fg": "#E2E8F0", "h_case": "uppercase", "h_weight": "700", "h_rule": "2px solid #3B82F6", "even": "#111B2E",
        "odd": "#162238", "hover": "#1E2D4A", "card": "#162238", "card_line": "#334155",
    },
    "Vibrant Accent": {
        "about": "Slate sidebar with an emerald bar on the active page; tables framed in slate with emerald-tinted stripes.",
        "page": "#0D1117", "sb": "#161B22", "sb_edge": "1px solid #30363D", "sb_active": "rgba(16,185,129,.18)",
        "sb_bar": "#10B981", "accent": "#10B981",
        "t_border": "1px solid #30363D", "t_radius": "8px", "t_line": "#21262D", "h_bg": "#21262D", "h_fg": "#E6EDF3",
        "h_case": "none", "h_weight": "700", "h_rule": "none", "even": "#0D1117", "odd": "#0F1A17", "hover": "#12291F",
        "card": "#161B22", "card_line": "#30363D",
    },
}
LAYOUT_NAME = auth.get_pref(USER["id"], "layout", "Clean Corporate")
if LAYOUT_NAME not in LAYOUTS:
    LAYOUT_NAME = "Clean Corporate"
LAYOUT = LAYOUTS[LAYOUT_NAME]
L = LAYOUT
st.markdown(f"""<style>
  .stApp, [data-testid="stAppViewContainer"] {{background: {L['page']};}}
  section[data-testid="stSidebar"] {{background: {L['sb']} !important; border-right: {L['sb_edge']} !important;}}
  section[data-testid="stSidebar"] > div {{background: {L['sb']} !important;}}
  a[data-testid="stSidebarNavLink"][aria-current="page"] {{background: {L['sb_active']} !important;
      box-shadow: inset 4px 0 0 {L['sb_bar']}; border-radius: 6px;}}
  a[data-testid="stSidebarNavLink"]:hover {{background: rgba(255,255,255,.07) !important;}}
  section[data-testid="stSidebar"] .muted, section[data-testid="stSidebar"] .pill {{color: #E2E8F0;}}
  [data-testid="stMetric"] {{background: {L['card']}; border-color: {L['card_line']} !important;}}
  [data-testid="stExpander"] details {{background: {L['card']};}}
</style>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- persistence


DATA_FILE = Path(__file__).with_name(f"watchlist_{USER['id']}.json")
_OLD = Path(__file__).with_name("watchlist.json")
if IS_ADMIN and not DATA_FILE.exists() and _OLD.exists():  # keep the watchlist from before accounts existed
    try:
        DATA_FILE.write_text(_OLD.read_text())
    except Exception:
        pass


def load_store() -> dict:
    try:
        return json.loads(DATA_FILE.read_text())
    except Exception:
        return {"watchlist": ["^NSEI", "RELIANCE.NS", "HDFCBANK.NS", "GC=F", "BTC-USD", "USDINR=X"], "alerts": []}


def save_store(store: dict):
    try:
        DATA_FILE.write_text(json.dumps(store, indent=2))
    except Exception as e:
        st.warning(f"Could not save the watchlist file: {e}")


if "store" not in st.session_state:
    st.session_state.store = load_store()
store = st.session_state.store
st.session_state.setdefault("detail_pick", "^NSEI")

# ---------------------------------------------------------------- Dhan connection

DCFG = D.load_config()


@st.cache_data(ttl=600, show_spinner=False)
def dhan_status(sig: tuple) -> dict:
    """Checks the token and data plan. sig changes when credentials change, which refreshes this."""
    try:
        p = D.profile(DCFG)
        return {"ok": True, "data": D.data_active(p), "profile": p}
    except D.DhanError as e:
        if e.code == "NETWORK":
            raise  # not cached; retried next run
        return {"ok": False, "data": False, "error": e.friendly, "code": e.code}


def _dhan_sig():
    return (str(DCFG.get("client_id")), str(DCFG.get("access_token", ""))[-16:])


if D.configured(DCFG):
    try:
        DS = dhan_status(_dhan_sig())
        sec_tok = DCFG.get("_secret_token")
        if not DS["ok"] and DS.get("code") in ("DH-901", "401", "807", "808", "809") and sec_tok \
                and sec_tok != DCFG.get("access_token"):
            DCFG["access_token"] = sec_tok  # the token pasted in the app expired; Secrets has a different one
            DS = dhan_status(_dhan_sig())
    except Exception as _e:
        DS = {"ok": False, "data": False, "error": f"Could not reach Dhan ({_e}).", "code": "NETWORK"}
else:
    DS = {"ok": False, "data": False, "error": None, "code": "NOCONFIG"}
DHAN_ON = DS["ok"]
DHAN_DATA = DHAN_ON and DS["data"] and DCFG.get("use_for_data", True)


@st.cache_resource(show_spinner=False)
def _renew_attempts() -> dict:
    return {}  # token tail -> time tried, shared by all sessions so a token is renewed once


def auto_renew_token():
    """A token can only be renewed while it is still valid: do it in its last 3 hours, so the app keeps working."""
    try:
        valid = datetime.strptime(str(DS["profile"].get("tokenValidity", "")), "%d/%m/%Y %H:%M").replace(tzinfo=IST)
    except Exception:
        return
    left = (valid - datetime.now(IST)).total_seconds()
    tried = _renew_attempts()
    tail = str(DCFG.get("access_token", ""))[-16:]
    if not (0 < left < 3 * 3600) or time.time() - tried.get(tail, 0) < 1800:
        return
    tried[tail] = time.time()
    try:
        if D.renew_token(DCFG):
            dhan_status.clear()
    except Exception as e:
        tried["error"] = f"{datetime.now(IST):%d %b %H:%M}: {getattr(e, 'friendly', e)}"


if DHAN_ON:
    auto_renew_token()


@st.cache_resource(show_spinner=False)
def get_feed(sig: tuple, version=None):
    """One live Dhan feed per set of credentials, shared by every page and browser tab."""
    for old in list(F.INSTANCES):
        old.stop()
        F.INSTANCES.remove(old)
    f = F.DhanFeed(DCFG["client_id"], DCFG["access_token"])
    F.INSTANCES.append(f)
    return f


FEED = get_feed(_dhan_sig(), getattr(F, "VERSION", 1)) if DHAN_DATA and DCFG.get("live_feed", True) else None


def feed_state(f) -> tuple[str, str]:
    """Feed status for the UI; works even with an older feed object still running."""
    if hasattr(f, "state"):
        return f.state()
    if getattr(f, "error", ""):
        return "error", f.error
    return ("live", "Dhan live ticks") if getattr(f, "connected", False) else ("connecting", "Dhan live feed connecting…")

# ---------------------------------------------------------------- formatting


def indian_group(n: float, dec: int = 2) -> str:
    """12345678.9 -> '1,23,45,678.90'"""
    neg = n < 0
    s = f"{abs(n):.{dec}f}"
    whole, frac = (s.split(".") + [""])[:2]
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + ("." + frac if frac else "")


def decimals_for(p: float) -> int:
    a = abs(p)
    return 5 if a < 2 else 4 if a < 20 else 2


def fmt_price(p, sym="") -> str:
    if p is None or pd.isna(p):
        return "—"
    g = U.group_of(sym)
    if g == "F&O Stocks":
        return "₹" + indian_group(p)
    if g == "Indian Indices":
        return indian_group(p)
    if g == "MCX (Dhan)":
        return "₹" + indian_group(p)
    if g == "Currency Futures (Dhan)":
        return (f"₹{p:,.4f}" if sym.endswith("INR") else f"{p:,.4f}")
    if sym.endswith("INR=X"):
        return f"₹{p:,.{decimals_for(p)}f}"
    if sym.endswith("-USD") or sym.endswith("=F") or sym == "XAUUSD=X":
        return f"${p:,.{decimals_for(p)}f}"
    return f"{p:,.{decimals_for(p)}f}"


def fmt_vol(v, sym="") -> str:
    if v is None or pd.isna(v) or v == 0:
        return "—"
    if sym.endswith((".NS", ".BO")):
        if v >= 1e7:
            return f"{v / 1e7:.2f} Cr"
        if v >= 1e5:
            return f"{v / 1e5:.2f} L"
        return f"{v:,.0f}"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v / div:.2f}{unit}"
    return f"{v:,.0f}"


def chg_html(chg: float, abs_chg: float | None = None) -> str:
    if chg is None or pd.isna(chg):
        return '<span class="muted">—</span>'
    cls = "chg-up" if chg >= 0 else "chg-down"
    arrow = "▲" if chg >= 0 else "▼"
    a = ""
    if abs_chg is not None and not pd.isna(abs_chg):
        a = f"{abs_chg:+,.{decimals_for(abs_chg) if abs_chg else 2}f} "
    return f'<span class="{cls}">{arrow} {a}({chg:+.2f}%)</span>'


def verdict(score) -> str:
    if score is None or pd.isna(score):
        return "—"
    return "Strong bullish" if score >= 4 else "Bullish" if score >= 2 else \
        "Strong bearish" if score <= -4 else "Bearish" if score <= -2 else "Neutral"


def name_of(sym: str) -> str:
    return U.all_names().get(sym, sym.replace(".NS", ""))

# ---------------------------------------------------------------- data


def _clean(df: pd.DataFrame):
    if df is None or df.empty:
        return None
    df = df.copy()
    df.columns = [str(c).title() if str(c).lower() != "adj close" else "Adj Close" for c in df.columns]
    if "Close" not in df:
        return None
    df = df.dropna(subset=["Close"])
    if df.empty:
        return None
    if "Volume" not in df:
        df["Volume"] = 0.0
    for c in ("Open", "High", "Low"):
        if c not in df:
            df[c] = df["Close"]
        df[c] = df[c].fillna(df["Close"])
    return df


def _download(symbols: tuple, period: str, interval: str) -> dict:
    out = {}
    if not symbols:
        return out
    raw = yf.download(list(symbols), period=period, interval=interval, group_by="ticker",
                      auto_adjust=False, threads=True, progress=False)
    if raw is None or raw.empty:
        return out
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = set(raw.columns.get_level_values(0))
        lvl1 = set(raw.columns.get_level_values(1))
        for s in symbols:
            if s in lvl0:
                df = raw[s]
            elif s in lvl1:
                df = raw.xs(s, axis=1, level=1)
            else:
                continue
            df = _clean(df)
            if df is not None:
                out[s] = df
    elif len(symbols) == 1:
        df = _clean(raw)
        if df is not None:
            out[symbols[0]] = df
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_hist(symbols: tuple) -> dict:
    """One year of daily bars; refreshed every 30 minutes."""
    data = _download(symbols, "1y", "1d")
    if not data:
        raise RuntimeError("No data returned")  # errors are not cached, so the next refresh retries
    return data


@st.cache_data(ttl=25, show_spinner=False)
def fetch_live(symbols: tuple) -> dict:
    """Last few daily bars, including today's live bar."""
    return _download(symbols, "5d", "1d")


def _yahoo_daily(symbols: tuple) -> dict:
    hist = fetch_hist(symbols)
    try:
        live = fetch_live(symbols)
    except Exception:
        live = {}
    out = {}
    for s in symbols:
        h, l = hist.get(s), live.get(s)
        if h is None and l is None:
            continue
        if h is None or l is None:
            out[s] = h if h is not None else l
            continue
        out[s] = pd.concat([h[h.index < l.index[0]], l])
    return out

# ---- Dhan market data

DSTAT: dict = {}  # last Dhan problems and loading progress, shown in the sidebar
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def dhan_maps(sig: tuple) -> dict:
    return {"idx": D.index_ids(DCFG), "eq": D.equity_ids(DCFG)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def dhan_futmap(sig: tuple, seg: str, instrument: str) -> dict:
    out = D.nearest_futures(seg, instrument, cfg=DCFG)
    if not out:
        raise RuntimeError("no contracts")
    return out


def _maps():
    try:
        return dhan_maps(_dhan_sig())
    except Exception as e:
        DSTAT["error"] = f"Dhan instrument list: {e}"
        return None


def futmap(seg: str, instrument: str) -> dict:
    try:
        return dhan_futmap(_dhan_sig(), seg, instrument)
    except Exception as e:
        DSTAT["error"] = f"Dhan contract list ({seg}): {e}"
        return {}


def dhan_ref(sym: str):
    """(segment, security id, instrument) when Dhan can price this symbol, else None."""
    if not DHAN_DATA:
        return None
    if sym.startswith(("MCX:", "CDS:", "FUT:")):
        seg, ins = {"MCX": ("MCX_COMM", "FUTCOM"), "CDS": ("NSE_CURRENCY", "FUTCUR"),
                    "FUT": ("NSE_FNO", "FUTSTK")}[sym[:3]]
        f = futmap(seg, ins).get(sym[4:])
        return (seg, f["id"], ins) if f else None
    m = _maps()
    if not m:
        return None
    label = U.index_label(sym)
    if label:
        i = m["idx"].get(label)
        return ("IDX_I", i, "INDEX") if i else None
    if sym.endswith(".NS"):
        i = m["eq"].get(sym[:-3].upper())
        return ("NSE_EQ", i, "EQUITY") if i else None
    return None


@st.cache_data(ttl=4, show_spinner=False)
def dhan_quotes(pairs: tuple) -> dict:
    return D.quotes(list(pairs), DCFG)


def quotes_for(refs) -> dict:
    """Latest quote per (segment, id): from the live feed when running, otherwise Dhan's REST API."""
    pairs = tuple(sorted({(r[0], int(r[1])) for r in refs}))
    if not pairs:
        return {}
    out, missing = {}, []
    if FEED is not None:
        FEED.subscribe(pairs)
        for p in pairs:
            q = FEED.quote(*p)
            if q:
                out[p] = q
            else:
                missing.append(p)
    else:
        missing = list(pairs)
    if missing:  # first view of new instruments: one REST call, then ticks take over
        try:
            out.update(dhan_quotes(tuple(missing)))
        except Exception as e:
            DSTAT["error"] = f"Dhan quotes: {getattr(e, 'friendly', e)}"
    return out


def dhan_histories(refs: dict, budget: float = 3.0, days: int = 400, oi: bool = False) -> dict:
    """Daily history per symbol. Downloads at most `budget` seconds per run; the rest fill in on later refreshes."""
    out, pending = {}, []
    for s, (seg, sid, ins) in refs.items():
        h = D.history_peek(seg, sid, days, oi)
        if h is None:
            pending.append(s)
        else:
            out[s] = h
    t0 = time.monotonic()
    for s in pending:
        if time.monotonic() - t0 > budget:
            break
        seg, sid, ins = refs[s]
        try:
            out[s] = D.history_cached(seg, sid, ins, days=days, oi=oi, cfg=DCFG)
        except Exception as e:
            DSTAT["error"] = f"Dhan history: {getattr(e, 'friendly', e)}"
            break
    left = sum(1 for s in refs if s not in out)
    DSTAT["hist_left" + ("_oi" if oi else "")] = left
    return out


def dhan_daily(symbols: tuple) -> dict:
    refs = {s: r for s in symbols if (r := dhan_ref(s))}
    q = quotes_for(refs.values())
    hist = dhan_histories(refs)
    out = {}
    for s, (seg, sid, ins) in refs.items():
        h = hist.get(s)
        h = h[OHLCV] if h is not None and not h.empty else pd.DataFrame(columns=OHLCV)
        qq = q.get((seg, int(sid)))
        bar = D.quote_to_bar(qq)
        if bar:
            td = pd.Timestamp(D.session_date(qq, seg))
            prev = bar.pop("PrevClose")
            live = D.market_live(seg)
            if h.empty and prev:  # history not loaded yet: use the previous close so change % still works
                h = pd.DataFrame([{"Open": prev, "High": prev, "Low": prev, "Close": prev, "Volume": 0.0}],
                                 index=pd.DatetimeIndex([td - pd.Timedelta(days=1)]))
            if h.empty or td > h.index[-1]:
                # During the session Dhan's ohlc.close is the official previous close; use it so today's change
                # matches the broker. After hours that field holds the day's close, so history is used instead.
                if (live or qq.get("_feed")) and prev and not h.empty and abs(float(h["Close"].iloc[-1]) / prev - 1) > 1e-4:
                    h = h.copy()
                    h.iloc[-1, h.columns.get_loc("Close")] = prev
                h = pd.concat([h, pd.DataFrame([bar], index=pd.DatetimeIndex([td]))[OHLCV]])
            # else: history already holds this session's final bar (e.g. overnight), so nothing to add
        if not h.empty:
            out[s] = h.astype(float)
    return out


def fetch_daily(symbols: tuple) -> dict:
    out = {}
    if DHAN_DATA:
        dsyms = tuple(s for s in symbols if dhan_ref(s))
        if dsyms:
            try:
                out.update(dhan_daily(dsyms))
            except Exception as e:
                DSTAT["error"] = f"Dhan: {getattr(e, 'friendly', e)}"
    rest = tuple(s for s in symbols if s not in out and not s.startswith(("MCX:", "CDS:", "FUT:")))
    if rest:
        try:
            out.update(_yahoo_daily(rest))
        except Exception:
            if not out:
                raise
    return out


@st.cache_data(ttl=20, show_spinner=False)
def fetch_history(symbol: str, period: str, interval: str):
    data = _download((symbol,), period, interval)
    df = data.get(symbol)
    if df is not None and isinstance(df.index, pd.DatetimeIndex) and interval not in ("1d", "1wk", "1mo"):
        idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
        df.index = idx.tz_convert("Asia/Kolkata")
    return df


DHAN_INTRA = {"1m": (1, 5), "5m": (5, 10), "15m": (15, 30), "25m": (25, 45), "1h": (60, 90)}


@st.cache_data(ttl=5, show_spinner=False)
def dhan_intraday(seg: str, sid: int, ins: str, tf: str) -> pd.DataFrame:
    interval, days = DHAN_INTRA[tf]
    return D.intraday(seg, sid, ins, interval, days, DCFG)


def chart_data(sym: str, tf: str, period: str, interval: str):
    """Bars for the chart page: Dhan for Indian symbols when connected, otherwise Yahoo."""
    ref = dhan_ref(sym)
    if ref:
        seg, sid, ins = ref
        if tf in DHAN_INTRA:
            return dhan_intraday(seg, sid, ins, tf), "Dhan"
        days = {"1D": 400, "1W": 1900, "1M": 3700}[tf]
        h = D.history_cached(seg, sid, ins, days=days, cfg=DCFG)[OHLCV] if days != 400 else pd.DataFrame()
        live = dhan_daily((sym,)).get(sym)
        if days == 400:
            return live, "Dhan"
        if live is not None and not live.empty:
            h = pd.concat([h, live[live.index > (h.index[-1] if not h.empty else pd.Timestamp(0))]])
        rule = "W-FRI" if tf == "1W" else "ME"
        h = h.resample(rule).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        return h.dropna(subset=["Close"]), "Dhan"
    if tf == "25m":
        return None, "Yahoo"
    return fetch_history(sym, period, interval), "Yahoo"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def resolve(specs: tuple) -> dict:
    """specs: ((label, (cand1, cand2, ...)), ...) -> {label: first candidate that has data}."""
    cands = tuple(dict.fromkeys(c for _, cs in specs for c in cs))
    data = fetch_hist(cands)
    out = {}
    for label, cs in specs:
        for c in cs:
            if c in data and len(data[c]) > 5:
                out[label] = c
                break
    if not out:
        raise RuntimeError("No index data")
    return out


def resolved(specs_list) -> dict:
    found, pending = {}, []
    for label, cs in specs_list:
        hit = next((c for c in cs if dhan_ref(c)), None) if DHAN_DATA else None
        if hit:
            found[label] = hit
        else:
            pending.append((label, tuple(cs)))
    if pending:
        try:
            found.update(resolve(tuple(pending)))
        except Exception:
            pass
    return {label: found[label] for label, _ in specs_list if label in found}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_info(symbol: str) -> dict:
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_news(symbol: str) -> list:
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:
        return []
    items = []
    for n in raw[:10]:
        c = n.get("content", n)
        title = c.get("title")
        url = None
        for k in ("canonicalUrl", "clickThroughUrl"):
            if isinstance(c.get(k), dict) and c[k].get("url"):
                url = c[k]["url"]
                break
        url = url or c.get("link")
        pub = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
        when = c.get("pubDate") or c.get("providerPublishTime")
        if isinstance(when, (int, float)):
            when = datetime.fromtimestamp(when, IST).strftime("%d %b %Y, %H:%M")
        elif isinstance(when, str):
            try:
                when = pd.Timestamp(when).tz_convert("Asia/Kolkata").strftime("%d %b %Y, %H:%M")
            except Exception:
                pass
        if title:
            items.append({"title": title, "url": url, "publisher": pub, "when": when})
    return items


@st.cache_data(ttl=4, show_spinner=False)
def _build_table(symbols: tuple, names: tuple, mode: bool) -> pd.DataFrame:
    data = fetch_daily(symbols)
    nm = dict(names)
    refs = {s: r for s in symbols if (r := dhan_ref(s))} if mode else {}
    q = quotes_for(refs.values()) if refs else {}
    rows = []
    for s in symbols:
        df = data.get(s)
        if df is None:
            continue
        r = ind.screener_row(df)
        if r is None:
            continue
        r.update({"Symbol": s, "Name": nm.get(s) or name_of(s), "Market": U.group_of(s),
                  "Turnover": r["Price"] * r["Volume"], "Last bar": df.index[-1],
                  "Source": "Dhan" if s in refs else "Yahoo"})
        qq = q.get((refs[s][0], int(refs[s][1]))) if s in refs else None
        if qq:
            r.update({"Avg Price": qq.get("average_price"), "Upper Circuit": qq.get("upper_circuit_limit"),
                      "Lower Circuit": qq.get("lower_circuit_limit"), "Buy Qty": qq.get("buy_quantity"),
                      "Sell Qty": qq.get("sell_quantity"), "OI": qq.get("oi"),
                      "Last Trade": qq.get("last_trade_time")})
        rows.append(r)
    if not rows:
        return pd.DataFrame()
    t = pd.DataFrame(rows)
    t["Rating"] = t["Score"].map(verdict)
    return t


def build_table(symbols: tuple, names: tuple = ()) -> pd.DataFrame:
    """Screener metrics for each symbol. names: optional ((symbol, display name), ...)."""
    return _build_table(symbols, names, bool(DHAN_DATA))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fno_universe() -> tuple[dict, str]:
    lots, src = fno.load()
    if src.startswith("built-in") and DHAN_DATA:  # NSE blocked (often from cloud servers): use Dhan's contract list
        try:
            d = D.fno_underlyings(DCFG)
            if len(d) > 50:
                return d, "Dhan F&O contract list"
        except Exception:
            pass
    return lots, src


INDEX_FUT = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "FINNIFTY": "Fin Nifty", "MIDCPNIFTY": "Midcap Select",
             "NIFTYNXT50": "Nifty Next 50"}


def buildup(price_chg, oi_chg) -> str:
    if pd.isna(price_chg) or pd.isna(oi_chg) or (price_chg == 0 and oi_chg == 0):
        return ""
    if price_chg >= 0:
        return "Long buildup" if oi_chg > 0 else "Short covering"
    return "Short buildup" if oi_chg > 0 else "Long unwinding"


def fno_futures_oi(stocks: list, instrument: str = "FUTSTK") -> pd.DataFrame:
    """Nearest future per underlying: price change, OI, OI change and buildup (Dhan)."""
    fm = futmap("NSE_FNO", instrument)
    refs = {s: ("NSE_FNO", fm[s]["id"], instrument) for s in stocks if s in fm}
    if not refs:
        return pd.DataFrame()
    q = quotes_for(refs.values())
    need_hist = {s: r for s, r in refs.items()
                 if not (q.get((r[0], int(r[1]))) or {}).get("prev_oi")}
    prev = dhan_histories(need_hist, budget=5.0, days=10, oi=True) if need_hist else {}
    if not need_hist:
        DSTAT["hist_left_oi"] = 0
    rows = []
    for s, (seg, sid, _) in refs.items():
        qq = q.get((seg, int(sid))) or {}
        ltp, oi = qq.get("last_price"), qq.get("oi")
        td = D.session_date(qq, seg)
        h = prev.get(s)
        before = h[h.index.date < td] if h is not None and not h.empty else None
        if qq.get("prev_oi"):  # live feed: exchange's previous close and previous-day OI
            prev_px = (qq.get("ohlc") or {}).get("close") or np.nan
            prev_oi = float(qq["prev_oi"])
        elif before is not None and not before.empty:
            prev_px = float(before["Close"].iloc[-1])
            prev_oi = float(before["OI"].iloc[-1]) if "OI" in before and before["OI"].iloc[-1] > 0 else np.nan
        else:
            prev_px = (qq.get("ohlc") or {}).get("close") if D.market_live(seg) else np.nan
            prev_oi = np.nan
        rows.append({"Stock": s, "Fut LTP": ltp, "Fut Chg %": ind.pct(ltp, prev_px) if ltp and prev_px else np.nan,
                     "OI": oi, "Prev OI": prev_oi, "OI Chg": (oi - prev_oi) if oi and pd.notna(prev_oi) else np.nan,
                     "OI Chg %": ind.pct(oi, prev_oi) if oi and pd.notna(prev_oi) else np.nan,
                     "Fut Volume": qq.get("volume"), "Fut Expiry": fm[s]["expiry"], "Fut Lot": fm[s]["lot"],
                     "OI Value Cr": (oi or 0) * (ltp or 0) / 1e7})
    f = pd.DataFrame(rows)
    f["Buildup"] = [buildup(p, o) for p, o in zip(f["Fut Chg %"], f["OI Chg %"])]
    return f


def fno_table(with_oi: bool = False) -> tuple[pd.DataFrame, str, list]:
    lots, src = fno_universe()
    syms = tuple(U.fno_yahoo(s) for s in sorted(lots))
    t = build_table(syms)
    if t.empty:
        return t, src, list(syms)
    t = t.copy()
    t["Stock"] = t["Symbol"].str.replace(".NS", "", regex=False)
    t["Sector"] = t["Stock"].map(U.FNO_SECTOR_OF).fillna("Other")
    t["Lot size"] = t["Stock"].map(lots)
    if with_oi and DHAN_DATA:
        f = fno_futures_oi(t["Stock"].tolist())
        if not f.empty:
            t = t.merge(f, on="Stock", how="left")
            t["Lot size"] = t["Lot size"].fillna(t["Fut Lot"])
            t["Basis"] = t["Fut LTP"] - t["Price"]
    t["Lot value"] = t["Lot size"] * t["Price"]
    t["Turnover Cr"] = t["Turnover"] / 1e7
    missing = sorted(set(syms) - set(t["Symbol"]))
    return t, src, missing


def safe(fn, *args):
    try:
        return fn(*args), None
    except Exception as e:  # network / rate limit
        return None, str(e)


def no_data_msg(err=None):
    if D.configured(DCFG) and not DHAN_DATA:
        # Dhan is set up but not usable, so Indian prices fell back to Yahoo, which often blocks cloud servers
        why = DS.get("error") or ("Dhan Data APIs are not active on this account." if DHAN_ON else
                                  "Dhan is not reachable.")
        st.error(f"**Market data did not load because Dhan is not connected right now:** {why}  \n"
                 + ("On Streamlit Cloud, Yahoo usually refuses requests, so F&O prices need a working Dhan token. "
                    if PUBLIC else "")
                 + "Dhan tokens last 24 hours: generate a new one on web.dhan.co and paste it in **Dhan Connect**"
                 + (f" (or update it in {SECRETS_HELP})." if PUBLIC else ".")
                 + (f"\n\nDetails: `{err}`" if err else ""), icon=":material/link_off:")
        if "P" in globals() and "dhan" in P and IS_ADMIN:
            st.page_link(P["dhan"], label="Open Dhan Connect", icon=":material/settings:")
        return
    st.error("Could not load market data from Yahoo Finance. Check your internet connection and press "
             "**Refresh now**. If it keeps failing, Yahoo may be limiting requests: set refresh to 2 min or more."
             + (" On Streamlit Cloud Yahoo often refuses requests: connect Dhan for Indian prices." if PUBLIC else "")
             + (f"\n\nDetails: `{err}`" if err else ""))

# ---------------------------------------------------------------- market status


def market_status(now_ist: datetime) -> list[tuple[str, str, str]]:
    wd, t = now_ist.weekday(), now_ist.time()
    hm = lambda s: datetime.strptime(s, "%H:%M").time()  # noqa: E731
    if wd < 5 and hm("09:15") <= t < hm("15:30"):
        nse = ("NSE / BSE", "Open", "open")
    elif wd < 5 and hm("09:00") <= t < hm("09:15"):
        nse = ("NSE / BSE", "Pre-open", "pre")
    else:
        nse = ("NSE / BSE", "Closed", "closed")
    now_utc = now_ist.astimezone(timezone.utc)
    uwd, uh = now_utc.weekday(), now_utc.hour
    fx_open = not (uwd == 5 or (uwd == 4 and uh >= 22) or (uwd == 6 and uh < 22))
    comex_open = fx_open and not (21 <= uh < 22)
    return [nse,
            ("Forex", "Open" if fx_open else "Closed", "open" if fx_open else "closed"),
            ("Gold & Oil", "Open" if comex_open else "Closed", "open" if comex_open else "closed"),
            ("Crypto", "Open 24×7", "open")]


def status_strip():
    now = datetime.now(IST)
    pills = "".join(f'<span class="pill {cls}">{m}: {s}</span>' for m, s, cls in market_status(now))
    live = '<span class="pill"><span class="live-dot"></span>Live</span>' if st.session_state.get("auto", True) else ""
    st.markdown(f'<div class="status-row">{live}{pills}<span class="pill">{now:%a %d %b %Y, %H:%M:%S} IST</span></div>',
                unsafe_allow_html=True)

# ---------------------------------------------------------------- alerts


def check_alerts(prices: dict):
    hits = []
    for a in store.get("alerts", []):
        p = prices.get(a["symbol"])
        if p is None or a.get("triggered"):
            continue
        if (a["cond"] == "above" and p >= a["level"]) or (a["cond"] == "below" and p <= a["level"]):
            a["triggered"] = datetime.now(IST).strftime("%d %b %H:%M")
            hits.append((a, p))
    if hits:
        save_store(store)
        for a, p in hits:
            st.toast(f"Alert: {name_of(a['symbol'])} is {a['cond']} {fmt_price(a['level'], a['symbol'])} "
                     f"(now {fmt_price(p, a['symbol'])})", icon="🔔")

# ---------------------------------------------------------------- navigation helpers


def go_detail(sym: str):
    st.session_state.detail_pick = sym
    st.session_state.goto = "chart"


def go_option_chain(underlying: str):
    st.session_state.oc_under = underlying
    st.session_state.goto = "options"


def dhan_quote_panel(q: dict, sym: str):
    """Market depth and Dhan-only quote details."""
    with st.expander("Market depth & Dhan quote", expanded=True):
        a, b, c, d, e = st.columns(5)
        a.metric("Avg price (VWAP)", fmt_price(q.get("average_price"), sym))
        b.metric("Upper circuit", fmt_price(q.get("upper_circuit_limit"), sym))
        c.metric("Lower circuit", fmt_price(q.get("lower_circuit_limit"), sym))
        bq, sq = q.get("buy_quantity") or 0, q.get("sell_quantity") or 0
        d.metric("Buy / sell qty", f"{fmt_vol(bq, '.NS')} / {fmt_vol(sq, '.NS')}",
                 f"{bq / (bq + sq) * 100:.0f}% buyers" if bq + sq else None, delta_color="off")
        if q.get("oi"):
            e.metric("Open interest", fmt_vol(q.get("oi"), ".NS"),
                     f"day range {fmt_vol(q.get('oi_day_low'), '.NS')} – {fmt_vol(q.get('oi_day_high'), '.NS')}",
                     delta_color="off")
        else:
            e.metric("Last trade", str(q.get("last_trade_time") or "—")[-8:],
                     f"qty {q.get('last_quantity') or 0:,}", delta_color="off")
        depth = q.get("depth") or {}
        buy, sell = depth.get("buy") or [], depth.get("sell") or []
        if buy or sell:
            n = max(len(buy), len(sell))
            rows = []
            for i in range(n):
                bb = buy[i] if i < len(buy) else {}
                ss = sell[i] if i < len(sell) else {}
                rows.append({"Bid orders": bb.get("orders"), "Bid qty": bb.get("quantity"), "Bid": bb.get("price"),
                             "Ask": ss.get("price"), "Ask qty": ss.get("quantity"), "Ask orders": ss.get("orders")})
            dd = pd.DataFrame(rows)
            st.dataframe(dd.style.map(lambda v: f"color: {UP}", subset=["Bid", "Bid qty"])
                         .map(lambda v: f"color: {DOWN}", subset=["Ask", "Ask qty"]).format(precision=2),
                         hide_index=True, width="stretch")


def _table_clicked(key: str):
    sel = st.session_state.get(key)
    syms = st.session_state.get(f"{key}__syms", [])
    try:
        rows = sel.selection.rows
    except AttributeError:
        rows = (sel or {}).get("selection", {}).get("rows", [])
    if rows and rows[0] < len(syms):
        go_detail(syms[rows[0]])


def color_signed(v):
    if not isinstance(v, (int, float)) or pd.isna(v):
        return ""
    return f"color: {UP}" if v > 0 else f"color: {DOWN}" if v < 0 else ""


PCT = st.column_config.NumberColumn(format="%+.2f%%")
COLCFG = {
    "Symbol": None,
    "Price": st.column_config.NumberColumn("LTP", format="%.2f"),
    "Chg": st.column_config.NumberColumn(format="%+.2f"),
    "Chg %": PCT, "Gap %": PCT, "1W %": PCT, "1M %": PCT, "3M %": PCT, "1Y %": PCT,
    "From 52W High %": PCT, "From 52W Low %": PCT,
    "Open": st.column_config.NumberColumn(format="%.2f"),
    "Day High": st.column_config.NumberColumn("High", format="%.2f"),
    "Day Low": st.column_config.NumberColumn("Low", format="%.2f"),
    "Prev Close": st.column_config.NumberColumn(format="%.2f"),
    "52W High": st.column_config.NumberColumn(format="%.2f"),
    "52W Low": st.column_config.NumberColumn(format="%.2f"),
    "Spark": st.column_config.LineChartColumn("30 days", width="small"),
    "Volume": st.column_config.NumberColumn(format="compact"),
    "Vol x Avg": st.column_config.NumberColumn("Vol × avg", format="%.2f×",
                                               help="Today's volume divided by the 20-day average"),
    "RSI": st.column_config.ProgressColumn("RSI 14", format="%.0f", min_value=0, max_value=100, width="small"),
    "ATR %": st.column_config.NumberColumn(format="%.2f%%", help="Average daily range (ATR 14) as % of price"),
    "Score": st.column_config.NumberColumn(help="−5 very bearish to +5 very bullish: price vs EMA20/50/200, "
                                                "MACD vs signal, Supertrend"),
    "Lot size": st.column_config.NumberColumn(format="%d"),
    "Lot value": st.column_config.NumberColumn("Lot value ₹", format="compact",
                                               help="Lot size × LTP: the contract's notional value"),
    "Turnover Cr": st.column_config.NumberColumn("Turnover ₹ Cr", format="%.1f"),
    "Avg Price": st.column_config.NumberColumn("Avg price", format="%.2f", help="Volume-weighted average price today (Dhan)"),
    "Upper Circuit": st.column_config.NumberColumn(format="%.2f"),
    "Lower Circuit": st.column_config.NumberColumn(format="%.2f"),
    "Buy Qty": st.column_config.NumberColumn("Total buy qty", format="compact", help="Pending buy quantity in the order book"),
    "Sell Qty": st.column_config.NumberColumn("Total sell qty", format="compact", help="Pending sell quantity in the order book"),
    "OI": st.column_config.NumberColumn("Fut OI", format="compact", help="Open interest of the nearest future"),
    "OI Chg %": st.column_config.NumberColumn(format="%+.2f%%", help="Open interest change vs previous day"),
    "Fut LTP": st.column_config.NumberColumn(format="%.2f"),
    "Fut Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
    "Basis": st.column_config.NumberColumn(format="%+.2f", help="Future price minus spot price"),
    "Fut Expiry": st.column_config.DateColumn(format="DD MMM"),
    "Prev OI": st.column_config.NumberColumn(format="compact"),
    "OI Chg": st.column_config.NumberColumn("OI change", format="compact"),
    "Fut Volume": st.column_config.NumberColumn(format="compact"),
    "OI Value Cr": st.column_config.NumberColumn("OI value ₹ Cr", format="%.0f", help="Open interest × futures price"),
}


# Column -> (header, cell type, live role). Types are drawn by the table widget; roles update on live ticks.
COLSPEC = {
    "Price": ("LTP", "price", "ltp"), "Chg": ("Chg", "signed", "chg"), "Chg %": ("Chg %", "pct", "pct"),
    "Gap %": ("Gap %", "pct", None), "1W %": ("1W %", "pct", None), "1M %": ("1M %", "pct", None),
    "3M %": ("3M %", "pct", None), "1Y %": ("1Y %", "pct", None), "From 52W High %": ("From 52W high", "pct", None),
    "From 52W Low %": ("From 52W low", "pct", None), "Open": ("Open", "price", None), "Day High": ("High", "price", None),
    "Day Low": ("Low", "price", None), "Prev Close": ("Prev close", "price", None), "52W High": ("52W high", "price", None),
    "52W Low": ("52W low", "price", None), "Avg Price": ("Avg price", "price", None),
    "Upper Circuit": ("Upper circuit", "price", None), "Lower Circuit": ("Lower circuit", "price", None),
    "Fut LTP": ("Fut LTP", "price", None), "Fut Chg %": ("Fut chg %", "pct", None), "Basis": ("Basis", "signed", None),
    "Spark": ("30 days", "spark", None), "Volume": ("Volume", "compact", "vol"), "Vol x Avg": ("Vol × avg", "ratio", None),
    "Turnover Cr": ("Turnover ₹ Cr", "num0", None), "OI Value Cr": ("OI value ₹ Cr", "num0", None),
    "Buy Qty": ("Buy qty", "compact", None), "Sell Qty": ("Sell qty", "compact", None), "OI": ("OI", "compact", None),
    "Prev OI": ("Prev OI", "compact", None), "OI Chg": ("OI chg", "signed0", None), "OI Chg %": ("OI chg %", "pct", None),
    "Fut Volume": ("Fut volume", "compact", None), "Lot size": ("Lot", "int", None), "Fut Lot": ("Lot", "int", None),
    "Lot value": ("Lot value ₹", "compact", None), "ATR %": ("ATR %", "pctu", None), "RSI": ("RSI 14", "rsi", None),
    "Score": ("Score", "signed0", None), "Trend": ("Trend", "badge", None), "Supertrend": ("Supertrend", "badge", None),
    "Rating": ("Rating", "badge", None), "Buildup": ("Buildup", "badge", None), "Fut Expiry": ("Expiry", "text", None),
    "Sector": ("Sector", "text", None), "Market": ("Market", "text", None), "Signals": ("Signals", "text", None),
}
FILTER_COLS = ["Sector", "Market", "Trend", "Buildup", "Rating", "Supertrend"]


def _py(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [_py(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%d %b %Y")
    if hasattr(v, "isoformat"):
        return pd.Timestamp(v).strftime("%d %b")
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def show_table(df: pd.DataFrame, cols: list, key: str, height: int | None = None, signed=None, search_hint: str = ""):
    """Every market table: layout-styled rows, search, sort, filters, gainers/losers chips, CSV, live ticks,
    click a name to open its chart."""
    cols = [c for c in cols if c in df.columns]
    name_col = next((c for c in ("Stock", "Name") if c in cols), cols[0] if cols else None)
    spec = []
    for c in cols:
        label, typ, role = COLSPEC.get(c, (c, "text", None))
        if c == name_col:
            typ = "name"
        dec = 0 if typ in ("num0", "signed0") else None
        typ = {"num0": "num", "signed0": "signed"}.get(typ, typ)
        spec.append({"k": c, "label": label, "t": typ, "role": role, **({"dec": dec} if dec is not None else {})})
    rows = []
    for _, r in df.iterrows():
        row = {c: _py(r[c]) for c in cols}
        sym = r.get("Symbol")
        if isinstance(sym, str):
            row["_sym"] = sym
            ref = dhan_ref(sym) if FEED is not None else None
            if ref:
                row["k"] = F.key(ref[0], ref[1])
        prev = r.get("Prev Close")
        if prev is None and "Price" in r and "Chg" in r and pd.notna(r["Price"]) and pd.notna(r["Chg"]):
            prev = r["Price"] - r["Chg"]
        row["_prev"] = _py(prev)
        rows.append(row)
    filters = [c for c in FILTER_COLS if c in cols and df[c].nunique() > 1][:3]
    live("table", rows, key=key, columns=spec, filters=filters, max_height=height or 640, csv_name=key,
         placeholder=search_hint or f"Search {name_col.lower() if name_col else ''}…")


def data_table(df: pd.DataFrame, key: str, labels: dict | None = None, signed: tuple = (), name_col: str | None = None,
               height: int = 480):
    """Plain records (portfolio, orders, trades) in the same table style, with search and sort."""
    labels = labels or {}
    cols = list(df.columns)
    name_col = name_col or (cols[0] if cols else None)
    spec = []
    for c in cols:
        num = pd.api.types.is_numeric_dtype(df[c])
        t = "name" if c == name_col else ("signed" if c in signed else "num" if num else "text")
        spec.append({"k": c, "label": labels.get(c, c), "t": t})
    rows = [{c: _py(v) for c, v in rec.items()} for rec in df.to_dict("records")]
    live("table", rows, key=key, columns=spec, filters=[], max_height=height, csv_name=key, placeholder="Search…")

# ---------------------------------------------------------------- charts


def plot_template():
    """Plotly template matching the app theme, with transparent backgrounds so charts sit on the page."""
    try:
        base = "plotly_dark" if st.context.theme.type != "light" else "plotly_white"
    except Exception:
        base = "plotly_dark"
    import plotly.io as pio
    t = go.layout.Template(pio.templates[base])
    t.layout.paper_bgcolor = "rgba(0,0,0,0)"
    t.layout.plot_bgcolor = "rgba(0,0,0,0)"
    t.layout.font.family = "Sora, sans-serif"
    grid = "rgba(140,160,190,0.14)" if base == "plotly_dark" else "rgba(30,50,80,0.10)"
    t.layout.xaxis.gridcolor = grid
    t.layout.yaxis.gridcolor = grid
    return t


_tv = components.declare_component("omni_tv", path=str(Path(__file__).resolve().parent / "tvchart"))


def _tv_times(idx, intraday: bool) -> list:
    """Bar times for TradingView Lightweight Charts: IST wall-clock seconds (the chart shows them as-is), or dates."""
    i = pd.DatetimeIndex(idx)
    if i.tz is not None:
        i = i.tz_convert(IST).tz_localize(None)
    if not intraday:
        return [d.strftime("%Y-%m-%d") for d in i]
    return ((i - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).tolist()


def _tv_series(times: list, s) -> list:
    return [[t, None if pd.isna(v) else round(float(v), 6)] for t, v in zip(times, s)]


def tv_chart(df: pd.DataFrame, sym: str, intraday: bool, overlays: list, piv: dict | None, tf_key: str):
    """Candles, overlays, RSI and MACD on a TradingView Lightweight Charts canvas. Gaps (nights, weekends) close up
    by themselves because the time axis is bar-indexed."""
    df = df[~df.index.duplicated(keep="last")].sort_index()
    c = df["Close"]
    t = _tv_times(df.index, intraday)
    has_vol = df["Volume"].fillna(0).sum() > 0
    bars = [[ti, float(o), float(h), float(lo), float(cl), float(v) if pd.notna(v) else 0.0]
            for ti, o, h, lo, cl, v in zip(t, df["Open"], df["High"], df["Low"], c, df["Volume"])]
    lines = []

    def add(name, s, color, label=None, width=1, style=0):
        lines.append({"name": name, "label": label, "color": color, "width": width, "style": style, "data": _tv_series(t, s)})

    palette = {"EMA 20": "#5C9DFF", "EMA 50": GOLD, "EMA 200": "#C77DFF"}
    for name, n in (("EMA 20", 20), ("EMA 50", 50), ("EMA 200", 200)):
        if name in overlays and len(c) > n // 2:
            add(name, ind.ema(c, n), palette[name], name, 2 if n == 200 else 1)
    if "Bollinger (20, 2)" in overlays:
        up, mid, lo = ind.bollinger(c)
        add("BB upper", up, "rgba(150,150,170,.8)", "BB U")
        add("BB mid", mid, "rgba(150,150,170,.45)", None, 1, 2)
        add("BB lower", lo, "rgba(150,150,170,.8)", "BB L")
    if "VWAP" in overlays and intraday and has_vol:
        add("VWAP", ind.vwap(df), "#FF9F43", "VWAP", 2, 1)
    if "Supertrend (10, 3)" in overlays and len(df) > 15:
        line, d = ind.supertrend(df)
        add("Supertrend up", line.where(d == 1), UP, "ST ▲", 2)
        add("Supertrend down", line.where(d == -1), DOWN, "ST ▼", 2)
    levels = []
    if piv and "Pivot levels" in overlays:
        levels = [{"name": k, "price": float(v), "color": GOLD if k == "Pivot" else (DOWN if k.startswith("R") else UP)}
                  for k, v in piv.items()]
    ml, ms, mh = ind.macd(c)
    _tv(bars=bars, lines=lines, levels=levels, vol=bool(has_vol), rsi=_tv_series(t, ind.rsi(c)),
        macd={"line": _tv_series(t, ml), "signal": _tv_series(t, ms), "hist": _tv_series(t, mh)},
        precision=decimals_for(float(c.iloc[-1])), intraday=intraday, title=f"{name_of(sym)} · {tf_key}",
        rev=f"{sym}-{tf_key}", height=560 if MOBILE else 760, mobile=MOBILE, key="main_chart", default=None)


def tile(col, label, sym, df):
    with col:
        if df is None or len(df) < 2:
            st.metric(label, "—", border=True)
            return
        last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
        chg = (last / prev - 1) * 100
        st.metric(label, fmt_price(last, sym), f"{last - prev:+,.{decimals_for(last)}f} ({chg:+.2f}%)",
                  chart_data=df["Close"].tail(30).tolist(), chart_type="area", border=True,
                  delta_color="inverse" if sym in ("^INDIAVIX", "USDINR=X") else "normal")


def ticker_tape(items: list[tuple[str, str, float, float]]):
    """items: (label, symbol, price, chg %)"""
    parts = []
    for label, sym, p, chg in items:
        cls = "chg-up" if chg >= 0 else "chg-down"
        arrow = "▲" if chg >= 0 else "▼"
        parts.append(f'<span class="tape-item"><b>{label}</b>{fmt_price(p, sym)} '
                     f'<span class="{cls}">{arrow} {chg:+.2f}%</span></span>')
    row = "".join(parts)
    st.markdown(f'<div class="tape"><div class="tape-track">{row}{row}</div></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- pages


def hist_note():
    left = DSTAT.get("hist_left", 0)
    if DHAN_DATA and left:
        st.info(f"Loading daily history from Dhan for indicators (RSI, EMAs, 52-week range): {left} symbols to go. "
                "Prices are already live; indicator columns fill in over the next few refreshes. "
                "This happens once a day.", icon="⏳")


_live = components.declare_component("omni_live", path=str(Path(__file__).resolve().parent / "livecomp"))


def live_item(sym: str, label: str, price=None, prev=None, **extra) -> dict:
    """One row/tile for the live widget. Instruments Dhan streams get a feed key and update tick by tick."""
    ref = dhan_ref(sym) if FEED is not None else None
    g = U.group_of(sym)
    if g in ("F&O Stocks", "MCX (Dhan)"):
        fmt = {"prefix": "₹", "locale": "en-IN", "dec": 2}
    elif g == "Indian Indices":
        fmt = {"prefix": "", "locale": "en-IN", "dec": 2}
    elif g == "Currency Futures (Dhan)" or sym.endswith("=X"):
        fmt = {"prefix": "₹" if "INR" in sym else "", "locale": "en-IN", "dec": 4}
    else:
        fmt = {"prefix": "$", "locale": "en-US", "dec": 2 if (price or 0) >= 1 else 5}
    it = {"sym": sym, "label": label, "price": None if price is None or pd.isna(price) else float(price),
          "prev": None if prev is None or pd.isna(prev) else float(prev), **fmt}
    if ref:
        it["k"] = F.key(ref[0], ref[1])
    for k2, v in extra.items():
        if isinstance(v, (float, np.floating)) and pd.isna(v):
            v = None
        elif isinstance(v, (np.integer, np.floating)):
            v = v.item()
        it[k2] = v
    return it


def _clicked(val, key: str) -> bool:
    if isinstance(val, dict) and val.get("nonce") and val["nonce"] != st.session_state.get(f"_lv_{key}"):
        st.session_state[f"_lv_{key}"] = val["nonce"]
        go_detail(val["open"])
        return True
    return False


def live(kind: str, items: list, key: str, **kw):
    """Render a live widget; clicking an instrument opens its chart.

    On this PC or home Wi-Fi, ticks stream straight to the browser from the local relay. On a public server
    (Streamlit Cloud) that port isn't reachable, so the widget is re-sent the latest ticks every 1-2 seconds."""
    keys = sorted({it["k"] for it in items if it.get("k")})
    if FEED is not None and PUBLIC and keys:
        every = 1.0 if len(items) <= 60 else 2.0

        @st.fragment(run_every=every)
        def _polled():
            ticks = {}
            for k in keys:
                t = FEED.ticks.get(k)
                if t and t.get("ltp"):
                    ticks[k] = F.DhanFeed._compact(t)
            val = _live(kind=kind, items=items, port=0, key=key, default=None, style=LAYOUT, ticks=ticks, **kw)
            if _clicked(val, key):
                st.rerun(scope="app")

        _polled()
        return None
    val = _live(kind=kind, items=items, port=(FEED.relay_port if FEED is not None else 0), key=key, default=None,
                style=LAYOUT, **kw)
    if _clicked(val, key):
        st.session_state.pop("goto", None)
        st.switch_page(P["chart"])
    return val


def items_from(data: dict, labels: list[tuple[str, str]]) -> list:
    out = []
    for label, s in labels:
        df = data.get(s)
        if df is None or len(df) < 2:
            continue
        out.append(live_item(s, label, df["Close"].iloc[-1], df["Close"].iloc[-2],
                             spark=[round(float(x), 4) for x in df["Close"].tail(30)]))
    return out


PERIODS = {"Today": "Chg %", "1 week": "1W %", "1 month": "1M %", "3 months": "3M %", "1 year": "1Y %"}


def page_dashboard():
    status_strip()
    res = resolved(U.DASHBOARD)
    if not res:
        no_data_msg()
        return
    syms = tuple(res.values())
    data, err = safe(fetch_daily, syms)
    if not data:
        no_data_msg(err)
        return

    live("tiles", items_from(data, [(label, res[label]) for label, _ in U.DASHBOARD if label in res]),
         key="dash_tiles", tape=True)
    if res.get("XAU/USD") == "GC=F":
        st.caption("XAU/USD shows COMEX gold futures (GC=F), which run a few dollars above spot. "
                   "US Oil is WTI crude futures.")

    # ---- sector performance
    hist_note()
    st.subheader("Sector performance")
    sector_specs = [(n, c) for n, k, c in U.INDEX_SPECS if k == "Sector"]
    sres = resolved(sector_specs)
    period = st.segmented_control("Period", list(PERIODS), default="Today", key="dash_period",
                                  label_visibility="collapsed") or "Today"
    col = PERIODS[period]
    if sres:
        t, err = safe(build_table, tuple(sres.values()), tuple((v, k) for k, v in sres.items()))
        if t is not None and not t.empty:
            t = t.dropna(subset=[col]).sort_values(col)
            fig = go.Figure(go.Bar(
                x=t[col], y=t["Name"].str.replace("Nifty ", "", regex=False), orientation="h",
                marker_color=np.where(t[col] >= 0, UP, DOWN),
                text=[f"{v:+.2f}%" for v in t[col]], textposition="outside", cliponaxis=False,
                customdata=t["Price"], hovertemplate="%{y}<br>%{x:+.2f}%<br>%{customdata:,.2f}<extra></extra>"))
            fig.update_layout(height=max(320, 26 * len(t) + 60), margin=dict(l=10, r=40, t=10, b=10),
                              xaxis=dict(ticksuffix="%", zeroline=True, zerolinecolor="rgba(128,128,128,.6)"),
                              template=plot_template(), bargap=0.25)
            st.plotly_chart(fig, width="stretch", key="sector_bar")
            up = int((t["Chg %"] > 0).sum())
            st.caption(f"{up} of {len(t)} sector indices are up today. Click **NSE Indices & Sectors** "
                       "in the menu for full details.")
    else:
        st.caption("Sector indices did not load. Try **Refresh now**.")

    # ---- F&O movers
    ft, _ = safe(fno_table)
    t = ft[0] if ft else pd.DataFrame()
    st.subheader("F&O stocks: top 10 gainers and losers")
    if t.empty:
        no_data_msg()
        return
    live("movers", [live_item(r["Symbol"], r["Stock"], r["Price"], r["Prev Close"], vol=r["Volume"])
                     for _, r in t.iterrows()], key="dash_movers", n=10)
    st.caption("Ranks update on every tick. Click a stock to open its chart.")
    check_alerts(dict(zip(t["Symbol"], t["Price"])))


def page_indices():
    status_strip()
    st.header("NSE indices & sectors")
    broad = resolved([(n, c) for n, k, c in U.INDEX_SPECS if k == "Broad"])
    if broad:
        bdata, _ = safe(fetch_daily, tuple(broad.values()))
        if bdata:
            live("tiles", items_from(bdata, list(broad.items())), key="idx_tiles")
    cols = ["Name", "Price", "Chg", "Chg %", "Spark", "Open", "Day High", "Day Low", "Prev Close", "1W %", "1M %",
            "3M %", "1Y %", "From 52W High %", "RSI", "Trend", "Rating"]
    for kind, title in (("Broad", "Broad market"), ("Sector", "Sectoral & thematic")):
        specs = [(n, c) for n, k, c in U.INDEX_SPECS if k == kind]
        res = resolved(specs)
        st.subheader(title)
        if not res:
            no_data_msg()
            continue
        t, err = safe(build_table, tuple(res.values()), tuple((v, k) for k, v in res.items()))
        if t is None or t.empty:
            no_data_msg(err)
            continue
        order = {n: i for i, (n, _) in enumerate(specs)}
        t = t.assign(_o=t["Name"].map(order)).sort_values("_o")
        if kind == "Sector":
            sort_by = st.selectbox("Sort by", ["Default order"] + list(PERIODS), key="idx_sort")
            if sort_by != "Default order":
                t = t.sort_values(PERIODS[sort_by], ascending=False)
        show_table(t, cols, f"idx_{kind}")
        missing = [n for n, _ in specs if n not in res]
        if missing:
            st.caption("Not available from Yahoo right now: " + ", ".join(missing))
    st.caption("Click any index to open its chart.")


FNO_SCANS = {
    "All F&O stocks": lambda d: d,
    "Gainers (sorted)": lambda d: d.sort_values("Chg %", ascending=False),
    "Losers (sorted)": lambda d: d.sort_values("Chg %"),
    "Volume spike (2× 20-day average)": lambda d: d[d["Vol x Avg"] >= 2].sort_values("Vol x Avg", ascending=False),
    "Gap up over 1%": lambda d: d[d["Gap %"] >= 1].sort_values("Gap %", ascending=False),
    "Gap down over 1%": lambda d: d[d["Gap %"] <= -1].sort_values("Gap %"),
    "Big movers (over 3% either way)": lambda d: d[d["Chg %"].abs() >= 3].sort_values("Chg %", ascending=False),
    "High volatility (ATR above 3% of price)": lambda d: d[d["ATR %"] > 3].sort_values("ATR %", ascending=False),
    "Near 52-week high (within 2%)": lambda d: d[d["From 52W High %"] >= -2],
    "Near 52-week low (within 3%)": lambda d: d[d["From 52W Low %"] <= 3],
    "Oversold (RSI below 30)": lambda d: d[d["RSI"] < 30],
    "Overbought (RSI above 70)": lambda d: d[d["RSI"] > 70],
    "Strong uptrend": lambda d: d[d["Trend"] == "Strong up"],
    "Strong downtrend": lambda d: d[d["Trend"] == "Strong down"],
    "Supertrend turned up today": lambda d: d[d["Signals"].str.contains("Supertrend flip up")],
    "Supertrend turned down today": lambda d: d[d["Signals"].str.contains("Supertrend flip down")],
    "MACD bullish crossover": lambda d: d[d["Signals"].str.contains("MACD bull")],
    "MACD bearish crossover": lambda d: d[d["Signals"].str.contains("MACD bear")],
}

FNO_COLS = ["Stock", "Sector", "Price", "Chg", "Chg %", "Spark", "Open", "Day High", "Day Low", "Prev Close",
            "Avg Price", "Gap %", "Volume", "Vol x Avg", "Turnover Cr", "Buy Qty", "Sell Qty",
            "Fut LTP", "Basis", "OI", "OI Chg %", "Buildup", "Fut Expiry", "Lot size", "Lot value",
            "Upper Circuit", "Lower Circuit", "ATR %", "RSI", "Trend", "Supertrend", "Rating",
            "1W %", "1M %", "3M %", "1Y %", "52W High", "52W Low", "From 52W High %", "From 52W Low %", "Signals"]


def page_fno():
    status_strip()
    st.header("F&O stocks")
    view = st.segmented_control("View", ["Live prices", "Full analytics"], key="fno_view",
                                default="Live prices" if FEED is not None else "Full analytics",
                                label_visibility="collapsed") or "Full analytics"
    if view == "Live prices":
        res, err = safe(fno_table)
        if res is None or res[0].empty:
            no_data_msg(err)
            return
        t = res[0]
        live("board", [live_item(r["Symbol"], r["Stock"], r["Price"], r["Prev Close"], vol=r["Volume"],
                                 open=r["Open"], high=r["Day High"], low=r["Day Low"], avg=r.get("Avg Price"))
                       for _, r in t.sort_values("Stock").iterrows()], key="fno_board")
        st.caption("Every F&O stock, updating tick by tick from Dhan. Click a column header to sort, or a name for "
                   "its chart. Switch to Full analytics for RSI, trend, gaps, OI and scans."
                   if FEED is not None else "Live ticks need Dhan connected with the live feed on.")
        return
    with_oi = False
    if DHAN_DATA:
        with_oi = st.toggle("Futures OI & buildup", key="fno_oi", value=bool(DCFG.get("fno_oi", False)),
                            help="Adds the nearest stock future's price, open interest, OI change and buildup "
                                 "(long buildup, short covering, short buildup, long unwinding) from Dhan. "
                                 "Downloads Dhan's F&O contract list once a day, which is a large file.")
    with st.spinner("Loading all F&O stocks…"):
        t, err = safe(fno_table, with_oi)
    if t is None:
        no_data_msg(err)
        return
    t, src, missing = t
    if t.empty:
        no_data_msg()
        return

    adv, dec = int((t["Chg %"] > 0).sum()), int((t["Chg %"] < 0).sum())
    m = st.columns(5)
    m[0].metric("F&O stocks", len(t), border=True)
    m[1].metric("Advancing", adv, border=True)
    m[2].metric("Declining", dec, border=True)
    m[3].metric("Average change", f"{t['Chg %'].mean():+.2f}%", border=True)
    m[4].metric("Up 3% or more", int((t["Chg %"] >= 3).sum()), f"{int((t['Chg %'] <= -3).sum())} down 3% or more",
                delta_color="off", border=True)

    with st.expander("Sector breadth", expanded=False):
        sb = t.groupby("Sector").agg(avg=("Chg %", "mean"), n=("Chg %", "size"),
                                     up=("Chg %", lambda s: int((s > 0).sum()))).sort_values("avg")
        fig = go.Figure(go.Bar(x=sb["avg"], y=sb.index, orientation="h",
                               marker_color=np.where(sb["avg"] >= 0, UP, DOWN),
                               text=[f"{a:+.2f}%  ({u}/{n} up)" for a, u, n in zip(sb["avg"], sb["up"], sb["n"])],
                               textposition="outside", cliponaxis=False))
        fig.update_layout(height=26 * len(sb) + 80, margin=dict(l=10, r=90, t=10, b=10),
                          xaxis=dict(ticksuffix="%"), template=plot_template())
        st.plotly_chart(fig, width="stretch", key="fno_sector")
        st.caption("Average change today of the F&O stocks in each sector.")

    scans = dict(FNO_SCANS)
    if "Buildup" in t:
        for b in ("Long buildup", "Short buildup", "Short covering", "Long unwinding"):
            scans[f"{b} (futures)"] = (lambda b: lambda d: d[d["Buildup"] == b].sort_values("OI Chg %", ascending=False))(b)
        scans["Highest OI increase (futures)"] = lambda d: d.sort_values("OI Chg %", ascending=False).head(25)
    c1, c2, c3 = st.columns([2, 2, 2])
    scan = c1.selectbox("Scan", list(scans), key="fno_scan")
    sectors = c2.multiselect("Sector", sorted(t["Sector"].unique()), key="fno_sectors")
    search = c3.text_input("Search stock", key="fno_search", placeholder="e.g. TATA")
    with st.expander("More filters"):
        f1, f2, f3 = st.columns(3)
        pmin, pmax = f1.slider("Price range ₹", 0, 50000, (0, 50000), 100, key="fno_price")
        rsi_r = f2.slider("RSI (14)", 0, 100, (0, 100), key="fno_rsi")
        trends = f3.multiselect("Trend", ["Strong up", "Up", "Sideways", "Down", "Strong down"], key="fno_trend")

    d = scans.get(scan, FNO_SCANS["All F&O stocks"])(t)
    if sectors:
        d = d[d["Sector"].isin(sectors)]
    if search:
        d = d[d["Stock"].str.contains(search.strip(), case=False, regex=False)]
    if (pmin, pmax) != (0, 50000):
        d = d[d["Price"].between(pmin, pmax)]
    if rsi_r != (0, 100):
        d = d[d["RSI"].between(*rsi_r)]
    if trends:
        d = d[d["Trend"].isin(trends)]

    st.caption(f"{len(d)} stocks shown. Click a row for the chart. Scroll the table sideways for all columns; "
               "click a column header to sort; use the table's ⋮ menu to download CSV.")
    show_table(d, FNO_COLS, "fno_table", height=720)
    srcs = t["Source"].value_counts().to_dict() if "Source" in t else {}
    price_src = ("Dhan live quotes" if srcs.get("Dhan") and not srcs.get("Yahoo") else
                 "Dhan, with Yahoo for symbols Dhan could not match" if srcs.get("Dhan") else "Yahoo Finance")
    st.caption(f"F&O list and lot sizes: {src}. Prices: {price_src}.")
    hist_note()
    if missing:
        with st.expander(f"{len(missing)} symbols without data"):
            st.write(", ".join(s.replace(".NS", "") for s in missing))


def page_market(group: str, title: str, tiles_n: int = 5, note: str = ""):
    tiles_n = 2 if MOBILE else tiles_n
    status_strip()
    st.header(title)
    syms = tuple(U.GROUPS[group])
    t, err = safe(build_table, syms)
    if t is None or t.empty:
        no_data_msg(err)
        return
    data = fetch_daily(syms)
    first = [s for s in syms if s in data][:tiles_n * 2]
    for i in range(0, len(first), tiles_n):
        cols = st.columns(tiles_n)
        for col, s in zip(cols, first[i:i + tiles_n]):
            tile(col, name_of(s), s, data.get(s))
    adv, dec = int((t["Chg %"] > 0).sum()), int((t["Chg %"] < 0).sum())
    st.markdown(f"<span class='chg-up'>{adv} up</span> · <span class='chg-down'>{dec} down</span>",
                unsafe_allow_html=True)
    sort_by = st.selectbox("Sort by", ["Default order", "Change today", "1 week", "1 month", "Volatility (ATR %)"],
                           key=f"sort_{group}")
    sort_map = {"Change today": "Chg %", "1 week": "1W %", "1 month": "1M %", "Volatility (ATR %)": "ATR %"}
    if sort_by in sort_map:
        t = t.sort_values(sort_map[sort_by], ascending=False)
    cols = ["Name", "Price", "Chg", "Chg %", "Spark", "Open", "Day High", "Day Low", "Prev Close"]
    if t["Volume"].sum() > 0:
        cols += ["Volume", "Vol x Avg"]
    cols += ["ATR %", "RSI", "Trend", "Supertrend", "Rating", "1W %", "1M %", "3M %", "1Y %", "52W High", "52W Low",
             "From 52W High %", "Signals"]
    show_table(t, cols, f"tbl_{group}")
    st.caption("Click a row to open its chart." + (" " + note if note else ""))
    check_alerts(dict(zip(t["Symbol"], t["Price"])))
    return t


def page_crypto():
    page_market("Crypto", "Crypto", note="Prices in US dollars, live around the clock.")


def page_forex():
    page_market("Forex", "Forex", note="Major and cross pairs. Forex trades Monday to Friday, around the clock.")


def page_currency():
    t = page_market("Currency (INR)", "Currency (INR)", note="Rupee value of one unit of each currency.")
    if t is None or t.empty:
        return
    st.subheader("Converter")
    rates = dict(zip(t["Symbol"], t["Price"]))
    c1, c2, c3 = st.columns([2, 2, 3])
    amt = c1.number_input("Amount", min_value=0.0, value=1000.0, step=100.0, key="conv_amt")
    opts = [s for s in U.INR_CURRENCY if s in rates]
    cur = c2.selectbox("Currency", opts, format_func=lambda s: s[:3], key="conv_cur")
    if cur:
        c3.metric(f"{amt:,.2f} {cur[:3]} in rupees", f"₹{indian_group(amt * rates[cur])}",
                  f"1 {cur[:3]} = ₹{rates[cur]:,.4f}", delta_color="off", border=True)


def page_commodities():
    page_market("Commodities", "Commodities", note="Futures prices in US dollars (COMEX, NYMEX, CBOT, ICE).")


TIMEFRAMES = {
    "1m": ("5d", "1m"), "5m": ("5d", "5m"), "15m": ("1mo", "15m"), "25m": (None, None), "1h": ("3mo", "1h"),
    "1D": ("1y", "1d"), "1W": ("5y", "1wk"), "1M": ("max", "1mo"),
}


def page_details():
    status_strip()
    sym = st.session_state.detail_pick
    options = list(dict.fromkeys([sym] + store["watchlist"] + list(U.all_names())))
    top1, top2, top3 = st.columns([3, 2, 1])
    with top1:
        sym = st.selectbox("Symbol", options, format_func=lambda s: f"{name_of(s)}  ·  {s}", key="detail_pick")
    with top2:
        tf = st.segmented_control("Timeframe", list(TIMEFRAMES), default="15m", key="tf") or "1D"
    with top3:
        st.write("")
        in_wl = sym in store["watchlist"]
        if st.button("★ Remove" if in_wl else "☆ Watch", width="stretch", key="wl_btn"):
            if in_wl:
                store["watchlist"].remove(sym)
            else:
                store["watchlist"].append(sym)
            save_store(store)
            st.rerun()

    daily, err = safe(fetch_daily, (sym,))
    ddf = (daily or {}).get(sym)
    if ddf is None or len(ddf) < 2:
        st.error(f"No data for **{sym}**. Check the symbol (NSE stocks end in .NS, e.g. RELIANCE.NS)."
                 + (f" (`{err}`)" if err else ""))
        return
    m = ind.screener_row(ddf)
    last, prev = m["Price"], m["Prev Close"]
    stock = sym.replace(".NS", "")

    h1, h2 = st.columns([2, 3])
    with h1:
        sector = U.FNO_SECTOR_OF.get(stock)
        sub = f"{sym} · {sector or U.group_of(sym)}"
        st.markdown(f"#### {name_of(sym)} <span class='muted'>{sub}</span>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-price'>{fmt_price(last, sym)}</div>{chg_html(m['Chg %'], m['Chg'])}"
                    f"<div class='muted'>Last bar {pd.Timestamp(ddf.index[-1]):%d %b %Y}</div>", unsafe_allow_html=True)
        lots, _ = fno_universe()
        if lots.get(stock):
            st.markdown(f"<div class='muted'>F&O lot size {lots[stock]:,} · lot value "
                        f"₹{indian_group(lots[stock] * last, 0)}</div>", unsafe_allow_html=True)
        oc_key = next((k for k, v in U.OC_INDEX_SYMBOL.items() if v == sym), None) or (stock if lots.get(stock) else None)
        if DHAN_DATA and oc_key:
            st.button("Option chain", icon=":material/table_chart:", key="to_oc", on_click=go_option_chain,
                      args=(oc_key,))
    with h2:
        a, b, c, d = st.columns(4)
        a.metric("Open", fmt_price(m["Open"], sym))
        b.metric("Prev close", fmt_price(prev, sym))
        c.metric("Day range", f"{fmt_price(m['Day Low'], sym)} – {fmt_price(m['Day High'], sym)}".replace("₹", ""))
        d.metric("Volume", fmt_vol(m["Volume"], sym),
                 f"{m['Vol x Avg']:.1f}× avg" if pd.notna(m["Vol x Avg"]) else None, delta_color="off")
        a, b, c, d = st.columns(4)
        a.metric("52W range", f"{fmt_price(m['52W Low'], sym)} – {fmt_price(m['52W High'], sym)}".replace("₹", ""))
        b.metric("RSI (14)", f"{m['RSI']:.1f}" if pd.notna(m["RSI"]) else "—")
        c.metric("ATR (14)", f"{m['ATR %']:.2f}%" if pd.notna(m["ATR %"]) else "—")
        d.metric("Technical rating", verdict(m["Score"]), f"{m['Score']:+d} / 5", delta_color="off")

    ref = dhan_ref(sym)
    if ref:
        qq = quotes_for([ref]).get((ref[0], int(ref[1])))
        if qq:
            o = qq.get("ohlc") or {}
            d = (qq.get("depth") or {})
            depth = [[(b or {}).get("quantity"), (a or {}).get("quantity"), (b or {}).get("orders"), (a or {}).get("orders"),
                      (b or {}).get("price"), (a or {}).get("price")]
                     for b, a in zip((d.get("buy") or []) + [{}] * 5, (d.get("sell") or []) + [{}] * 5)][:5]
            live("quote", [live_item(sym, name_of(sym), qq.get("last_price"), prev, open=o.get("open"),
                                     high=o.get("high"), low=o.get("low"), avg=qq.get("average_price"),
                                     vol=qq.get("volume"), oi=qq.get("oi") or None, poi=qq.get("prev_oi"),
                                     tbq=qq.get("buy_quantity"), tsq=qq.get("sell_quantity"), depth=depth,
                                     ltt=str(qq.get("last_trade_time") or "")[-8:])], key=f"q_{sym}")

    overlays = st.multiselect(
        "Indicators", ["EMA 20", "EMA 50", "EMA 200", "Bollinger (20, 2)", "VWAP", "Supertrend (10, 3)", "Pivot levels"],
        default=["EMA 20", "EMA 50", "VWAP", "Pivot levels"], key="overlays")

    period, interval = TIMEFRAMES[tf]
    intraday = interval not in ("1d", "1wk", "1mo")
    res, herr = safe(chart_data, sym, tf, period, interval)
    hdf, csrc = res if res else (None, "")
    today_ist = datetime.now(IST).date()
    base = ddf.iloc[-2] if pd.Timestamp(ddf.index[-1]).date() >= today_ist else ddf.iloc[-1]
    piv = ind.pivots(float(base["High"]), float(base["Low"]), float(base["Close"]))
    if hdf is None or hdf.empty:
        st.warning(f"No {tf} data for this symbol right now."
                   + (" The 25-minute timeframe needs Dhan." if tf == "25m" and not ref else "")
                   + (f" (`{herr}`)" if herr else ""))
    else:
        if intraday and tf in ("1m", "5m"):
            hdf = hdf[hdf.index >= hdf.index[-1] - pd.Timedelta(days=2 if tf == "1m" else 5)]
        tv_chart(hdf, sym, intraday, overlays, piv if intraday or tf == "1D" else None, tf)
        st.caption(f"Chart data: {csrc}. Times in IST.")

    tabs = st.tabs(["Technical summary", "Levels", "Performance", "Fundamentals", "News"])
    with tabs[0]:
        c = ddf["Close"]
        ml, ms, _ = ind.macd(c)
        rows = [
            ("Price vs EMA 20", fmt_price(m["EMA20"], sym), "Bullish" if last > m["EMA20"] else "Bearish"),
            ("Price vs EMA 50", fmt_price(m["EMA50"], sym), "Bullish" if last > m["EMA50"] else "Bearish"),
            ("Price vs EMA 200", fmt_price(m["EMA200"], sym),
             "—" if pd.isna(m["EMA200"]) else "Bullish" if last > m["EMA200"] else "Bearish"),
            ("MACD vs signal", f"{ml.iloc[-1]:.3f} / {ms.iloc[-1]:.3f}", "Bullish" if ml.iloc[-1] > ms.iloc[-1] else "Bearish"),
            ("Supertrend (10, 3)", m["Supertrend"], "Bullish" if m["Supertrend"] == "Up" else "Bearish"),
            ("RSI (14)", f"{m['RSI']:.1f}" if pd.notna(m["RSI"]) else "—",
             "Oversold" if m["RSI"] < 30 else "Overbought" if m["RSI"] > 70 else "Neutral"),
            ("Trend (EMA stack)", m["Trend"], ""),
            ("Signals today", m["Signals"] or "None", ""),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Indicator", "Value", "Reading"]), hide_index=True, width="stretch")
        st.caption("Daily timeframe. Rating counts five checks: price above EMA 20, 50 and 200, MACD above signal, "
                   "and Supertrend up.")
    with tabs[1]:
        lc1, lc2 = st.columns(2)
        with lc1:
            st.markdown("**Classic pivots** (from previous session)")
            st.dataframe(pd.DataFrame([(k, fmt_price(v, sym), f"{(v / last - 1) * 100:+.2f}%") for k, v in piv.items()],
                                      columns=["Level", "Price", "Distance"]), hide_index=True, width="stretch")
        with lc2:
            st.markdown("**Key daily levels**")
            lv = [("52-week high", m["52W High"]), ("52-week low", m["52W Low"]), ("EMA 20", m["EMA20"]),
                  ("EMA 50", m["EMA50"]), ("EMA 200", m["EMA200"]),
                  ("1-month high", float(ddf["High"].tail(21).max())), ("1-month low", float(ddf["Low"].tail(21).min()))]
            st.dataframe(pd.DataFrame([(k, fmt_price(v, sym), f"{(v / last - 1) * 100:+.2f}%" if pd.notna(v) else "—")
                                       for k, v in lv], columns=["Level", "Price", "Distance"]),
                         hide_index=True, width="stretch")
    with tabs[2]:
        c = ddf["Close"]
        ytd = c[c.index >= pd.Timestamp(datetime.now(IST).year, 1, 1)]
        perf = {"1 day": m["Chg %"], "1 week": m["1W %"], "1 month": m["1M %"], "3 months": m["3M %"],
                "6 months": ind.pct(last, float(c.iloc[-127])) if len(c) > 127 else np.nan,
                "Year to date": ind.pct(last, float(ytd.iloc[0])) if len(ytd) else np.nan, "1 year": m["1Y %"]}
        pf = pd.DataFrame({"Period": list(perf), "Return %": list(perf.values())})
        fig = go.Figure(go.Bar(x=pf["Period"], y=pf["Return %"], marker_color=np.where(pf["Return %"] >= 0, UP, DOWN),
                               text=[f"{v:+.2f}%" if pd.notna(v) else "" for v in pf["Return %"]], textposition="outside"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10), yaxis_title="%", template=plot_template())
        st.plotly_chart(fig, width="stretch", key="perf_chart")
    with tabs[3]:
        if not sym.endswith((".NS", ".BO")):
            st.caption("Fundamentals are available for stocks only.")
        else:
            info = fetch_info(sym)
            if not info:
                st.caption("Fundamentals did not load. Yahoo sometimes limits this; try again later.")
            else:
                def g(k, kind="num"):
                    v = info.get(k)
                    if v is None:
                        return "—"
                    if kind == "pct":
                        return f"{v * 100:.2f}%"
                    if kind == "cr":
                        return f"₹{indian_group(v / 1e7, 0)} Cr"
                    if kind == "rs":
                        return f"₹{v:,.2f}"
                    return f"{v:,.2f}" if isinstance(v, (int, float)) else str(v)

                dy = info.get("dividendYield")
                f1, f2, f3 = st.columns(3)
                f1.dataframe(pd.DataFrame([
                    ("Sector", g("sector")), ("Industry", g("industry")), ("Market cap", g("marketCap", "cr")),
                    ("Enterprise value", g("enterpriseValue", "cr")), ("Beta", g("beta")),
                    ("Shares outstanding", fmt_vol(info.get("sharesOutstanding"), sym))],
                    columns=["Company", ""]), hide_index=True, width="stretch")
                f2.dataframe(pd.DataFrame([
                    ("P/E (trailing)", g("trailingPE")), ("P/E (forward)", g("forwardPE")),
                    ("Price / book", g("priceToBook")), ("EPS (trailing)", g("trailingEps", "rs")),
                    ("Book value / share", g("bookValue", "rs")),
                    ("Dividend yield", f"{dy:.2f}%" if dy is not None else "—")],
                    columns=["Valuation", ""]), hide_index=True, width="stretch")
                f3.dataframe(pd.DataFrame([
                    ("Return on equity", g("returnOnEquity", "pct")), ("Return on assets", g("returnOnAssets", "pct")),
                    ("Profit margin", g("profitMargins", "pct")), ("Operating margin", g("operatingMargins", "pct")),
                    ("Revenue growth (YoY)", g("revenueGrowth", "pct")), ("Debt / equity", g("debtToEquity"))],
                    columns=["Quality", ""]), hide_index=True, width="stretch")
                if info.get("longBusinessSummary"):
                    with st.expander("About the company"):
                        st.write(info["longBusinessSummary"])
    with tabs[4]:
        news = fetch_news(sym)
        if not news:
            st.caption("No recent headlines from Yahoo for this symbol.")
        for n in news:
            line = f"[{n['title']}]({n['url']})" if n["url"] else n["title"]
            st.markdown(f"{line}  \n<span class='muted'>{n['publisher'] or ''} · {n['when'] or ''}</span>",
                        unsafe_allow_html=True)


SCREEN_PRESETS = {
    "All symbols": lambda d: d,
    "Top gainers today": lambda d: d.sort_values("Chg %", ascending=False).head(20),
    "Top losers today": lambda d: d.sort_values("Chg %").head(20),
    "Volume spike (2× 20-day average)": lambda d: d[d["Vol x Avg"] >= 2],
    "Oversold (RSI below 30)": lambda d: d[d["RSI"] < 30],
    "Overbought (RSI above 70)": lambda d: d[d["RSI"] > 70],
    "Near 52-week high (within 2%)": lambda d: d[d["From 52W High %"] >= -2],
    "Near 52-week low (within 3%)": lambda d: d[d["From 52W Low %"] <= 3],
    "Strong uptrend (Price > EMA20 > EMA50 > EMA200)": lambda d: d[d["Trend"] == "Strong up"],
    "Strong downtrend (Price < EMA20 < EMA50 < EMA200)": lambda d: d[d["Trend"] == "Strong down"],
    "Pullback in uptrend (above EMA200, RSI 35–50)": lambda d: d[(d["Price"] > d["EMA200"]) & d["RSI"].between(35, 50)],
    "Golden cross (50 over 200 SMA, last 5 days)": lambda d: d[d["Signals"].str.contains("Golden cross")],
    "Death cross (last 5 days)": lambda d: d[d["Signals"].str.contains("Death cross")],
    "MACD bullish crossover (last 3 bars)": lambda d: d[d["Signals"].str.contains("MACD bull")],
    "MACD bearish crossover (last 3 bars)": lambda d: d[d["Signals"].str.contains("MACD bear")],
    "Supertrend turned up today": lambda d: d[d["Signals"].str.contains("Supertrend flip up")],
    "Supertrend turned down today": lambda d: d[d["Signals"].str.contains("Supertrend flip down")],
    "Gap up over 1%": lambda d: d[d["Gap %"] >= 1],
    "Gap down over 1%": lambda d: d[d["Gap %"] <= -1],
    "High volatility (ATR above 3% of price)": lambda d: d[d["ATR %"] > 3],
}


def page_screener():
    status_strip()
    st.header("Screener")
    c1, c2 = st.columns([2, 3])
    with c1:
        markets = st.multiselect("Markets", list(U.GROUPS) + ["My watchlist"], default=["Crypto"], key="scr_markets")
    with c2:
        preset = st.selectbox("Scan", list(SCREEN_PRESETS), key="scr_preset")
    syms = []
    for mk in markets:
        if mk == "My watchlist":
            syms += store["watchlist"]
        elif mk == "F&O Stocks":
            lots, _ = fno_universe()
            syms += [U.fno_yahoo(s) for s in sorted(lots)]
        else:
            syms += list(U.GROUPS[mk])
    extra = st.text_input("Add symbols to this scan (comma separated)", key="scr_extra",
                          placeholder="e.g. IRCTC, DIXON, PEPE, GBPINR")
    syms += [U.normalize(x) for x in extra.split(",") if x.strip()]
    syms = tuple(dict.fromkeys(syms))
    if not syms:
        st.info("Pick at least one market to scan.")
        return
    with st.spinner(f"Scanning {len(syms)} symbols…"):
        t, err = safe(build_table, syms)
    if t is None or t.empty:
        no_data_msg(err)
        return
    d = SCREEN_PRESETS[preset](t)
    st.caption(f"{len(d)} of {len(t)} symbols match. Click a row to open its chart.")
    show_table(d, ["Name", "Market", "Price", "Chg %", "Spark", "Gap %", "Volume", "Vol x Avg", "RSI", "Trend",
                   "Supertrend", "Rating", "Score", "1W %", "1M %", "3M %", "1Y %", "From 52W High %",
                   "From 52W Low %", "ATR %", "Signals"], "screener_table")


def page_watchlist():
    status_strip()
    st.header("Watchlist & alerts")
    a1, a2 = st.columns([4, 1])
    new = a1.text_input("Add symbols (comma separated)", key="wl_add", placeholder="e.g. TATAPOWER, ETH, GBPINR, silver")
    a2.write("")
    if a2.button("Add", width="stretch", key="wl_add_btn") and new.strip():
        for x in new.split(","):
            s = U.normalize(x)
            if s and s not in store["watchlist"]:
                store["watchlist"].append(s)
        save_store(store)
        st.rerun()
    wl = tuple(store["watchlist"])
    if not wl:
        st.info("Your watchlist is empty. Add symbols above or press ☆ Watch on any chart.")
    else:
        t, err = safe(build_table, wl)
        if t is None or t.empty:
            no_data_msg(err)
        else:
            wq = st.text_input("Search watchlist", key="wl_q", placeholder="Name or symbol")
            if wq:
                t = t[t["Name"].str.contains(wq.strip(), case=False, regex=False)
                      | t["Symbol"].str.contains(wq.strip(), case=False, regex=False)]
            for _, r in t.iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 2, 2, 1, 1])
                c1.markdown(f"**{r['Name']}**  \n<span class='muted'>{r['Symbol']}</span>", unsafe_allow_html=True)
                c2.markdown(f"{fmt_price(r['Price'], r['Symbol'])}  \n{chg_html(r['Chg %'])}", unsafe_allow_html=True)
                c3.markdown(f"RSI {r['RSI']:.0f}  \n<span class='muted'>{r['Trend']}</span>" if pd.notna(r["RSI"])
                            else "RSI —", unsafe_allow_html=True)
                c4.markdown(f"{verdict(r['Score'])}  \n<span class='muted'>{r['Signals'] or 'No signals'}</span>",
                            unsafe_allow_html=True)
                c5.button("Chart", key=f"open_{r['Symbol']}", on_click=go_detail, args=(r["Symbol"],))
                if c6.button("✕", key=f"rm_{r['Symbol']}", help="Remove from watchlist"):
                    store["watchlist"].remove(r["Symbol"])
                    save_store(store)
                    st.rerun()
            check_alerts(dict(zip(t["Symbol"], t["Price"])))

    st.divider()
    if PUBLIC:
        st.caption("On Streamlit Cloud, watchlists and alerts reset when the app restarts.")
    st.subheader("Price alerts")
    st.caption("Alerts are checked on every refresh while this app is open, and show as a pop-up.")
    b1, b2, b3, b4 = st.columns([3, 2, 2, 1])
    asym = b1.text_input("Symbol", key="al_sym", placeholder="e.g. GOLD or NIFTY")
    acond = b2.selectbox("When price is", ["above", "below"], key="al_cond")
    alvl = b3.number_input("Level", min_value=0.0, value=0.0, step=1.0, format="%.4f", key="al_lvl")
    b4.write("")
    if b4.button("Set", width="stretch", key="al_set") and asym.strip() and alvl > 0:
        store.setdefault("alerts", []).append({"symbol": U.normalize(asym), "cond": acond, "level": alvl})
        save_store(store)
        st.rerun()
    alerts = store.get("alerts", [])
    if not alerts:
        st.caption("No alerts set.")
    for i, a in enumerate(alerts):
        c1, c2, c3 = st.columns([5, 3, 1])
        c1.write(f"{name_of(a['symbol'])} ({a['symbol']}) {a['cond']} {fmt_price(a['level'], a['symbol'])}")
        c2.markdown(f"<span class='chg-up'>Triggered {a['triggered']}</span>" if a.get("triggered")
                    else "<span class='muted'>Waiting</span>", unsafe_allow_html=True)
        if c3.button("✕", key=f"al_rm_{i}"):
            alerts.pop(i)
            save_store(store)
            st.rerun()

# ---------------------------------------------------------------- sidebar menu and run



# ---------------------------------------------------------------- sector performance

SECTOR_INDEX = {  # F&O sector -> NSE sector index shown beside it
    "Banks": "Nifty Bank", "Financial Services": "Nifty Financial Services", "IT": "Nifty IT", "Auto": "Nifty Auto",
    "Pharma & Healthcare": "Nifty Pharma", "FMCG": "Nifty FMCG", "Metals & Mining": "Nifty Metal",
    "Oil, Gas & Power": "Nifty Energy", "Capital Goods & Infra": "Nifty Infrastructure",
    "Cement & Construction": "Nifty Commodities", "Consumer & Retail": "Nifty Consumption",
    "Realty": "Nifty Realty", "Chemicals": "Nifty Chemicals", "Telecom": "Nifty Services",
}


def breadth_bar(adv: int, dec: int, unch: int = 0, big: bool = False) -> str:
    tot = adv + dec + unch or 1
    return (f'<div class="bbar{" big" if big else ""}" title="{adv} up, {dec} down, {unch} unchanged">'
            f'<span style="width:{adv / tot * 100:.1f}%;background:{UP}"></span>'
            f'<span style="width:{unch / tot * 100:.1f}%;background:rgba(128,128,128,.45)"></span>'
            f'<span style="width:{dec / tot * 100:.1f}%;background:{DOWN}"></span></div>')


def pct_html(v) -> str:
    if v is None or pd.isna(v):
        return '<div class="cell muted">—</div>'
    cls = "chg-up" if v > 0 else "chg-down" if v < 0 else "muted"
    return f'<div class="cell"><span class="{cls}">{v:+.2f}%</span></div>'


def _pick_sector(sec: str):
    st.session_state.sec_pick = sec


def page_sectors():
    status_strip()
    st.header("Sector performance")
    with st.spinner("Loading F&O stocks…"):
        res, err = safe(fno_table)
    if res is None or res[0].empty:
        no_data_msg(err)
        return
    t = res[0]
    period = st.segmented_control("Period", list(PERIODS), default="Today", key="sec_period",
                                  label_visibility="collapsed") or "Today"
    col = PERIODS[period]

    # ---- overall breadth (always today's move)
    adv, dec = int((t["Chg %"] > 0).sum()), int((t["Chg %"] < 0).sum())
    unch = len(t) - adv - dec
    m = st.columns(5)
    m[0].metric("Advancing", adv, border=True)
    m[1].metric("Declining", dec, border=True)
    m[2].metric("Unchanged", unch, border=True)
    m[3].metric("Advance / decline ratio", f"{adv / dec:.2f}" if dec else "—",
                None if adv == dec else ("more advancing" if adv > dec else "-more declining"),
                delta_color="normal", border=True)
    m[4].metric(f"Average move ({period.lower()})", f"{t[col].mean():+.2f}%", border=True)
    st.markdown(breadth_bar(adv, dec, unch, big=True), unsafe_allow_html=True)
    hist_note()

    # ---- sector index moves
    idx_specs = [(n, c) for n, k, c in U.INDEX_SPECS if n in set(SECTOR_INDEX.values())]
    ires = resolved(idx_specs)
    idx_move = {}
    if ires:
        it, _ = safe(build_table, tuple(ires.values()), tuple((v, k) for k, v in ires.items()))
        if it is not None and not it.empty:
            idx_move = dict(zip(it["Name"], it[col]))

    # ---- sector summary
    rows = []
    for sec, g in t.groupby("Sector"):
        g = g.dropna(subset=[col])
        if g.empty:
            continue
        best, worst = g.loc[g[col].idxmax()], g.loc[g[col].idxmin()]
        rows.append({"Sector": sec, "n": len(g), "adv": int((g["Chg %"] > 0).sum()), "dec": int((g["Chg %"] < 0).sum()),
                     "avg": g[col].mean(), "idx": idx_move.get(SECTOR_INDEX.get(sec)),
                     "idx_name": SECTOR_INDEX.get(sec) if SECTOR_INDEX.get(sec) in idx_move else None,
                     "best": (best["Stock"], best[col]), "worst": (worst["Stock"], worst[col]),
                     "turnover": g["Turnover Cr"].sum()})
    sec_df = pd.DataFrame(rows).sort_values("avg", ascending=False)
    if st.session_state.get("sec_pick") not in set(sec_df["Sector"]):
        st.session_state.sec_pick = sec_df["Sector"].iloc[0]
    pick = st.session_state.sec_pick

    st.subheader("Sectors")
    sq1, sq2 = st.columns([2, 4])
    sq = sq1.text_input("Find a sector or stock", key="sec_find", placeholder="e.g. Banks or TCS")
    if sq:
        hit = t[t["Stock"].str.contains(sq.strip(), case=False, regex=False)]["Sector"].unique().tolist()
        sec_df = sec_df[sec_df["Sector"].str.contains(sq.strip(), case=False, regex=False) | sec_df["Sector"].isin(hit)]
        if not sec_df.empty and st.session_state.sec_pick not in set(sec_df["Sector"]):
            st.session_state.sec_pick = sec_df["Sector"].iloc[0]
            pick = st.session_state.sec_pick
        sq2.markdown(f'<div class="cell muted">{len(sec_df)} sector(s) match</div>', unsafe_allow_html=True)
    box = st.container(key="rows_wide_sectors")
    widths = [2.4, 1.1, 1.3, 2.3, 1.9, 1.9, 1.2]
    h = box.columns(widths)
    for c, label in zip(h, ["Sector (click to see stocks)", "Avg move", "Sector index", "Advance / decline",
                            "Best", "Worst", "Turnover ₹ Cr"]):
        c.markdown(f'<div class="hdr">{label}</div>', unsafe_allow_html=True)
    for _, r in sec_df.iterrows():
        c = box.columns(widths, vertical_alignment="center")
        c[0].button(("▸ " if r["Sector"] == pick else "") + f'{r["Sector"]}  ({r["n"]})', key=f"sec_{r['Sector']}",
                    type="tertiary", on_click=_pick_sector, args=(r["Sector"],))
        c[1].markdown(pct_html(r["avg"]), unsafe_allow_html=True)
        c[2].markdown(pct_html(r["idx"]) if r["idx_name"] else '<div class="cell muted">—</div>',
                      unsafe_allow_html=True)
        c[3].markdown(breadth_bar(r["adv"], r["dec"], r["n"] - r["adv"] - r["dec"]) +
                      f'<div class="muted"><span class="chg-up">{r["adv"]}▲</span> · '
                      f'<span class="chg-down">{r["dec"]}▼</span></div>', unsafe_allow_html=True)
        for k, key in ((4, "best"), (5, "worst")):
            name, v = r[key]
            cls = "chg-up" if v > 0 else "chg-down" if v < 0 else "muted"
            c[k].markdown(f'<div class="cell">{name} <span class="{cls}">{v:+.2f}%</span></div>', unsafe_allow_html=True)
        c[6].markdown(f'<div class="cell">{r["turnover"]:,.0f}</div>', unsafe_allow_html=True)
    st.caption(f"Sectors sorted by average move ({period.lower()}). Advance/decline counts use today's change. "
               "Sector index: the matching NSE index's move over the same period.")

    # ---- stocks in the selected sector
    st.divider()
    g = t[t["Sector"] == pick].copy()
    sr = sec_df[sec_df["Sector"] == pick].iloc[0]
    a, b = st.columns([3, 2])
    a.subheader(f"{pick}: {len(g)} stocks")
    a.markdown(f'<span class="chg-up">{sr["adv"]} advancing</span> · <span class="chg-down">{sr["dec"]} declining</span>'
               f' · average {sr["avg"]:+.2f}% ({period.lower()})', unsafe_allow_html=True)
    sort_by = b.selectbox("Sort stocks by", [f"Change ({period.lower()})", "Volume vs average", "RSI", "Name"],
                          key="sec_sort")
    f1, f2, f3 = st.columns([2, 2, 2])
    q = f1.text_input("Search stock", key="sec_q", placeholder="e.g. HDFC")
    show = f2.segmented_control("Show", ["All", "Advancing", "Declining"], default="All", key="sec_show") or "All"
    trend = f3.multiselect("Trend", ["Strong up", "Up", "Sideways", "Down", "Strong down"], key="sec_trend")
    if q:
        g = g[g["Stock"].str.contains(q.strip(), case=False, regex=False)]
    if show != "All":
        g = g[g["Chg %"] > 0] if show == "Advancing" else g[g["Chg %"] < 0]
    if trend:
        g = g[g["Trend"].isin(trend)]
    key = {"Volume vs average": "Vol x Avg", "RSI": "RSI", "Name": "Stock"}.get(sort_by, col)
    g = g.sort_values(key, ascending=key == "Stock", na_position="last")
    if g.empty:
        st.caption("No stocks match. Clear the search or filters.")

    box = st.container(key="rows_wide_secstocks")
    widths = [2.2, 1.5, 1.2, 1.2, 1.2, 1.2, 1.1, 1.5, 1.1]
    h = box.columns(widths)
    period_label = "Today %" if col == "Chg %" else period
    for c, label in zip(h, ["Stock (click for chart)", "LTP", "Today %", period_label if col != "Chg %" else "1 week",
                            "Gap %", "Vol × avg", "RSI", "Trend", "Lot"]):
        c.markdown(f'<div class="hdr">{label}</div>', unsafe_allow_html=True)
    second = col if col != "Chg %" else "1W %"
    for _, r in g.iterrows():
        c = box.columns(widths, vertical_alignment="center")
        c[0].button(r["Stock"], key=f"secstk_{r['Stock']}", type="tertiary", on_click=go_detail, args=(r["Symbol"],),
                    help="Open chart")
        c[1].markdown(f'<div class="cell">{fmt_price(r["Price"], r["Symbol"])}</div>', unsafe_allow_html=True)
        c[2].markdown(pct_html(r["Chg %"]), unsafe_allow_html=True)
        c[3].markdown(pct_html(r[second]), unsafe_allow_html=True)
        c[4].markdown(pct_html(r["Gap %"]), unsafe_allow_html=True)
        vx = r["Vol x Avg"]
        c[5].markdown(f'<div class="cell">{vx:.2f}×</div>' if pd.notna(vx) else '<div class="cell muted">—</div>',
                      unsafe_allow_html=True)
        c[6].markdown(f'<div class="cell">{r["RSI"]:.0f}</div>' if pd.notna(r["RSI"]) else '<div class="cell muted">—</div>',
                      unsafe_allow_html=True)
        c[7].markdown(f'<div class="cell">{r["Trend"]}</div>', unsafe_allow_html=True)
        lot = r.get("Lot size")
        c[8].markdown(f'<div class="cell">{int(lot):,}</div>' if pd.notna(lot) else '<div class="cell muted">—</div>',
                      unsafe_allow_html=True)
    check_alerts(dict(zip(t["Symbol"], t["Price"])))


# ---------------------------------------------------------------- OI analysis

BUILDUPS = {  # name: (colour, meaning)
    "Long buildup": (UP, "Price up, OI up: fresh buying"),
    "Short buildup": (DOWN, "Price down, OI up: fresh selling"),
    "Short covering": ("#5CC8FF", "Price up, OI down: shorts exiting"),
    "Long unwinding": ("#FF9F43", "Price down, OI down: longs exiting"),
}


@st.cache_data(ttl=5, show_spinner=False)
def oi_data(mode: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    lots, _ = fno_universe()
    stocks = fno_futures_oi(sorted(lots), "FUTSTK")
    if not stocks.empty:
        stocks["Sector"] = stocks["Stock"].map(U.FNO_SECTOR_OF).fillna("Other")
        stocks["Symbol"] = stocks["Stock"].map(U.fno_yahoo)
    idx = fno_futures_oi(list(INDEX_FUT), "FUTIDX")
    if not idx.empty:
        idx["Name"] = idx["Stock"].map(INDEX_FUT)
        idx["Symbol"] = idx["Stock"].map(lambda k: U.OC_INDEX_SYMBOL.get(k, "^NSEI"))
    return stocks, idx


def oi_list(df: pd.DataFrame, key: str, sort_col: str, ascending: bool, n: int = 10):
    """Compact clickable list: stock (opens chart), price change, OI change."""
    d = df.dropna(subset=[sort_col]).sort_values(sort_col, ascending=ascending).head(n)
    if d.empty:
        st.caption("None right now.")
        return
    box = st.container(key=f"rows_n_{key}")
    widths = [2.2, 1.5, 1.5, 1.4]
    h = box.columns(widths)
    for c, label in zip(h, ["Stock", "Price %", "OI %", "OI"]):
        c.markdown(f'<div class="hdr">{label}</div>', unsafe_allow_html=True)
    for _, r in d.iterrows():
        c = box.columns(widths, vertical_alignment="center")
        c[0].button(r["Stock"], key=f"{key}_{r['Stock']}", type="tertiary", on_click=go_detail, args=(r["Symbol"],))
        c[1].markdown(pct_html(r["Fut Chg %"]), unsafe_allow_html=True)
        c[2].markdown(pct_html(r["OI Chg %"]), unsafe_allow_html=True)
        c[3].markdown(f'<div class="cell">{fmt_vol(r["OI"], ".NS")}</div>', unsafe_allow_html=True)


def page_oi():
    status_strip()
    st.header("OI analysis")
    if not DHAN_DATA:
        need_dhan()
        return
    with st.spinner("Loading futures open interest… The first run downloads Dhan's F&O contract list "
                    "(large; kept for a week)."):
        res, err = safe(oi_data, True)
    if res is None:
        no_data_msg(err)
        return
    t, idx = res
    if t.empty:
        st.error("No stock futures data from Dhan. " + (DSTAT.get("error") or ""))
        return
    left = DSTAT.get("hist_left_oi", 0)
    if left:
        st.info(f"Loading previous-day open interest from Dhan: {left} contracts to go. OI change and buildup fill "
                "in over the next few refreshes (once a day).", icon="⏳")
    sess = D.last_session_date("NSE_FNO")
    live = D.market_live("NSE_FNO")
    st.caption(("Live session" if live else f"Market closed: showing the {sess:%a %d %b} session") +
               " · nearest-month futures · changes vs the previous session's close and open interest.")

    # ---- index futures
    if not idx.empty:
        cols = st.columns(len(idx))
        for c, (_, r) in zip(cols, idx.iterrows()):
            b = r["Buildup"]
            c.metric(f'{r["Name"]} fut', indian_group(r["Fut LTP"]) if pd.notna(r["Fut LTP"]) else "—",
                     f'{r["Fut Chg %"]:+.2f}% · OI {r["OI Chg %"]:+.1f}%' if pd.notna(r["OI Chg %"]) and pd.notna(r["Fut Chg %"])
                     else None, border=True)
            if b:
                c.markdown(f'<span class="pill" style="color:{BUILDUPS[b][0]};border-color:{BUILDUPS[b][0]}">{b}</span>',
                           unsafe_allow_html=True)

    # ---- buildup counts
    counts = t["Buildup"].value_counts()
    m = st.columns(4)
    for c, (b, (color, meaning)) in zip(m, BUILDUPS.items()):
        c.markdown(f'<div style="border:1px solid {color}55;border-radius:10px;padding:.7rem .9rem">'
                   f'<div class="hdr" style="color:{color};opacity:1">{b}</div>'
                   f'<div style="font-size:1.7rem;font-weight:700">{int(counts.get(b, 0))}</div>'
                   f'<div class="muted">{meaning}</div></div>', unsafe_allow_html=True)
    tot = len(t)
    bar = "".join(f'<span style="width:{counts.get(b, 0) / tot * 100:.1f}%;background:{BUILDUPS[b][0]}"></span>'
                  for b in BUILDUPS)
    st.markdown(f'<div class="bbar big">{bar}</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Buildup", "OI gainers & losers", "Sector OI", "All futures"])
    with tabs[0]:
        r1 = st.columns(2)
        r2 = st.columns(2)
        for c, b in zip(r1 + r2, BUILDUPS):
            with c:
                st.markdown(f'<div class="hdr" style="color:{BUILDUPS[b][0]};opacity:1;font-size:.85rem">'
                            f'{b} · top 10 by OI change</div>', unsafe_allow_html=True)
                sub = t[t["Buildup"] == b].assign(_a=lambda d: d["OI Chg %"].abs())
                oi_list(sub, "bu_" + b.lower().replace(" ", "_"), "_a", ascending=False)
        st.caption("Click a stock to open its chart. Ranked by the size of the open-interest change.")
    with tabs[1]:
        g, l = st.columns(2)
        with g:
            st.markdown("**OI gainers** · biggest rise in open interest")
            oi_list(t, "oig", "OI Chg %", ascending=False, n=15)
        with l:
            st.markdown("**OI losers** · biggest fall in open interest")
            oi_list(t, "oil", "OI Chg %", ascending=True, n=15)
        st.caption("Rising OI means new positions are being added; falling OI means positions are being closed. "
                   "Read it with the price move: see the buildup tab.")
    with tabs[2]:
        sec = t[t["Buildup"] != ""].groupby(["Sector", "Buildup"]).size().unstack(fill_value=0)
        sec = sec.reindex(columns=list(BUILDUPS), fill_value=0)
        sec = sec.loc[(sec["Long buildup"] + sec["Short covering"] - sec["Short buildup"] - sec["Long unwinding"])
                      .sort_values().index]
        fig = go.Figure()
        for b in BUILDUPS:
            fig.add_trace(go.Bar(y=sec.index, x=sec[b], name=b, orientation="h", marker_color=BUILDUPS[b][0]))
        fig.update_layout(barmode="stack", height=28 * len(sec) + 90, margin=dict(l=10, r=10, t=30, b=10),
                          legend=dict(orientation="h", y=1.08), template=plot_template(), xaxis_title="Stocks")
        st.plotly_chart(fig, width="stretch", key="oi_sector")
        st.caption("Number of F&O stocks in each buildup, by sector. Sectors with the most long buildup and short "
                   "covering are at the top.")
    with tabs[3]:
        f1, f2, f3 = st.columns(3)
        bsel = f1.multiselect("Buildup", list(BUILDUPS), key="oi_bsel")
        ssel = f2.multiselect("Sector", sorted(t["Sector"].unique()), key="oi_ssel")
        q = f3.text_input("Search stock", key="oi_q")
        d = t
        if bsel:
            d = d[d["Buildup"].isin(bsel)]
        if ssel:
            d = d[d["Sector"].isin(ssel)]
        if q:
            d = d[d["Stock"].str.contains(q.strip(), case=False, regex=False)]
        d = d.sort_values("OI Chg %", ascending=False, na_position="last")
        show_table(d, ["Stock", "Sector", "Fut LTP", "Fut Chg %", "OI", "Prev OI", "OI Chg", "OI Chg %", "Buildup",
                       "OI Value Cr", "Fut Volume", "Fut Lot", "Fut Expiry"], "oi_all", height=640)
        st.caption(f"{len(d)} stock futures. Click a row to open the stock's chart.")


# ---------------------------------------------------------------- trade setups (validated in research/)


def page_setups():
    status_strip()
    st.header("Trade setups")
    st.caption("Rules found in Omnipuls research on 14 years of NSE data, tested year by year with costs. "
               "They decide at 9:15 from the opening gap. Past results don't guarantee future ones; size so a run of "
               "losses is survivable.")
    res, err = safe(fno_table)
    if res is None or res[0].empty:
        no_data_msg(err)
        return
    t = res[0]
    # Nifty and sector gaps at the open
    nres = resolved([("Nifty 50", ["^NSEI"])])
    ndata, _ = safe(fetch_daily, tuple(nres.values())) if nres else (None, None)
    nifty_gap = None
    if ndata and nres.get("Nifty 50") in ndata:
        nd = ndata[nres["Nifty 50"]]
        if len(nd) >= 2:
            nifty_gap = float(nd["Open"].iloc[-1] / nd["Close"].iloc[-2] - 1)
    sec_specs = [(n, c) for n, k, c in U.INDEX_SPECS if n in set(SECTOR_INDEX.values())]
    sres = resolved(sec_specs)
    sec_gap = {}
    if sres:
        sdata, _ = safe(fetch_daily, tuple(sres.values()))
        for label, sym in sres.items():
            d = (sdata or {}).get(sym)
            if d is not None and len(d) >= 2:
                sec_gap[label] = float(d["Open"].iloc[-1] / d["Close"].iloc[-2] - 1)
    rows = []
    for _, r in t.iterrows():
        if not (pd.notna(r["Open"]) and pd.notna(r["Prev Close"]) and r["Prev Close"] > 0 and r["Open"] > 0):
            continue
        rows.append({"sym": r["Stock"], "Symbol": r["Symbol"], "sector": r["Sector"], "open": r["Open"],
                     "prev_close": r["Prev Close"], "ltp": r["Price"], "high": r["Day High"], "low": r["Day Low"],
                     "sector_gap": sec_gap.get(SECTOR_INDEX.get(r["Sector"]), np.nan)})
    g = SU.gap_table(rows)
    sig = SU.signals(g, nifty_gap)
    last_bar = pd.Timestamp(t["Last bar"].max()).date() if "Last bar" in t else None
    live_today = last_bar == datetime.now(IST).date()
    m = st.columns(4)
    m[0].metric("Session", f"{last_bar:%a %d %b}" if last_bar else "—", "today" if live_today else "last session",
                delta_color="off", border=True)
    m[1].metric("Nifty gap at open", f"{nifty_gap * 100:+.2f}%" if nifty_gap is not None else "—",
                "panic day" if nifty_gap is not None and nifty_gap <= -0.005 else None, delta_color="off", border=True)
    m[2].metric("F&O stocks gapping 3%+", int((g["abs_gap"] >= 0.03).sum()) if not g.empty else 0, border=True)
    m[3].metric("Gap-downs / gap-ups 3%+", f"{int((g['gap'] <= -0.03).sum())} / {int((g['gap'] >= 0.03).sum())}"
                if not g.empty else "—", border=True)
    if not live_today:
        st.info("The market hasn't opened today yet, so these are the last session's signals. Today's appear at "
                "9:15 once opening prices are in.", icon=":material/schedule:")
    for key, meta in SU.SETUPS.items():
        st.subheader(meta["name"])
        st.markdown(f"**Rule:** {meta['rule']}  \n<span class='muted'>{meta['stats']}</span>", unsafe_allow_html=True)
        df = sig.get(key)
        if df is None or df.empty:
            st.caption("No signal" + (" (not a panic day: Nifty didn't open 0.5% lower)." if key == "panic_gap" else "."))
            continue
        view = pd.DataFrame({"Stock": df["sym"], "Symbol": df["Symbol"], "Sector": df["sector"], "Side": df["side"],
                             "Gap %": df["gap"] * 100, "Entry (open)": df["entry"], "Stop": df["stop_px"],
                             "LTP": df["ltp"], "P&L now %": df["pnl_now%"],
                             "Status": np.where(df["stopped"], "Stopped", "Open")})
        data_table(view.drop(columns=["Symbol"]), f"setup_{key}", signed=("Gap %", "P&L now %"), name_col="Stock",
                   height=150)
    st.subheader("BTC trend filter")
    bdata, _ = safe(fetch_daily, ("BTC-USD",))
    bt = SU.btc_trend(bdata["BTC-USD"]["Close"]) if bdata and "BTC-USD" in bdata else {}
    if bt:
        st.metric("BTC vs 100-day average", f"${bt['price']:,.0f}", f"{bt['distance%']:+.1f}% · "
                  + ("LONG allowed" if bt["long"] else "STAY FLAT"), delta_color="normal" if bt["long"] else "inverse")
        st.caption("Rule: hold BTC (or trade it long only) while the daily close is above its 100-day average; "
                   "stay flat below. 2021-2026: 31%/yr with a -38% worst drawdown, vs 19%/yr and -77% for buy and hold.")
    else:
        st.caption("BTC prices didn't load.")


# ---------------------------------------------------------------- scanners (intraday research, Oct 2026)

SCAN_BADGE = {"best": ("#0f9d58", "Use"), "ok": ("#1a73e8", "Small edge"), "weak": ("#f29900", "Weak"),
              "no": ("#d93025", "Rejected")}


def _badge(verdict: str) -> str:
    c, t = SCAN_BADGE[verdict]
    return (f"<span style='background:{c}1a;color:{c};border:1px solid {c}55;border-radius:999px;"
            f"padding:1px 10px;font-size:0.8rem;font-weight:600'>{t}</span>")


@st.cache_resource(show_spinner=False)
def get_scan_service(source: str, sig: tuple, version: int = 1):
    """One background loader per data source (and Dhan login), shared by every tab."""
    for old in list(SS.INSTANCES):
        if old.source == source:
            old.stop()
            SS.INSTANCES.remove(old)
    svc = SS.ScanService(source, DCFG if source == "dhan" else None)
    SS.INSTANCES.append(svc)
    return svc


def scan_universe(choice: str) -> tuple:
    if choice.startswith("Nifty"):
        return tuple(SC.NIFTY100)
    return tuple(sorted(fno_universe()[0]))


def page_scanners():
    status_strip()
    st.header("Scanners")
    st.caption("Intraday scanners from the Omnipuls research. They run on all F&O stocks; the backtests behind "
               "them used 5-minute data for the Nifty 100 stocks, Feb 2015 to Apr 2026, after 0.12% costs on shares "
               "and 2% of premium on options. Each tab shows today's signals, how each trade is doing, and what the "
               "backtest found. Past results don't guarantee future ones.")
    c1, c2 = st.columns(2, vertical_alignment="bottom")
    src_opts = (["Dhan (live)"] if DHAN_DATA else []) + ["Yahoo (delayed)"]
    src = c1.selectbox("Data source", src_opts, key="scan_src")
    uni = c2.selectbox("Stocks", ["All F&O stocks", "Nifty 100 (the tested list)"], key="scan_uni")
    source = "dhan" if src.startswith("Dhan") else "yahoo"
    svc = get_scan_service(source, _dhan_sig() if source == "dhan" else ("yahoo",), SS.VERSION)
    svc.set_universe(scan_universe(uni))
    svc.touch()
    scanner_body(svc, uni)


@st.fragment(run_every=20)
def scanner_body(svc, uni):
    now = datetime.now(IST)
    done, total = svc.progress()
    bars, nifty_df = svc.bars()
    fresh = svc.freshness()
    info = st.columns([3, 1], vertical_alignment="center")
    if done < total:
        info[0].progress(done / max(total, 1), text=f"Loading earlier sessions in the background: {done} of {total} "
                         "stocks. Results below fill in as they arrive; after the first load of the day this is instant.")
    else:
        upd = (f"today's bars updated {int(fresh)}s ago" if fresh is not None and SS.market_hours()
               else "market closed: showing the latest session")
        info[0].caption(f"{len(bars)} stocks with data · {upd} · source: {svc.source.title()}"
                        + (f" · last issue: {svc.error}" if svc.error and svc.status.startswith("error") else ""))
    if info[1].button("Refresh view", icon=":material/refresh:", width="stretch", key="scan_refresh"):
        svc.touch()
    if not bars or nifty_df is None or nifty_df.empty:
        st.info("Waiting for the first data… (" + svc.status + ")", icon=":material/hourglass_top:")
        return
    session = SC.session_of(nifty_df)
    S = SC.prepare(bars, session)
    N = SC.Stock("NIFTY 50", nifty_df, session)
    N = N if N.ok else None
    nifty_gap = N.gap if N is not None else None
    live_today = session is not None and session.date() == now.date()
    m = st.columns(4)
    m[0].metric("Session", f"{session:%a %d %b}", "today" if live_today else "last session", delta_color="off", border=True)
    m[1].metric("Stocks scanned", len(S), border=True)
    m[2].metric("Nifty gap at open", f"{nifty_gap * 100:+.2f}%" if nifty_gap is not None else "—",
                "panic day" if nifty_gap is not None and nifty_gap <= -0.005 else None, delta_color="off", border=True)
    last_bar = max(s.today.index[-1] for s in S.values()) if S else None
    m[3].metric("Last 5-min bar", f"{last_bar:%H:%M}" if last_bar is not None else "—", border=True)
    if not live_today:
        st.info("The market isn't open yet today, so these are the last session's signals.", icon=":material/schedule:")

    def head(i):
        name, where, verdict, sh, op, yrs, note = SC.RESEARCH[i]
        st.markdown(f"{_badge(verdict)}&nbsp; **Shares:** {sh} per trade · **Options:** {op} · **Years profitable:** {yrs}"
                    f"<br><span class='muted'>{note}</span>", unsafe_allow_html=True)

    signed = ("P&L %", "Gap %", "Change by 10:00 %")
    tabs = st.tabs(["Research summary", "Gap fade", "Version 3 breakout", "Momentum radar"])
    with tabs[0]:
        rs = pd.DataFrame([{"Setup": r[0], "Verdict": SC.VERDICT_LABEL[r[2]], "Trade with": r[1],
                            "Shares / trade": r[3], "Options / trade": r[4], "Years +": r[5], "Notes": r[6]}
                           for r in SC.RESEARCH])
        data_table(rs, "scan_research", name_col="Setup", height=520)
        st.markdown(
            "**What to trade:** the gap fade, entered at the opening price with a pre-open order on the cash shares "
            "(9:00-9:08), 0.75-1% stop, exit 15:20. The Trade Setups page lists it each morning too.  \n"
            "**For stock options:** nothing tested holds up from 9:20 onward. Run "
            "`research/intraday/gapfade_options_dhan.py` to see whether options bought at 9:15-9:16 still catch the "
            "gap fade on real Dhan option prices.  \n"
            "**Before real money:** paper-trade for 3-4 weeks.")
    with tabs[1]:
        head(0)
        st.caption("Rule: the 2 F&O stocks with the biggest opening gap of 3%+. Buy gap-downs, short gap-ups at the "
                   "open. Stop 1% from entry. Exit 15:20. Panic days (Nifty opens 0.5%+ lower) are the strongest for "
                   "the buy side. '9:15 candle reversed' = the first candle already moved against the gap.")
        g = SC.gap_fade(S, nifty_gap)
        if g.empty:
            st.caption("No stock gapped 3% or more " + ("today." if live_today else "that session."))
        else:
            data_table(g, "scan_gap", signed=signed, name_col="Stock", height=200)
    with tabs[2]:
        head(4)
        st.caption("Rule: at 9:30 rank stocks by ATR%, 9:15-9:30 range, RVOL and gap size; take the top 2. Entry when "
                   "a 5-min candle closes beyond the 9:15-9:30 range by 12:00 with volume 1.5x its 10-day slot "
                   "average and Nifty not broken the other way; enter next candle. Stop 0.5 ATR, trail 1 ATR, exit 15:20.")
        flt = st.toggle("Use the volume and Nifty filters (the test found they add nothing)", value=True, key="v3f")
        v, ranked = SC.version3(S, N, filters=flt)
        if v.empty:
            st.caption("No breakout signal yet." if live_today else "No signal that session.")
        else:
            data_table(v, "scan_v3", signed=signed, name_col="Stock", height=200)
        with st.expander("Top-ranked stocks at 9:30"):
            if not ranked.empty:
                data_table(ranked, "scan_v3_rank", signed=("Gap %",), name_col="Stock", height=380)
    with tabs[3]:
        head(5)
        st.caption("Each stock 1%+ from yesterday's close, compared with the same time window on its last sessions: "
                   "volume since the open and in the last 30 minutes, range, move vs ATR, futures OI change (near + "
                   "next month) and big-money bars (a 5-minute candle with 4x its usual volume, in the move's "
                   "direction, with OI added). Ranked by the tested score; OI and big-money bars are shown but not "
                   "scored. Trade idea that was tested: the #1 stock at 10:30, entry at the 10:30 candle's open, "
                   "1% stop, exit 15:20. OI readings are unreliable in expiry week, when positions roll into these "
                   "contracts.")
        c1, c2 = st.columns(2)
        lookback = c1.select_slider("Compare with the last", [5, 10, 20], value=20, key="rad_lb",
                                    format_func=lambda n: f"{n} sessions")
        asof = c2.radio("Window up to", ["Now", "10:30 (tested time)"], horizontal=True, key="rad_at")
        oi = svc.oi() if hasattr(svc, "oi") else {}
        rd = SC.radar(S, oi, at=SC.dtime(10, 30) if asof.startswith("10:30") else None, lookback=lookback)
        if svc.source == "dhan" and getattr(svc, "oi_status", "") not in ("ready", "off"):
            st.caption(f"Futures OI: {svc.oi_status}")
        if rd.empty:
            st.caption("No stock is 1%+ from yesterday's close yet.")
        else:
            fit = rd[rd["TradeFinder fit"] == "Yes"].head(5)
            st.markdown("**Shortlist: TradeFinder pattern** (broke yesterday's high for CE / low for PE, its sector "
                        "moving the same way, volume 1.5x+ its 20-day usual for this time; top 5 by score)")
            if fit.empty:
                st.caption("No stock fits the pattern yet.")
            else:
                data_table(fit, "scan_radar_fit", signed=("Move %", "From open %", "Sector move %", "OI chg %"),
                           name_col="Stock", height=230)
            st.caption("Checked on 360 of their verified trades (Dec 2024 - Oct 2026): at 10:30 this top 5 held their "
                       "stock on about 27% of days, the top 10 on about 37%. Their pick then ran a further 3% on "
                       "average; the rest of the shortlist usually does not. Use it to narrow the field, then apply "
                       "your own confirmation (5-minute candle, OI build-up) and a small stop.")
            with st.expander(f"All {len(rd)} stocks 1%+ from yesterday's close"):
                data_table(rd, "scan_radar", signed=("Move %", "From open %", "Sector move %", "OI chg %"),
                           name_col="Stock", height=520)
        if live_today:
            radar_log_today(S, oi, session)
        with st.expander("Track record of the 10:30 picks (logged daily)"):
            radar_track_record(bars)


RADAR_LOG = Path(__file__).with_name("radar_log.csv")


def radar_log_today(S: dict, oi: dict, session):
    """Once a day after 10:35, save the radar's top 3 as of 10:30 with their entry (10:30 candle open) and OI readings."""
    now = datetime.now(IST)
    if (now.hour, now.minute) < (10, 35):
        return
    day = f"{session:%Y-%m-%d}"
    try:
        if RADAR_LOG.exists() and day in set(pd.read_csv(RADAR_LOG, usecols=["Date"])["Date"].astype(str)):
            return
    except Exception:
        pass
    rd = SC.radar(S, oi, at=SC.dtime(10, 30), lookback=10).head(3)
    rows = []
    for _, r in rd.iterrows():
        s = S[r["Stock"]]
        nb = s.today[s.today.index.time >= SC.dtime(10, 30)]
        if nb.empty:
            continue
        side = 1 if r["Side"].startswith("BUY") else -1
        entry = float(nb["Open"].iloc[0])
        rows.append({"Date": day, "Rank": r["Rank"], "Stock": r["Stock"], "Side": side,
                     "Entry time": f"{nb.index[0]:%H:%M}", "Entry": entry, "Stop": entry * (1 - side * 0.01),
                     **{k: r[k] for k in ("Score", "Move %", "Volume vs usual", "OI chg %", "OI vs usual", "Buildup",
                                          "Big-money bars")}})
    if rows:
        pd.DataFrame(rows).to_csv(RADAR_LOG, mode="a", header=not RADAR_LOG.exists(), index=False)


def radar_track_record(bars: dict):
    if not RADAR_LOG.exists():
        st.caption("Nothing logged yet: the first picks are saved after 10:35 on a market day with this page open.")
        return
    log = pd.read_csv(RADAR_LOG)
    out = []
    for _, r in log.iterrows():
        df = bars.get(r["Stock"])
        if df is None or df.empty:
            continue
        s = SC.Stock(r["Stock"], df, pd.Timestamp(r["Date"]))
        if not s.ok:
            continue
        hh, mm = map(int, str(r["Entry time"]).split(":"))
        t = s.today[s.today.index.time >= SC.dtime(hh, mm)]
        if t.empty:
            continue
        res = SC.track(s, int(r["Side"]), t.index[0], float(r["Entry"]), float(r["Stop"]))
        out.append({"Date": r["Date"], "Rank": r["Rank"], "Stock": r["Stock"], "Side": "BUY" if r["Side"] > 0 else "SELL",
                    "Entry": r["Entry"], **res, "Net %": res["P&L %"] - 0.12, "Buildup": r["Buildup"],
                    "OI vs usual": r["OI vs usual"], "Big-money bars": r["Big-money bars"]})
    t = pd.DataFrame(out)
    if t.empty:
        st.caption("No logged picks within the loaded data yet.")
        return
    done = t[~t["Status"].isin(["Open"])]
    if not done.empty:
        oi_ok = done["Buildup"].isin(["Long buildup", "Short buildup"])
        summ = []
        for name, x in [("#1 pick", done[done["Rank"] == 1]), ("Top 3", done), ("Top 3, OI confirms (fresh buildup)",
                        done[oi_ok]), ("Top 3, OI does not confirm", done[~oi_ok])]:
            if len(x):
                summ.append({"Group": name, "Trades": len(x), "Avg net %": x["Net %"].mean(),
                             "Win %": (x["Net %"] > 0).mean() * 100})
        st.markdown(f"**{done['Date'].nunique()} days logged.** Net = after 0.12% costs. A few weeks are needed before "
                    "these numbers mean anything.")
        data_table(pd.DataFrame(summ), "radar_summary", signed=("Avg net %",), name_col="Group", height=200)
    data_table(t.sort_values(["Date", "Rank"], ascending=[False, True]), "radar_log", signed=("P&L %", "Net %"),
               name_col="Stock", height=380)

# ---------------------------------------------------------------- Dhan pages


def need_dhan(data: bool = True):
    if not D.configured(DCFG):
        st.info("Connect your Dhan account to use this page.", icon=":material/link:")
    elif not DHAN_ON:
        st.error(DS.get("error") or "Dhan is not reachable right now.")
    elif data and not DS.get("data"):
        st.warning("This page needs Dhan's Data APIs, which are not active on your account. Subscribe under "
                   "My Profile → Access DhanHQ APIs on web.dhan.co, then generate a new token.")
    elif data and not DCFG.get("use_for_data", True):
        st.info("Dhan market data is switched off in Dhan Connect.")
    st.page_link(P["dhan"], label="Open Dhan Connect", icon=":material/settings:")


@st.cache_data(ttl=600, show_spinner=False)
def oc_expiries(sid: int, seg: str) -> list:
    r = D.expiries(sid, seg, DCFG)
    if not r:
        raise D.DhanError("DH-907", "No expiries")
    return r


@st.cache_data(ttl=3, show_spinner=False)
def oc_chain(sid: int, seg: str, expiry: str):
    return D.option_chain(sid, seg, expiry, DCFG)


def oc_refs(under: str) -> list:
    if under in U.OC_INDICES:
        return [U.OC_INDICES[under]]
    m = _maps()
    sid = (m or {}).get("eq", {}).get(under)
    return [(sid, "NSE_FNO"), (sid, "NSE_EQ")] if sid else []


def page_option_chain():
    status_strip()
    st.header("Option chain")
    if not DHAN_DATA:
        need_dhan()
        return
    lots, _ = fno_universe()
    options = list(U.OC_INDICES) + sorted(s for s in lots if s not in U.OC_INDICES)
    if st.session_state.get("oc_under") not in options:
        st.session_state.oc_under = "NIFTY"
    c1, c2, c3 = st.columns([2, 2, 2])
    under = c1.selectbox("Underlying", options, key="oc_under")
    used, exps, err = None, None, None
    for sid, seg in oc_refs(under):
        try:
            exps = oc_expiries(sid, seg)
            used = (sid, seg)
            break
        except Exception as e:
            err = e
    if not exps:
        st.error(f"No option expiries from Dhan for {under}. " + (getattr(err, "friendly", str(err or ""))))
        return
    today = datetime.now(IST).date()
    live = [e for e in exps if pd.Timestamp(e).date() >= today]  # Dhan can still list yesterday's expiry
    exps = live or exps
    if st.session_state.get(f"oc_exp_{under}") not in exps:
        st.session_state.pop(f"oc_exp_{under}", None)
    expiry = c2.selectbox("Expiry", exps, key=f"oc_exp_{under}",
                          format_func=lambda d: pd.Timestamp(d).strftime("%a %d %b %Y"))
    width = c3.slider("Strikes each side of ATM", 5, 40, 12, key="oc_width")
    g1, g2 = st.columns([1, 3])
    show_greeks = g1.toggle("Greeks", key="oc_greeks")
    try:
        with st.spinner("Loading option chain…"):
            spot, ch = oc_chain(used[0], used[1], expiry)
    except D.DhanError as e:
        st.error(e.friendly)
        return
    if ch.empty:
        st.warning("Dhan returned an empty chain for this expiry.")
        return
    if not spot:
        spot = float(ch["Strike"].median())
    atm = float(ch.loc[(ch["Strike"] - spot).abs().idxmin(), "Strike"])
    ce_oi, pe_oi = ch["CE OI"].fillna(0).sum(), ch["PE OI"].fillna(0).sum()
    ce_ch, pe_ch = ch["CE Chg OI"].sum(), ch["PE Chg OI"].sum()
    pcr = pe_oi / ce_oi if ce_oi else np.nan
    mp = D.max_pain(ch)
    res = float(ch.loc[ch["CE OI"].fillna(0).idxmax(), "Strike"])
    sup = float(ch.loc[ch["PE OI"].fillna(0).idxmax(), "Strike"])
    arow = ch[ch["Strike"] == atm].iloc[0]
    atm_iv = np.nanmean([arow["CE IV"] or np.nan, arow["PE IV"] or np.nan])
    dte = (pd.Timestamp(expiry).date() - datetime.now(IST).date()).days
    straddle = (arow["CE LTP"] or 0) + (arow["PE LTP"] or 0)

    m = st.columns(6)
    m[0].metric("Spot", indian_group(spot), border=True)
    m[1].metric("ATM strike", f"{atm:,.0f}", f"IV {atm_iv:.1f}%" if pd.notna(atm_iv) else None, delta_color="off", border=True)
    m[2].metric("PCR (OI)", f"{pcr:.2f}" if pd.notna(pcr) else "—",
                "more puts" if pcr > 1 else "more calls", delta_color="normal" if pcr > 1 else "inverse", border=True)
    m[3].metric("Max pain", f"{mp:,.0f}" if mp else "—", f"{(mp / spot - 1) * 100:+.2f}% from spot" if mp else None,
                delta_color="off", border=True)
    m[4].metric("Support (max put OI)", f"{sup:,.0f}", border=True)
    m[5].metric("Resistance (max call OI)", f"{res:,.0f}", border=True)
    n = st.columns(4)
    n[0].metric("Total call OI", fmt_vol(ce_oi, ".NS"),
                f"{'+' if ce_ch >= 0 else '-'}{fmt_vol(abs(ce_ch), '.NS')} today", delta_color="off")
    n[1].metric("Total put OI", fmt_vol(pe_oi, ".NS"),
                f"{'+' if pe_ch >= 0 else '-'}{fmt_vol(abs(pe_ch), '.NS')} today", delta_color="off")
    n[2].metric("ATM straddle", f"{straddle:,.2f}", f"±{straddle / spot * 100:.2f}% expected move" if spot else None,
                delta_color="off")
    n[3].metric("Days to expiry", "Expires today" if dte == 0 else dte)

    i = int((ch["Strike"] - atm).abs().idxmin())
    view = ch.iloc[max(0, i - width): i + width + 1].reset_index(drop=True)
    o1, o2, o3 = st.columns([2, 2, 2])
    which = o1.segmented_control("Strikes", ["All", "ITM calls", "ITM puts"], default="All", key="oc_which") or "All"
    jump = o2.number_input("Centre on strike", min_value=0.0, value=0.0, step=float(ch["Strike"].diff().median() or 50),
                           key=f"oc_jump_{under}", help="0 = at the money")
    min_oi = o3.number_input("Min OI (either side)", min_value=0, value=0, step=1000, key="oc_minoi")
    if jump:
        j = int((ch["Strike"] - jump).abs().idxmin())
        view = ch.iloc[max(0, j - width): j + width + 1].reset_index(drop=True)
    if which == "ITM calls":
        view = view[view["Strike"] < spot].reset_index(drop=True)
    elif which == "ITM puts":
        view = view[view["Strike"] > spot].reset_index(drop=True)
    if min_oi:
        view = view[(view["CE OI"].fillna(0) >= min_oi) | (view["PE OI"].fillna(0) >= min_oi)].reset_index(drop=True)
    if view.empty:
        st.caption("No strikes match these filters.")
        return
    gk = ["Delta", "Theta", "Gamma", "Vega"] if show_greeks else []
    left = [f"CE {c}" for c in ["OI", "Chg OI", "Volume"] + gk + ["IV", "Chg", "LTP"]]
    right = [f"PE {c}" for c in ["LTP", "Chg", "IV"] + gk + ["Volume", "Chg OI", "OI"]]
    tbl = view[left + ["Strike"] + right]

    def shade(df):
        css = pd.DataFrame("", index=df.index, columns=df.columns)
        itm = "background-color: rgba(232,179,58,.13)"
        for r in df.index:
            k = df.at[r, "Strike"]
            if k < spot:
                css.loc[r, left] = itm
            if k > spot:
                css.loc[r, right] = itm
            if k == atm:
                css.loc[r, "Strike"] = f"font-weight: 700; color: {GOLD}"
            if k == res:
                css.loc[r, "CE OI"] = f"background-color: rgba(239,83,80,.40); font-weight: 700"
            if k == sup:
                css.loc[r, "PE OI"] = f"background-color: rgba(38,166,154,.40); font-weight: 700"
        return css

    styled = (tbl.style.apply(shade, axis=None)
              .map(color_signed, subset=["CE Chg OI", "PE Chg OI", "CE Chg", "PE Chg"]))
    whole = st.column_config.NumberColumn(format="localized")
    two = st.column_config.NumberColumn(format="%.2f")
    cfg = {c: whole for c in ["CE OI", "CE Chg OI", "CE Volume", "PE OI", "PE Chg OI", "PE Volume"]}
    cfg.update({c: two for c in ["CE IV", "CE Chg", "CE LTP", "PE LTP", "PE Chg", "PE IV"]})
    cfg.update({f"{side} {g}": st.column_config.NumberColumn(format="%.4f" if g == "Gamma" else "%.2f")
                for side in ("CE", "PE") for g in ("Delta", "Theta", "Gamma", "Vega")})
    cfg["Strike"] = st.column_config.NumberColumn(format="%.0f", width="small")
    st.dataframe(styled, hide_index=True, width="stretch", height=36 * (len(tbl) + 1) + 4, column_config=cfg)
    st.caption("Shaded cells are in the money. Calls are on the left, puts on the right. The strongest call OI "
               "(resistance) and put OI (support) are highlighted. Source: Dhan option chain, refreshed at most "
               "every 3 seconds.")

    t1, t2, t3 = st.tabs(["Open interest", "Change in OI", "IV smile"])
    for tab, (ce, pe, title) in zip((t1, t2, t3), [("CE OI", "PE OI", "Open interest"),
                                                   ("CE Chg OI", "PE Chg OI", "Change in open interest"),
                                                   ("CE IV", "PE IV", "Implied volatility %")]):
        with tab:
            fig = go.Figure()
            kind = go.Scatter if "IV" in ce else go.Bar
            extra = dict(mode="lines+markers") if kind is go.Scatter else {}
            fig.add_trace(kind(x=view["Strike"], y=view[ce], name="Calls", marker_color=DOWN, **extra))
            fig.add_trace(kind(x=view["Strike"], y=view[pe], name="Puts", marker_color=UP, **extra))
            fig.add_vline(x=spot, line=dict(color=GOLD, dash="dash"), annotation_text=f"Spot {spot:,.0f}")
            fig.update_layout(height=360, barmode="group", margin=dict(l=10, r=10, t=30, b=10), title=title,
                              template=plot_template(), legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig, width="stretch", key=f"oc_{ce}")


def page_mcx():
    if not DHAN_DATA:
        status_strip()
        st.header("MCX commodities")
        need_dhan()
        return
    page_market("MCX (Dhan)", "MCX commodities", tiles_n=4,
                note="Nearest MCX futures in rupees from Dhan, rolled to the next contract at expiry.")
    contracts_note("MCX_COMM", "FUTCOM", U.MCX)


def page_cdsfut():
    if not DHAN_DATA:
        status_strip()
        st.header("Currency futures")
        need_dhan()
        return
    page_market("Currency Futures (Dhan)", "Currency futures (NSE)", tiles_n=4,
                note="Nearest NSE currency futures from Dhan.")
    contracts_note("NSE_CURRENCY", "FUTCUR", U.CURRENCY_FUT)


def contracts_note(seg, ins, names):
    fm = futmap(seg, ins)
    rows = [{"Contract": names[k], "Dhan name": fm[k[4:]]["name"], "Expiry": fm[k[4:]]["expiry"],
             "Lot": fm[k[4:]]["lot"]} for k in names if k[4:] in fm]
    if rows:
        with st.expander("Contracts in use"):
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


@st.cache_data(ttl=15, show_spinner=False)
def pf_fetch(sig: tuple, what: str):
    return {"funds": D.funds, "holdings": D.holdings, "positions": D.positions, "orders": D.orders,
            "trades": D.trades}[what](DCFG)


def _pf(what):
    try:
        return pf_fetch(_dhan_sig(), what), None
    except Exception as e:
        return None, getattr(e, "friendly", str(e))


def page_portfolio():
    status_strip()
    st.header("Portfolio")
    if not DHAN_ON:
        need_dhan(data=False)
        return
    f, err = _pf("funds")
    if f:
        m = st.columns(5)
        m[0].metric("Available balance", f"₹{indian_group(f.get('availableBalance') or 0)}", border=True)
        m[1].metric("Used margin", f"₹{indian_group(f.get('utilizedAmount') or 0)}", border=True)
        m[2].metric("Collateral", f"₹{indian_group(f.get('collateralAmount') or 0)}", border=True)
        m[3].metric("Withdrawable", f"₹{indian_group(f.get('withdrawableBalance') or 0)}", border=True)
        m[4].metric("Opening limit", f"₹{indian_group(f.get('sodLimit') or 0)}", border=True)
    elif err:
        st.error(err)

    tabs = st.tabs(["Holdings", "Positions", "Orders", "Trades"])
    with tabs[0]:
        h, err = _pf("holdings")
        if err:
            st.error(err)
        elif not h:
            st.caption("No holdings.")
        else:
            df = pd.DataFrame(h)
            df["Qty"] = pd.to_numeric(df.get("totalQty"), errors="coerce")
            df["Avg cost"] = pd.to_numeric(df.get("avgCostPrice"), errors="coerce")
            df["Invested"] = df["Qty"] * df["Avg cost"]
            if DHAN_DATA:
                pairs = [("BSE_EQ" if str(r.get("exchange", "")).upper().startswith("BSE") else "NSE_EQ",
                          int(r["securityId"])) for r in h if r.get("securityId")]
                q = quotes_for([(a, b, "EQUITY") for a, b in pairs])
                ltp, pc = [], []
                for (seg, sid) in pairs:
                    qq = q.get((seg, sid)) or {}
                    ltp.append(qq.get("last_price"))
                    pc.append((qq.get("ohlc") or {}).get("close"))
                df["LTP"], df["Prev close"] = ltp, pc
                df["Current value"] = df["Qty"] * df["LTP"]
                df["P&L"] = df["Current value"] - df["Invested"]
                df["P&L %"] = df["P&L"] / df["Invested"] * 100
                df["Day P&L"] = df["Qty"] * (df["LTP"] - df["Prev close"])
                inv, cur, day = df["Invested"].sum(), df["Current value"].sum(), df["Day P&L"].sum()
                k = st.columns(4)
                k[0].metric("Invested", f"₹{indian_group(inv)}")
                k[1].metric("Current value", f"₹{indian_group(cur)}")
                k[2].metric("Total P&L", f"₹{indian_group(cur - inv)}", f"{(cur / inv - 1) * 100:+.2f}%" if inv else None)
                k[3].metric("Today's P&L", f"₹{indian_group(day)}")
            cols = [c for c in ["tradingSymbol", "Qty", "Avg cost", "LTP", "Invested", "Current value", "P&L", "P&L %",
                                "Day P&L", "availableQty", "t1Qty", "collateralQty", "exchange", "isin"] if c in df]
            data_table(df[cols], "pf_holdings", signed=("P&L", "P&L %", "Day P&L"), name_col="tradingSymbol",
                       labels={"tradingSymbol": "Stock", "availableQty": "Free qty", "t1Qty": "T1 qty",
                               "collateralQty": "Pledged", "exchange": "Exchange", "isin": "ISIN"})
    with tabs[1]:
        p, err = _pf("positions")
        if err:
            st.error(err)
        elif not p:
            st.caption("No open positions today.")
        else:
            df = pd.DataFrame(p)
            for c in ("realizedProfit", "unrealizedProfit"):
                df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0)
            df["MTM"] = df["realizedProfit"] + df["unrealizedProfit"]
            k = st.columns(3)
            k[0].metric("Total MTM", f"₹{indian_group(df['MTM'].sum())}")
            k[1].metric("Realised", f"₹{indian_group(df['realizedProfit'].sum())}")
            k[2].metric("Unrealised", f"₹{indian_group(df['unrealizedProfit'].sum())}")
            cols = [c for c in ["tradingSymbol", "positionType", "productType", "netQty", "buyQty", "buyAvg", "sellQty",
                                "sellAvg", "realizedProfit", "unrealizedProfit", "MTM", "drvExpiryDate",
                                "drvOptionType", "drvStrikePrice", "exchangeSegment"] if c in df]
            data_table(df[cols], "pf_positions", signed=("realizedProfit", "unrealizedProfit", "MTM"), name_col="tradingSymbol",
                       labels={"tradingSymbol": "Symbol", "positionType": "Side", "productType": "Product",
                               "netQty": "Net qty", "buyQty": "Buy qty", "buyAvg": "Buy avg", "sellQty": "Sell qty",
                               "sellAvg": "Sell avg", "realizedProfit": "Realised", "unrealizedProfit": "Unrealised",
                               "drvExpiryDate": "Expiry", "drvOptionType": "Type", "drvStrikePrice": "Strike",
                               "exchangeSegment": "Segment"})
    with tabs[2]:
        o, err = _pf("orders")
        if err:
            st.error(err)
        elif not o:
            st.caption("No orders today.")
        else:
            df = pd.DataFrame(o)
            cols = [c for c in ["createTime", "tradingSymbol", "transactionType", "orderType", "productType", "quantity",
                                "filledQty", "price", "triggerPrice", "averageTradedPrice", "orderStatus",
                                "omsErrorDescription"] if c in df]
            data_table(df[cols], "pf_orders", name_col="tradingSymbol",
                       labels={"createTime": "Time", "tradingSymbol": "Symbol", "transactionType": "Side",
                               "orderType": "Type", "productType": "Product", "quantity": "Qty", "filledQty": "Filled",
                               "price": "Price", "triggerPrice": "Trigger", "averageTradedPrice": "Avg traded",
                               "orderStatus": "Status", "omsErrorDescription": "Message"})
    with tabs[3]:
        tr, err = _pf("trades")
        if err:
            st.error(err)
        elif not tr:
            st.caption("No trades today.")
        else:
            df = pd.DataFrame(tr)
            cols = [c for c in ["exchangeTime", "tradingSymbol", "transactionType", "tradedQuantity", "tradedPrice",
                                "productType", "orderType", "exchangeTradeId"] if c in df]
            data_table(df[cols], "pf_trades", name_col="tradingSymbol",
                       labels={"exchangeTime": "Time", "tradingSymbol": "Symbol", "transactionType": "Side",
                               "tradedQuantity": "Qty", "tradedPrice": "Price", "productType": "Product",
                               "orderType": "Type", "exchangeTradeId": "Trade ID"})
    st.caption("Read-only view of your Dhan account. Omnipuls never places, changes or cancels orders.")


def _save_setting(key: str, state_key: str):
    cfg = D.load_config()
    cfg[key] = bool(st.session_state.get(state_key))
    D.save_config(cfg)


def page_dhan():
    st.header("Dhan connect")
    if DHAN_ON:
        p = DS.get("profile") or {}
        st.success(f"Connected to Dhan as client **{p.get('dhanClientId') or DCFG.get('client_id')}**.",
                   icon=":material/check_circle:")
        k = st.columns(4)
        k[0].metric("Access token valid until", str(p.get("tokenValidity") or "—"))
        k[1].metric("Data API plan", str(p.get("dataPlan") or "—"))
        k[2].metric("Data plan valid until", str(p.get("dataValidity") or "—")[:16])
        k[3].metric("Segments", str(p.get("activeSegment") or "—")[:40])
        if not DS.get("data"):
            st.warning("Your Data API plan is not active, so prices come from Yahoo. Portfolio pages still work. "
                       "To get Dhan live data, option chain, MCX and currency futures, subscribe to Data APIs "
                       "on web.dhan.co and generate a new token.")
    elif DS.get("error"):
        st.error(DS["error"])
    else:
        st.info("Not connected. Follow the steps below.", icon=":material/link_off:")

    st.subheader("Connect")
    st.markdown(
        "1. Log in to **web.dhan.co** and open **My Profile → Access DhanHQ APIs**.\n"
        "2. Generate an **access token** (it is valid for 24 hours) and copy it with your **Client ID**.\n"
        "3. Paste both below and press **Save & connect**.\n\n"
        "Live market data, option chain, MCX and currency futures need Dhan's **Data APIs** subscription. "
        "Holdings, positions, funds, orders and trades work with any Dhan account.")
    env = bool(os.environ.get("DHAN_ACCESS_TOKEN"))
    with st.form("dhan_form"):
        cid = st.text_input("Client ID", value=str(DCFG.get("client_id") or ""), key="dh_cid")
        tok = st.text_input("Access token", type="password", key="dh_tok",
                            placeholder="Paste a new token" + (" (leave empty to keep the saved one)"
                                                               if DCFG.get("access_token") else ""))
        ok = st.form_submit_button("Save & connect", type="primary")
    if ok:
        cfg = D.load_config()
        if cid.strip():
            cfg["client_id"] = cid.strip()
        if tok.strip():
            cfg["access_token"] = tok.strip()
        if not (cfg.get("client_id") and cfg.get("access_token")):
            st.error("Enter both the Client ID and the access token.")
        else:
            D.save_config(cfg)
            dhan_status.clear()
            st.session_state.pop("dh_tok", None)
            st.rerun()
    if env:
        st.caption("The DHAN_ACCESS_TOKEN environment variable is set, so it is used instead of the saved token.")
    if PUBLIC:
        st.info("**On Streamlit Cloud, keep your Dhan details in Secrets.** A token pasted above works until the app "
                f"restarts. To keep it, add these lines in **{SECRETS_HELP}** with your own values:", icon=":material/key:")
        st.code('[dhan]\nclient_id = "your client ID"\naccess_token = "your access token"', language="toml")
        st.caption("Dhan tokens expire after 24 hours, so update access_token there each day (or paste the new one "
                   "above for the day). Never put the token in your GitHub files.")
    else:
        st.caption("Your token is saved only in dhan_config.json inside the app folder on this computer. Don't share "
                   "that file. The token expires after 24 hours; renew it below while it is still valid, or paste a "
                   "new one.")

    c1, c2, c3 = st.columns(3)
    if c1.button("Renew token (+24 h)", disabled=not DHAN_ON, width="stretch"):
        try:
            if D.renew_token():
                dhan_status.clear()
                st.success("Token renewed for another 24 hours.")
                st.rerun()
            else:
                st.warning("Dhan did not return a new token. Generate one on web.dhan.co instead.")
        except D.DhanError as e:
            st.error(e.friendly)
    if c2.button("Re-download instrument lists", width="stretch",
                 help="Use if a newly listed stock or contract is missing. Lists refresh daily anyway."):
        for f in D.CACHE.glob("instr_*.pkl"):
            f.unlink(missing_ok=True)
        (D.CACHE / "master.pkl").unlink(missing_ok=True)
        dhan_maps.clear()
        dhan_futmap.clear()
        st.toast("Instrument lists will be downloaded again.")
    if c3.button("Disconnect", disabled=not D.configured(DCFG), width="stretch"):
        cfg = D.load_config()
        cfg.pop("access_token", None)
        D.save_config(cfg)
        dhan_status.clear()
        st.rerun()

    st.subheader("Settings")
    st.toggle("Use Dhan for Indian market data", value=bool(DCFG.get("use_for_data", True)), key="set_use",
              on_change=_save_setting, args=("use_for_data", "set_use"),
              help="Indices, F&O stocks, charts and quotes from Dhan. Crypto, forex, global commodities and "
                   "XAU/USD always come from Yahoo, because Dhan doesn't carry them.")
    st.toggle("Live tick-by-tick feed", value=bool(DCFG.get("live_feed", True)), key="set_feed",
              on_change=_save_setting, args=("live_feed", "set_feed"),
              help="Streams every trade from Dhan's live market feed into the app. Turn off to fall back to "
                   "Dhan's quote API on each refresh.")
    if FEED is not None:
        kind, text = feed_state(FEED)
        st.caption(f"**{text}** · {len(FEED.wanted)} instruments subscribed · {FEED.msgs:,} messages · "
                   f"{getattr(FEED, 'attempts', 0)} connection attempt{'s' if getattr(FEED, 'attempts', 0) != 1 else ''}"
                   + (f"  \n{FEED.error}" if FEED.error and kind == "error" else ""))
        b1, b2 = st.columns(2)
        if b1.button("Check status", icon=":material/refresh:", width="stretch"):
            st.rerun()
        if b2.button("Restart live feed", icon=":material/restart_alt:", width="stretch"):
            get_feed.clear()
            st.rerun()
    st.toggle("Show futures OI & buildup on the F&O page by default", value=bool(DCFG.get("fno_oi", False)),
              key="set_oi", on_change=_save_setting, args=("fno_oi", "set_oi"),
              help="Needs Dhan's F&O contract list, a large download once a day.")
    st.caption("Dhan limits: quotes 1 request per second (up to 1,000 instruments each), history 5 per second, "
               "option chain 1 per 3 seconds. The app paces its requests to stay inside these.")



# ---------------------------------------------------------------- account and users


def page_account():
    st.header("Account")
    st.markdown(f"Signed in as **{USER['name']}** (`{USER['id']}`) · {USER['role']}")
    st.subheader("Appearance")
    names = list(LAYOUTS)
    choice = st.radio("Layout", names, index=names.index(LAYOUT_NAME), key="layout_pick", horizontal=not MOBILE,
                      captions=[LAYOUTS[n]["about"] for n in names])
    if choice != LAYOUT_NAME:
        auth.set_pref(USER["id"], "layout", choice)
        st.rerun()
    st.caption("Your choice is saved to your account and applies on every device you sign in from.")

    st.subheader("Change your password")
    with st.form("pw_form", clear_on_submit=True):
        cur = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password",
                            help="At least 8 characters, mixing letters with numbers or symbols.")
        new2 = st.text_input("Confirm new password", type="password")
        ok = st.form_submit_button("Change password", type="primary")
    if ok:
        if not auth.verify(USER["id"], cur):
            st.error("Your current password is not correct.")
        elif new != new2:
            st.error("The new passwords don't match.")
        else:
            err = auth.set_password(USER["id"], new)
            st.error(err) if err else st.success("Password changed.")
            if not err and PUBLIC:
                st.session_state["_secrets_snip"] = auth.secrets_entry(USER["id"])

    if not IS_ADMIN:
        if PUBLIC:
            st.caption("On Streamlit Cloud, a password changed here lasts until the app restarts. Ask the admin to "
                       "save it in Secrets so it stays.")
        return
    url = lan_url()
    if PUBLIC:
        st.subheader("Open on any device")
        try:
            host = st.context.headers.get("Host") or ""
        except Exception:
            host = ""
        if host:
            st.markdown("Omnipuls is online. Open this address on any phone or computer and sign in:")
            st.code(f"https://{host}", language=None)
    else:
        st.subheader("Open on your phone")
    if PUBLIC:
        pass
    elif url:
        st.markdown(f"Connect your phone to the **same Wi-Fi** as this computer, then open **{url}** in its "
                    "browser and sign in. Add it to your home screen for an app-like icon.")
        st.code(url, language=None)
        st.caption("The first time, Windows may ask whether Python can use the network: allow it on private "
                   "networks. Use this only on your home or office Wi-Fi; don't expose it to the internet.")
    else:
        st.caption("This computer isn't on a network right now.")

    snip = st.session_state.get("_secrets_snip")
    if PUBLIC and snip:
        st.warning("**Save this account in Secrets to keep it.** Streamlit Cloud clears the app's files when it "
                   f"restarts, so accounts added or changed here last only until then. Copy these lines into "
                   f"**{SECRETS_HELP}** (replace any existing lines for this user), then save. The password is "
                   "stored as a hash.")
        st.code(snip, language="toml")
        if st.button("Done, I've saved it", key="snip_done"):
            st.session_state.pop("_secrets_snip", None)
            st.rerun()

    st.subheader("Users")
    users = auth.load()
    rows = [{"User ID": uid, "Name": u["name"], "Role": u["role"],
             "Stored in": "Secrets" if u.get("source") == "secrets" else ("App (until restart)" if PUBLIC else "App"),
             "Created": (u.get("created") or "")[:16].replace("T", " "),
             "Last sign-in": (u.get("last_login") or "never")[:16].replace("T", " ")} for uid, u in sorted(users.items())]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    app_only = [uid for uid, u in sorted(users.items()) if u.get("source") == "app"]
    if PUBLIC and app_only:
        with st.expander(f"{len(app_only)} account(s) not yet saved in Secrets"):
            who_s = st.selectbox("Account", app_only, key="snip_user")
            st.code(auth.secrets_entry(who_s), language="toml")
            st.caption(f"Paste into {SECRETS_HELP} and save, replacing any existing lines for this user, so the "
                       "account survives restarts.")

    a, b = st.columns(2)
    with a:
        with st.form("add_user", clear_on_submit=True):
            st.markdown("**Add a user**")
            name = st.text_input("Name")
            uid = st.text_input("User ID")
            pw = st.text_input("Temporary password", type="password")
            role = st.selectbox("Role", ["user", "admin"],
                                help="Users see market pages. Admins also see Portfolio and Dhan Connect, and manage users.")
            add = st.form_submit_button("Add user", type="primary")
        if add:
            err = auth.create(uid, pw, role, name)
            if err:
                st.error(err)
            else:
                st.success(f"Added {auth.normalize(uid)}. Share the temporary password with them privately.")
                if PUBLIC:
                    st.session_state["_secrets_snip"] = auth.secrets_entry(uid)
                st.rerun()
    with b:
        others = [u for u in sorted(users) if u != USER["id"]]
        st.markdown("**Manage a user**")
        if not others:
            st.caption("No other users yet.")
        else:
            who = st.selectbox("User", others, key="mg_user")
            with st.form("reset_pw", clear_on_submit=True):
                npw = st.text_input("New password for this user", type="password")
                if st.form_submit_button("Reset password"):
                    err = auth.set_password(who, npw)
                    st.error(err) if err else st.success(f"Password reset for {who}.")
            r1, r2 = st.columns(2)
            new_role = "user" if users[who]["role"] == "admin" else "admin"
            if r1.button(f"Make {new_role}", key="mg_role", width="stretch"):
                err = auth.set_role(who, new_role)
                st.error(err) if err else st.rerun()
            confirm = r2.checkbox("Confirm delete", key="mg_conf")
            if r2.button("Delete user", key="mg_del", disabled=not confirm, width="stretch"):
                err = auth.delete(who)
                st.error(err) if err else st.rerun()


def _sign_out():
    for k in list(st.session_state.keys()):
        del st.session_state[k]

PAGE_DEFS = [  # (url, function, menu title, icon)
    ("dashboard", page_dashboard, "Dashboard", ":material/dashboard:"),
    ("indices", page_indices, "NSE Indices & Sectors", ":material/account_balance:"),
    ("setups", page_setups, "Trade Setups", ":material/target:"),
    ("scanners", page_scanners, "Scanners", ":material/radar:"),
    ("sectors", page_sectors, "Sector Performance", ":material/donut_small:"),
    ("fno", page_fno, "F&O Stocks", ":material/candlestick_chart:"),
    ("oi", page_oi, "OI Analysis", ":material/stacked_bar_chart:"),
    ("options", page_option_chain, "Option Chain", ":material/table_chart:"),
    ("crypto", page_crypto, "Crypto", ":material/currency_bitcoin:"),
    ("forex", page_forex, "Forex", ":material/currency_exchange:"),
    ("currency", page_currency, "Currency (INR)", ":material/currency_rupee:"),
    ("commodities", page_commodities, "Commodities", ":material/oil_barrel:"),
    ("mcx", page_mcx, "MCX Commodities", ":material/diamond:"),
    ("cdsfut", page_cdsfut, "Currency Futures", ":material/payments:"),
    ("portfolio", page_portfolio, "Portfolio", ":material/account_balance_wallet:"),
    ("dhan", page_dhan, "Dhan Connect", ":material/link:"),
    ("chart", page_details, "Chart & Details", ":material/show_chart:"),
    ("screener", page_screener, "Screener", ":material/filter_alt:"),
    ("watchlist", page_watchlist, "Watchlist & Alerts", ":material/notifications:"),
    ("account", page_account, "Account", ":material/manage_accounts:"),
]
# Start page: Dashboard, or set NAVV_START_PAGE (e.g. fno, crypto) to open somewhere else.
_start = os.environ.get("NAVV_START_PAGE", "dashboard")
if _start not in {d[0] for d in PAGE_DEFS}:
    _start = "dashboard"
P = {u: st.Page(f, title=t, icon=i, url_path=u, default=(u == _start)) for u, f, t, i in PAGE_DEFS}
nav = st.navigation({
    "Markets": [P["dashboard"], P["setups"], P["scanners"], P["indices"], P["sectors"], P["fno"], P["oi"], P["options"], P["crypto"], P["forex"], P["currency"],
                P["commodities"]],
    "Dhan": [P["mcx"], P["cdsfut"]] + ([P["portfolio"], P["dhan"]] if IS_ADMIN else []),
    "Tools": [P["chart"], P["screener"], P["watchlist"], P["account"]],
})

with st.sidebar:
    u1, u2 = st.columns([3, 2], vertical_alignment="center")
    u1.markdown(f"<span class='muted'>Signed in as</span><br><b>{USER['name']}</b>", unsafe_allow_html=True)
    u2.button("Sign out", key="signout", on_click=_sign_out, width="stretch")
    if FEED is not None:
        if not FEED.connected and not FEED.error and time.time() - getattr(FEED, 'started', 0) < 4:
            for _ in range(15):  # just started: give the socket a moment so the pill isn't stuck on "connecting"
                time.sleep(0.2)
                if FEED.connected or FEED.error:
                    break
        kind, text = feed_state(FEED)
        cls = {"live": "open", "idle": "open", "connecting": "pre", "error": "closed"}[kind]
        dot = '<span class="live-dot"></span>' if kind == "live" else ""
        st.markdown(f'<span class="pill {cls}">{dot}{text if kind != "error" else "Dhan live feed: not connected"}'
                    '</span>', unsafe_allow_html=True)
        if kind == "error":
            st.caption(f"{text} Prices still load from Dhan's quote API.")
    elif DHAN_DATA:
        st.markdown('<span class="pill open">Dhan live data</span>', unsafe_allow_html=True)
    elif DHAN_ON:
        st.markdown('<span class="pill pre">Dhan connected · prices from Yahoo</span>', unsafe_allow_html=True)
    elif D.configured(DCFG):
        st.markdown('<span class="pill closed">Dhan: reconnect needed</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="pill">Dhan not connected · prices from Yahoo</span>', unsafe_allow_html=True)
    sb_status = st.empty()
    st.divider()

    def _quick():
        q = st.session_state.get("quick", "")
        if q.strip():
            go_detail(U.normalize(q))
            st.session_state.quick = ""

    st.text_input("Open any symbol", key="quick", on_change=_quick, placeholder="reliance, btc, usdinr, gold")
    auto = st.toggle("Auto-refresh tables & indicators", value=True, key="auto",
                     help="Live prices stream tick by tick on their own; this refreshes the rest of the page.")
    every = st.select_slider("Refresh every", options=[5, 10, 15, 30, 60, 120, 300],
                             value=60 if FEED is not None else (10 if DHAN_DATA else 30),
                             format_func=lambda s: f"{s}s" if s < 60 else f"{s // 60} min", key="every",
                             disabled=not auto)
    if st.button("Refresh now", width="stretch"):
        fetch_live.clear()
        _build_table.clear()
        dhan_quotes.clear()
        st.rerun()
    if IS_ADMIN and not PUBLIC and st.button("Quit Omnipuls", icon=":material/power_settings_new:", width="stretch",
                 help="Stops the app on this computer. Start it again from the desktop shortcut."):
        st.info("Omnipuls has stopped. You can close this window.")
        import threading
        threading.Timer(1.0, lambda: os._exit(0)).start()
        st.stop()
    st.caption(("Indian markets: Dhan live quotes. " if DHAN_DATA else "Indian markets: Yahoo Finance (can lag a few "
                "minutes). ") + "Crypto, forex, global commodities: Yahoo Finance. F&O list: NSE. "
               "For information only, not investment advice.")

_goto = st.session_state.pop("goto", None)
if _goto in P and getattr(nav, "url_path", "") != _goto:
    st.switch_page(P[_goto])

st.session_state["_last_full"] = time.time()
_BOOT.empty()
st.session_state["_booted"] = True
if DHAN_DATA:  # start loading scanner data in the background so the Scanners page is ready when opened
    try:
        get_scan_service("dhan", _dhan_sig(), SS.VERSION).set_universe(scan_universe(
            st.session_state.get("scan_uni", "All F&O stocks")))
    except Exception:
        pass
if auto:
    @st.fragment(run_every=every)
    def _tick():
        if time.time() - st.session_state.get("_last_full", 0) >= every - 1:
            st.rerun(scope="app")
    _tick()

nav.run()

if DSTAT.get("error"):
    sb_status.caption(f":orange[{DSTAT['error'][:160]}]")
