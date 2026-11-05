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


def _reload_changed_modules():
    """Streamlit re-runs app.py on every page load but keeps imported modules in memory, so after the server pulls new
    code the pages could keep using the old helpers (new levels / cards / AI Desk not showing). Pure helper modules
    whose file changed are dropped from memory here and imported fresh below. Modules that hold live state (Dhan,
    the scan service, the feed, accounts, storage) are never reloaded."""
    import os
    seen = getattr(bootstrap, "_mtimes", None)
    first = seen is None
    if first:
        seen = bootstrap._mtimes = {}
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ("mv_ui", "funnel", "index_funnel", "index_levels", "desk_agents", "agents", "market_view", "bot",
                 "desk", "activity", "indicators", "momentum_study", "five_star", "trend_alert", "setups", "apex", "autotrader", "closing", "btc_sniper", "crash_buy", "bn_ebp"):
        try:
            m = os.stat(os.path.join(base, name + ".py")).st_mtime
        except OSError:
            continue
        if (name in seen and seen[name] != m) or first:  # first pass of a running server: start fresh once
            sys.modules.pop(name, None)
        seen[name] = m


_reload_changed_modules()

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
from plotly.subplots import make_subplots
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
import apex as AP
import activity as A
import indices as IX
import trend_alert as TA
import desk as DK
import twelve as TW
import market_view as MV
import mv_ui as MX
import desk_agents as DA
import funnel as FN
import index_funnel as IF
import index_levels as LV
import bot as BOT
import paths as PATHS
import cryptocom as CC
import cloudstore as CS
import desk_log as DL
import five_star as FIVE
import chain_log as CL
import trade_odds as TO
import fade as FADE
import gold_flow as GF


def _process_start() -> float:
    """When this server process started (Linux, i.e. Streamlit Cloud); elsewhere 'now', so nothing counts as stale."""
    try:
        with open("/proc/self/stat") as fh:
            ticks = int(fh.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/stat") as fh:
            boot = next(int(line.split()[1]) for line in fh if line.startswith("btime"))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except Exception:
        return time.time()


def _stop_background():
    """Stop every background refresher this process started (they live outside Streamlit's caches)."""
    for b in sys.__dict__.get("_omni_boxes", []):
        b["stop"] = True
    sys.__dict__["_omni_boxes"] = []


def _reload_changed():
    """A running Streamlit server re-reads only app.py after a code update (git pull on Streamlit Cloud); imported
    modules can stay old. Reload any module whose file changed, once per file version (remembered per process in
    sys, which survives reruns and cache clears). If a reload fails (Streamlit may be swapping the same module), drop
    it from sys.modules and rerun, so app.py's own import loads the new file."""
    import importlib
    mods = [CS, U, D, ind, auth, fno, F, SC, SU, SS, AP, A, IX, TA, DK, TW, CC, MV, BOT, DL, FIVE, CL, TO, FADE, GF]  # dependencies before the modules that use them
    import hashlib
    seen = sys.__dict__.setdefault("_omni_seen", {})
    started = None
    stale = []

    def digest(path):
        try:
            return hashlib.sha1(Path(path).read_bytes()).hexdigest()
        except Exception:
            return None

    for m in mods:
        try:
            mt = os.path.getmtime(m.__file__)
        except Exception:
            continue
        prev = seen.get(m.__name__)
        if prev is not None and not isinstance(prev, tuple):
            prev = (prev, None)  # remembered by an older version of this function (mtime only)
        if prev is None:  # first look in this process: stale only if the file changed after the process started
            started = _process_start() if started is None else started
            if mt > started + 1:
                stale.append(m)
            seen[m.__name__] = (mt, digest(m.__file__))
        elif mt != prev[0]:
            # A sync tool (OneDrive, Dropbox) can touch a file without changing it; reloading then cleared every
            # cache and the live feed, so the whole app loaded again from scratch. Reload only on a real change.
            h = digest(m.__file__)
            if h != prev[1]:
                stale.append(m)
            seen[m.__name__] = (mt, h)
    if not stale:
        return
    _stop_background()
    for m in (SS, F):  # stop the old background loaders and feeds; the reloaded modules start new ones
        for old in list(getattr(m, "INSTANCES", [])):
            try:
                old.stop()
            except Exception:
                pass
    failed = False
    for m in mods:
        try:
            if sys.modules.get(m.__name__) is m:
                importlib.reload(m)
            else:
                failed = True  # already replaced in sys.modules: the next run imports the new one
        except Exception:
            sys.modules.pop(m.__name__, None)
            failed = True
    st.cache_resource.clear()  # cached loaders, feeds and data were built by the old code
    if failed:
        st.rerun()


_reload_changed()


def _supabase_cfg() -> dict:
    try:
        return dict(st.secrets.get("supabase") or {})
    except Exception:
        return {}


CS.configure(_supabase_cfg().get("url"), _supabase_cfg().get("key"))  # before sign-in, so accounts can be restored

IST = timezone(timedelta(hours=5, minutes=30))
UP, DOWN, GOLD = "#26A69A", "#EF5350", "#E8B33A"
DATA_FILE = PATHS.state("watchlist.json")  # replaced per user after sign-in

ASSETS = Path(__file__).resolve().parent / "assets"
st.set_page_config(page_title="Omnipuls", page_icon=str(ASSETS / "omnipuls_icon.png"), layout="wide",
                   initial_sidebar_state="collapsed")
st.logo(str(ASSETS / "omnipuls_logo.png"), icon_image=str(ASSETS / "omnipuls_mark.png"), size="large")


def _home_screen_icon():
    """Phone home-screen icon and name: Streamlit's page has no apple-touch-icon, so iPhones drew a plain "O". The
    tags are added to the page head (the icons are served from ./static by Streamlit's static serving)."""
    components.html("""<script>
    (function () {
      const d = window.parent.document, h = d.head;
      if (h.querySelector('link[data-omni]')) return;
      const add = (tag, attrs) => { const e = d.createElement(tag); e.setAttribute('data-omni', '1');
        for (const k in attrs) e.setAttribute(k, attrs[k]); h.appendChild(e); };
      add('link', {rel: 'apple-touch-icon', sizes: '180x180', href: '/app/static/apple-touch-icon.png'});
      add('link', {rel: 'manifest', href: '/app/static/manifest.json'});
      add('meta', {name: 'apple-mobile-web-app-title', content: 'Omnipuls'});
      add('meta', {name: 'application-name', content: 'Omnipuls'});
      add('meta', {name: 'apple-mobile-web-app-capable', content: 'yes'});
      add('meta', {name: 'theme-color', content: '#0B1220'});
    })();
    </script>""", height=0)


_home_screen_icon()

st.markdown(
    """
<style>
  /* ---------- Omnipuls design tokens: every colour, size and corner in the app comes from here ---------- */
  :root {
    --om-bg:#0B1220; --om-surface:#121C2E; --om-surface-2:#162238; --om-sunken:#101A2B;
    --om-border:#22314A; --om-border-soft:#1C2A42; --om-border-strong:#2A3A56;
    --om-text:#E6EDF7; --om-text-2:#C9D6EA; --om-text-3:#AFC0DA; --om-muted:#8EA1BF; --om-faint:#7F93B2;
    --om-up:#26A69A; --om-down:#EF5350; --om-warn:#E8B33A; --om-accent:#3B82F6; --om-neutral:#94A3B8;
    --om-up-soft:rgba(38,166,154,.16); --om-down-soft:rgba(239,83,80,.16); --om-accent-soft:rgba(59,130,246,.16);
    --fs-2xs:.68rem; --fs-xs:.74rem; --fs-sm:.85rem; --fs-md:.95rem; --fs-lg:1.15rem; --fs-xl:1.35rem;
    --fs-2xl:1.75rem; --fs-3xl:2.1rem;
    --r-sm:8px; --r-md:12px; --r-lg:16px; --r-pill:999px;
    --font-num:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  }
  html, body, [data-testid="stAppViewContainer"] {font-feature-settings:"tnum" 1, "cv11" 1;}
  [data-testid="stDataFrame"], [data-testid="stTable"], .cell, .tape {font-variant-numeric: tabular-nums;}
  h1, h2, h3 {letter-spacing:-.01em;}
  .om-howto {font-size:var(--fs-sm); color:var(--om-text-3); margin:-.2rem 0 .5rem; padding:.45rem .75rem;
             border-left:3px solid var(--om-accent); background:var(--om-accent-soft); border-radius:0 var(--r-sm) var(--r-sm) 0;}
  .block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
  [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums; font-size:var(--fs-xl);}
  [data-testid="stMetricLabel"] p {font-size:var(--fs-xs); letter-spacing: .05em; text-transform: uppercase; opacity: .78;}
  .status-row {display:flex; flex-wrap:wrap; gap:.45rem; margin:.1rem 0 .8rem;}
  .pill {padding:.16rem .6rem; border-radius:999px; font-size:var(--fs-xs); border:1px solid rgba(128,128,128,.35);}
  .pill.open {color:var(--om-up); border-color:var(--om-up);}
  .pill.closed {color:var(--om-down); border-color:var(--om-down);}
  .pill.pre {color:var(--om-warn); border-color:var(--om-warn);}
  .big-price {font-size:var(--fs-3xl); font-weight:700; font-variant-numeric: tabular-nums; line-height:1.1;}
  .chg-up {color:var(--om-up); font-weight:600;} .chg-down {color:var(--om-down); font-weight:600;}
  .muted {opacity:.65; font-size:var(--fs-sm);}
  .tape {overflow:hidden; white-space:nowrap; border-block:1px solid rgba(128,128,128,.25);
         padding:.45rem 0; margin-bottom:1rem; mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);}
  .tape-track {display:inline-block; animation: tape 45s linear infinite; font-variant-numeric: tabular-nums;}
  .tape:hover .tape-track {animation-play-state: paused;}
  .tape-item {display:inline-block; margin-right:2.2rem; font-size:var(--fs-md);}
  .tape-item b {margin-right:.4rem;}
  @keyframes tape {from {transform: translateX(0);} to {transform: translateX(-50%);}}
  @media (prefers-reduced-motion: reduce) {.tape-track {animation: none;}}
  .live-dot {display:inline-block; width:.5rem; height:.5rem; border-radius:50%; background:var(--om-up);
             margin-right:.35rem; animation: pulse 1.6s ease-in-out infinite;}
  @keyframes pulse {50% {opacity:.25;}}
  .bbar {display:flex; height:8px; border-radius:4px; overflow:hidden; margin-top:.55rem; background:rgba(128,128,128,.2);}
  .bbar span {display:block; height:100%;}
  .bbar.big {height:12px; margin:.2rem 0 .4rem;}
  .cell {padding-top:.45rem; font-variant-numeric: tabular-nums;}
  .hdr {font-size:var(--fs-xs); letter-spacing:.05em; text-transform:uppercase; opacity:.6;}
  /* ---------- phones and small tablets ---------- */
  @media (max-width: 640px) {
    .block-container {padding: .8rem .7rem 3rem !important;}
    h1 {font-size:1.55rem !important;} h2 {font-size:var(--fs-xl) !important;} h3 {font-size:1.08rem !important;}
    [data-testid="stMetricValue"] {font-size:1.1rem;}
    .big-price {font-size:1.7rem;}
    .status-row {gap:.3rem;} .pill {font-size:var(--fs-2xs); padding:.12rem .5rem;}
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
    [class*="st-key-rows_"] .cell, [class*="st-key-rows_"] p, [class*="st-key-rows_"] button {font-size:var(--fs-sm) !important;}
  }
  /* ---------- sign-in screen ---------- */
  .signin-note {opacity:.7; font-size:var(--fs-sm);}
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
# Live ticks straight to the browser even on a public server (needs the HTTPS web server that passes /ticks to the
# relay: deploy/docker-compose.cloud.yml). Without it a public server sends prices every few seconds instead.
TICKS = os.environ.get("OMNIPULS_TICKS") == "1"
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


LANDING_CSS = """<style>
[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl'],header[data-testid='stHeader']{display:none}
.block-container{padding-top:1rem;max-width:1240px}
.stApp{background:
  radial-gradient(900px 520px at 8% -8%,rgba(46,230,246,.16),transparent 60%),
  radial-gradient(800px 600px at 105% 10%,rgba(168,85,247,.14),transparent 60%),
  radial-gradient(900px 700px at 50% 120%,rgba(59,130,246,.16),transparent 60%),#070C18 !important}
.stApp:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.35;
  background-image:linear-gradient(rgba(148,163,184,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(148,163,184,.06) 1px,transparent 1px);
  background-size:44px 44px;mask-image:radial-gradient(ellipse at 50% 30%,#000 30%,transparent 75%)}
.lp-nav{display:flex;justify-content:space-between;align-items:center;padding:6px 2px 14px;border-bottom:1px solid rgba(148,163,184,.10)}
.lp-nav .brand svg{height:38px;width:auto}
.lp-nav .r{display:flex;gap:10px;align-items:center;font-size:var(--fs-xs);color:var(--om-text-3)}
.lp-pill{display:inline-flex;align-items:center;gap:7px;padding:4px 11px;border-radius:999px;border:1px solid rgba(38,166,154,.5);
  color:#5EEAD4;background:rgba(38,166,154,.10);font-size:var(--fs-xs)}
.lp-pill i{width:7px;height:7px;border-radius:50%;background:#2DD4BF;box-shadow:0 0 10px #2DD4BF;animation:lpp 1.6s infinite}
.lp-pill.off{border-color:rgba(148,163,184,.4);color:var(--om-text-3);background:rgba(148,163,184,.08)}
.lp-pill.off i{background:#94A3B8;box-shadow:none;animation:none}
@keyframes lpp{50%{opacity:.3}}
.lp-hero{padding:34px 0 8px}
.lp-eyebrow{display:inline-flex;gap:8px;align-items:center;font-size:var(--fs-xs);letter-spacing:.08em;text-transform:uppercase;
  color:#9FD8FF;padding:5px 12px;border-radius:999px;border:1px solid rgba(46,230,246,.35);background:rgba(46,230,246,.07)}
.lp-hero h1{font-size:clamp(2.1rem,4.6vw,3.6rem);line-height:1.04;letter-spacing:-.02em;margin:18px 0 14px;font-weight:800;
  background:linear-gradient(100deg,#F8FAFC 0%,#C7E7FF 45%,#2EE6F6 75%,#A78BFA 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.lp-hero .sub{font-size:1.06rem;line-height:1.6;color:var(--om-text-3);max-width:600px}
.lp-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:26px 0 6px;max-width:640px}
.lp-stats div{border:1px solid rgba(148,163,184,.14);border-radius:14px;padding:12px 14px;background:rgba(15,23,42,.55);backdrop-filter:blur(6px)}
.lp-stats b{display:block;font-family:var(--font-num);font-size:1.5rem;color:#F1F5F9}
.lp-stats span{font-size:var(--fs-xs);color:var(--om-faint)}
.st-key-login_card{border:1px solid rgba(148,163,184,.22);border-radius:22px;padding:26px 24px 18px !important;margin-top:40px;
  background:linear-gradient(160deg,rgba(30,41,59,.72),rgba(15,23,42,.62));backdrop-filter:blur(14px);
  box-shadow:0 30px 80px -30px rgba(46,230,246,.35),inset 0 1px 0 rgba(255,255,255,.06)}
.st-key-login_card input{background:rgba(2,6,23,.6) !important;border-radius:12px !important}
.st-key-login_card button[kind="primary"],.st-key-login_card button[data-testid="stBaseButton-primary"],
.st-key-login_card [data-testid="stFormSubmitButton"] button{background:linear-gradient(90deg,#2563EB,#06B6D4) !important;border:0 !important;
  border-radius:12px !important;height:46px;font-weight:700;box-shadow:0 10px 30px -10px rgba(6,182,212,.6)}
.lp-card-h h3{margin:0 0 4px;font-size:1.35rem}.lp-card-h p{margin:0 0 16px;color:var(--om-text-3);font-size:var(--fs-sm)}
.lp-trust{display:flex;flex-direction:column;gap:7px;margin-top:14px;font-size:var(--fs-xs);color:var(--om-text-3)}
.lp-trust span:before{content:"✓";color:#2DD4BF;font-weight:700;margin-right:8px}
.lp-tape{overflow:hidden;white-space:nowrap;border-block:1px solid rgba(148,163,184,.12);margin:30px 0 8px;padding:10px 0;
  mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent)}
.lp-tape div{display:inline-block;animation:lpt 40s linear infinite}
.lp-tape span{margin:0 22px;font-size:var(--fs-sm);color:var(--om-text-3);letter-spacing:.04em}
.lp-tape span b{color:#E2E8F0;margin-right:6px}
@keyframes lpt{from{transform:translateX(0)}to{transform:translateX(-50%)}}
@media (prefers-reduced-motion:reduce){.lp-tape div,.lp-pill i{animation:none}}
.lp-sec{margin:46px 0 14px;text-align:center}
.lp-sec .k{font-size:var(--fs-xs);letter-spacing:.14em;text-transform:uppercase;color:#2EE6F6}
.lp-sec h2{font-size:clamp(1.5rem,2.6vw,2.1rem);margin:8px 0 6px;letter-spacing:-.01em}
.lp-sec p{color:var(--om-text-3);max-width:640px;margin:0 auto}
.lp-preview{position:relative;border:1px solid rgba(148,163,184,.18);border-radius:22px;padding:18px;margin-top:18px;
  background:linear-gradient(180deg,rgba(15,23,42,.85),rgba(2,6,23,.85));box-shadow:0 40px 120px -40px rgba(59,130,246,.45)}
.lp-preview .bar{display:flex;gap:6px;margin-bottom:12px}.lp-preview .bar i{width:10px;height:10px;border-radius:50%;background:#334155}
.lp-preview .tag{position:absolute;top:14px;right:16px;font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;color:var(--om-faint)}
.lp-grid{display:grid;grid-template-columns:1fr 1.4fr;gap:12px;margin-top:12px}
.lp-preview .mx-pulse{grid-template-columns:repeat(3,1fr)}.lp-preview .mx-sig{grid-template-columns:repeat(3,1fr)}
@media (max-width:900px){.lp-preview .mx-pulse{grid-template-columns:none}.lp-preview .mx-sig{grid-template-columns:1fr}}
.lp-feat{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:18px}
.lp-f{border:1px solid rgba(148,163,184,.14);border-radius:18px;padding:18px;background:rgba(15,23,42,.6);transition:transform .2s,border-color .2s}
.lp-f:hover{transform:translateY(-3px);border-color:rgba(46,230,246,.45)}
.lp-f .ic{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;font-size:20px;margin-bottom:12px;
  background:color-mix(in srgb,var(--c) 18%,transparent);border:1px solid color-mix(in srgb,var(--c) 45%,transparent)}
.lp-f h4{margin:0 0 6px;font-size:1.02rem}.lp-f p{margin:0;font-size:var(--fs-sm);color:var(--om-text-3);line-height:1.5}
.lp-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:18px}
.lp-s{position:relative;border-radius:18px;padding:20px;border:1px solid rgba(148,163,184,.14);background:rgba(15,23,42,.5)}
.lp-s b{font-family:var(--font-num);font-size:2rem;background:linear-gradient(90deg,#2EE6F6,#A78BFA);-webkit-background-clip:text;color:transparent}
.lp-s h4{margin:6px 0}.lp-s p{margin:0;color:var(--om-text-3);font-size:var(--fs-sm);line-height:1.5}
.lp-honest{margin:40px 0 10px;border-radius:20px;padding:22px 24px;border:1px solid rgba(250,204,21,.3);
  background:linear-gradient(120deg,rgba(250,204,21,.08),rgba(15,23,42,.6));display:flex;gap:18px;align-items:center}
.lp-honest .ic{font-size:30px}.lp-honest h4{margin:0 0 4px}.lp-honest p{margin:0;color:var(--om-text-3);font-size:var(--fs-sm)}
.lp-foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;margin:34px 0 10px;padding-top:14px;
  border-top:1px solid rgba(148,163,184,.10);font-size:var(--fs-xs);color:var(--om-faint)}
@media (max-width:900px){.lp-feat,.lp-steps{grid-template-columns:1fr 1fr}.lp-grid{grid-template-columns:1fr}.lp-stats{grid-template-columns:1fr 1fr}
  .st-key-login_card{margin-top:8px}.lp-hero{padding-top:18px}}
@media (max-width:560px){.lp-feat,.lp-steps{grid-template-columns:1fr}.lp-nav .r .hide{display:none}}
</style>"""


def _landing_hero() -> tuple[str, str]:
    """(top: nav + headline + stats; rest: tape, product preview, features, how it works, honesty strip, footer)."""
    try:
        logo = (Path(__file__).resolve().parent / "brand" / "concept1_momentum_logo_dark_bg.svg").read_text()
    except Exception:
        logo = "<b style='font-size:1.4rem'>omnipuls</b>"
    now = datetime.now(IST)
    live = now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"
    pill = (f"<span class='lp-pill'><i></i>NSE live</span>" if live else "<span class='lp-pill off'><i></i>NSE closed</span>")
    top = f"""<div class='lp-nav'><div class='brand'>{logo}</div>
  <div class='r'>{pill}<span class='hide'>{now:%a %d %b · %H:%M} IST</span></div></div>
<div class='lp-hero'>
  <span class='lp-eyebrow'>● Live market intelligence · private access</span>
  <h1>See where the smart money moves, before the crowd.</h1>
  <div class='sub'>Omnipuls turns live market data into clear, ready-to-act ideas for Indian F&amp;O traders, all on one
  screen, refreshed through the day.</div>
  <div class='lp-stats'><div><b>235</b><span>F&amp;O stocks covered</span></div><div><b>5</b><span>indices tracked</span></div>
  <div><b>41</b><span>markets on the AI Desk</span></div><div><b>24/7</b><span>bots at work</span></div></div>
</div>"""
    tape = "".join(f"<span><b>{a}</b>{b}</span>" for a, b in (
        ("MARKET VIEW", "the whole market on one page"), ("SMART WATCHLIST", "the stocks worth watching now"),
        ("INDEX INTELLIGENCE", "Nifty · Bank Nifty · Fin Nifty · Sensex · Midcap"), ("BOTS", "watching all day"),
        ("AI DESK", "Indian market · crypto · forex · commodities · rupee"), ("SECTORS", "where the money is going")))
    gauge = MX.gauge(46, "Bullish", 9, 4, 3)
    tiles = MX.pulse([
        MX.pulse_tile("Nifty 50", {"last": 24368.5, "chg": 0.62, "closes": pd.Series(np.cumsum(np.r_[0, np.sin(np.arange(40) / 5) * 6 + 2]) + 24200)}, None),
        MX.pulse_tile("Bank Nifty", {"last": 55912.3, "chg": -0.21, "closes": pd.Series(55950 - np.cumsum(np.r_[0, np.cos(np.arange(40) / 4) * 9 + 1]))}, None),
        MX.pulse_tile("India VIX", {"last": 12.84, "chg": -3.1, "closes": pd.Series(13.3 - np.arange(41) * 0.012)}, None, invert=True)])
    funnel = MX.funnel([("Stocks covered", 235, "updated through the day"), ("Shortlisted", 24, ""),
                        ("Watchlist", 5, "ranked")])
    sig = MX.signal_cards(pd.DataFrame([
        {"Signal": "Index signal: LONG", "Status": "● SIGNAL", "Evidence": "Tested", "Details": "entry, stop and target on screen"},
        {"Signal": "Index signal: SHORT", "Status": "● SIGNAL", "Evidence": "Tested", "Details": "entry, stop and target on screen"},
        {"Signal": "Stock idea: LONG", "Status": "Watch", "Evidence": "Context", "Details": "ranked on the watchlist"}]), 3)
    feats = "".join(f"<div class='lp-f' style='--c:{c}'><div class='ic'>{i}</div><h4>{h}</h4><p>{p}</p></div>" for i, c, h, p in (
        ("◎", "#3B82F6", "Market View", "The whole market at a glance, with every live signal on one page."),
        ("⧩", "#2EE6F6", "Smart watchlist", "A short, ranked list of the stocks worth watching right now."),
        ("▲", "#26A69A", "Index intelligence", "Nifty, Bank Nifty, Fin Nifty, Sensex and Midcap with key levels and signals."),
        ("⚡", "#F59E0B", "Bots", "Bots watch the market all day and flag what changes."),
        ("✦", "#A855F7", "AI Desk", "Indian market first, then crypto, forex, commodities and the rupee."),
        ("◫", "#EF5350", "Sectors", "See which sectors and stocks the money is moving into.")))
    rest = f"""<div class='lp-tape'><div>{tape}{tape}</div></div>
<div class='lp-sec'><div class='k'>Inside the app</div><h2>Everything that moves the market, in one place</h2>
<p>A preview of the app (sample data).</p></div>
<div class='lp-preview'><div class='bar'><i></i><i></i><i></i></div><span class='tag'>Preview · sample data</span>
  {tiles}<div class='lp-grid'><div>{gauge}</div><div>{funnel}</div></div><div style='margin-top:12px'>{sig}</div></div>
<div class='lp-sec'><div class='k'>Features</div><h2>Built for intraday F&amp;O traders</h2></div>
<div class='lp-feat'>{feats}</div>
<div class='lp-sec'><div class='k'>How it works</div><h2>Open, read, act</h2></div>
<div class='lp-steps'>
  <div class='lp-s'><b>01</b><h4>Live data</h4><p>Market data flows in through the trading day.</p></div>
  <div class='lp-s'><b>02</b><h4>Bots do the work</h4><p>Our bots watch everything so you don't have to.</p></div>
  <div class='lp-s'><b>03</b><h4>Clear ideas</h4><p>Signals with entry, stop and target, logged and scored.</p></div>
</div>
<div class='lp-honest'><div class='ic'>⚖</div><div><h4>Honest by design</h4><p>Every signal is logged and scored, so results speak
for themselves.</p></div></div>
<div class='lp-foot'><span>© Omnipuls · private app</span><span>For information only, not investment advice.</span></div>"""
    return top, rest


def login_screen():
    for _c in (LANDING_CSS, MX.CSS, MX.FUNNEL_CSS):
        st.markdown(_c, unsafe_allow_html=True)
    top, rest = _landing_hero()
    left, right = (st.container(), st.container()) if MOBILE else st.columns([1.5, 1], gap="large")
    with left:
        st.markdown(top, unsafe_allow_html=True)
    with right:
        card = st.container(key="login_card")
        with card:
            if not auth.has_users() and PUBLIC:
                st.markdown("<div class='lp-card-h'><h3>Set up the admin account</h3><p>This server is public, so accounts "
                            "are added in the app's Secrets, not here.</p></div>", unsafe_allow_html=True)
                st.code('[users.navneet]\nname = "Navneet"\nrole = "admin"\npassword = "choose-a-strong-password"',
                        language="toml")
                st.caption(f"Add it in {SECRETS_HELP}, save, and reload this page.")
            elif not auth.has_users():
                st.markdown("<div class='lp-card-h'><h3>Create your admin account</h3><p>First start: the admin adds users, "
                            "connects Dhan and sees the portfolio.</p></div>", unsafe_allow_html=True)
                with st.form("setup_form", border=False):
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
                st.markdown("<div class='lp-card-h'><h3>Welcome back 👋</h3><p>Sign in to open today's market."
                            "</p></div>", unsafe_allow_html=True)
                if not st.session_state.get("_show_login"):
                    if st.button("Sign in", type="primary", width="stretch", icon=":material/login:", key="show_login"):
                        st.session_state["_show_login"] = True
                        st.rerun()
                else:
                    with st.form("login_form", border=False):
                        uid = st.text_input("User ID", key="li_uid", autocomplete="username")
                        pw = st.text_input("Password", type="password", key="li_pw", autocomplete="current-password")
                        ok = st.form_submit_button("Sign in", type="primary", width="stretch", icon=":material/login:")
                    if ok:
                        wait = auth.locked_for(uid)
                        user = None if wait else auth.verify(uid, pw)
                        if user:
                            st.session_state.user = user
                            st.rerun()
                        wait = auth.locked_for(uid)
                        st.error(f"Too many wrong passwords. Try again in {wait // 60 + 1} min." if wait
                                 else "Wrong user ID or password.")
                    st.caption("Forgot your password? Ask the admin to reset it under Account.")
                st.markdown("<div class='lp-trust'><span>Private: invite-only accounts</span><span>Live market data"
                            "</span><span>Every signal logged and scored</span></div>", unsafe_allow_html=True)
    st.markdown(rest, unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def _link_secret() -> bytes:
    import secrets as _sec
    return _sec.token_bytes(32)  # new on every server start, so old chart links stop working after a restart


if "user" not in st.session_state and st.query_params.get("t"):
    _u = auth.check_link_token(st.query_params.get("t"), _link_secret())
    if _u:
        st.session_state.user = _u
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


DATA_FILE = PATHS.state(f"watchlist_{USER['id']}.json")
_OLD = PATHS.state("watchlist.json")
if IS_ADMIN and not DATA_FILE.exists() and _OLD.exists():  # keep the watchlist from before accounts existed
    try:
        DATA_FILE.write_text(_OLD.read_text())
    except Exception:
        pass


def load_store() -> dict:
    CS.restore(DATA_FILE)  # after a cloud restart: the watchlist kept in Supabase
    try:
        return json.loads(DATA_FILE.read_text())
    except Exception:
        return {"watchlist": ["^NSEI", "RELIANCE.NS", "HDFCBANK.NS", "GC=F", "BTC-USD", "USDINR=X"], "alerts": []}


def save_store(store: dict):
    try:
        DATA_FILE.write_text(json.dumps(store, indent=2))
        CS.save(DATA_FILE.name, store)
    except Exception as e:
        st.warning(f"Could not save the watchlist file: {e}")


if "store" not in st.session_state:
    st.session_state.store = load_store()
store = st.session_state.store
st.session_state.setdefault("detail_pick", "^NSEI")

# ---------------------------------------------------------------- Dhan connection

DCFG = D.load_config()
TOKEN_CODES = ("DH-901", "401", "807", "808", "809")


@st.cache_resource(show_spinner=False)
def _auto_token() -> dict:
    import threading
    return {"token": None, "expiry": None, "error": None, "made": None, "tried": 0.0, "lock": threading.Lock()}


def ensure_auto_token(force: bool = False):
    """With the Dhan PIN and TOTP secret in Secrets, keep a valid token with no daily step: a new one is made when
    there is none, when it has under an hour left, or when Dhan rejects it (force). Shared by every visitor; at most
    one attempt every 2 minutes."""
    if not D.can_auto_token(DCFG):
        return
    box = _auto_token()
    now = datetime.now(IST)
    with box["lock"]:
        try:  # a newer token saved by another process (the data recorder) wins over the one in memory, so the two
            disk_exp = datetime.fromisoformat(str(DCFG.get("token_expiry")))  # don't keep replacing each other's
        except ValueError:
            disk_exp = None
        if disk_exp is not None and disk_exp.tzinfo is None:
            disk_exp = disk_exp.replace(tzinfo=IST)
        if (DCFG.get("access_token") and disk_exp and DCFG["access_token"] != box["token"]
                and (box["expiry"] is None or disk_exp > box["expiry"]) and disk_exp - now > timedelta(hours=1)):
            box.update(token=DCFG["access_token"], expiry=disk_exp)
        fresh = bool(box["token"] and box["expiry"] and box["expiry"] - now > timedelta(hours=1))
        if not fresh and not force:
            try:
                exp = datetime.fromisoformat(str(DCFG.get("token_expiry")))
            except ValueError:
                exp = None
            if DCFG.get("access_token") and exp and exp - now > timedelta(hours=1):
                box.update(token=DCFG["access_token"], expiry=exp)  # still valid from this computer's last run
                fresh = True
        if (force or not fresh) and time.time() - box["tried"] > 120:
            box["tried"] = time.time()
            try:
                tok, exp = D.generate_token(DCFG)
                box.update(token=tok, expiry=exp, error=None, made=now)
            except Exception as e:
                box["error"] = f"{now:%d %b %H:%M}: {getattr(e, 'friendly', e)}"
        if box["token"]:
            DCFG["access_token"] = box["token"]


ensure_auto_token()


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


@st.cache_resource(show_spinner=False)
def _dhan_down() -> dict:
    return {"until": 0.0, "error": "", "sig": None}  # shared by every session: when Dhan last failed to answer


DHAN_RETRY_AFTER = 120  # seconds to wait after a network failure before asking Dhan again


def dhan_status_safe(sig: tuple) -> dict:
    """dhan_status, but a network failure is remembered for 2 minutes. Without this, every page load and every
    auto-refresh waited on Dhan again (up to a minute with retries) while Dhan was unreachable."""
    down = _dhan_down()
    if down["sig"] == sig and time.time() < down["until"]:  # new credentials are always checked straight away
        raise RuntimeError(down["error"] or "Dhan did not answer")
    try:
        return dhan_status(sig)
    except Exception as e:
        down.update(until=time.time() + DHAN_RETRY_AFTER, error=str(e)[:200], sig=sig)
        raise


if D.configured(DCFG):
    try:
        DS = dhan_status_safe(_dhan_sig())
        sec_tok = DCFG.get("_secret_token")
        if not DS["ok"] and DS.get("code") in TOKEN_CODES and D.can_auto_token(DCFG):
            ensure_auto_token(force=True)  # rejected (expired, or replaced by a token made elsewhere): make a new one
            DS = dhan_status_safe(_dhan_sig())
        elif not DS["ok"] and DS.get("code") in TOKEN_CODES and sec_tok and sec_tok != DCFG.get("access_token"):
            DCFG["access_token"] = sec_tok  # the token pasted in the app expired; Secrets has a different one
            DS = dhan_status_safe(_dhan_sig())
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
    """A token can only be renewed while it is still valid: do it in its last 3 hours, so the app keeps working.
    Not needed (and not used) when tokens are made automatically from the PIN and TOTP."""
    if D.can_auto_token(DCFG):
        return
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
    err = None
    if rest and time.time() >= YAHOO_STATE["down_until"]:
        try:
            got = _yahoo_daily(rest)
            out.update(got)
            if not got:
                raise RuntimeError("No data returned")
        except Exception as e:
            err = e
            YAHOO_STATE.update(down_until=time.time() + 900, error=str(e)[:200])  # skip Yahoo 15 min, don't wait on it
    missing = tuple(s for s in rest if s not in out)
    if missing:  # crypto: Crypto.com's free public prices, so Twelve Data's daily credits go to forex and gold
        out.update(CC.daily(missing))
        missing = tuple(s for s in missing if s not in out)
    if missing and _twelve_key():
        out.update(TW.daily(missing, _twelve_key()))
    if rest and not out and err is not None:
        raise err
    if rest and not out and time.time() < YAHOO_STATE["down_until"]:
        raise RuntimeError("Yahoo is not answering from this server" +
                           ("" if _twelve_key() else "; add a Twelve Data key in Secrets as the fallback"))
    return out


@st.cache_resource(show_spinner=False)
def _yahoo_state() -> dict:
    return {"down_until": 0.0, "error": ""}


# Must survive reruns: as a plain dict here it was reset on every page load (app.py runs top to bottom each time),
# so "skip Yahoo for 15 minutes after a failure" never took effect and every refresh waited on Yahoo again.
YAHOO_STATE = _yahoo_state()


def _twelve_key() -> str:
    try:
        k = (st.secrets.get("twelvedata") or {}).get("api_key")
    except Exception:
        k = None
    return str(k or os.environ.get("TWELVEDATA_API_KEY") or "")


@st.cache_data(ttl=20, show_spinner=False)
def fetch_history(symbol: str, period: str, interval: str):
    data = _download((symbol,), period, interval)
    df = data.get(symbol)
    if df is not None and isinstance(df.index, pd.DatetimeIndex) and interval not in ("1d", "1wk", "1mo"):
        idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
        df.index = idx.tz_convert("Asia/Kolkata")
    return df


DHAN_INTRA = {"1m": (1, 5), "3m": (1, 5), "5m": (5, 10), "10m": (5, 20), "15m": (15, 30), "25m": (25, 45),
              "1h": (60, 90)}
RESAMPLED = {"3m": 3, "10m": 10}  # built from 1- and 5-minute candles


def resample_bars(df: pd.DataFrame, minutes: int, indian: bool = True) -> pd.DataFrame:
    """Candles of `minutes` from smaller ones; Indian sessions start at 9:15."""
    if df is None or df.empty:
        return df
    return df.resample(f"{minutes}min", origin="start_day", offset="15min" if indian else "0min").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])


@st.cache_data(ttl=5, show_spinner=False)
def dhan_intraday(seg: str, sid: int, ins: str, tf: str) -> pd.DataFrame:
    interval, days = DHAN_INTRA[tf]
    df = D.intraday(seg, sid, ins, interval, days, DCFG)
    return resample_bars(df, RESAMPLED[tf]) if tf in RESAMPLED else df


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
    yahoo_down = time.time() < YAHOO_STATE["down_until"]
    df = None if yahoo_down else fetch_history(sym, period, interval)
    src = "Yahoo"
    if (df is None or df.empty) and CC.coin_of(sym):  # Yahoo failed: Crypto.com for crypto (free, no key)
        df = CC.candles(sym, interval, 300)
        if df is not None and not df.empty:
            src = "Crypto.com"
            if interval not in ("1d", "1wk", "1mo"):
                df = df.copy()
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
    if (df is None or df.empty) and _twelve_key():  # Yahoo failed (common on cloud servers): Twelve Data
        bars = {"5d": 7200, "1mo": 3000, "3mo": 1600, "1y": 260, "5y": 270, "max": 400}.get(period, 1500)
        df = TW.history(sym, interval, _twelve_key(), bars)
        if df is not None and not df.empty:
            src = "Twelve Data"
            if interval not in ("1d", "1wk", "1mo"):
                df = df.copy()
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
    if df is None or df.empty:
        return df, src
    if tf in RESAMPLED:
        df = resample_bars(df, RESAMPLED[tf], indian=str(sym).endswith((".NS", ".BO")) or str(sym).startswith("^NSE"))
    return df, src


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
    if pending and time.time() >= YAHOO_STATE["down_until"]:
        try:
            found.update(resolve(tuple(pending)))
        except Exception as e:
            YAHOO_STATE.update(down_until=time.time() + 900, error=str(e)[:200])  # don't re-probe on every run
    for label, cs in pending:  # Yahoo down: the first candidate Twelve Data covers, else the first one
        if label not in found:
            found[label] = next((c for c in cs if TW.td_symbol(c)), cs[0])
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


_NOTES: list = []  # method / research texts of this page run, shown together in one collapsed box at the bottom


def note(*args, **kw):
    """How a reading is computed or what the research found (admin only). Collected into the page's collapsed
    "How it works" box instead of filling the page."""
    if IS_ADMIN and args and all(args[0] != a[1][0] for a in _NOTES):
        _NOTES.append(("caption", args, kw))


def note_md(*args, **kw):
    if IS_ADMIN and args and all(args[0] != a[1][0] for a in _NOTES):
        _NOTES.append(("markdown", args, kw))


HOWTO = {  # one line under each page's status bar: what the page is for and how to use it
    "view": "Start here. Trade only what the top box calls a tested signal; the rest helps you pick the side.",
    "dashboard": "The full desk: mood, index plans and focus lists. Today's plan card lists the tested setups.",
    "scanners": "Each tab is one setup with today's signals. Follow entry, stop and exit exactly as shown.",
    "funnel": "ATR active → range expanding → sector money → stock money growing → with the market = watchlist, ranked by score.",
    "agents": "Six agents read the Indian market first, then crypto, forex, commodities and the rupee. TRADE only when all agree and risk passes; paper-track first.",
    "bot": "Live radar of every F&O stock: sudden changes vs its own usual, with past-days odds. Tested = trade; good odds = paper-trade first.",
    "options": "Pick an index and expiry. Most puts written = support, most calls written = resistance.",
    "apex": "Trade with the side that dominates the first hour; 'Since yesterday' adds yesterday's positions.",
    "smart": "Sectors where fresh futures money is going, and their strongest stocks.",
    "fno": "All F&O stocks: filter, sort, and open Unusual activity or Money flow from the switch at the top.",
    "oi": "Futures OI build-up by stock: long build-up and short covering are bullish, the other two bearish.",
    "chart": "Pick a symbol and timeframe; levels and indicators are drawn on the chart.",
    "screener": "Choose a ready scan or set filters; click a row to open its chart.",
    "watchlist": "Your symbols and price alerts; alerts pop up while the app is open.",
}


def status_strip():
    now = datetime.now(IST)
    _how = HOWTO.get(getattr(globals().get("nav"), "url_path", "") or "")
    if _how:
        st.markdown(f"<div class='om-howto'>{_how}</div>", unsafe_allow_html=True)
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


def chart_link(sym: str) -> str:
    """URL that opens this symbol's chart in a new browser tab, already signed in (link valid 12 hours)."""
    import urllib.parse
    return f"chart?sym={urllib.parse.quote(sym)}&t={auth.link_token(USER['id'], _link_secret())}"


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
    "O=H/L": ("Open = H/L", "text", None),
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
    "R-factor": ("R-factor", "num0", None), "Flow Cr": ("Flow ₹ Cr", "signed0", None),
    "Volume vs usual": ("Vol × usual", "ratio", None), "OI vs usual": ("OI × usual", "ratio", None),
    "Range vs usual": ("Range × usual", "ratio", None), "Move / ATR": ("Move / ATR", "ratio", None),
    "Broke yday high/low": ("Broke yday H/L", "text", None), "Big-money bars": ("Big bars", "int", None),
    "Side": ("Side", "text", None),
    # unusual activity
    "Smart": ("Smart score", "signed0", None), "Peak Smart": ("Peak today", "signed0", None),
    "Activity": ("Activity", "num0", None), "Direction": ("Direction", "signed", None),
    "Candle": ("Candle", "badge", None), "Time": ("Candle at", "text", None),
    "Vol x (time)": ("Vol × avg (time)", "ratio", None), "Turnover x (time)": ("Turnover × avg (time)", "ratio", None),
    "Range x (time)": ("Range × avg (time)", "ratio", None), "Candle Vol x": ("Candle vol ×", "ratio", None),
    "Candle Range x": ("Candle range ×", "ratio", None), "Candle OI x": ("Candle OI ×", "ratio", None),
    "Gap x": ("Gap × usual", "ratio", None), "ATR used %": ("ATR used %", "num0", None),
    "vs VWAP %": ("vs VWAP %", "pct", None), "From open %": ("From open %", "pct", None),
    "Buy/Sell": ("Buy ÷ sell qty", "ratio", None), "Candle Turnover Cr": ("Candle ₹ Cr", "num", None),
    # money flow
    "Inflow Cr": ("Inflow ₹ Cr", "num", None), "Outflow Cr": ("Outflow ₹ Cr", "num", None),
    "Net Flow Cr": ("Net flow ₹ Cr", "signed", None), "Buy share %": ("Buying %", "pctu", None),
    "Window Turnover Cr": ("Turnover in window ₹ Cr", "num", None), "Flow % of usual": ("Flow % of usual day", "pct", None),
    "OI Value Chg Cr": ("Futures OI ₹ Cr chg", "signed", None), "Avg Chg %": ("Avg chg %", "pct", None),
    "Stocks": ("Stocks", "int", None), "Stocks with inflow": ("With inflow", "int", None),
    "Top inflow stock": ("Top inflow", "text", None), "Top outflow stock": ("Top outflow", "text", None),
    "Weight %": ("Index weight %", "pctu", None), "Contribution pts": ("Index pts today", "signed", None),
    "Weighted flow": ("Weighted flow", "signed", None),
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
        return float(v) if np.isfinite(v) else None  # NaN and infinity are not valid JSON for the widgets
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
    if "O=H/L" not in df.columns and {"Open", "Day High", "Day Low"} <= set(df.columns):
        df = df.assign(**{"O=H/L": [ind.ohl_flag(o, h, l) for o, h, l in zip(df["Open"], df["Day High"], df["Day Low"])]})
    cols = [c for c in cols if c in df.columns]
    if "O=H/L" in df.columns and "O=H/L" not in cols and df["O=H/L"].astype(str).str.len().gt(0).any():
        after = next((c for c in ("Chg %", "Price", "Move %") if c in cols), None)  # show it next to the move
        cols.insert(cols.index(after) + 1 if after else min(1, len(cols)), "O=H/L")
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
        t = "name" if c == name_col else ("signed" if c in signed else
                                          "int" if pd.api.types.is_integer_dtype(df[c]) else "num" if num else "text")
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


def _signal_levels(sym: str) -> list:
    """Today's recorded signals for this symbol (server's bots): entry, stop and targets as chart lines."""
    key = sym.replace(".NS", "")
    key = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^BSESN": "SENSEX", "NIFTY_FIN_SERVICE.NS": "FINNIFTY",
           "NIFTY_MID_SELECT.NS": "MIDCPNIFTY"}.get(sym, key)
    try:
        trades = json.loads((PATHS.DATA / "bots" / "trades" / f"{datetime.now(IST):%Y-%m-%d}.json").read_text())
    except Exception:
        return []
    out = []
    for t in trades:
        if t.get("symbol", "").split(" ")[0] != key:
            continue
        tag = f"{t['source'].split(' (')[0].replace('Index momentum bot', 'Momentum')} {t['time']}"
        out += [{"name": f"Entry {tag}", "price": float(t["entry"]), "color": "#3B82F6", "solid": True, "width": 2},
                {"name": "Stop", "price": float(t["sl"]), "color": DOWN, "solid": True, "width": 2},
                {"name": "TP1", "price": float(t["tp1"]), "color": UP}, {"name": "TP2", "price": float(t["tp2"]), "color": UP}]
    return out[-12:]  # the latest 3 signals


def tv_chart(df: pd.DataFrame, sym: str, intraday: bool, overlays: list, piv: dict | None, tf_key: str,
             extra_levels: list | None = None):
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
    levels += list(extra_levels or [])
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
    (Streamlit Cloud) that port isn't reachable, so the widget is re-sent the latest ticks every 3-6 seconds."""
    keys = sorted({it["k"] for it in items if it.get("k")})
    kw.setdefault("chart_url", f"chart?sym=@SYM@&t={auth.link_token(USER['id'], _link_secret())}")
    if FEED is not None and PUBLIC and not TICKS and keys:
        every = 3.0 if len(items) <= 60 else 6.0

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
                style=LAYOUT, wskey=getattr(FEED, "relay_key", ""), **kw)
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


# Self-refreshing sections (Scanners, Smart Money, Unusual activity, Money flow): every minute while NSE is open,
# every 5 minutes otherwise (enough for gold's 15-minute bars, and still picks up the open within 5 minutes).
LIVE_EVERY = 60 if SS.market_hours() else 300
PERIODS = {"Today": "Chg %", "1 week": "1W %", "1 month": "1M %", "3 months": "3M %", "1 year": "1Y %"}


def page_dashboard():
    status_strip()
    res = resolved(U.DASHBOARD)
    data, err = safe(fetch_daily, tuple(res.values())) if res else (None, None)
    if data:  # the ticker tiles are nice to have: the desk below works without them
        live("tiles", items_from(data, [(label, res[label]) for label, _ in U.DASHBOARD if label in res]),
             key="dash_tiles", tape=True)
    elif not DHAN_DATA:
        no_data_msg(err)
        return
    ft, _ = safe(fno_table)
    t = ft[0] if ft else pd.DataFrame()
    if DHAN_DATA:
        svc = get_scan_service("dhan", _dhan_sig(), SS.VERSION)
        idx = index_defs()
        svc.set_universe(tuple(sorted(set(scan_universe("All F&O stocks")) |
                                      {m for d in idx.values() for m in d["w"]})))
        svc.set_indices({**{k: d["id"] for k, d in idx.items()}, "INDIAVIX": 21})
        svc.touch()
        dashboard_desk(svc, t)
    else:
        st.info("Connect Dhan for market strength, signals, money flow and today's picks.", icon=":material/link:")
    if t.empty:
        return
    st.subheader("F&O movers")
    live("movers", [live_item(r["Symbol"], r["Stock"], r["Price"], r["Prev Close"], vol=r["Volume"])
                     for _, r in t.iterrows()], key="dash_movers", n=10)
    check_alerts(dict(zip(t["Symbol"], t["Price"])))


@st.cache_resource(show_spinner=False)
def _memo(name: str) -> dict:
    """A dict that survives reruns (app.py runs top to bottom on every page load; plain module dicts don't)."""
    return {}


@st.cache_resource(show_spinner=False)
def _heavy_lock():
    import threading
    return threading.RLock()  # one heavy recompute at a time, shared by every viewer and background job


def _fresh_or_last(memo: dict, key: tuple, compute, tag: str = "v"):
    """memo[tag] for `key`, whose first item is the group (loader and session) it belongs to.

    The scanner, R-factor and unusual-activity numbers take tens of seconds to rebuild for ~200 stocks, and they had
    to be rebuilt after every loader pass (each minute or two in market hours) by whichever page view came first, so
    that view, and every auto-refresh, sat waiting. Now, when a result for the same loader and session exists, it is
    shown straight away and the new one is built in the background (one at a time); it shows on the next refresh.
    Only the very first result of the day is built while the page waits."""
    import threading
    kk, busy = tag + "_k", tag + "_busy"
    if memo.get(kk) == key:
        return memo[tag]
    old = memo.get(kk)
    if old is not None and old[0] == key[0] and tag in memo:
        if not memo.get(busy):
            memo[busy] = True

            def run():
                try:
                    with _heavy_lock():
                        if memo.get(kk) != key:
                            memo[tag] = compute()  # value first, then key: a reader never pairs a key with old data
                            memo[kk] = key
                except Exception:
                    pass
                finally:
                    memo[busy] = False

            threading.Thread(target=run, daemon=True, name=f"omni-{tag}").start()
        return memo[tag]
    with _heavy_lock():
        if memo.get(kk) != key:
            memo[tag] = compute()
            memo[kk] = key
    return memo[tag]


_SCAN_CACHE = _memo("scan")


def _scan_now(svc):
    """Radar shortlist and V3 breakouts on the loader's latest bars; recomputed only when new bars arrive."""
    bars, nifty_df = svc.bars()
    if not bars or nifty_df is None or nifty_df.empty:
        return None
    key = ((id(svc), SC.session_of(nifty_df)), svc.last_pass, len(bars))

    def compute():
        S, session = _prepared_now(svc)
        N = SC.Stock("NIFTY 50", nifty_df, session)
        rd = SC.radar(S, svc.oi())
        v3, _ = SC.version3(S, N if N.ok else None)
        return rd, v3, session

    return _fresh_or_last(_SCAN_CACHE, key, compute)


class _timed:
    """Adds this block's seconds to the page's timing record (st.session_state["_perf"], sent to app_perf)."""
    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.t = time.time()

    def __exit__(self, *a):
        try:
            pf = st.session_state.setdefault("_perf", {})
            pf[self.name] = pf.get(self.name, 0) + time.time() - self.t
        except Exception:
            pass
        return False


_IXBOT_CACHE = _memo("ixbots")


def _index_bots(svc) -> dict:
    """The index bots on the loader's latest candles (index funnel, Bank Nifty fade, trend day / Gap & go, momentum
    bot for every index), rebuilt only when new candles arrive and in the background (the last result shows at
    once): they took ~5 s on every refresh of every viewer. A fresh copy each call (callers add live blocks)."""
    import copy
    bars, nifty_df = svc.bars()
    if not bars:
        return {"ix_rows": [], "bn_fb": None, "gaps": {}, "moms": {}}
    idx_b = svc.idx_bars()
    key = ((id(svc), datetime.now(IST).strftime("%Y-%m-%d")), svc.last_pass, len(bars),
           str(max((b.index.max() for b in idx_b.values() if b is not None and len(b)), default="")))

    def compute():
        w = {k: d.get("w", {}) for k, d in index_defs().items()}
        fut = svc.ifut_bars()
        out = {"ix_rows": [], "bn_fb": None, "gaps": {}, "moms": {}}
        try:
            out["ix_rows"] = IF.live(idx_b, bars, w, idx_b.get("INDIAVIX"))
            out["bn_fb"] = LV.failed_break(idx_b.get("BANKNIFTY"))
        except Exception as e:
            print(f"index bots: setups: {e}", flush=True)
        for k in ("NIFTY", "BANKNIFTY"):
            try:
                out["gaps"][k] = (IF.day_trend(idx_b.get(k), bars, w.get(k, {})), IF.gap_go(idx_b.get(k), bars, w.get(k, {})))
            except Exception as e:
                print(f"index bots: gap & go {k}: {e}", flush=True)
        for k, nm in IF.INDEXES.items():
            try:
                out["moms"][k] = IF.momentum_now(idx_b.get(k), bars, w.get(k, {}), nm, mode=IF.MOM_MODE.get(k), fut=fut.get(k))
            except Exception as e:
                print(f"index bots: momentum {k}: {e}", flush=True)
        return out

    return copy.deepcopy(_fresh_or_last(_IXBOT_CACHE, key, compute))


_FUNNEL_CACHE = _memo("funnel")


def _funnel_now(svc, bars: dict, per: dict, cfg: dict):
    """FN.build for every F&O stock (~10 s), rebuilt only when new candles arrive or the settings change, in the
    background after the first time."""
    fno = set(U.FNO_SECTOR_OF)
    key = ((id(svc), datetime.now(IST).strftime("%Y-%m-%d"), tuple(sorted(cfg.items()))), svc.last_pass, len(bars))
    t, sec = _fresh_or_last(_FUNNEL_CACHE, key, lambda: FN.build({s: b for s, b in bars.items() if s in fno}, per,
                                                                 U.FNO_SECTOR_OF, cfg))
    return t.copy(), sec


def _names(df: pd.DataFrame, n: int = 3, side_col: str | None = None, extra: str | None = None) -> str:
    out = []
    for _, r in df.head(n).iterrows():
        s = str(r["Stock"])
        if side_col and side_col in r and str(r[side_col]):
            s += " " + ("▲" if str(r[side_col]).upper().startswith(("BUY", "BULL", "LONG")) else "▼")
        if extra and extra in r and pd.notna(r[extra]):
            s += f" ({r[extra]:+.1f}%)" if isinstance(r[extra], (int, float, np.floating)) else f" ({r[extra]})"
        out.append(s)
    return ", ".join(out)


DESK_CSS = """
<style>
.dk-hero{border:1px solid var(--om-border);border-radius:var(--r-lg);padding:18px 22px;margin:4px 0 14px;
  background:radial-gradient(120% 140% at 0% 0%,var(--dk-glow) 0%,rgba(19,29,47,.0) 55%),linear-gradient(180deg,var(--om-surface),var(--om-sunken))}
.dk-row{display:flex;flex-wrap:wrap;gap:18px;align-items:center;justify-content:space-between}
.dk-kicker{font-size:var(--fs-xs);letter-spacing:.14em;text-transform:uppercase;color:var(--om-faint)}
.dk-verdict{font-size:var(--fs-3xl);font-weight:800;line-height:1.1;color:var(--dk-c)}
.dk-score{font-family:var(--font-num);font-size:var(--fs-2xl);font-weight:700;color:var(--dk-c);text-align:right}
.dk-desc{color:var(--om-text-2);font-size:var(--fs-md);margin-top:4px;max-width:640px}
.dk-scale-note{font-size:var(--fs-xs);font-weight:400;color:var(--om-faint)}
.dk-scale{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:8px}
.dk-band{border:1px solid var(--om-border);border-radius:var(--r-sm);padding:6px 8px;background:var(--om-sunken);text-align:center;font-size:var(--fs-xs);color:var(--om-muted);line-height:1.3}
.dk-band b{display:block;font-weight:600;color:var(--om-text-3)}
.dk-band span{font-family:var(--font-num);font-size:var(--fs-xs)}
.dk-band.on{border-color:var(--b);background:color-mix(in srgb,var(--b) 18%,var(--om-sunken));color:var(--om-text)}
.dk-band.on b{color:var(--b)}
@media (max-width:640px){.dk-scale{grid-template-columns:repeat(5,minmax(0,1fr));gap:3px}.dk-band{padding:4px 2px;font-size:var(--fs-2xs)}.dk-band span{font-size:.6rem}}
.dk-gauge{position:relative;height:8px;border-radius:6px;margin:12px 0 6px;
  background:linear-gradient(90deg,var(--om-down) 0%,#3A475E 50%,var(--om-up) 100%)}
.dk-gauge i{position:absolute;top:-5px;width:4px;height:18px;border-radius:2px;background:#fff;box-shadow:0 0 8px #fff}
.dk-parts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.dk-chip{font-size:var(--fs-sm);padding:4px 10px;border-radius:999px;border:1px solid var(--om-border-strong);background:var(--om-surface-2);color:var(--om-text-2)}
.dk-chip b{color:var(--c)}
.dk-idx{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.dk-card{border:1px solid var(--om-border);border-radius:var(--r-md);padding:10px 12px;background:var(--om-surface)}
.dk-card .n{font-size:var(--fs-xs);color:var(--om-muted);letter-spacing:.04em}
.dk-card .p{font-family:var(--font-num);font-size:var(--fs-lg);font-weight:700;color:var(--om-text)}
.dk-card .c{font-family:var(--font-num);font-size:var(--fs-sm)}
.dk-plan{border:1px solid var(--om-border);border-left:4px solid var(--c);border-radius:var(--r-md);padding:12px 14px;background:var(--om-surface);
  margin-bottom:10px}
.dk-plan .h{display:flex;justify-content:space-between;align-items:baseline}
.dk-plan .side{font-weight:800;font-size:var(--fs-xl);color:var(--c)}
.dk-plan .t{color:var(--om-text-3);font-size:var(--fs-sm);margin-top:4px}
.dk-list{border:1px solid var(--om-border);border-radius:var(--r-md);overflow:hidden;background:var(--om-sunken)}
.dk-list .hd{padding:10px 14px;font-weight:700;letter-spacing:.06em;font-size:var(--fs-sm);
  background:linear-gradient(90deg,var(--c) -400%,var(--om-surface-2) 60%);color:var(--om-text);display:flex;justify-content:space-between}
.dk-item{padding:10px 14px;border-top:1px solid var(--om-border-soft)}
.dk-item .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.dk-item .s{font-weight:700;color:var(--om-text)}
.dk-item .num{font-family:var(--font-num);font-size:var(--fs-sm);color:var(--om-text-2)}
.dk-item .why{font-size:var(--fs-xs);color:var(--om-muted);margin-top:3px}
.dk-dots{letter-spacing:2px;color:var(--c);font-size:var(--fs-sm)}
.dk-empty{padding:14px;color:var(--om-faint);font-size:var(--fs-sm)}
.dk-note{border:1px solid var(--om-border-strong);border-radius:var(--r-md);padding:14px 18px;background:var(--om-surface)}
.dk-note p{margin:.25rem 0}
</style>
"""


def _spark(closes: pd.Series, color: str) -> str:
    v = closes.dropna().to_numpy()[-60:]
    if len(v) < 3:
        return ""
    lo, hi = v.min(), v.max()
    span = hi - lo or 1
    pts = " ".join(f"{i * 120 / (len(v) - 1):.1f},{30 - (x - lo) / span * 26:.1f}" for i, x in enumerate(v))
    return (f"<svg width='100%' height='32' viewBox='0 0 120 32' preserveAspectRatio='none'>"
            f"<polyline fill='none' stroke='{color}' stroke-width='1.6' points='{pts}'/></svg>")


def _idx_snapshot(df: pd.DataFrame | None) -> dict | None:
    """Last price, change vs yesterday's close, change from today's open, ATR % and today's closes."""
    if df is None or df.empty:
        return None
    d = SC.clean(df)
    if d.empty:
        return None
    day = d.index.normalize()
    days = sorted(set(day))
    today = d[day == days[-1]]
    prev = d[day == days[-2]]["Close"].iloc[-1] if len(days) > 1 else np.nan
    daily = d.groupby(day).agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    atr = ((daily["h"] - daily["l"]) / daily["c"]).iloc[-15:-1].mean() * 100 if len(daily) > 3 else np.nan
    last = float(today["Close"].iloc[-1])
    return {"last": last, "chg": (last / prev - 1) * 100 if pd.notna(prev) else np.nan,
            "from_open": (last / float(today["Open"].iloc[0]) - 1) * 100, "atr": atr, "closes": today["Close"]}


def _focus_html(df: pd.DataFrame, title: str, color: str, side: str) -> str:
    rows = []
    for _, r in df.iterrows():
        n = int(min(abs(r["Score"]), 8))
        rows.append(f"<div class='dk-item'><div class='top'><span class='s'>{r['Stock']}</span>"
                    f"<span class='num'>{r['Price']:,.2f} &nbsp;<b style='color:{color}'>{r['Chg %']:+.2f}%</b></span></div>"
                    f"<div class='top'><span class='why'>{r['Why']}</span><span class='dk-dots'>{'●' * n}</span></div></div>")
    body = "".join(rows) or "<div class='dk-empty'>No stock has 3+ readings agreeing yet.</div>"
    return (f"<div class='dk-list' style='--c:{color}'><div class='hd'><span>{title}</span><span>{side}</span></div>"
            f"{body}</div>")


def _anthropic_key() -> str:
    try:
        k = (st.secrets.get("anthropic") or {}).get("api_key")
    except Exception:
        k = None
    return str(k or os.environ.get("ANTHROPIC_API_KEY") or "")


@st.cache_data(ttl=300, show_spinner=False)
def _claude_note(snapshot_json: str, bucket: int) -> str:
    """One Claude call per 5-minute bucket for the same market state, shared by every viewer."""
    return DK.claude_note(json.loads(snapshot_json), _anthropic_key())


def _github_cfg() -> dict:
    try:
        return dict(st.secrets.get("github") or {})
    except Exception:
        return {}


def _log_paper(svc, idx_b: dict, og, now: datetime):
    """Paper trades of the tested setups: the opening setups once a day after 9:20, Bank Nifty 5-STAR when it fires
    and again with its result after 15:15. Checked at most every 5 minutes (it recomputes 5-STAR and gold flow, ~2.5 s)."""
    memo = _memo("desk_log")
    if time.time() - memo.get("paper_at", 0) < 300:
        return
    memo["paper_at"] = time.time()
    done = memo.setdefault("paper", set())
    day = now.strftime("%Y-%m-%d")
    rows = []
    if og is not None and now.strftime("%H:%M") >= "09:20" and (day, "setups") not in done:
        done.add((day, "setups"))
        rows += DL.setup_rows(now, og[1], {k: m["name"] for k, m in SU.SETUPS.items()})
    bn = idx_b.get("BANKNIFTY")
    if bn is not None and not bn.empty and pd.DatetimeIndex(bn.index).max().date() == now.date():
        internals, _ = _five_star_data(svc)
        sg = FIVE.evaluate(bn, internals).get("signal")
        if sg and (day, "5star") not in done:
            done.add((day, "5star"))
            rows += DL.star_row(now, sg, final=False)
        if sg and sg["state"] != "open" and (day, "5star_final") not in done:
            done.add((day, "5star_final"))
            rows += DL.star_row(now, sg, final=True)
        for tr in FADE.evaluate(bn, now).get("trades", []):
            key = (day, "fade", tr["time"])
            if key not in done:
                done.add(key)
                rows += DL.fade_row(now, tr, final=False)
            if tr["state"] != "open" and key + ("final",) not in done:
                done.add(key + ("final",))
                rows += DL.fade_row(now, tr, final=True)
    try:
        for tr in (_gold_flow() or {}).get("trades", []):
            if tr["entry"] is None or tr["signal_time"] < GOLD_LOG_START:
                continue
            key = ("gold", str(tr["signal_time"]))
            if key not in done:
                done.add(key)
                rows += DL.gold_row(now, tr, final=False)
            if tr["state"] != "open" and key + ("final",) not in done:
                done.add(key + ("final",))
                rows += DL.gold_row(now, tr, final=True)
    except Exception as e:
        DL.STATUS["error"] = f"gold log: {e}"[:200]
    if rows:
        DL.save(rows, _github_cfg())


def _log_desk(snaps: dict, verdict: dict, plans: list, ce, pe):
    """Record the desk at 9:20, 9:45, 10:30, 12:00, 13:30 and 15:00 on market days (only from today's live data), once per checkpoint."""
    now = datetime.now(IST).replace(tzinfo=None)
    n = snaps.get("NIFTY")
    if not n or n["closes"].empty or n["closes"].index.max().date() != now.date():
        return
    done = _memo("desk_log").setdefault("done", set())
    check = DL.due(now, done)
    if not check:
        return
    done.add((now.strftime("%Y-%m-%d"), check))
    try:
        DL.save(DL.rows_from(now, check, verdict, plans, ce, pe), _github_cfg())
    except Exception as e:
        DL.STATUS["error"] = str(e)[:200]


def trading_desk(svc, t, sf, R, flow, secflow, idx_b, fut_b, sc, picks, og):
    st.markdown(DESK_CSS, unsafe_allow_html=True)
    snaps = {k: _idx_snapshot(idx_b.get(k)) for k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "INDIAVIX")}
    box = apex_live(_dhan_sig())
    share = AP.dominance(box["bars"])[0] if box.get("bars") is not None else None
    adv = int((t["Chg %"] > 0).sum()) if not t.empty and "Chg %" in t else None
    dec = int((t["Chg %"] < 0).sum()) if not t.empty and "Chg %" in t else None
    buy_share = (flow["Inflow Cr"].sum() / (flow["Inflow Cr"].sum() + flow["Outflow Cr"].sum()) * 100
                 if not flow.empty else None)
    fut_money = float(sf["Smart money (Rs cr)"].sum()) if not sf.empty else None
    n = snaps.get("NIFTY") or {}
    vix = snaps.get("INDIAVIX") or {}
    verdict = DK.regime(share, adv, dec, buy_share, fut_money, vix.get("chg"), n.get("from_open"), n.get("atr"))
    s = verdict["score"]
    color = UP if pd.notna(s) and s >= 20 else DOWN if pd.notna(s) and s <= -20 else "#94A3B8"
    glow = "rgba(38,166,154,.22)" if color == UP else "rgba(239,83,80,.22)" if color == DOWN else "rgba(148,163,184,.12)"
    pos = 50 if pd.isna(s) else (s + 100) / 2
    chips = "".join(f"<span class='dk-chip' style='--c:{UP if p['pull'] > 0 else DOWN if p['pull'] < 0 else '#94A3B8'}'>"
                    f"{p['reading']}: <b>{p['value']}</b></span>" for p in verdict["parts"])
    now = datetime.now(IST)
    nday = (snaps.get("NIFTY") or {}).get("closes")
    sess = nday.index.max() if nday is not None and len(nday) else None
    when = (f"{now:%a %d %b · %H:%M} IST" if sess is None or sess.date() == now.date()
            else f"{sess:%a %d %b} session (market closed now)")
    bands = [("Strong bearish", "−100 to −55", DOWN), ("Bearish", "−55 to −20", DOWN), ("Neutral", "−20 to +20", "#94A3B8"),
             ("Bullish", "+20 to +55", UP), ("Strong bullish", "+55 to +100", UP)]
    scale = "".join(f"<div class='dk-band{' on' if lab == verdict['label'] else ''}' style='--b:{c}'><b>{lab}</b>"
                    f"<span>{rng}</span></div>" for lab, rng, c in bands)
    st.markdown(
        f"<div class='dk-hero' style='--dk-c:{color};--dk-glow:{glow}'><div class='dk-row'>"
        f"<div><div class='dk-kicker'>The mood right now · {when}</div>"
        f"<div class='dk-verdict'>{verdict['label']}</div>"
        f"<div class='dk-desc'>{DK.MOOD_TEXT.get(verdict['label'], '')}</div></div>"
        f"<div class='dk-score'>{'—' if pd.isna(s) else f'{s:+.0f}'} <span style='color:#7F93B2'>/ 100</span>"
        f"<div class='dk-scale-note'>−100 all bearish · 0 balanced · +100 all bullish</div></div></div>"
        f"<div class='dk-gauge'><i style='left:calc({pos:.0f}% - 2px)'></i></div><div class='dk-scale'>{scale}</div>"
        f"<div class='dk-parts'>{chips}</div>"
        f"<div class='dk-scale-note' style='margin-top:8px'>The mood describes the market now; it is not a forecast. "
        f"Each chip is one reading: green pulls the score up, red pulls it down.</div></div>", unsafe_allow_html=True)

    # index strip
    cards = []
    for k, name in (("NIFTY", "NIFTY 50"), ("BANKNIFTY", "BANK NIFTY"), ("FINNIFTY", "FIN NIFTY"), ("SENSEX", "SENSEX"),
                    ("INDIAVIX", "INDIA VIX")):
        x = snaps.get(k)
        if not x:
            continue
        up_ = x["chg"] >= 0 if pd.notna(x["chg"]) else True
        c = (DOWN if up_ else UP) if k == "INDIAVIX" else (UP if up_ else DOWN)
        cards.append(f"<div class='dk-card'><div class='n'>{name}</div><div class='p'>{x['last']:,.2f}</div>"
                     f"<div class='c' style='color:{c}'>{x['chg']:+.2f}% <span style='color:#7F93B2'>· open "
                     f"{x['from_open']:+.2f}%</span></div>{_spark(x['closes'], c)}</div>")
    if cards:
        st.markdown(f"<div class='dk-idx'>{''.join(cards)}</div>", unsafe_allow_html=True)

    # index option plans + CE / PE focus
    plans = []
    for k, name in (("NIFTY", "Nifty"), ("BANKNIFTY", "Bank Nifty")):
        x = snaps.get(k)
        if not x:
            continue
        tr = TA.evaluate(k, idx_b.get(k), fut_b.get(k), idx_b.get("INDIAVIX"), None,
                         TA.days_to_expiry(k, idx_b.get(k).index.max()))
        plans.append(DK.index_plan(name, x["last"], TA.STEP.get(k, 50), verdict, tr,
                                   share if k == "NIFTY" else None))
    sec_flag = sf.set_index("Sector")["Flow"].to_dict() if not sf.empty else {}
    rd = sc[0] if sc is not None else pd.DataFrame()
    ce, pe = DK.focus(R, flow, rd, picks, sec_flag)
    _log_desk(snaps, verdict, plans, ce, pe)
    try:
        if datetime.now(IST).weekday() < 5:
            _log_paper(svc, idx_b, og, datetime.now(IST).replace(tzinfo=None))
    except Exception as e:
        DL.STATUS["error"] = f"paper log: {e}"[:200]
    c1, c2, c3 = st.columns([1.1, 1, 1]) if not MOBILE else (st.container(), st.container(), st.container())
    with c1:
        st.markdown("<div class='dk-kicker' style='margin:2px 0 8px'>Index options</div>", unsafe_allow_html=True)
        for p in plans:
            pc = UP if p["tone"] > 0 else DOWN if p["tone"] < 0 else "#94A3B8"
            strike = f" {p['strike']:,.0f}" if p.get("strike") and p["side"] in ("CE", "PE") else ""
            st.markdown(f"<div class='dk-plan' style='--c:{pc}'><div class='h'><span>{p['index']}</span>"
                        f"<span class='side'>{p['side']}{strike}</span></div><div class='t'>{p['text']}</div></div>",
                        unsafe_allow_html=True)
        if not plans:
            st.caption("Index bars are still loading.")
    with c2:
        st.markdown(_focus_html(ce, "CE FOCUS", UP, "bullish confluence"), unsafe_allow_html=True)
    with c3:
        st.markdown(_focus_html(pe, "PE FOCUS", DOWN, "bearish confluence"), unsafe_allow_html=True)
    note("Focus lists: stocks where 3+ independent readings agree with today's move (activity score, futures "
               "buildup, sector money, own money flow, radar shortlist, yesterday's high/low, smart-money pick); dots = "
               "points. Confluence, not a tested signal: confirm on the chart and keep a small stop.")

    # desk note: rule-based always, Claude on request
    openings = []
    if og is not None:
        for key, meta in SU.SETUPS.items():
            df = og[1].get(key)
            if df is not None and not df.empty:
                openings.append(f"{meta['name']}: " + ", ".join(df["sym"].head(3)))
    top_in = secflow.iloc[0]["Sector"] if not secflow.empty else None
    top_out = secflow.iloc[-1]["Sector"] if not secflow.empty else None
    desk_lines = DK.desk_note(verdict, ce, pe, plans, top_in, top_out, openings)
    key = _anthropic_key()
    snap = {"time": f"{now:%Y-%m-%d %H:%M} IST", "verdict": verdict, "index_plans": plans,
            "indices": {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "closes"}
                        for k, v in snaps.items() if v},
            "ce_focus": ce[["Stock", "Price", "Chg %", "Score", "Why"]].round(2).to_dict("records") if len(ce) else [],
            "pe_focus": pe[["Stock", "Price", "Chg %", "Score", "Why"]].round(2).to_dict("records") if len(pe) else [],
            "sector_money_in": secflow.head(3)[["Sector", "Net Flow Cr"]].round(0).to_dict("records") if not secflow.empty else [],
            "sector_money_out": secflow.tail(3)[["Sector", "Net Flow Cr"]].round(0).to_dict("records") if not secflow.empty else [],
            "opening_setups": openings}
    l, r = st.columns([3, 1], vertical_alignment="bottom")
    l.markdown("<div class='dk-kicker' style='margin:6px 0'>Desk note</div>", unsafe_allow_html=True)
    if key and r.button("Ask Claude", icon=":material/auto_awesome:", width="stretch", key="dk_claude"):
        with st.spinner("Claude is reading the market…"):
            try:
                st.session_state["dk_claude_note"] = (now.strftime("%H:%M"),
                                                      _claude_note(json.dumps(snap, sort_keys=True, default=str),
                                                                   int(time.time() // 300)))
            except Exception as e:
                st.session_state["dk_claude_note"] = (now.strftime("%H:%M"), f"Claude could not answer: {e}")
    if not key:
        r.link_button("Open claude.ai", "https://claude.ai/new", icon=":material/open_in_new:", width="stretch")
    body = "".join(f"<p>{_md_inline(x)}</p>" for x in desk_lines)
    st.markdown(f"<div class='dk-note'>{body}</div>", unsafe_allow_html=True)
    cl = st.session_state.get("dk_claude_note")
    if cl:
        with st.container(border=True):
            st.markdown(f"**Claude's read** · {cl[0]} IST")
            st.markdown(cl[1])
            st.caption("Written by Claude from the readings above; information, not investment advice.")
    if not key:
        with st.expander("Get Claude's read for free (copy → paste into claude.ai)", icon=":material/auto_awesome:"):
            st.caption("Press the copy icon at the top right of the box, open claude.ai (free account), paste and send. "
                       "The text holds this minute's readings, so copy it again later for a fresh read.")
            st.code((DK.SYSTEM if IS_ADMIN else DK.SYSTEM_PUBLIC) + "\n\nLive snapshot:\n" + json.dumps(snap, default=str, indent=1, ensure_ascii=False),
                    language=None, wrap_lines=True)



def _md_inline(s: str) -> str:
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def _plan_rows(svc, idx_b: dict, og, trend: list) -> list[dict]:
    """State of each TESTED setup (research/FINAL_SETUPS.md), in plain words: fired (with entry, stop, target),
    waiting (window still open) or none. Each part is guarded so one failure never hides the others."""
    now = datetime.now(IST)
    hm = now.strftime("%H:%M")
    rows = []

    def add(name, state, text, where):
        rows.append({"name": name, "state": state, "text": text, "where": where})

    # 1. opening setups: decided at 9:15, entered at the opening price
    try:
        if og is None:
            add("Opening setups (gap fade, panic gap-down, sector overreaction)", "wait" if hm < "09:15" else "nodata",
                "Decided at 9:15 from the opening gaps; enter at the opening price (pre-open orders 9:00–9:08)."
                if hm < "09:15" else "No opening prices yet.", "Scanners → Opening setups")
        else:
            _, sig, _ = og
            for key, meta in SU.SETUPS.items():
                df = sig.get(key)
                if df is None or df.empty:
                    add(meta["name"], "none", "No signal today.", "Scanners → Opening setups")
                    continue
                parts = []
                for _, r in df.iterrows():
                    buy = str(r["side"]).upper().startswith("BUY")
                    parts.append(f"**{r['sym']} {'BUY' if buy else 'SELL'}** at the open ₹{float(r['entry']):,.2f}, "
                                 f"stop ₹{float(r['stop_px']):,.2f}, exit 15:20 (now {float(r['pnl_now%']):+.2f}%)")
                add(meta["name"], "fired", "; ".join(parts) + ". Only valid at the opening price.",
                    "Scanners → Opening setups")
    except Exception as e:
        add("Opening setups", "nodata", f"Not available ({str(e)[:80]}).", "Scanners → Opening setups")

    bn = idx_b.get("BANKNIFTY")
    # 2. Bank Nifty failed-break fade (signals 9:20-14:30, close back inside within 30 min)
    try:
        r = FADE.evaluate(bn, now.replace(tzinfo=None)) if bn is not None and not bn.empty else {"status": "no data"}
        if r.get("trades"):
            tr = r["trades"][-1]
            pts = f"{tr['pts']:+.0f} pts" if pd.notna(tr.get("pts")) else ""
            add("Bank Nifty failed-break fade", "fired" if tr["state"] == "open" else "closed",
                f"**{'BUY' if tr['side'] > 0 else 'SELL'}** at {tr['time']} from {tr['entry']:,.0f} "
                f"({tr['level'].lower()} broken at {tr['break_time']}, back inside), stop {tr['stop']:,.0f}, "
                f"target {tr['target']:,.0f}: {tr['state']} {pts}.", "Scanners → Bank Nifty fade")
        elif r.get("status") == "ok":
            late = hm > "15:00"
            add("Bank Nifty failed-break fade", "none" if late else "wait",
                " · ".join(f"{s['level']} {s['price']:,.0f}: {s['state']}" for s in r["sides"]),
                "Scanners → Bank Nifty fade")
        else:
            add("Bank Nifty failed-break fade", "nodata", f"{r.get('status', 'no data')}.", "Scanners → Bank Nifty fade")
    except Exception as e:
        add("Bank Nifty failed-break fade", "nodata", f"Not available ({str(e)[:80]}).", "Scanners → Bank Nifty fade")

    # 3. Bank Nifty 5-STAR momentum (all six checks on one 5-min candle, 9:30-15:00)
    try:
        internals, _ = _five_star_data(svc)
        r = FIVE.evaluate(bn, internals) if bn is not None and not bn.empty else {"status": "no data"}
        sg = r.get("signal")
        if sg:
            add("Bank Nifty 5-STAR momentum", "fired" if sg["state"] == "open" else "closed",
                f"**{'BUY' if sg['side'] > 0 else 'SELL'}** at {sg['time']} from {sg['entry']:,.0f}, stop "
                f"{sg['stop']:,.0f} (trail with Supertrend, exit by 15:15): {sg['state']} {sg['pts']:+.0f} pts.",
                "Scanners → Bank Nifty 5-STAR")
        elif r.get("last"):
            last = r["last"]
            done = hm > "15:00"
            add("Bank Nifty 5-STAR momentum", "none" if done else "wait",
                ("No signal today." if done else f"Last candle {last['time']}: {last['checks']} of 6 checks "
                 f"(leaning {last['lean']}). Fires when all 6 agree, 9:30–15:00."), "Scanners → Bank Nifty 5-STAR")
        else:
            add("Bank Nifty 5-STAR momentum", "nodata", f"{r.get('status', 'no data')}.", "Scanners → Bank Nifty 5-STAR")
    except Exception as e:
        add("Bank Nifty 5-STAR momentum", "nodata", f"Not available ({str(e)[:80]}).", "Scanners → Bank Nifty 5-STAR")

    # 4. index trend day + futures OI rising (option buys, first signal 10:30-13:00)
    for k, r in trend:
        try:
            name = f"Trend day + OI, {TREND_NAMES[k]} (options)"
            if r.get("status") == "SIGNAL":
                add(name, "fired", f"**BUY {r['side']} {r['strike']:,.0f}** (signal {r.get('sig_time', '')} at "
                    f"{r.get('sig_px', float('nan')):,.0f}): ATM option, stop −30%, trail 30% from the peak after +30%, "
                    "exit 15:15.", "Scanners → Index trend-day")
            else:
                mv = (f" Move {r['move_atr']:+.2f} ATR, needs ±{r['thr']:.1f}." if pd.notna(r.get("move_atr")) else "")
                add(name, "none" if hm > "13:00" else "wait", f"{str(r.get('status', '—')).capitalize()}.{mv}",
                    "Scanners → Index trend-day")
        except Exception as e:
            add(f"Trend day + OI, {k}", "nodata", f"Not available ({str(e)[:80]}).", "Scanners → Index trend-day")

    # 5. Gold Order Flow (15-min, runs almost round the clock)
    try:
        g = _gold_flow() or {}
        trs = [x for x in g.get("trades", []) if x.get("entry") is not None]
        tr = trs[-1] if trs else None
        stt = g.get("state") or {}
        if tr is not None and tr["state"] == "open":
            add("Gold Order Flow (15-min)", "fired",
                f"**{'BUY' if tr['side'] > 0 else 'SELL'}** from {tr['entry']:,.1f}, stop {tr['stop']:,.1f}, target "
                f"{tr['target']:,.1f}: open, {tr['pct']:+.2f}%.", "Scanners → Gold Order Flow")
        else:
            add("Gold Order Flow (15-min)", "wait",
                f"No open trade. Flow: {stt.get('flow', '—')}, structure: {stt.get('structure', '—')}"
                + (f" (needs {'bullish' if 'Buy' in str(stt.get('flow')) else 'bearish'} structure to fire)."
                   if stt else "."), "Scanners → Gold Order Flow")
    except Exception as e:
        add("Gold Order Flow (15-min)", "nodata", f"Not available ({str(e)[:80]}).", "Scanners → Gold Order Flow")
    return rows


def todays_plan(svc, idx_b: dict, og, trend: list):
    """The first thing on the desk: only the setups that held up in testing, and a plain 'no trade' when none has
    fired. Everything below it (verdict, focus lists, activity, flow) is context, not a tested signal."""
    rows = _plan_rows(svc, idx_b, og, trend)
    hm = datetime.now(IST).strftime("%H:%M")
    fired = [r for r in rows if r["state"] == "fired"]
    waiting = [r for r in rows if r["state"] == "wait"]
    icon = {"fired": ":green[● SIGNAL]", "closed": ":blue[● DONE]", "wait": ":orange[○ waiting]",
            "none": ":gray[– none today]", "nodata": ":gray[? no data]"}
    with st.container(border=True):
        st.subheader("Today's plan: tested setups only")
        if fired:
            st.markdown(f"#### :green[{len(fired)} tested setup{'s' if len(fired) > 1 else ''} with a live signal]")
        elif waiting and SS.market_hours():
            st.markdown("#### No tested setup has fired yet. No trade until one does.")
        elif SS.market_hours() or hm < "09:15":
            st.markdown("#### No tested setup today. No trade is the right call.")
        else:
            st.markdown("#### Market closed: the last session's tested setups")
        order = {"fired": 0, "closed": 1, "wait": 2, "none": 3, "nodata": 4}
        for r in sorted(rows, key=lambda r: order[r["state"]]):
            st.markdown(f"{icon[r['state']]} &nbsp; **{r['name']}**: {r['text']} "
                        f"<span class='muted'>({r['where']})</span>", unsafe_allow_html=True)
        st.caption("Only setups that made money after costs in testing (research/FINAL_SETUPS.md); most days have one "
                   "or none, and no signal means no edge. Paper-trade them first: every signal and result is saved to "
                   "the desk log. Not investment advice.")


@st.fragment(run_every=120)
def dashboard_desk(svc, t: pd.DataFrame):
    """One screen for a running market: how strong it is, what every scanner says now, where the money goes."""
    with _timed("sector futures money"):
        sf = sector_flow_table()
    with _timed("index build-up"):
        box = apex_live(_dhan_sig())
    act = _activity_data(svc)
    R, E, per, _ = act if act else (pd.DataFrame(), pd.DataFrame(), {}, None)
    flow = A.flow_window(per, None) if per else pd.DataFrame()
    if not flow.empty:
        flow["Sector"] = flow["Stock"].map(U.FNO_SECTOR_OF).fillna("Other")
        flow = flow[flow["Stock"].isin(set(U.FNO_SECTOR_OF))]
    secflow = A.sector_flow(flow) if not flow.empty else pd.DataFrame()
    idx_b, fut_b = svc.idx_bars(), svc.ifut_bars()

    with _timed("opening signals"):
        og = opening_signals()
    with _timed("scanners"):
        sc = _scan_now(svc)
    with _timed("smart money"):
        rf, _ = smart_money_stocks(svc)
        picks = best_picks(rf, sf) if not rf.empty and not sf.empty else pd.DataFrame()
    vix = idx_b.get("INDIAVIX")
    trend = []
    for k in ("NIFTY", "BANKNIFTY"):
        spot = idx_b.get(k)
        if spot is None or spot.empty:
            continue
        trend.append((k, TA.evaluate(k, spot, fut_b.get(k), vix, None, TA.days_to_expiry(k, spot.index.max()))))
    todays_plan(svc, idx_b, og, trend)
    st.markdown("##### Market context")
    st.caption("Readings that describe the market (verdict, CE / PE focus lists, activity, money flow). Useful for "
               "context, but not tested as signals on their own: trade the plan above, not these.")
    trading_desk(svc, t, sf, R, flow, secflow, idx_b, fut_b, sc, picks, og)

    # ---- 2. every scanner, one line each
    st.subheader("Signals right now")
    rows = []
    if og is not None:
        g, sig, _ = og
        for key, meta in SU.SETUPS.items():
            df = sig.get(key)
            if df is not None and not df.empty:
                names = ", ".join(f"{r['sym']} {'▲' if str(r['side']).upper().startswith('BUY') else '▼'} "
                                  f"({r['pnl_now%']:+.1f}%)" for _, r in df.head(3).iterrows())
                rows.append({"Scanner": meta["name"], "Now": f"{len(df)} signal(s)", "Stocks": names,
                             "Where": "Setups & Scanners → Opening setups"})
            else:
                rows.append({"Scanner": meta["name"], "Now": "No signal", "Stocks": "",
                             "Where": "Setups & Scanners → Opening setups"})
    if sc is not None:
        rd, v3, _ = sc
        fit = rd[rd["TradeFinder fit"] == "Yes"] if not rd.empty else rd
        rows.append({"Scanner": "Momentum radar shortlist", "Now": f"{len(fit)} fit" if len(fit) else "None yet",
                     "Stocks": _names(fit, 3, "Side", "Move %") if len(fit) else "",
                     "Where": "Setups & Scanners → Momentum radar"})
        rows.append({"Scanner": "Breakout (V3), top-2 movers", "Now": f"{len(v3)} breakout(s)" if len(v3) else "None yet",
                     "Stocks": _names(v3, 2, "Side") if len(v3) else "", "Where": "Setups & Scanners → Breakout (V3)"})
    if not R.empty:
        bull = R[R["Smart"] >= 40].sort_values("Smart", ascending=False)
        bear = R[R["Smart"] <= -40].sort_values("Smart")
        rows.append({"Scanner": "Unusual activity, bullish", "Now": f"{len(bull)} stocks",
                     "Stocks": _names(bull, 3, None, "Chg %"), "Where": "F&O Stocks → Unusual activity"})
        rows.append({"Scanner": "Unusual activity, bearish", "Now": f"{len(bear)} stocks",
                     "Stocks": _names(bear, 3, None, "Chg %"), "Where": "F&O Stocks → Unusual activity"})
    rows.append({"Scanner": "Smart-money picks (R-factor)", "Now": f"{len(picks)} picks" if len(picks) else "None yet",
                 "Stocks": _names(picks, 3, "Side", "Chg %") if len(picks) else "", "Where": "Smart Money Sectors"})
    if not secflow.empty:
        rows.append({"Scanner": "Money flow by sector", "Now": f"In: {secflow.iloc[0]['Sector']}",
                     "Stocks": f"Out: {secflow.iloc[-1]['Sector']} · top stock in: "
                               f"{flow.sort_values('Net Flow Cr', ascending=False).iloc[0]['Stock']}",
                     "Where": "F&O Stocks → Money flow"})
    for k, r in trend:
        rows.append({"Scanner": f"Trend-day alert, {TREND_NAMES[k]}",
                     "Now": f"BUY {r['side']} {r['strike']:,.0f}" if r.get("status") == "SIGNAL" else r.get("status", "—"),
                     "Stocks": f"move {r['move_atr']:+.2f} ATR (needs ±{r['thr']:.1f})" if pd.notna(r.get("move_atr")) else "",
                     "Where": "Setups & Scanners → Index trend-day"})
    if rows:
        data_table(pd.DataFrame(rows), "dash_signals", name_col="Scanner", height=420)
        st.caption("▲ buy / CE, ▼ sell / PE; brackets: change today (opening setups: P&L since the open). "
                   "Refreshes every minute. Open the page in the last column for details and entry rules.")
    b = st.columns(4)
    for col, (label, view, page) in zip(b, [("Opening setups & radar", None, "scanners"),
                                             ("Unusual activity", "Unusual activity", "fno"),
                                             ("Money flow", "Money flow", "fno"), ("Smart money sectors", None, "smart")]):
        if col.button(label, width="stretch", key=f"go_{label}"):
            if view:
                st.session_state["fno_view"] = view
            st.switch_page(P[page])

    # ---- 3. where the money is: heatmap + sector flow
    left, right = st.columns([3, 2]) if not MOBILE else (st.container(), st.container())
    with left:
        st.subheader("Sector heatmap")
        mode = st.segmented_control("Colour by", ["Smart money", "Price change"], default="Smart money",
                                    key="dash_heat", label_visibility="collapsed") or "Smart money"
        res, _ = safe(oi_data, True)
        flows = SC.stock_flows(res[0]) if res else pd.DataFrame()
        fig = sector_heatmap(t, flows, sf, mode)
        if fig is None:
            st.caption("Waiting for prices and futures OI.")
        else:
            st.plotly_chart(fig, width="stretch", key="dash_heatmap", config={"displayModeBar": False})
    with right:
        st.subheader("Money flow by sector")
        if secflow.empty:
            st.caption("Waiting for the day's candles.")
        else:
            sb = secflow.sort_values("Net Flow Cr")
            fig = go.Figure(go.Bar(y=sb["Sector"], x=sb["Net Flow Cr"], orientation="h",
                                   marker_color=np.where(sb["Net Flow Cr"] >= 0, UP, DOWN),
                                   text=[f"{v:+,.0f}" for v in sb["Net Flow Cr"]], textposition="outside",
                                   cliponaxis=False, hovertemplate="%{y}: ₹%{x:+,.0f} Cr<extra></extra>"))
            fig.update_layout(height=28 * len(sb) + 60, template=plot_template(), margin=dict(l=10, r=40, t=10, b=10),
                              xaxis=dict(title="net ₹ crore today"))
            st.plotly_chart(fig, width="stretch", key="dash_secflow", config={"displayModeBar": False})

    # ---- 4. what to look at
    l2, r2 = st.columns(2) if not MOBILE else (st.container(), st.container())
    with l2:
        st.subheader("Today's picks")
        if picks.empty:
            st.caption("No stock is moving with a favoured sector yet.")
        else:
            show_table(picks.head(5), ["Stock", "Side", "Price", "Chg %", "R-factor", "Buildup", "Sector"],
                       "dash_picks", height=250)
    with r2:
        st.subheader("Most unusual now")
        if R.empty:
            st.caption("Loading activity scores…")
        else:
            top = R.reindex(R["Smart"].abs().sort_values(ascending=False).index).head(5)
            show_table(top, [c_ for c_ in ["Stock", "Side", "Price", "Chg %", "Smart", "Buildup", "Sector"]
                             if c_ in top.columns], "dash_unusual", height=250)


def sector_heatmap(t: pd.DataFrame, flows: pd.DataFrame, sf: pd.DataFrame, mode: str):
    if t is None or t.empty or "Chg %" not in t:
        return None
    d = t[["Stock", "Sector", "Price", "Chg %"]].dropna(subset=["Chg %"]).copy()
    d = d[d["Sector"] != "Other"]
    if not flows.empty:
        f = flows.set_index("Stock")
        d["size"] = d["Stock"].map(f["OI"] * f["Fut LTP"] / 1e7)
        d["flow"] = d["Stock"].map(f["flow"])
        d["Buildup"] = d["Stock"].map(f["Buildup"]).fillna("")
    else:
        d["size"], d["flow"], d["Buildup"] = np.nan, np.nan, ""
    d["size"] = d["size"].fillna(d["size"].median() if d["size"].notna().any() else 1).clip(lower=1)
    if mode == "Smart money" and d["flow"].notna().any():
        cap = max(float(d["flow"].abs().quantile(0.9)), 1.0)
        d["c"] = (d["flow"].fillna(0) / cap).clip(-1, 1)
        bias = sf.set_index("Sector")["Bias %"] / 100 if not sf.empty else pd.Series(dtype=float)
        sec_c = {s: float(bias.get(s, 0) or 0) for s in d["Sector"].unique()}
    else:
        d["c"] = (d["Chg %"] / 3).clip(-1, 1)
        sec_c = (d.groupby("Sector")["Chg %"].mean() / 3).clip(-1, 1).to_dict()
    sec = d.groupby("Sector").agg(size=("size", "sum"), chg=("Chg %", "mean")).reset_index()
    money = sf.set_index("Sector")["Smart money (Rs cr)"] if not sf.empty else pd.Series(dtype=float)
    ids = list(sec["Sector"]) + [f"{r.Sector}/{r.Stock}" for r in d.itertuples()]
    labels = [f"{s}  {money.get(s, np.nan):+,.0f} cr" if pd.notna(money.get(s, np.nan)) else s for s in sec["Sector"]] \
        + list(d["Stock"])
    parents = [""] * len(sec) + list(d["Sector"])
    values = list(sec["size"]) + list(d["size"])
    colors = [sec_c.get(s, 0) for s in sec["Sector"]] + list(d["c"])
    text = [f"{c:+.2f}% avg" for c in sec["chg"]] + [
        f"{r['Chg %']:+.2f}%" + (f"<br>{r['Buildup']}" if r["Buildup"] else "") for _, r in d.iterrows()]
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total", text=text,
        texttemplate="<b>%{label}</b><br>%{text}", hovertemplate="<b>%{label}</b><br>%{text}<extra></extra>",
        marker=dict(colors=colors, colorscale=[[0, DOWN], [0.5, "#1E293B"], [1, UP]], cmin=-1, cmax=1,
                    line=dict(width=1, color="#0B1220")),
        tiling=dict(pad=2), pathbar=dict(visible=False)))
    fig.update_layout(template=plot_template(), height=380 if MOBILE else 560, margin=dict(l=0, r=0, t=0, b=0))
    return fig


def apex_live(sig: tuple) -> dict:
    return _apex_live(sig)


@st.cache_resource(show_spinner=False)
def _apex_live(sig: tuple) -> dict:
    """Nifty build-up kept fresh in the background (every 2 minutes in market hours), so the dashboard never waits."""
    import threading
    _stop_background()  # only one refresher: a new token or a code update must not leave the old one running
    box = {"bars": None, "info": None, "err": None, "stop": False}
    sys.__dict__.setdefault("_omni_boxes", []).append(box)

    def loop():
        while not box["stop"]:
            try:
                bars, info = AP.buildup("NIFTY", 5, 3, DCFG)
                box.update(bars=bars, info=info, err=None)
            except Exception as e:
                box["err"] = getattr(e, "friendly", str(e))
            wait = 120 if SS.market_hours() else 900
            while wait > 0 and not box["stop"]:
                time.sleep(5)
                wait -= 5

    threading.Thread(target=loop, daemon=True, name="apex-nifty").start()
    return box


def _current_cfg() -> dict:
    """Dhan settings with the latest token (the automatic one when on), read fresh on every call: the recorder thread
    outlives the page run that started it."""
    cfg = D.load_config()
    tok = _auto_token().get("token")
    if tok:
        cfg["access_token"] = tok
    return cfg


@st.cache_resource(show_spinner=False)
def _chain_recorder() -> dict:
    """Option-chain recorder (chain_log.py), one per server process; registered so updates stop it."""
    box = {"stop": False}
    sys.__dict__.setdefault("_omni_boxes", []).append(box)
    CL.start(box, _current_cfg, _github_cfg)
    return box


def best_picks(rf: pd.DataFrame, sf: pd.DataFrame) -> pd.DataFrame:
    """Top R-factor stocks moving with a sector the money favours: up with long build-up / short covering in a
    Bullish sector, down with short build-up / long unwinding in a Bearish one; at most 3 per sector, best 10."""
    flow = sf.set_index("Sector")["Flow"]
    sec_flow = rf["Sector"].map(flow)
    with_money = (((sec_flow == "Bullish") & (rf["Chg %"] > 0) & rf["Buildup"].isin(["Long buildup", "Short covering"]))
                  | ((sec_flow == "Bearish") & (rf["Chg %"] < 0)
                     & rf["Buildup"].isin(["Short buildup", "Long unwinding"])))
    picks = rf[with_money].copy()
    picks["Side"] = np.where(picks["Chg %"] > 0, "BUY / CE", "SELL / PE")
    return picks.groupby("Sector", sort=False).head(3).head(10)


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
    view = st.segmented_control("View", ["Live prices", "Full analytics", "Unusual activity", "Money flow"],
                                key="fno_view", default=None if "fno_view" in st.session_state else
                                ("Live prices" if FEED is not None else "Full analytics"),
                                label_visibility="collapsed") or "Full analytics"
    if view in ("Unusual activity", "Money flow"):
        page_activity(view)
        return
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


def page_market(group: str, title: str, tiles_n: int = 5, note: str = "", bare: bool = False):
    tiles_n = 2 if MOBILE else tiles_n
    if not bare:
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


def page_global():
    status_strip()
    st.header("Global markets")
    pick = st.segmented_control("Market", ["Commodities", "Currency (INR)", "Forex", "Crypto"], default="Commodities",
                                key="global_pick", label_visibility="collapsed") or "Commodities"
    {"Crypto": page_crypto, "Forex": page_forex, "Currency (INR)": page_currency,
     "Commodities": page_commodities}[pick]()


def page_crypto():
    page_market("Crypto", "Crypto", note="Prices in US dollars, live around the clock.", bare=True)


def page_forex():
    page_market("Forex", "Forex", note="Major and cross pairs. Forex trades Monday to Friday, around the clock.",
                bare=True)


def page_currency():
    t = page_market("Currency (INR)", "Currency (INR)", note="Rupee value of one unit of each currency.", bare=True)
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
    page_market("Commodities", "Commodities", note="Futures prices in US dollars (COMEX, NYMEX, CBOT, ICE).",
                bare=True)


TIMEFRAMES = {
    "1m": ("5d", "1m"), "3m": ("5d", "1m"), "5m": ("5d", "5m"), "10m": ("1mo", "5m"), "15m": ("1mo", "15m"),
    "25m": (None, None), "1h": ("3mo", "1h"),
    "1D": ("1y", "1d"), "1W": ("5y", "1wk"), "1M": ("max", "1mo"),
}


def page_details():
    status_strip()
    if st.query_params.get("sym"):  # opened from a chart link in a new tab
        st.session_state.detail_pick = U.normalize(st.query_params["sym"])
        for k in ("sym", "t"):
            st.query_params.pop(k, None)
    sym = st.session_state.detail_pick
    options = list(dict.fromkeys([sym] + store["watchlist"] + list(U.all_names())))
    top1, top2, top3 = st.columns([3, 2, 1])
    with top1:
        sym = st.selectbox("Symbol", options, format_func=lambda s: f"{name_of(s)}  ·  {s}", key="detail_pick")
    with top2:
        tf = st.segmented_control("Timeframe", list(TIMEFRAMES), default="15m", key="tf") or "1D"
    with top3:
        st.write("")
        _tvu = MX.tv_url(sym, {"1m": "1", "3m": "3", "5m": "5", "10m": "10", "15m": "15", "25m": "30", "1h": "60",
                               "1D": "D", "1W": "W", "1M": "M"}.get(tf, "5"))
        if _tvu:
            st.link_button("TradingView ↗", _tvu, width="stretch", help="Opens this chart on TradingView in a new tab: "
                           "all of its indicators and drawing tools.")
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
        _rf = lambda v: (f"{v:,.0f}" if v and v >= 1000 else fmt_price(v, sym).replace("₹", ""))  # noqa: E731
        c.metric("Day range", f"{_rf(m['Day Low'])} – {_rf(m['Day High'])}")
        d.metric("Volume", fmt_vol(m["Volume"], sym),
                 f"{m['Vol x Avg']:.1f}× avg" if pd.notna(m["Vol x Avg"]) else None, delta_color="off")
        a, b, c, d = st.columns(4)
        a.metric("52W range", f"{_rf(m['52W Low'])} – {_rf(m['52W High'])}")
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
        "Indicators", ["EMA 20", "EMA 50", "EMA 200", "Bollinger (20, 2)", "VWAP", "Supertrend (10, 3)", "Pivot levels",
                       "Yesterday high / low", "Today's signal levels"],
        default=["EMA 20", "EMA 50", "VWAP", "Pivot levels", "Yesterday high / low", "Today's signal levels"], key="overlays")

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
        if intraday and tf in ("1m", "3m", "5m", "10m"):
            hdf = hdf[hdf.index >= hdf.index[-1] - pd.Timedelta(days={"1m": 2, "3m": 3, "5m": 5, "10m": 10}[tf])]
        extra = []
        if "Yesterday high / low" in overlays:
            extra += [{"name": "Yesterday high", "price": float(base["High"]), "color": "#94A3B8"},
                      {"name": "Yesterday low", "price": float(base["Low"]), "color": "#94A3B8"}]
        sig_lv = _signal_levels(sym) if "Today's signal levels" in overlays else []
        extra += sig_lv
        tv_chart(hdf, sym, intraday, overlays, piv if intraday or tf == "1D" else None, tf, extra)
        st.caption(f"Chart data: {csrc}. Times in IST (hover a candle: its date and time show in the legend)."
                   + (f" Signal levels: {', '.join(sorted({x['name'].split(' ')[0] for x in sig_lv}))}." if sig_lv else ""))

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
        markets = st.multiselect("Markets", list(U.GROUPS) + ["My watchlist"], default=["F&O Stocks"],
                                 key="scr_markets")
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
                c5.link_button("Chart", chart_link(r["Symbol"]))
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


def _sector_data(t: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """F&O stocks with R-factor, smart score, activity and money flow (live from Dhan), and the flow by sector."""
    t = t.copy()
    t["Change"] = t["Price"] - t["Price"] / (1 + t["Chg %"] / 100)
    for c in ("R-factor", "Smart", "Activity %", "OI Chg %", "Flow Cr", "Inflow Cr", "Outflow Cr", "Net Flow Cr"):
        t[c] = np.nan
    t["Buildup"], t["O=H/L"] = "", ""
    secflow = pd.DataFrame()
    if not DHAN_DATA:
        return t, secflow
    try:
        svc = get_scan_service("dhan", _dhan_sig(), SS.VERSION)
        idx = index_defs()
        svc.set_universe(tuple(sorted(set(scan_universe("All F&O stocks")) | {m for d in idx.values() for m in d["w"]})))
        svc.set_indices({**{k: d["id"] for k, d in idx.items()}, "INDIAVIX": 21})
        svc.touch()
    except Exception:
        return t, secflow
    try:
        rf, _ = smart_money_stocks(svc)
        if not rf.empty:
            f = rf.set_index("Stock")
            for c in ("R-factor", "OI Chg %", "Flow Cr", "Buildup"):
                if c in f:
                    t[c] = t["Stock"].map(f[c])
            t["Buildup"] = t["Buildup"].fillna("")
    except Exception:
        pass
    try:
        act = _activity_data(svc)
        if act:
            R, per = act[0], act[2]
            if not R.empty:
                r = R.set_index("Stock")
                t["Smart"] = t["Stock"].map(r["Smart"]) if "Smart" in r else np.nan
                if "Vol x (time)" in r:
                    t["Activity %"] = t["Stock"].map(r["Vol x (time)"]) * 100
                if "O=H/L" in r:
                    t["O=H/L"] = t["Stock"].map(r["O=H/L"]).fillna("")
            flow = A.flow_window(per, None) if per else pd.DataFrame()
            if not flow.empty:
                fl = flow.set_index("Stock")
                for c in ("Inflow Cr", "Outflow Cr", "Net Flow Cr"):
                    t[c] = t["Stock"].map(fl[c])
                flow["Sector"] = flow["Stock"].map(dict(zip(t["Stock"], t["Sector"]))).fillna("Other")
                secflow = A.sector_flow(flow).reset_index().rename(columns={"index": "Sector"})
                if "Sector" not in secflow:
                    secflow = secflow.rename(columns={secflow.columns[0]: "Sector"})
    except Exception:
        pass
    return t, secflow


def page_sectors():
    status_strip()
    st.header("Sectors")
    for _c in (MX.CSS, MX.SECTOR_CSS):
        st.markdown(_c, unsafe_allow_html=True)
    with st.spinner("Loading F&O stocks…"):
        res, err = safe(fno_table)
    if res is None or res[0].empty:
        no_data_msg(err)
        return
    t, secflow = _sector_data(res[0])
    fl_of = secflow.set_index("Sector").to_dict("index") if not secflow.empty else {}

    # ---- market at a glance
    adv, dec = int((t["Chg %"] > 0).sum()), int((t["Chg %"] < 0).sum())
    net = float(secflow["Net Flow Cr"].sum()) if not secflow.empty else None
    st.markdown(MX.kpis([
        MX.kpi("Advancing", f"{adv}", f"of {len(t)} F&O stocks", MX.UP),
        MX.kpi("Declining", f"{dec}", f"{len(t) - adv - dec} unchanged", MX.DOWN),
        MX.kpi("Advance / decline", f"{adv / dec:.2f}" if dec else "—", "above 1 = more stocks up",
               MX.UP if adv > dec else MX.DOWN if dec > adv else MX.NEUTRAL),
        MX.kpi("Average move", f"{t['Chg %'].mean():+.2f}%", "today", MX.tone_color(t["Chg %"].mean())),
        MX.kpi("Net money", f"₹{net:+,.0f} Cr" if net is not None else "—", "all F&O stocks, today",
               MX.tone_color(net or 0)),
        MX.kpi("Most active", (t.loc[t["Activity %"].idxmax(), "Stock"] if t["Activity %"].notna().any() else "—"),
               "volume vs usual by this time", MX.ACCENT),
    ]), unsafe_allow_html=True)
    heat = MX.heatmap(secflow)
    if heat:
        st.markdown(MX.section("Sector money", "size = turnover · colour = net money in / out") + heat,
                    unsafe_allow_html=True)

    # ---- every sector as a card
    s1, s2 = st.columns([2, 3], vertical_alignment="bottom")
    sort = s1.segmented_control("Sort sectors by", ["Change", "Net money", "R-factor", "Smart score", "Activity"],
                                default="Change", key="sx_sort") or "Change"
    q = s2.text_input("Find a sector or stock", key="sx_find", placeholder="e.g. Banks or TCS")
    rows = []
    for sec, g in t.groupby("Sector"):
        rows.append({"Sector": sec, "Change": g["Chg %"].mean(), "Net money": (fl_of.get(sec) or {}).get("Net Flow Cr", np.nan),
                     "R-factor": g["R-factor"].mean(), "Smart score": g["Smart"].mean(), "Activity": g["Activity %"].mean()})
    order = pd.DataFrame(rows).sort_values(sort, ascending=False, na_position="last")["Sector"].tolist()
    if q:
        hit = set(t[t["Stock"].str.contains(q.strip(), case=False, regex=False)]["Sector"])
        order = [s for s in order if q.strip().lower() in s.lower() or s in hit]
    if not order:
        st.caption("No sector or stock matches.")
        return
    if st.session_state.get("sx_pick") not in order:
        st.session_state.sx_pick = order[0]
    pick = st.session_state.sx_pick
    st.markdown(MX.section("All sectors", "R = R-factor (0-100) · Smart = smart score · Activity = volume vs usual by now")
                + MX.sector_grid([MX.sector_card(s, t[t["Sector"] == s], fl_of.get(s) or {}, s == pick) for s in order]),
                unsafe_allow_html=True)

    # ---- the chosen sector as a full live table
    st.markdown(MX.section("Sector detail", "pick a sector"), unsafe_allow_html=True)
    pick = st.pills("Sector", order, default=pick, key="sx_pill", label_visibility="collapsed") or pick
    st.session_state.sx_pick = pick
    g = t[t["Sector"] == pick].sort_values("Chg %", ascending=False)
    fl = fl_of.get(pick) or {}
    st.markdown(MX.sector_card(pick, g, fl, True).replace("sx-list", "sx-list' style='display:none"),
                unsafe_allow_html=True)
    cols = ["Stock", "Price", "Change", "Chg %", "R-factor", "Smart", "Activity %", "Buildup", "OI Chg %",
            "Inflow Cr", "Outflow Cr", "Net Flow Cr", "Gap %", "Vol x Avg", "RSI", "Trend", "O=H/L", "Lot size", "Symbol"]
    df = g[[c for c in cols if c in g]].copy()
    df["Chart"] = df["Symbol"].map(chart_link) if "Symbol" in df else None
    df["TradingView"] = df["Stock"].map(MX.tv_url)
    st.dataframe(df.drop(columns=["Symbol"], errors="ignore"), hide_index=True, width="stretch",
                 height=min(42 + 35 * len(df), 620), column_config={
                     "Price": st.column_config.NumberColumn(format="%.2f"),
                     "Change": st.column_config.NumberColumn(format="%+.2f"),
                     "Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
                     "R-factor": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                     "Smart": st.column_config.NumberColumn(format="%+.0f"),
                     "Activity %": st.column_config.NumberColumn(format="%.0f%%"),
                     "OI Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
                     "Inflow Cr": st.column_config.NumberColumn("In ₹ Cr", format="%.1f"),
                     "Outflow Cr": st.column_config.NumberColumn("Out ₹ Cr", format="%.1f"),
                     "Net Flow Cr": st.column_config.NumberColumn("Net ₹ Cr", format="%+.1f"),
                     "Gap %": st.column_config.NumberColumn(format="%+.2f%%"),
                     "Vol x Avg": st.column_config.NumberColumn("Vol × avg", format="%.2f×"),
                     "RSI": st.column_config.NumberColumn(format="%.0f"),
                     "Lot size": st.column_config.NumberColumn("Lot", format="%d"),
                     "Chart": st.column_config.LinkColumn("Chart", display_text="Open"),
                     "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗")})
    st.caption("Live from Dhan. R-factor: how unusual today's volume, futures OI change, range and move are vs the "
               "same time on the last 20 sessions (0-100). Smart score: unusual-activity score (+ bullish, − bearish). "
               "Activity: volume so far vs the usual by this time (100% = normal). Money in / out: turnover split by "
               "where each candle closed.")
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
        c[0].markdown(f"[{r['Stock']}]({chart_link(r['Symbol'])})")
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


def opening_signals():
    """Opening-gap setups (gap table, signals per setup, Nifty gap), or None without prices."""
    res, err = safe(fno_table)
    if res is None or res[0].empty:
        return None
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
    return g, SU.signals(g, nifty_gap), nifty_gap


def setups_body():
    note("Rules found in Omnipuls research on 14 years of NSE data, tested year by year with costs. "
               "They decide at 9:15 from the opening gap. Past results don't guarantee future ones; size so a run of "
               "losses is survivable.")
    og = opening_signals()
    if og is None:
        no_data_msg()
        return
    g, sig, nifty_gap = og
    if not g.empty:
        st.caption(f"F&O stocks gapping 3%+: {int((g['gap'] <= -0.03).sum())} down, {int((g['gap'] >= 0.03).sum())} up.")
    for key, meta in SU.SETUPS.items():
        st.subheader(meta["name"])
        note_md(f"**Rule:** {meta['rule']}  \n<span class='muted'>{meta['stats']}</span>", unsafe_allow_html=True)
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
    st.header("Setups & scanners")
    note("Intraday scanners from the Omnipuls research. They run on all F&O stocks; the backtests behind "
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
    svc.set_indices({**{k: d["id"] for k, d in index_defs().items()}, "INDIAVIX": 21})
    svc.touch()
    scanner_body(svc, uni)


@st.fragment(run_every=LIVE_EVERY)
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
        note_md(f"{_badge(verdict)}&nbsp; **Shares:** {sh} per trade · **Options:** {op} · **Years profitable:** {yrs}"
                    f"<br><span class='muted'>{note}</span>", unsafe_allow_html=True)

    signed = ("P&L %", "Gap %", "Change by 10:00 %")
    tabs = st.tabs(["Opening setups", "Momentum radar", "Breakout (V3)", "Index trend-day + OI (options)",
                    "Bank Nifty 5-STAR", "BN failed-break fade", "Gold Order Flow"] + (["Research"] if IS_ADMIN else []))
    with tabs[3]:
        index_trend_tab(svc)
    with tabs[4]:
        five_star_tab(svc)
    with tabs[5]:
        fade_tab(svc)
    with tabs[6]:
        gold_flow_tab()
    with tabs[0]:
        setups_body()
    if IS_ADMIN:
        with tabs[7]:
            rs = pd.DataFrame([{"Setup": r[0], "Verdict": SC.VERDICT_LABEL[r[2]], "Trade with": r[1],
                                "Shares / trade": r[3], "Options / trade": r[4], "Years +": r[5], "Notes": r[6]}
                               for r in SC.RESEARCH])
            data_table(rs, "scan_research", name_col="Setup", height=520)
            st.markdown(
                "**What to trade:** the gap fade, entered at the opening price with a pre-open order on the cash shares "
                "(9:00-9:08), 0.75-1% stop, exit 15:20. The Opening setups tab lists it each morning.  \n"
                "**For stock options:** nothing tested holds up from 9:20 onward. Run "
                "`research/intraday/gapfade_options_dhan.py` to see whether options bought at 9:15-9:16 still catch the "
                "gap fade on real Dhan option prices.  \n"
                "**Before real money:** paper-trade for 3-4 weeks.")
    with tabs[2]:
        head(4)
        note("Rule: at 9:30 rank stocks by ATR%, 9:15-9:30 range, RVOL and gap size; take the top 2. Entry when "
                   "a 5-min candle closes beyond the 9:15-9:30 range by 12:00 with volume 1.5x its 10-day slot "
                   "average and Nifty not broken the other way; enter next candle. Stop 0.5 ATR, trail 1 ATR, exit 15:20.")
        flt = st.toggle("Use the volume and Nifty filters (the test found they add nothing)", value=True, key="v3f")
        v, ranked = SC.version3(S, N, filters=flt)
        if v.empty:
            st.caption("No breakout signal yet." if live_today else "No signal that session.")
        else:
            data_table(v, "scan_v3", signed=signed, name_col="Stock", height=200)
        try:
            diag, early = SC.v3_diagnose(S, N)
        except Exception:
            diag, early = pd.DataFrame(), None
        st.markdown("**★ V3 early pick** (testing next to V3: the day's first top-10 breakout by 9:45, no block deal, "
                    "not gapped 0-1% the trade's way · 54 days: 57% wins, +0.59% a trade after costs, to be confirmed live)")
        if early:
            data_table(pd.DataFrame([early]), "scan_v3_early", signed=signed, name_col="Stock", height=110)
        else:
            st.caption("No early pick yet (none by 9:45 that passes)." if live_today else "No early pick that session.")
        if not diag.empty:
            st.markdown("**Top 10 at 9:30: why each was or was not traded**")
            data_table(diag, "scan_v3_why", signed=("Gap %",), name_col="Stock", height=380)
        with st.expander("Top-ranked stocks at 9:30 (ranking details)"):
            if not ranked.empty:
                data_table(ranked, "scan_v3_rank", signed=("Gap %",), name_col="Stock", height=380)
                note("Block deal? = opening volume 20x+ its 20-day usual: almost always one large negotiated "
                           "trade at the open, not traders piling in. Its RVOL is real but says little about follow-"
                           "through; treat that stock's rank with care.")
    with tabs[1]:
        head(5)
        note("Each stock 1%+ from yesterday's close, compared with the same time window on its last sessions: "
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
        if not rd.empty and DHAN_DATA:
            rd = with_sector_money(rd)
        if svc.source == "dhan" and getattr(svc, "oi_status", "") not in ("ready", "off"):
            st.caption(f"Futures OI: {svc.oi_status}")
        if rd.empty:
            st.caption("No stock is 1%+ from yesterday's close yet.")
        else:
            fit = rd[rd["TradeFinder fit"] == "Yes"].head(5)
            st.markdown("**Shortlist**")
            note_md("**Shortlist: TradeFinder pattern** (broke yesterday's high for CE / low for PE, its sector "
                        "moving the same way, volume 1.5x+ its 20-day usual for this time; top 5 by score)")
            if fit.empty:
                st.caption("No stock fits the pattern yet.")
            else:
                if DHAN_DATA:
                    fit = with_option_flow(fit, session)
                data_table(fit, "scan_radar_fit", signed=("Move %", "From open %", "Sector move %", "OI chg %", "Sector money (Rs cr)",
                                                          "Put OI chg %", "Call OI chg %"), name_col="Stock", height=230)
                if DHAN_DATA:
                    note("Option writing: OI change vs yesterday on the 3 strikes each side of the money, "
                               "nearest expiry (Dhan option chain, refreshed about every 90 s). Puts written = option "
                               "sellers expect the stock to hold up; calls written = they expect it to stay down. "
                               "'Options confirm' when that backs the stock's direction; TradeFinder skips stocks "
                               "where it starts late. Not backtested: there is no option-chain history.")
                    note("Sector money: the sector's fresh futures positions today (see Index Build-up). "
                               "'Money favours' Yes when it backs the stock's side; TradeFinder picks stocks from the "
                               "sector the money favours.")
            note("Checked on 360 of their verified trades (Dec 2024 - Oct 2026): at 10:30 this top 5 held their "
                       "stock on about 27% of days, the top 10 on about 37%. Their pick then ran a further 3% on "
                       "average; the rest of the shortlist usually does not. Use it to narrow the field, then apply "
                       "your own confirmation (5-minute candle, OI build-up) and a small stop.")
            with st.expander(f"All {len(rd)} stocks 1%+ from yesterday's close"):
                data_table(rd, "scan_radar", signed=("Move %", "From open %", "Sector move %", "OI chg %", "Sector money (Rs cr)"),
                           name_col="Stock", height=520)
        if live_today:
            radar_log_today(S, oi, session)
        if IS_ADMIN:
            with st.expander("Track record of the 10:30 picks (logged daily)"):
                radar_track_record(bars)


def with_sector_money(rd: pd.DataFrame) -> pd.DataFrame:
    """Add the sector's smart-money flow (futures OI build-up, today) and whether it backs the stock's side."""
    sf = sector_flow_table()
    if sf.empty:
        return rd
    flow = sf.set_index("Sector")
    rd = rd.copy()
    rd["Sector money"] = rd["Sector"].map(flow["Flow"]).fillna("—")
    rd["Sector money (Rs cr)"] = rd["Sector"].map(flow["Smart money (Rs cr)"])
    buy = rd["Side"].astype(str).str.startswith("BUY")
    rd["Money favours"] = np.where((buy & (rd["Sector money"] == "Bullish")) | (~buy & (rd["Sector money"] == "Bearish")),
                                   "Yes", np.where(rd["Sector money"].isin(["Mixed", "—"]), rd["Sector money"], "No"))
    return rd


RADAR_LOG = PATHS.state("radar_log.csv")


@st.cache_data(ttl=90, show_spinner=False)
def stock_option_flow(sym: str, side: int) -> dict:
    """Option writing near the money for one stock (nearest live expiry). Dhan allows one chain call per 3 s."""
    for sid, seg in oc_refs(sym):
        try:
            exps = oc_expiries(sid, seg)
        except Exception:
            continue
        today = datetime.now(IST).date()
        live = [e for e in exps if pd.Timestamp(e).date() >= today] or exps
        try:
            spot, ch = D.option_chain(sid, seg, live[0], DCFG)
        except Exception:
            return {}
        return SC.option_writing(ch, spot, side)
    return {}


@st.cache_resource(show_spinner=False)
def _option_confirmed_at() -> dict:
    return {}  # (session day, stock, side) -> first time the options confirmed, shared by all viewers


def with_option_flow(df: pd.DataFrame, session) -> pd.DataFrame:
    """Add option-writing columns to the shortlist, and when the options first confirmed the move today."""
    seen = _option_confirmed_at()
    now = datetime.now(IST).strftime("%H:%M")
    rows = []
    for _, r in df.iterrows():
        side = 1 if str(r["Side"]).startswith("BUY") else -1
        f = stock_option_flow(r["Stock"], side)
        key = (f"{session:%Y-%m-%d}", r["Stock"], side)
        # only during that session's market hours: a time stamped after the close or the next day is meaningless
        if f.get("Options confirm") == "Yes" and session.date() == datetime.now(IST).date() and SS.market_hours():
            seen.setdefault(key, now)
        rows.append({**f, "Confirmed since": seen.get(key, "")})
    extra = pd.DataFrame(rows, index=df.index)
    for c in ("Option writing", "Put OI chg %", "Call OI chg %", "Options confirm", "Confirmed since"):
        if c not in extra:
            extra[c] = np.nan if c.endswith("%") else ""
    return pd.concat([df, extra[["Option writing", "Put OI chg %", "Call OI chg %", "Options confirm",
                                 "Confirmed since"]]], axis=1)


def radar_log_today(S: dict, oi: dict, session):
    """Once a day after 10:35, save the top 3 as of 10:30 (TradeFinder-pattern shortlist first, then the score) with
    their entry (10:30 candle open), futures OI and option-writing readings."""
    now = datetime.now(IST)
    if (now.hour, now.minute) < (10, 35):
        return
    day = f"{session:%Y-%m-%d}"
    try:
        if RADAR_LOG.exists() and day in set(pd.read_csv(RADAR_LOG, usecols=["Date"])["Date"].astype(str)):
            return
    except Exception:
        pass
    rd = SC.radar(S, oi, at=SC.dtime(10, 30))
    if rd.empty:
        return
    rd = pd.concat([rd[rd["TradeFinder fit"] == "Yes"], rd[rd["TradeFinder fit"] != "Yes"]]).head(3)
    rows = []
    for _, r in rd.iterrows():
        s = S[r["Stock"]]
        nb = s.today[s.today.index.time >= SC.dtime(10, 30)]
        if nb.empty:
            continue
        side = 1 if r["Side"].startswith("BUY") else -1
        entry = float(nb["Open"].iloc[0])
        opt = stock_option_flow(r["Stock"], side) if DHAN_DATA else {}
        rows.append({"Date": day, "Rank": r["Rank"], "Stock": r["Stock"], "Side": side,
                     "Entry time": f"{nb.index[0]:%H:%M}", "Entry": entry, "Stop": entry * (1 - side * 0.01),
                     **{k: r[k] for k in ("Score", "Move %", "Volume vs usual", "OI chg %", "OI vs usual", "Buildup",
                                          "Big-money bars", "TradeFinder fit")},
                     "Option writing": opt.get("Option writing", ""), "Options confirm": opt.get("Options confirm", "")})
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
                    "OI vs usual": r["OI vs usual"], "Big-money bars": r["Big-money bars"],
                    "Options confirm": r.get("Options confirm", "")})
    t = pd.DataFrame(out)
    if t.empty:
        st.caption("No logged picks within the loaded data yet.")
        return
    done = t[~t["Status"].isin(["Open"])]
    if not done.empty:
        oi_ok = done["Buildup"].isin(["Long buildup", "Short buildup"])
        summ = []
        for name, x in [("#1 pick", done[done["Rank"] == 1]), ("Top 3", done), ("Top 3, OI confirms (fresh buildup)",
                        done[oi_ok]), ("Top 3, OI does not confirm", done[~oi_ok]),
                        ("Top 3, option writing confirms", done[done["Options confirm"] == "Yes"]),
                        ("Top 3, option writing does not confirm", done[done["Options confirm"] != "Yes"])]:
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
        if D.can_auto_token(DCFG):
            box = _auto_token()
            st.caption("Automatic token: on (PIN + TOTP). A new 24-hour token is made when the current one has under an "
                       "hour left or is rejected." + (f" Last made {box['made']:%d %b %H:%M}." if box["made"] else ""))
        if not DS.get("data"):
            st.warning("Your Data API plan is not active, so prices come from Yahoo. Portfolio pages still work. "
                       "To get Dhan live data, option chain, MCX and currency futures, subscribe to Data APIs "
                       "on web.dhan.co and generate a new token.")
    elif DS.get("error"):
        st.error(DS["error"])
    else:
        st.info("Not connected. Follow the steps below.", icon=":material/link_off:")
    if D.can_auto_token(DCFG) and _auto_token()["error"]:
        st.warning(f"Automatic token failed: {_auto_token()['error']}", icon=":material/error:")
    if IS_ADMIN and not D.can_auto_token(DCFG):
        sec = D.secrets_config()
        have = {k: bool(sec.get(k) or DCFG.get(k)) for k in ("client_id", "pin", "totp_secret")}
        st.warning("**Automatic token is OFF**, so the token still has to be pasted every day. It needs all three in "
                   "Secrets under `[dhan]`: " + " · ".join(f"`{k}` {'✅' if ok else '❌ missing'}" for k, ok in have.items())
                   + ". After saving Secrets the app restarts by itself; this line disappears once all three are found.",
                   icon=":material/key_off:")

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
        st.info("**No daily token: let the app make its own.** In **" + SECRETS_HELP + "** put your Client ID, your "
                "6-digit Dhan PIN and your TOTP secret. The app then creates a fresh 24-hour token by itself whenever "
                "one is needed, so nothing has to be pasted again.", icon=":material/key:")
        st.code('[dhan]\nclient_id = "your client ID"\npin = "your 6-digit Dhan PIN"\n'
                'totp_secret = "the TOTP secret key from Dhan"', language="toml")
        st.caption("To get the TOTP secret: web.dhan.co → DhanHQ Trading APIs → Setup TOTP → confirm the OTP. When the "
                   "QR code shows, choose to see the code/key instead and copy it (add the same key to Google "
                   "Authenticator too). These stay only in Secrets: never in GitHub files or dhan_config.json. "
                   "A token pasted above still works for the day if you prefer the manual way.")
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


@st.cache_data(ttl=150, show_spinner=False)
def apex_data(index: str, strikes: int):
    return AP.buildup(index, strikes, 3, DCFG)


def sector_flow_table() -> pd.DataFrame:
    res, _ = safe(oi_data, True)
    return SC.sector_smart_money(res[0]) if res else pd.DataFrame()


# ---------------------------------------------------------------- unusual activity (smart score)

_ACT_CACHE = _memo("activity")


def _activity_data(svc):
    """Scores for every stock, recomputed only when the background loader has new bars or snapshots."""
    bars, nifty_df = svc.bars()
    if not bars:
        return None
    session = SC.session_of(nifty_df) if nifty_df is not None and not nifty_df.empty else \
        max(df.index.normalize().max() for df in bars.values() if not df.empty)
    key = ((id(svc), session), svc.last_pass, svc.last_snap, len(bars))

    def compute():
        R, E, per = A.rank({s: SC.clean(df) for s, df in bars.items()}, session, svc.oi(), svc.snapshots(),
                           U.FNO_SECTOR_OF)
        if not R.empty:
            R["Symbol"] = R["Stock"] + ".NS"
            R["Side"] = np.where(R["Smart"] >= 25, "Bullish", np.where(R["Smart"] <= -25, "Bearish", ""))
        if not E.empty:
            E["Symbol"] = E["Stock"] + ".NS"
            E["Candle"] = np.where(E["Candle"] == "Green", "Bullish", "Bearish")
        return R, E, per, session

    return _fresh_or_last(_ACT_CACHE, key, compute)


def page_activity(view: str = "Unusual activity"):
    src_opts = (["Dhan (live)"] if DHAN_DATA else []) + ["Yahoo (delayed)"]
    c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
    src = c1.selectbox("Data source", src_opts, key="act_src")
    source = "dhan" if src.startswith("Dhan") else "yahoo"
    if source == "yahoo":
        c2.caption("Yahoo has no open interest or order-book quantities, so those parts of the score are left out.")
    svc = get_scan_service(source, _dhan_sig() if source == "dhan" else ("yahoo",), SS.VERSION)
    idx = index_defs()
    svc.set_universe(tuple(sorted(set(scan_universe("All F&O stocks")) |
                                  {m for d in idx.values() for m in d["w"]})))
    svc.set_indices({**{k: d["id"] for k, d in idx.items()}, "INDIAVIX": 21})
    svc.touch()
    (flow_body if view == "Money flow" else activity_body)(svc)


@st.fragment(run_every=LIVE_EVERY)
def activity_body(svc):
    done, total = svc.progress()
    fresh = svc.freshness()
    info = st.columns([3, 1], vertical_alignment="center")
    if done < total:
        info[0].progress(done / max(total, 1), text=f"Loading the last 40 sessions of 5-minute bars: {done} of {total} "
                         "stocks (needed for the time-of-day averages). Scores fill in as stocks arrive; after the "
                         "first load of the day this is instant.")
    else:
        upd = (f"bars updated {int(fresh)}s ago" if fresh is not None and SS.market_hours()
               else "market closed: showing the latest session")
        n_fut = sum(1 for v in svc.oi().values() if not v.empty)
        info[0].caption(f"{done} stocks · {upd} · futures OI for {n_fut} stocks · "
                        f"order-book snapshots: {len(svc.snaps)} · status: {svc.status}")
    if info[1].button("Refresh view", icon=":material/refresh:", width="stretch", key="act_refresh"):
        svc.touch()
    res = _activity_data(svc)
    if res is None or res[0].empty:
        st.info("Waiting for the first data… (" + svc.status + ")", icon=":material/hourglass_top:")
        return
    R, E, per, session = res
    live_today = session is not None and pd.Timestamp(session).date() == datetime.now(IST).date()
    last_bar = R["Time"].max()
    m = st.columns(5)
    m[0].metric("Session", f"{pd.Timestamp(session):%a %d %b}", "today" if live_today else "last session",
                delta_color="off", border=True)
    m[1].metric("Last candle", last_bar, border=True)
    m[2].metric("Bullish unusual", int((R["Smart"] >= 40).sum()), "smart score 40+", delta_color="off", border=True)
    m[3].metric("Bearish unusual", int((R["Smart"] <= -40).sum()), "smart score -40 or less", delta_color="off",
                border=True)
    m[4].metric("Unusual candles today", len(E), border=True)

    tabs = st.tabs(["Smart score ranking", "Unusual candles", "Stock candle by candle"]
                   + (["How the score works"] if IS_ADMIN else []))
    with tabs[0]:
        f1, f2, f3 = st.columns([1, 1, 2])
        side = f1.segmented_control("Side", ["All", "Bullish", "Bearish"], default="All", key="act_side") or "All"
        min_act = f2.slider("Minimum activity", 0, 100, 0, 5, key="act_min",
                            help="Activity 0 = normal for the time of day; 50+ = clearly unusual; 80+ = extreme.")
        secs = f3.multiselect("Sector", sorted(x for x in R["Sector"].unique() if x), key="act_sec")
        d = R[R["Activity"] >= min_act]
        if side == "Bullish":
            d = d[d["Smart"] > 0].sort_values("Smart", ascending=False)
        elif side == "Bearish":
            d = d[d["Smart"] < 0].sort_values("Smart")
        if secs:
            d = d[d["Sector"].isin(secs)]
        show_table(d, ["Stock", "Sector", "Price", "Chg %", "Smart", "Side", "Activity", "Direction", "Peak Smart",
                       "Gap %", "Gap x", "Vol x (time)", "Turnover x (time)", "Turnover Cr", "Range x (time)",
                       "ATR used %", "Candle Vol x", "Candle Range x", "From open %", "vs VWAP %", "RSI", "Buy/Sell",
                       "OI Chg %", "Candle OI x", "Buildup", "Signals", "Time"], "act_rank", height=720)
        st.caption("Sorted by the strength of the smart score (either side). Every '× avg' compares with the same time "
                   "of day over the last 20 sessions. Click a name for its chart; the 'Stock candle by candle' tab "
                   "shows how the score built up.")
    with tabs[1]:
        if E.empty:
            st.info("No unusual candles yet today.")
        else:
            w = st.segmented_control("Show", ["Last 30 minutes", "All day"], default="All day", key="act_ev_win") or "All day"
            ev = E
            if w == "Last 30 minutes":
                cut = (pd.Timestamp(f"2000-01-01 {last_bar}") - pd.Timedelta(minutes=30)).strftime("%H:%M")
                ev = E[E["Time"] > cut]
            show_table(ev, ["Time", "Stock", "Candle", "Candle Vol x", "Candle Range x", "Candle OI x",
                            "Candle Turnover Cr", "Price", "Chg %", "Vol x (time)", "Smart"], "act_events", height=640)
            st.caption("Candles with volume 3× or more, range 2.5× or more, or an OI change 4× or more of what is "
                       "usual for that candle (same time of day, last 20 sessions). Newest first. In the history a "
                       "single big candle often snaps back: it shows where activity is, not which way it will go.")
    with tabs[2]:
        opts = R["Stock"].tolist()
        sym = st.selectbox("Stock", opts, key="act_stock")
        c = per.get(sym)
        if c is not None and not c.empty:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.5, 0.25, 0.25],
                                subplot_titles=("Price and VWAP", "Candle volume ÷ usual for that time",
                                                "Smart score and futures OI change %"),
                                specs=[[{}], [{}], [{"secondary_y": True}]])
            fig.add_trace(go.Candlestick(x=c["Time"], open=c["Open"], high=c["High"], low=c["Low"], close=c["Close"],
                                         increasing_line_color=UP, decreasing_line_color=DOWN, name="Price"), 1, 1)
            fig.add_trace(go.Scatter(x=c["Time"], y=c["VWAP"], name="VWAP", line=dict(color=GOLD, width=1.5)), 1, 1)
            fig.add_trace(go.Bar(x=c["Time"], y=c["Candle Vol x"], name="Candle vol ×",
                                 marker_color=np.where(c["Close"] >= c["Open"], UP, DOWN),
                                 marker_opacity=np.where(c["Candle Vol x"] >= 3, 1.0, 0.45)), 2, 1)
            fig.add_hline(y=1, line_dash="dot", line_color="grey", row=2, col=1)
            fig.add_trace(go.Scatter(x=c["Time"], y=c["Smart"], name="Smart score", line=dict(width=2)), 3, 1)
            if c["OI Chg %"].notna().any():
                fig.add_trace(go.Scatter(x=c["Time"], y=c["OI Chg %"], name="OI chg %",
                                         line=dict(width=1.5, dash="dot", color=GOLD)), 3, 1, secondary_y=True)
            fig.update_layout(height=720, template=plot_template(), showlegend=False, xaxis_rangeslider_visible=False,
                              margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, width="stretch", key="act_chart")
            cols = ["Time", "Close", "Chg %", "Smart", "Activity", "Direction", "Candle Vol x", "Vol x (time)",
                    "Turnover Cr", "Candle Range x", "Range x (time)", "ATR used %", "RSI", "vs VWAP %", "Buy Qty",
                    "Sell Qty", "Buy/Sell", "OI", "OI Chg %", "Candle OI x", "Buildup"]
            t = c[[x for x in cols if x in c]].iloc[::-1].round(2)
            data_table(t, f"act_c_{sym}", name_col="Time", height=480,
                       signed=("Chg %", "Smart", "Direction", "vs VWAP %", "OI Chg %"))
    if IS_ADMIN:
        with tabs[3]:
            st.markdown(A.HOW)
            note("Order-book quantities (total buy and sell quantity waiting in the market depth) are recorded from "
                       "live quotes about once a minute while this page's loader runs, and saved daily so they can be "
                       "compared with the usual reading over time. Near futures expiry, OI falls as positions roll to the "
                       "next month, so 'long unwinding' readings in the last few days are less meaningful.")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def index_defs() -> dict:
    return IX.load()


FLOW_WINDOWS = {"Whole day": None, "Last 60 min": 60, "Last 30 min": 30, "Last 15 min": 15}


@st.fragment(run_every=LIVE_EVERY)
def flow_body(svc):
    done, total = svc.progress()
    if done < total:
        st.progress(done / max(total, 1), text=f"Loading 5-minute history: {done} of {total} stocks…")
    res = _activity_data(svc)
    if res is None or res[0].empty:
        st.info("Waiting for the first data… (" + svc.status + ")", icon=":material/hourglass_top:")
        return
    R, E, per, session = res
    last_bar = R["Time"].max()
    idx = index_defs()
    scopes = ["All F&O"] + [d["name"] for d in idx.values()]
    scope = st.segmented_control("Scope", scopes, default="All F&O", key="flow_scope") or "All F&O"
    c1, c2 = st.columns([2, 3], vertical_alignment="bottom")
    win = c1.segmented_control("Period", list(FLOW_WINDOWS), default="Whole day", key="flow_win") or "Whole day"
    mins = FLOW_WINDOWS[win]
    start = None if mins is None else (pd.Timestamp(f"2000-01-01 {last_bar}") - pd.Timedelta(minutes=mins - 5)).strftime("%H:%M")
    c2.caption(f"Session {pd.Timestamp(session):%a %d %b} · last candle {last_bar}"
               + (f" · window {start}–{last_bar}" if start else "") + " · ₹ crore, F&O stocks")
    stocks = A.flow_window(per, start)
    if stocks.empty:
        st.info("No candles in this window yet.")
        return
    if scope != "All F&O":
        key = next(k for k, d in idx.items() if d["name"] == scope)
        index_flow(svc, per, stocks, idx, key, start)
        return
    stocks = stocks[stocks["Stock"].isin(set(fno_universe()[0]) | set(SC.NIFTY100)) |
                    ~stocks["Stock"].isin({m for d in idx.values() for m in d["w"]})]
    stocks["Sector"] = stocks["Stock"].map(U.FNO_SECTOR_OF).fillna("Other")
    stocks["Symbol"] = stocks["Stock"] + ".NS"
    sec = A.sector_flow(stocks)
    tot_in, tot_out = stocks["Inflow Cr"].sum(), stocks["Outflow Cr"].sum()
    m = st.columns(5)
    m[0].metric("Turnover", f"₹{tot_in + tot_out:,.0f} Cr", border=True)
    m[1].metric("Net flow, all F&O", f"₹{tot_in - tot_out:+,.0f} Cr", f"{tot_in / (tot_in + tot_out) * 100:.1f}% buying",
                delta_color="off", border=True)
    m[2].metric("Sectors with inflow", f"{int((sec['Net Flow Cr'] > 0).sum())} of {len(sec)}", border=True)
    m[3].metric("Most inflow", sec.iloc[0]["Sector"], f"₹{sec.iloc[0]['Net Flow Cr']:+,.0f} Cr", border=True)
    m[4].metric("Most outflow", sec.iloc[-1]["Sector"], f"₹{sec.iloc[-1]['Net Flow Cr']:+,.0f} Cr", border=True)

    tabs = st.tabs(["Sectors", "Rotation: from → to", "Through the day", "Stocks"] + (["How it works"] if IS_ADMIN else []))
    with tabs[0]:
        sb = sec.sort_values("Net Flow Cr")
        fig = go.Figure()
        fig.add_trace(go.Bar(y=sb["Sector"], x=-sb["Outflow Cr"], orientation="h", name="Outflow",
                             marker_color=DOWN, opacity=0.35, hovertemplate="%{y}: outflow ₹%{customdata:,.0f} Cr",
                             customdata=sb["Outflow Cr"]))
        fig.add_trace(go.Bar(y=sb["Sector"], x=sb["Inflow Cr"], orientation="h", name="Inflow",
                             marker_color=UP, opacity=0.35, hovertemplate="%{y}: inflow ₹%{x:,.0f} Cr"))
        fig.add_trace(go.Scatter(y=sb["Sector"], x=sb["Net Flow Cr"], mode="markers+text", name="Net",
                                 marker=dict(size=11, color=np.where(sb["Net Flow Cr"] >= 0, UP, DOWN), symbol="diamond"),
                                 text=[f"{v:+,.0f}" for v in sb["Net Flow Cr"]], textposition="middle right"))
        fig.update_layout(barmode="overlay", height=34 * len(sb) + 90, template=plot_template(),
                          margin=dict(l=10, r=40, t=10, b=10), xaxis=dict(title="₹ crore"),
                          legend=dict(orientation="h", y=1.04))
        st.plotly_chart(fig, width="stretch", key="flow_sec_chart")
        st.caption("Pale bars: total buying (right) and selling (left) turnover in each sector. Diamond: net flow.")
        show_table(sec.rename(columns={"Sector": "Stock"}).assign(Sector=lambda d: d["Stock"]),
                   ["Stock", "Net Flow Cr", "Inflow Cr", "Outflow Cr", "Buy share %", "Avg Chg %", "Stocks",
                    "Stocks with inflow", "OI Value Chg Cr", "Top inflow stock", "Top outflow stock"],
                   "flow_sectors", height=480, search_hint="Search sector…")
    with tabs[1]:
        links = A.rotation_links(sec)
        if not links:
            st.info("Every sector is moving the same way in this window, so there is no rotation to show.")
        else:
            srcs = list(dict.fromkeys(a for a, _, _ in links)); dsts = list(dict.fromkeys(b for _, b, _ in links))
            labels = [f"{x} (out)" for x in srcs] + [f"{x} (in)" for x in dsts]
            fig = go.Figure(go.Sankey(
                node=dict(label=labels, pad=18, thickness=16,
                          color=[DOWN] * len(srcs) + [UP] * len(dsts)),
                link=dict(source=[srcs.index(a) for a, _, _ in links],
                          target=[len(srcs) + dsts.index(b) for _, b, _ in links],
                          value=[v for _, _, v in links], color="rgba(150,150,150,0.25)",
                          hovertemplate="%{source.label} → %{target.label}: ₹%{value:,.0f} Cr<extra></extra>")))
            fig.update_layout(height=520, template=plot_template(), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch", key="flow_sankey")
            st.caption("Left: sectors with net outflow. Right: sectors with net inflow. Exchanges don't report who "
                       "sold to whom, so each outflow is shared across the inflow sectors in proportion to their size: "
                       "read it as 'money is leaving these and arriving in these'.")
        cc = st.columns(2)
        with cc[0]:
            st.markdown("**Biggest outflow stocks**")
            data_table(stocks.nsmallest(10, "Net Flow Cr")[["Stock", "Sector", "Net Flow Cr", "Chg %"]].round(2),
                       "flow_out10", signed=("Net Flow Cr", "Chg %"), height=380)
        with cc[1]:
            st.markdown("**Biggest inflow stocks**")
            data_table(stocks.nlargest(10, "Net Flow Cr")[["Stock", "Sector", "Net Flow Cr", "Chg %"]].round(2),
                       "flow_in10", signed=("Net Flow Cr", "Chg %"), height=380)
    with tabs[2]:
        bucket = st.segmented_control("Bucket", ["15 min", "30 min", "60 min"], default="30 min", key="flow_bucket") or "30 min"
        tl = A.sector_timeline(per, U.FNO_SECTOR_OF, int(bucket.split()[0]))
        if tl.empty:
            st.info("No data yet.")
        else:
            order = tl.sum().sort_values().index
            z = tl[order].T
            lim = float(np.nanmax(np.abs(z.values))) or 1
            fig = go.Figure(go.Heatmap(z=z.values, x=z.columns, y=z.index, colorscale=[[0, DOWN], [0.5, "#f5f5f5"], [1, UP]],
                                       zmin=-lim, zmax=lim, text=np.round(z.values).astype("float"),
                                       texttemplate="%{text:+,.0f}", hovertemplate="%{y} %{x}: ₹%{z:+,.0f} Cr<extra></extra>",
                                       colorbar=dict(title="₹ Cr")))
            fig.update_layout(height=34 * len(z) + 80, template=plot_template(), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch", key="flow_heat")
            st.caption("Net flow per sector in each time bucket: watch for a sector turning from red to green (money "
                       "arriving) or the reverse.")
            cum = tl.fillna(0).cumsum()
            top = list(cum.iloc[-1].abs().sort_values(ascending=False).index[:6])
            fig2 = go.Figure([go.Scatter(x=cum.index, y=cum[c], name=c, mode="lines+markers") for c in top])
            fig2.add_hline(y=0, line_dash="dot", line_color="grey")
            fig2.update_layout(height=380, template=plot_template(), margin=dict(l=10, r=10, t=30, b=10),
                               yaxis=dict(title="cumulative net flow ₹ Cr"), title="Running total, six biggest movers")
            st.plotly_chart(fig2, width="stretch", key="flow_cum")
    with tabs[3]:
        f1, f2 = st.columns([1, 2])
        side = f1.segmented_control("Show", ["All", "Inflow", "Outflow"], default="All", key="flow_side") or "All"
        secs = f2.multiselect("Sector", sorted(stocks["Sector"].unique()), key="flow_secs")
        d = stocks
        if side == "Inflow":
            d = d[d["Net Flow Cr"] > 0].sort_values("Net Flow Cr", ascending=False)
        elif side == "Outflow":
            d = d[d["Net Flow Cr"] < 0].sort_values("Net Flow Cr")
        else:
            d = d.sort_values("Net Flow Cr", key=lambda x: x.abs(), ascending=False)
        if secs:
            d = d[d["Sector"].isin(secs)]
        show_table(d, ["Stock", "Sector", "Price", "Chg %", "Net Flow Cr", "Flow % of usual", "Inflow Cr", "Outflow Cr",
                       "Buy share %", "Window Turnover Cr", "Turnover Cr", "Turnover x (time)", "OI Value Chg Cr",
                       "Buildup", "Smart"], "flow_stocks", height=680)
        st.caption("Flow % of usual day: net flow ÷ the stock's normal full-day turnover, so small and large stocks "
                   "can be compared. Futures OI ₹ Cr: new money in (+) or out (−) of the nearest future.")
    if IS_ADMIN:
        with tabs[4]:
            st.markdown(A.FLOW_HOW)


def _index_stats(stocks: pd.DataFrame, d: dict, prev_close: float | None) -> tuple[pd.DataFrame, dict]:
    w = d["w"]
    m = stocks[stocks["Stock"].isin(w)].copy()
    m["Weight %"] = m["Stock"].map(w)
    m["Symbol"] = m["Stock"] + ".NS"
    m["Sector"] = m["Stock"].map(U.FNO_SECTOR_OF).fillna("Other")
    m["Contribution pts"] = m["Weight %"] / 100 * m["Chg %"] / 100 * (prev_close or np.nan)
    m["Weighted flow"] = m["Weight %"] / 100 * m["Flow % of usual"]
    tin, tout = m["Inflow Cr"].sum(), m["Outflow Cr"].sum()
    st_ = {"net": tin - tout, "buy": tin / (tin + tout) * 100 if tin + tout else np.nan,
           "n_in": int((m["Net Flow Cr"] > 0).sum()), "n": len(m), "wflow": m["Weighted flow"].sum(),
           "missing": sorted(set(w) - set(m["Stock"])),
           "pts_up": m.loc[m["Contribution pts"] > 0, "Contribution pts"].sum(),
           "pts_dn": m.loc[m["Contribution pts"] < 0, "Contribution pts"].sum()}
    return m, st_


def _idx_level(svc, key):
    df = svc.idx_bars().get(key)
    if df is None or df.empty:
        return None, None, None
    df = SC.clean(df)
    d = df.index.normalize()
    today = df[d == d.max()]
    prev = df[d < d.max()]
    pc = float(prev["Close"].iloc[-1]) if not prev.empty else None
    return today, pc, (float(today["Close"].iloc[-1]) if not today.empty else None)


def index_flow(svc, per: dict, stocks: pd.DataFrame, idx: dict, key: str, start):
    # strip: all five indices
    cols = st.columns(len(idx))
    for col, (k, d) in zip(cols, idx.items()):
        _, pc, lvl = _idx_level(svc, k)
        _, s_ = _index_stats(stocks, d, pc)
        chg = f"{(lvl / pc - 1) * 100:+.2f}%" if lvl and pc else "—"
        col.metric(d["name"], f"₹{s_['net']:+,.0f} Cr", f"index {chg} · {s_['buy']:.0f}% buying",
                   delta_color="off", border=True)
    d = idx[key]
    today, pc, lvl = _idx_level(svc, key)
    m, s_ = _index_stats(stocks, d, pc)
    if m.empty:
        st.info("No constituent data yet.")
        return
    st.markdown(f"#### {d['name']}")
    c = st.columns(5)
    c[0].metric("Index", f"{lvl:,.2f}" if lvl else "—", f"{(lvl / pc - 1) * 100:+.2f}%" if lvl and pc else None,
                border=True)
    c[1].metric("Net flow, constituents", f"₹{s_['net']:+,.0f} Cr", f"{s_['buy']:.1f}% buying", delta_color="off",
                border=True)
    c[2].metric("Stocks with inflow", f"{s_['n_in']} of {s_['n']}", border=True)
    c[3].metric("Weighted flow", f"{s_['wflow']:+.2f}%",
                help="Each stock's net flow as % of its usual day's turnover, weighted by its index weight. Shows "
                     "buying/selling pressure in the index independent of stock size: above 0 = net buying.",
                border=True)
    c[4].metric("Points up / down today", f"{s_['pts_up']:+,.0f} / {s_['pts_dn']:+,.0f}" if pc else "—", border=True)

    t1, t2, t3 = st.tabs(["Stocks: inflow vs outflow", "Through the day", "Table"])
    with t1:
        b = m.sort_values("Net Flow Cr")
        fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.6, 0.4], horizontal_spacing=0.03,
                            subplot_titles=("Net flow ₹ Cr", "Index points contributed today"))
        fig.add_trace(go.Bar(y=b["Stock"], x=b["Net Flow Cr"], orientation="h",
                             marker_color=np.where(b["Net Flow Cr"] >= 0, UP, DOWN),
                             text=[f"{v:+,.0f}  ({w:.1f}%)" for v, w in zip(b["Net Flow Cr"], b["Weight %"])],
                             textposition="outside", cliponaxis=False,
                             hovertemplate="%{y}: ₹%{x:+,.1f} Cr<extra></extra>"), 1, 1)
        if b["Contribution pts"].notna().any():
            fig.add_trace(go.Bar(y=b["Stock"], x=b["Contribution pts"], orientation="h",
                                 marker_color=np.where(b["Contribution pts"] >= 0, UP, DOWN), opacity=0.6,
                                 hovertemplate="%{y}: %{x:+,.1f} pts<extra></extra>"), 1, 2)
        fig.update_layout(height=max(360, 24 * len(b) + 80), template=plot_template(), showlegend=False,
                          margin=dict(l=10, r=40, t=30, b=10))
        st.plotly_chart(fig, width="stretch", key=f"idxflow_{key}")
        st.caption("Bars: net money flow into each constituent (label: flow and index weight). Right: how many index "
                   "points each stock added or removed today (weight × its % change). A heavyweight with big outflow "
                   "is what drags the index.")
    with t2:
        parts = []
        for sym, w in d["w"].items():
            cdf = per.get(sym)
            if cdf is None or cdf.empty:
                continue
            usual = cdf["Usual Day Turnover Cr"].iloc[-1]
            parts.append(pd.DataFrame({"net": cdf["Net Flow Cr"].values,
                                       "wf": (w / 100 * cdf["Net Flow Cr"] / usual * 100).values}, index=cdf["Time"]))
        if parts:
            agg = pd.concat(parts).groupby(level=0).sum().sort_index().cumsum()
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=agg.index, y=agg["net"], name="Cumulative net flow ₹ Cr",
                                 marker_color=np.where(agg["net"] >= 0, UP, DOWN), opacity=0.5))
            if today is not None and not today.empty:
                fig.add_trace(go.Scatter(x=today.index.strftime("%H:%M"), y=today["Close"], name=d["name"],
                                         line=dict(color=GOLD, width=2)), secondary_y=True)
            fig.update_layout(height=420, template=plot_template(), margin=dict(l=10, r=10, t=30, b=10),
                              legend=dict(orientation="h", y=1.08))
            fig.update_yaxes(title_text="₹ Cr", secondary_y=False)
            st.plotly_chart(fig, width="stretch", key=f"idxday_{key}")
            st.caption("Running total of money flowing into the index's stocks (bars) against the index itself (line). "
                       "Watch for the line rising while flow turns down (weak rally) or the reverse.")
    with t3:
        show_table(m.sort_values("Weight %", ascending=False),
                   ["Stock", "Weight %", "Price", "Chg %", "Contribution pts", "Net Flow Cr", "Flow % of usual",
                    "Weighted flow", "Inflow Cr", "Outflow Cr", "Buy share %", "Turnover Cr", "Turnover x (time)",
                    "OI Value Chg Cr", "Buildup", "Smart"], f"idxtbl_{key}", height=640)
    st.caption(f"Weights: {d['src']}." + (f" No data yet for: {', '.join(s_['missing'])}." if s_["missing"] else "")
               + (" Flow is for the selected period; index points are for the whole day." if start else ""))


TREND_NAMES = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty", "FINNIFTY": "Fin Nifty", "SENSEX": "Sensex",
               "MIDCPNIFTY": "Midcap Select"}


def _five_star_data(svc):
    """Market internals from the Nifty 100 stocks, rebuilt once per loader pass."""
    bars, _ = svc.bars()
    memo = _memo("five_star")
    key = (id(svc), svc.last_pass, len(bars))
    if memo.get("k") != key:
        stocks = {x: bars[x] for x in SC.NIFTY100 if x in bars}
        memo.update(k=key, v=(FIVE.market_internals(stocks), stocks))
    return memo["v"]


GOLD_LOG_START = pd.Timestamp("2026-11-02")  # paper trades are logged from here on (UTC signal time)


@st.cache_data(ttl=300, show_spinner=False)
def _gold_flow() -> dict:
    """Gold Order Flow on 15-minute PAXG candles (60 days from Binance), refreshed every 5 minutes."""
    try:
        return GF.run(GF.to_15m(TO.binance_5m("PAXGUSDT", 60)))
    except Exception as e:
        return {"error": str(e)[:200]}


def gold_flow_tab():
    note_md(f"{_badge('ok')}&nbsp; **Your TradingView strategy, gold 15-min:** +0.31% a trade after costs over 2 years "
            "(176 trades, 41% wins, 7 of 9 quarters positive); TradingView's own Strategy Tester gives the same trades. "
            "Stop 1.5%, target 3%, about 90 trades a year, trades can last days. Paper-trade first.",
            unsafe_allow_html=True)
    if IS_ADMIN:
        with st.expander("Rules"):
            st.markdown(GF.__doc__.split("\n", 4)[4])
    r = _gold_flow()
    if r.get("error"):
        st.error(f"Gold candles did not load: {r['error']}")
        return
    stt, trs = r["state"], r["trades"]
    ist = lambda t: (pd.Timestamp(t) + pd.Timedelta(hours=5, minutes=30)).strftime("%d %b %H:%M")  # noqa: E731
    m = st.columns(4)
    m[0].metric("Gold (PAXG)", f"${stt['last']:,.2f}", f"candle {ist(stt['time'])} IST", delta_color="off")
    m[1].metric("Order flow", stt["flow"])
    m[2].metric("Structure", stt["structure"])
    m[3].metric("Order block", stt["in_ob"])
    cur = trs[-1] if trs and trs[-1]["state"] in ("open", "waiting for next candle") else None
    if cur:
        col = UP if cur["side"] > 0 else DOWN
        with st.container(border=True):
            st.markdown(f"<div style='font-size:1.5rem;font-weight:800;color:{col}'>"
                        f"{'BUY' if cur['side'] > 0 else 'SELL'} gold · signal {ist(cur['signal_time'])} IST "
                        f"({cur['kind']})</div>", unsafe_allow_html=True)
            k = st.columns(4)
            k[0].metric("Entry", f"${cur['entry']:,.2f}" if cur["entry"] else "next candle")
            k[1].metric("Stop (1.5%)", f"${cur['stop']:,.2f}")
            k[2].metric("Target (3%)", f"${cur['target']:,.2f}")
            k[3].metric("Now", f"{cur['pct']:+.2f}%" if cur["pct"] is not None else "—", cur["state"],
                        delta_color="off")
    else:
        st.markdown("<div style='font-size:1.3rem;font-weight:700;color:#94A3B8'>No open trade: waiting for the next "
                    "order-flow cross with the structure</div>", unsafe_allow_html=True)
    done = [t for t in trs if t["state"] in ("stopped", "target hit")]
    if done:
        v = pd.Series([t["pct"] - GF.COST_PCT for t in done])
        st.caption(f"Last 60 days: {len(done)} closed trades, {100 * (v > 0).mean():.0f}% wins, average {v.mean():+.2f}%, "
                   f"total {v.sum():+.1f}% (after about 0.5 $ cost a trade).")
    tbl = pd.DataFrame([{"Signal (IST)": ist(t["signal_time"]), "Side": "BUY" if t["side"] > 0 else "SELL",
                         "Type": t["kind"], "Entry": t["entry"], "Stop": t["stop"], "Target": t["target"],
                         "Exit": t["exit"], "Exit (IST)": ist(t["exit_time"]) if t["exit_time"] is not None else "",
                         "Result": t["state"], "Result %": (t["pct"] - GF.COST_PCT) if t["pct"] is not None else None}
                        for t in reversed(trs)])
    if not tbl.empty:
        data_table(tbl.round(2), "gold_flow_trades", name_col="Signal (IST)", signed=("Result %",), height=420)
    st.caption("15-minute candles of PAXG (a gold-backed token that tracks XAUUSD) from Binance; check the XAUUSD price at "
               "your broker before entering. Refreshes every 5 minutes.")


def fade_tab(svc):
    note_md(f"{_badge('ok')}&nbsp; **Bank Nifty failed-break fade:** +26 pts a trade after 5 pts cost (Dec 2021 - "
            "Oct 2026), 58 trades a year, 49% wins, positive in both halves and in all 36 tried stop / window / exit "
            "mixes. Best before 11:00 (+43). Wide stop (0.4 x daily ATR, about 250 pts): size by it. Paper-trade first.",
            unsafe_allow_html=True)
    if IS_ADMIN:
        with st.expander("Rules"):
            st.markdown(FADE.__doc__.split("\n", 3)[3])
    bn = svc.idx_bars().get("BANKNIFTY")
    if bn is None or bn.empty:
        st.info("Waiting for Bank Nifty 5-minute bars from the loader.", icon=":material/hourglass_top:")
        return
    r = FADE.evaluate(bn, datetime.now(IST).replace(tzinfo=None))
    if r.get("status") != "ok":
        st.caption(f"Not ready: {r.get('status')}.")
        return
    sess = pd.Timestamp(r["session"])
    live_today = sess.date() == datetime.now(IST).date()
    m = st.columns(4)
    m[0].metric("Yesterday's high", f"{r['pdh']:,.1f}", f"{r['last'] - r['pdh']:+,.0f} from it now", delta_color="off")
    m[1].metric("Yesterday's low", f"{r['pdl']:,.1f}", f"{r['last'] - r['pdl']:+,.0f} from it now", delta_color="off")
    m[2].metric("Bank Nifty", f"{r['last']:,.1f}", f"candle {r['last_time']}", delta_color="off")
    m[3].metric("Stop distance", f"{r['risk']:,.0f} pts", f"0.4 x ATR {r['atr']:,.0f}", delta_color="off")
    if not live_today:
        st.caption(f"Market closed: showing {sess:%a %d %b}.")
    for tr in r["trades"]:
        col = UP if tr["side"] > 0 else DOWN
        with st.container(border=True):
            st.markdown(f"<div style='font-size:1.5rem;font-weight:800;color:{col}'>"
                        f"{'BUY' if tr['side'] > 0 else 'SELL'} Bank Nifty · {tr['time']}</div>"
                        f"<span class='muted'>{tr['level']} broke at {tr['break_time']} and closed back inside</span>",
                        unsafe_allow_html=True)
            k = st.columns(5)
            k[0].metric("Entry", f"{tr['entry']:,.1f}")
            k[1].metric("Stop", f"{tr['stop']:,.1f}", f"{tr['risk']:,.0f} pts", delta_color="off")
            k[2].metric("Target (2R)", f"{tr['target']:,.1f}", f"{2 * tr['risk']:,.0f} pts", delta_color="off")
            k[3].metric("Points", f"{tr['pts']:+,.0f}", tr["state"], delta_color="normal" if tr["pts"] >= 0 else "inverse")
            k[4].metric("Exit", f"{tr['exit']:,.1f}" if tr["exit"] else "—", tr["exit_time"] or "15:10 close if nothing hits",
                        delta_color="off")
    if not r["trades"]:
        st.markdown("<div style='font-size:1.3rem;font-weight:700;color:#94A3B8'>No fade "
                    f"{'yet' if live_today else 'that session'}</div>", unsafe_allow_html=True)
    st.markdown("**Each level now**")
    for sd in r["sides"]:
        st.markdown(f"- **{sd['level']} {sd['price']:,.1f}**: {sd['state']}")
    st.caption("5-minute index candles, closed candles only; refreshes with the page. Trade the future or an option "
               "and check its price before entering.")


def five_star_tab(svc):
    note_md(f"{_badge('ok')}&nbsp; **Bank Nifty futures:** +29 pts a trade after 12 pts cost (2015-2026), 72 trades a "
            "year, 50% wins, 9 of 12 years positive; last 12 months on Dhan data +13 pts. Profit comes from a few wide "
            "trend days: fixed lots, keep capital for 2x the worst drawdown (-1,720 pts). Paper-trade first.",
            unsafe_allow_html=True)
    if IS_ADMIN:
        with st.expander("Rules"):
            st.markdown(FIVE.__doc__.split("\n", 2)[2])
    bn = svc.idx_bars().get("BANKNIFTY")
    if bn is None or bn.empty:
        st.info("Waiting for Bank Nifty 5-minute bars from the loader.", icon=":material/hourglass_top:")
        return
    internals, stocks = _five_star_data(svc)
    r = FIVE.evaluate(bn, internals)
    if r.get("status") in ("no data", "need 12 earlier sessions"):
        st.caption(f"Not ready: {r['status']}.")
        return
    sess = pd.Timestamp(r["session"])
    live_today = sess.date() == datetime.now(IST).date()
    sg = r.get("signal")
    c1, c2 = st.columns([1.2, 1]) if not MOBILE else (st.container(), st.container())
    with c1:
        with st.container(border=True):
            if sg:
                side = "BUY" if sg["side"] > 0 else "SELL"
                col = UP if sg["side"] > 0 else DOWN
                st.markdown(f"<div style='font-size:1.6rem;font-weight:800;color:{col}'>{side} Bank Nifty · "
                            f"{sg['time']}</div>", unsafe_allow_html=True)
                m = st.columns(4)
                m[0].metric("Entry", f"{sg['entry']:,.1f}")
                m[1].metric("Stop now (Supertrend)", f"{sg['stop']:,.1f}", f"risk at entry {sg['risk']:,.0f} pts",
                            delta_color="off")
                m[2].metric("Points", f"{sg['pts']:+,.0f}", sg["state"], delta_color="normal" if sg["pts"] >= 0 else "inverse")
                m[3].metric("Exit", f"{sg['exit']:,.1f}" if sg["exit"] else "—", sg["exit_time"] or "trail the Supertrend",
                            delta_color="off")
            else:
                last = r["last"]
                st.markdown(f"<div style='font-size:1.4rem;font-weight:700;color:#94A3B8'>No signal "
                            f"{'yet' if live_today else 'that session'}</div>", unsafe_allow_html=True)
                st.caption(f"Latest candle {last['time']}: {last['checks']} of 6 checks, leaning {last['lean']} · "
                           f"Bank Nifty {last['close']:,.1f}, Supertrend {last['st']:,.1f}")
            if not live_today:
                st.caption(f"Market closed: showing {sess:%a %d %b}.")
        rows = r["rows"]
        lastrow = rows.iloc[-1]
        st.markdown("**Latest candle, " + lastrow["Time"] + "**")
        for n in FIVE.CHECK_NAMES:
            st.markdown(("✅ " if lastrow[n] else "▫️ ") + n)
    with c2:
        st.markdown("**Market internals**")
        it = FIVE.internals_now(internals, stocks)
        if it:
            m = st.columns(2)
            m[0].metric("Nifty 50 above VWAP", f"{100 * it['breadth']:.0f}%" if pd.notna(it["breadth"]) else "—",
                        f"{it['breadth_n']} stocks", delta_color="off")
            m[1].metric("Volume, last candle", f"{it['vol_x']:.1f}x usual" if pd.notna(it["vol_x"]) else "—",
                        f"day {it['turnover_x']:.2f}x" if pd.notna(it["turnover_x"]) else None, delta_color="off")
            m = st.columns(2)
            m[0].metric("Net volume, last candle", f"{it['net_z']:+.1f}" if pd.notna(it["net_z"]) else "—",
                        "buying" if (it["net_z"] or 0) > 0 else "selling", delta_color="off")
            m[1].metric("Net volume today", f"₹{it['cum_net_cr']:+,.0f} Cr", f"turnover ₹{it['turnover_cr']:,.0f} Cr",
                        delta_color="off")
            if it["heavy"]:
                st.markdown(" · ".join(f"**{k}** <span style='color:{UP if v['chg'] >= 0 else DOWN}'>{v['chg']:+.2f}%</span>"
                                       f"{' ▲VWAP' if v['above_vwap'] else ' ▼VWAP'}" for k, v in it["heavy"].items()),
                            unsafe_allow_html=True)
            note(f"As of {it['time']}. Volume and net volume: Nifty 100 stocks' turnover vs the same candle on the "
                 "last 20 sessions; net = turnover split by where each candle closed in its range.")
    st.markdown("**Today's candles**")
    show = rows.copy()
    for n in FIVE.CHECK_NAMES:
        show[n] = np.where(show[n], "✅", "")
    data_table(show.iloc[::-1].round(2), "five_star_rows", name_col="Time", height=420,
               signed=("RSI",))
    st.caption("Refreshes with the scanner page (every minute). Bank Nifty bars come from the index; check the futures "
               "price before entering.")


def index_trend_tab(svc):
    note_md(f"{_badge('ok')}&nbsp; **Index options (buy):** +4.1% of premium a trade on Bank Nifty, +1.9% on Nifty "
                "(fixed check times); 10-20 trades a year per index · win ~40-47%<br><span class='muted'>"
                "Trend established by mid-morning AND futures OI rising (new positions behind the move) is the only "
                "pattern in the index study where buying options paid. Noisy on its own: paper-trade first, size small."
                "</span>", unsafe_allow_html=True)
    if IS_ADMIN:
        with st.expander("Rules"):
            st.markdown(TA.__doc__.split("\n", 2)[2])
    thr_cols = st.columns(len(TREND_NAMES))
    thr = {k: c.number_input(f"{TREND_NAMES[k]} threshold (ATR)", 0.3, 2.0, TA.DEFAULT_THR[k], 0.1, key=f"ta_thr_{k}")
           for c, k in zip(thr_cols, TREND_NAMES)}
    idx_b, fut_b = svc.idx_bars(), svc.ifut_bars()
    vix = idx_b.get("INDIAVIX")
    if svc.source != "dhan":
        st.warning("This alert needs Dhan (index futures OI and volume). Switch the data source to Dhan.")
    cards = st.columns(len(TREND_NAMES))
    rows = []
    for col, k in zip(cards, TREND_NAMES):
        spot = idx_b.get(k)
        r = TA.evaluate(k, spot, fut_b.get(k), vix, thr[k],
                        TA.days_to_expiry(k, spot.index.max() if spot is not None and not spot.empty else datetime.now(IST)))
        with col.container(border=True):
            st.markdown(f"**{TREND_NAMES[k]}**")
            if r["status"] in ("no data", "need 15 earlier sessions"):
                st.caption(r["status"])
                continue
            if r["status"] == "SIGNAL":
                st.markdown(f"{_badge('best')}&nbsp; **BUY {r['side']} {r['strike']:,.0f}** at {r['sig_time']}",
                            unsafe_allow_html=True)
                st.caption(f"Index {r['sig_px']:,.1f} → {r['last']:,.1f} ({r['idx_move']:+,.1f} pts) · est. option "
                           f"{r['opt_now'] * 100:+.0f}% (best {r['opt_peak'] * 100:+.0f}%) · {r['trade_state']}")
            else:
                st.markdown(f"<span class='muted'>{r['status']}</span>", unsafe_allow_html=True)
            st.metric("Move from open", f"{r['move_atr']:+.2f} ATR", f"needs ±{r['thr']:.1f}", delta_color="off")
            for name, ok in r.get("checks", {}).items():
                st.markdown(("✅ " if ok else "▫️ ") + name)
            oi = r.get("oi_chg")
            st.caption(f"Futures OI vs yesterday: {oi:+.2f}%" if pd.notna(oi) else "Futures OI: —")
        rows.append(r)
    sig = [r for r in rows if r.get("status") == "SIGNAL"]
    if sig:
        fig = go.Figure()
        for r in sig:
            p = r.get("opt_path") or []
            if p:
                fig.add_trace(go.Scatter(x=[a for a, _ in p], y=[b * 100 for _, b in p], mode="lines",
                                         name=f"{TREND_NAMES[r['key']]} {r['side']}"))
        fig.add_hline(y=-30, line_dash="dot", line_color=DOWN)
        fig.add_hline(y=30, line_dash="dot", line_color=UP)
        fig.update_layout(height=320, template=plot_template(), margin=dict(l=10, r=10, t=30, b=10),
                          yaxis=dict(title="est. option P&L %"), title="Today's signals: estimated option P&L")
        st.plotly_chart(fig, width="stretch", key="ta_chart")
    st.caption("Option P&L is an estimate (Black-Scholes with India VIX, ATM strike, days to expiry from the current "
               "expiry calendar); check the real premium in the option chain. Checks run on 5-minute closes.")


def page_apex():
    status_strip()
    st.header("Index build-up")
    if not DHAN_DATA:
        need_dhan()
        return
    st.caption("Who is adding positions every 3 minutes, from open interest. Green = bullish build-up, red = bearish. "
               "Trade with the side that dominates the first hour.")
    c1, c2 = st.columns([2, 3])
    index = c1.selectbox("Index", list(AP.INDICES), key="apex_idx")
    strikes = c2.slider("Strikes each side of the money", 2, 10, 5, key="apex_strikes")
    try:
        box = apex_live(_dhan_sig()) if index == "NIFTY" and strikes == 5 else {}
        if box.get("bars") is not None:
            bars, info = box["bars"], box["info"]
        else:
            with st.spinner("Loading 1-minute OI for the index options and future (about 30 s on first load)…"):
                bars, info = apex_data(index, strikes)
    except D.DhanError as e:
        st.error(e.friendly)
        return
    except Exception as e:
        st.error(f"Could not load the build-up: {e}")
        return
    m = st.columns(4)
    for col, (label, until) in zip(m, [("Up to 9:45", "09:45"), ("Up to 10:15", "10:15"), ("Up to 10:30", "10:30"),
                                       ("Whole session", None)]):
        share, text = AP.dominance(bars, until)
        col.metric(label, text, f"{share:.0f}% bullish" if pd.notna(share) else None,
                   delta_color="normal" if pd.isna(share) or share >= 50 else "inverse")
    st.caption(f"{info['index']} · {info['session']:%a %d %b} · expiry {pd.Timestamp(info['expiry']):%d %b} · strikes "
               f"{info['strikes'][0]:g}-{info['strikes'][-1]:g} · updated {info['updated']}")

    # positions already open: carried from yesterday's close (OI is the stock of open positions; bars are the change)
    pv, nw = info.get("prev") or {}, info.get("now") or {}
    if pv.get("session"):
        st.markdown(f"##### Carried from yesterday ({pv['session']:%a %d %b})")
        k = st.columns(4)
        k[0].metric("Yesterday's build-up", f"{pv['net']:+,.0f} lots",
                    f"{pv['share']:.0f}% bullish" if pd.notna(pv.get("share")) else None,
                    delta_color="normal" if pd.isna(pv.get("share")) or pv["share"] >= 50 else "inverse", border=True)
        k[1].metric("Futures OI open", f"{nw.get('fut_oi', np.nan):,.0f} lots" if pd.notna(nw.get("fut_oi")) else "—",
                    f"{nw['fut_oi'] - pv['fut_oi']:+,.0f} today vs yday close {pv['fut_oi']:,.0f}"
                    if pd.notna(nw.get("fut_oi")) and pd.notna(pv.get("fut_oi")) else None, delta_color="off",
                    border=True)
        k[2].metric("Option OI open (calls / puts)",
                    f"{nw.get('ce_oi', 0):,.0f} / {nw.get('pe_oi', 0):,.0f}",
                    f"yday close {pv.get('ce_oi', 0):,.0f} / {pv.get('pe_oi', 0):,.0f} lots", delta_color="off",
                    border=True)
        k[3].metric("PCR at these strikes", f"{nw.get('pcr', np.nan):.2f}" if pd.notna(nw.get("pcr")) else "—",
                    f"yday close {pv['pcr']:.2f}" if pd.notna(pv.get("pcr")) else None, delta_color="off", border=True)
        st.caption("OI is the total of positions still open, so it already includes everything built on earlier days. "
                   "The bars below are only today's change; 'Since yesterday' adds yesterday's net build-up to the "
                   "running total.")
    view = st.segmented_control("Running total", ["Today only", "Since yesterday"], default="Since yesterday",
                                key="apex_cum") or "Since yesterday"
    cum = bars["cum_2d"] if view == "Since yesterday" and "cum_2d" in bars else bars["cum"]

    from plotly.subplots import make_subplots
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45], vertical_spacing=0.03,
                        specs=[[{}], [{"secondary_y": True}]])
    x = bars.index.strftime("%H:%M")
    fig.add_trace(go.Candlestick(x=x, open=bars["Open"], high=bars["High"], low=bars["Low"], close=bars["Close"],
                                 increasing_line_color=UP, decreasing_line_color=DOWN, name=index), 1, 1)
    fig.add_trace(go.Bar(x=x, y=bars["bull"], marker_color=UP, name="Bullish build-up"), 2, 1)
    fig.add_trace(go.Bar(x=x, y=-bars["bear"], marker_color=DOWN, name="Bearish build-up"), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=cum, name=f"Running total ({view.lower()})", line=dict(color=GOLD, width=2)),
                  2, 1, secondary_y=True)
    fig.update_layout(template=plot_template(), height=620, barmode="relative", showlegend=False,
                      margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False)
    fig.update_xaxes(type="category", nticks=14)
    fig.update_yaxes(title_text="Lots per bar", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Running total", row=2, col=1, secondary_y=True, showgrid=False)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with st.expander("Bar data"):
        t = bars.reset_index(names="Time")
        t["Time"] = t["Time"].dt.strftime("%H:%M")
        data_table(t[["Time", "Close", "opt_bull", "opt_bear", "fut_bull", "fut_bear", "net", "cum"]
                     + (["cum_2d"] if "cum_2d" in t else [])].round(1),
                   "apex_bars", labels={"opt_bull": "Options bull", "opt_bear": "Options bear", "fut_bull":
                                        "Futures bull", "fut_bear": "Futures bear", "net": "Net", "cum": "Today total",
                                        "cum_2d": "Since yesterday"},
                   signed=("net", "cum", "cum_2d"), height=360)

    st.page_link(P["smart"], label="Smart money sectors and their best R-factor stocks", icon=":material/insights:")


_PREP_CACHE = _memo("prepared")


def _prepared(svc):
    """Per-stock day statistics for the loader's latest bars, built once per loader pass and shared by the radar,
    breakout and R-factor (each rebuild walks every stock's history)."""
    bars, nifty_df = svc.bars()
    session = SC.session_of(nifty_df)
    key = ((id(svc), session), svc.last_pass, len(bars))
    return _fresh_or_last(_PREP_CACHE, key, lambda: (SC.prepare(bars, session), session))


def _prepared_now(svc):
    """_prepared for background jobs: always the loader's latest bars (builds them now if needed)."""
    bars, nifty_df = svc.bars()
    session = SC.session_of(nifty_df)
    key = ((id(svc), session), svc.last_pass, len(bars))
    with _heavy_lock():
        if _PREP_CACHE.get("v_k") != key:
            _PREP_CACHE["v"] = (SC.prepare(bars, session), session)
            _PREP_CACHE["v_k"] = key
        return _PREP_CACHE["v"]


def smart_money_stocks(svc) -> tuple[pd.DataFrame, object]:
    """Every F&O stock with its live price, today's futures buildup and rupee flow, and its R-factor."""
    res, _ = safe(oi_data, True)
    flows = SC.stock_flows(res[0]) if res else pd.DataFrame()
    bars, nifty_df = svc.bars()
    if not bars or nifty_df is None or nifty_df.empty:
        return pd.DataFrame(), None
    S, session = _prepared(svc)
    key = ((id(svc), session), svc.last_pass, len(bars))
    rf = _fresh_or_last(_PREP_CACHE, key, lambda: SC.r_factor(_prepared_now(svc)[0], svc.oi() if hasattr(svc, "oi")
                                                              else {}), tag="rf").copy()
    if rf.empty:
        return rf, session
    rf = rf.drop(columns=["Buildup", "OI chg %", "Side", "Sector"], errors="ignore")
    rf["Prev Close"] = rf["Stock"].map(lambda s: S[s].prev_close if s in S else np.nan)
    rf["Chg %"] = rf["Move %"]
    if not flows.empty:
        f = flows.set_index("Stock")
        rf["Fut LTP"] = rf["Stock"].map(f["Fut LTP"])
        rf["OI Chg %"] = rf["Stock"].map(f["OI Chg %"])
        rf["Buildup"] = rf["Stock"].map(f["Buildup"]).fillna("")
        rf["Flow Cr"] = rf["Stock"].map(f["flow"])
    for c, v in (("Fut LTP", np.nan), ("OI Chg %", np.nan), ("Buildup", ""), ("Flow Cr", np.nan)):
        if c not in rf:
            rf[c] = v
    rf["Sector"] = rf["Stock"].map(U.FNO_SECTOR_OF).fillna("Other")
    rf["Symbol"] = rf["Stock"].map(U.fno_yahoo)
    return rf, session


SMART_COLS = ["Stock", "Price", "Chg %", "R-factor", "Buildup", "OI Chg %", "Flow Cr", "Volume vs usual",
              "OI vs usual", "Range vs usual", "Move / ATR", "Broke yday high/low", "Big-money bars", "Sector"]


def page_smart_money():
    status_strip()
    st.header("Smart money sectors")
    if not DHAN_DATA:
        need_dhan()
        return
    note("Sectors ranked by fresh positions in their stock futures today, not by price or volume. Inside each "
               "sector, stocks are ranked by R-factor: how unusual today's volume, futures OI change, range and move "
               "are versus the same time window on the last 20 sessions (0-100, across all F&O stocks). TradeFinder's "
               "way: take the sector the money favours, then its top 2-3 R-factor stocks moving with it.")
    svc = get_scan_service("dhan", _dhan_sig(), SS.VERSION)
    svc.set_universe(scan_universe("All F&O stocks"))
    svc.touch()
    smart_money_body(svc)


@st.fragment(run_every=LIVE_EVERY)
def smart_money_body(svc):
    sf = sector_flow_table()
    if DSTAT.get("hist_left_oi", 0):
        st.info(f"Loading previous-day open interest: {DSTAT['hist_left_oi']} contracts to go, so sectors are still "
                "filling in.", icon="⏳")
    if sf.empty:
        st.caption("No futures OI data yet.")
        return
    done, total = svc.progress()
    with st.spinner("Loading stock bars…"):
        rf, session = smart_money_stocks(svc)
    if done < total:
        st.progress(done / max(total, 1), text=f"Loading earlier sessions for R-factor: {done} of {total} stocks.")
    if session is not None:
        live_today = session.date() == datetime.now(IST).date()
        st.caption(("Live session" if live_today else f"Market closed: showing the {session:%a %d %b} session") +
                   (" · refreshes every minute" if LIVE_EVERY == 60 else " · refreshes every 5 min"))

    # ---- best picks: top R-factor stocks moving with a favoured sector
    st.subheader("Best picks")
    if rf.empty:
        st.caption("Stock bars are still loading.")
    else:
        picks = best_picks(rf, sf)
        if picks.empty:
            st.caption("No stock is moving with a bullish or bearish sector yet.")
        else:
            show_table(picks, ["Stock", "Side"] + SMART_COLS[1:], "smart_picks", height=420)
            note("Stocks in a Bullish sector that are up with long build-up or short covering in their future "
                       "(Bearish: down with short build-up or long unwinding), top 3 per sector by R-factor, best 10 "
                       "overall. Then check the radar's yesterday high/low break and option writing before entry.")

    # ---- sector table
    st.subheader("Sectors by smart money")
    data_table(sf, "smart_sectors", signed=("Smart money (Rs cr)", "Bias %", "Price move %"), name_col="Sector",
               height=480)
    note("Rupee value of fresh positions in each sector's stock futures today (near month, OI change x price): "
               "long build-up counts fully bullish, short covering half, short build-up fully bearish, long "
               "unwinding half.")

    # ---- stocks per sector
    if rf.empty:
        return
    st.subheader("Stocks in each sector")
    for _, r in sf.iterrows():
        g = rf[rf["Sector"] == r["Sector"]]
        if g.empty:
            continue
        with st.expander(f"{r['Sector']} · {r['Flow']} · ₹{r['Smart money (Rs cr)']:+,.0f} cr · {len(g)} stocks",
                         expanded=False):
            show_table(g, SMART_COLS[:-1], f"smart_sec_{r['Sector']}", height=420)


RESEARCH_DOCS = {"Final setups (summary)": "research/FINAL_SETUPS.md", "Intraday studies": "research/intraday/README.md",
                 "Daily data studies": "research/README.md", "Work log": "WORKLOG.md"}


def page_research():
    """Admin only: every research note and the methods behind the scanners, in one locked place."""
    status_strip()
    st.header("Research notes")
    if not IS_ADMIN:
        st.error("Admins only.")
        return
    st.caption("Only admins see this page, the Research tab, the 'How it works' tabs and the method notes under "
               "each scanner. Other users see the signals and tables only.")
    gh = _github_cfg()
    st.caption(f"Option-chain recorder (cloud copy, every 5 min in market hours): {CL.STATUS['snaps']} snapshots, "
               f"{CL.STATUS['rows']} rows this run, last {CL.STATUS['last'] or '—'}; written to GitHub "
               f"{CL.STATUS['written'] or 'not yet'}" + (f"; last error: {CL.STATUS['error']}" if CL.STATUS["error"] else "."))
    st.caption(f"Desk log (9:20, 9:45, 10:30, 12:00, 13:30, 15:00 on market days): last saved {DL.STATUS['last'] or 'not yet in this run'}; "
               + ("copies to GitHub branch `logs`." if gh.get("token") else
                  "**GitHub copy off**: add `[github]` `token = \"…\"` in Secrets, or the log is lost on restart.")
               + (f" Last GitHub error: {DL.STATUS['error']}" if DL.STATUS["error"] else ""))
    pick = st.segmented_control("Note", list(RESEARCH_DOCS), default=list(RESEARCH_DOCS)[0], key="rs_doc",
                                label_visibility="collapsed") or list(RESEARCH_DOCS)[0]
    try:
        st.markdown((Path(__file__).parent / RESEARCH_DOCS[pick]).read_text(encoding="utf-8"))
    except Exception as e:
        st.warning(f"Could not open {RESEARCH_DOCS[pick]}: {e}")
    with st.expander("Scanner research table"):
        rs = pd.DataFrame([{"Setup": r[0], "Verdict": SC.VERDICT_LABEL[r[2]], "Trade with": r[1],
                            "Shares / trade": r[3], "Options / trade": r[4], "Years +": r[5], "Notes": r[6]}
                           for r in SC.RESEARCH])
        data_table(rs, "rs_table", name_col="Setup", height=520)


@st.cache_data(ttl=300, show_spinner=False)
def _desk_log(_bucket: int) -> pd.DataFrame:
    return DL.load(_github_cfg())


def _closes(stocks: tuple) -> dict:
    """{stock: daily closes} (today's bar is the live price)."""
    data, _ = safe(fetch_daily, tuple(U.fno_yahoo(x) for x in stocks))
    out = {}
    for x in stocks:
        df = (data or {}).get(U.fno_yahoo(x))
        if df is not None and not df.empty:
            idx = pd.DatetimeIndex(df.index)
            idx = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
            c = pd.Series(df["Close"].to_numpy(), index=idx)
            out[x] = c[~c.index.duplicated(keep="last")]
    return out


def _review(f: pd.DataFrame, closes: dict) -> pd.DataFrame:
    """One row per logged pick: result from its log price to that day's close, and to the next day's close."""
    rows = []
    for _, r in f.iterrows():
        c = closes.get(r["name"])
        sgn = 1 if r["side"] == "CE" else -1
        day = pd.Timestamp(r["date"])
        res = {"Date": r["date"], "Time": r["check"], "Stock": r["name"], "Side": r["side"],
               "Score": r["score"], "Price": r["price"], "Why": r["why"], "To close %": np.nan, "Next day %": np.nan}
        if c is not None and pd.notna(r["price"]) and float(r["price"]) > 0:
            if day in c.index:
                res["To close %"] = sgn * (c.loc[day] / float(r["price"]) - 1) * 100
            nxt = c[c.index > day]
            if len(nxt):
                res["Next day %"] = sgn * (nxt.iloc[0] / float(r["price"]) - 1) * 100
        rows.append(res)
    return pd.DataFrame(rows)


def _paper_results(L: pd.DataFrame) -> pd.DataFrame:
    """Results of the logged tested-setup paper trades. Opening setups: entry at the open, stop from the rule, exit at
    the close, 0.12% costs; the stop is checked on the day's low (buys) / high (shorts), so it counts as hit even if
    the close later recovered. 5-STAR: points from its own trailing-stop record, 12 points cost."""
    out = []
    st_ = L[L["kind"] == "setup"]
    if not st_.empty:
        data, _ = safe(fetch_daily, tuple(U.fno_yahoo(x) for x in sorted(set(st_["name"]))))
        for _, r in st_.iterrows():
            df = (data or {}).get(U.fno_yahoo(r["name"]))
            res = np.nan
            if df is not None and not df.empty:
                idx = pd.DatetimeIndex(df.index)
                idx = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
                d = df.set_axis(idx)
                day = pd.Timestamp(r["date"])
                if day in d.index:
                    bar = d.loc[[day]].iloc[-1]
                    e = float(r["price"])
                    stop = float(str(r["extra"]).replace("stop", "").strip() or "nan")
                    side = 1 if r["side"] == "CE" else -1
                    hit = (bar["Low"] <= stop) if side > 0 else (bar["High"] >= stop)
                    px = stop if hit else float(bar["Close"])
                    res = side * (px / e - 1) * 100 - 0.12
            out.append({"Date": r["date"], "Setup": r["why"], "Stock": r["name"],
                        "Side": "BUY" if r["side"] == "CE" else "SHORT", "Entry": r["price"],
                        "Result %": res, "Note": "stop hit" if pd.notna(res) and res < -0.5 else ""})
    fin = L[L["kind"] == "5star_final"]
    for _, r in fin.iterrows():
        out.append({"Date": r["date"], "Setup": "Bank Nifty 5-STAR", "Stock": "BANKNIFTY",
                    "Side": "BUY" if r["side"] == "CE" else "SELL", "Entry": r["price"],
                    "Result pts": float(r["score"]) - 12, "Note": r["why"]})
    opened = L[(L["kind"] == "5star") & ~L["date"].isin(set(fin["date"]))]
    for _, r in opened.iterrows():
        out.append({"Date": r["date"], "Setup": "Bank Nifty 5-STAR", "Stock": "BANKNIFTY",
                    "Side": "BUY" if r["side"] == "CE" else "SELL", "Entry": r["price"], "Note": "result not logged yet"})
    ff = L[L["kind"] == "fade_final"]
    done_f = set(zip(ff["date"], ff["check"]))
    for _, r in ff.iterrows():
        out.append({"Date": r["date"], "Setup": "Bank Nifty failed-break fade", "Stock": "BANKNIFTY",
                    "Side": "BUY" if r["side"] == "CE" else "SELL", "Entry": r["price"],
                    "Result pts": float(r["score"]) - FADE.COST, "Note": f"{r['why']} ({r['extra']})"})
    gf = L[L["kind"] == "gold_flow_final"]
    done_g = set(zip(gf["date"], gf["check"]))
    for _, r in gf.iterrows():
        out.append({"Date": r["date"], "Setup": "Gold Order Flow", "Stock": "GOLD",
                    "Side": "BUY" if r["side"] == "CE" else "SELL", "Entry": r["price"],
                    "Result %": float(r["score"]) - GF.COST_PCT, "Note": f"{r['why']} ({r['extra']})"})
    for _, r in L[L["kind"] == "gold_flow"].iterrows():
        if (r["date"], r["check"]) not in done_g:
            out.append({"Date": r["date"], "Setup": "Gold Order Flow", "Stock": "GOLD",
                        "Side": "BUY" if r["side"] == "CE" else "SELL", "Entry": r["price"], "Note": "still open"})
    for _, r in L[(L["kind"] == "fade")].iterrows():
        if (r["date"], r["check"]) not in done_f:
            out.append({"Date": r["date"], "Setup": "Bank Nifty failed-break fade", "Stock": "BANKNIFTY",
                        "Side": "BUY" if r["side"] == "CE" else "SELL", "Entry": r["price"],
                        "Note": "result not logged yet"})
    return pd.DataFrame(out)


@st.cache_data(ttl=300, show_spinner=False)
def _odds_bars(market: str, sym: str | None) -> tuple[pd.DataFrame, str]:
    """About 60 sessions of 5-minute bars: Dhan for India (Yahoo if Dhan is off), Binance for crypto and gold."""
    if market in TO.BINANCE:
        return TO.binance_5m(TO.BINANCE[market]), "Binance" + (" PAXG, which tracks gold" if market == "Gold" else "")
    if DHAN_DATA:
        try:
            cfg = _current_cfg()
            seg, sid, ins = (("IDX_I", 13, "INDEX") if market == "Nifty 50" else ("IDX_I", 25, "INDEX")
                             if market == "Bank Nifty" else ("NSE_EQ", D.equity_ids(cfg)[sym], "EQUITY"))
            df = SS._naive(D.intraday(seg, sid, ins, 5, 90, cfg))
            if not df.empty:
                return df, "Dhan"
        except Exception:
            pass
    tick = "^NSEI" if market == "Nifty 50" else "^NSEBANK" if market == "Bank Nifty" else f"{sym}.NS"
    df = yf.download(tick, period="60d", interval="5m", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return SS._naive(df[["Open", "High", "Low", "Close", "Volume"]].dropna()), "Yahoo"


def page_odds():
    st.title("Trade odds")
    st.caption("Before a small fixed-target trade: from this price and this time of day, how often did the target "
               "come before the stop? Built from the market's own 5-minute candles over about the last 60 sessions.")
    c = st.columns([1.2, 1.2, 1, 1]) if not MOBILE else [st.container() for _ in range(4)]
    mkt = c[0].selectbox("Market", list(TO.MARKETS), key="od_mkt")
    tgt_d, cost_d, cost_unit, india = TO.MARKETS[mkt]
    sym = c[1].selectbox("Stock", sorted(U.FNO_SECTOR_OF), key="od_sym") if mkt == "F&O stock" else None
    side_txt = c[2 if sym else 1].radio("Side", ["Buy / CE", "Sell / PE"], horizontal=True, key="od_side")
    side = 1 if side_txt.startswith("Buy") else -1
    holds = ["30 min", "60 min", "120 min", "Till 15:15"] if india else ["30 min", "60 min", "120 min", "240 min"]
    hold = c[3].selectbox("Hold for", holds, index=1, key=f"od_hold_{india}")
    with st.spinner("Loading 5-minute candles..."):
        got, err = safe(_odds_bars, mkt, sym)
    if got is None or got[0].empty:
        st.error(f"No 5-minute candles for {sym or mkt}: {err or 'empty'}")
        return
    bars, source = got
    last = float(bars["Close"].iloc[-1])
    pct = mkt == "F&O stock"
    unit = "%" if pct else "pts"
    c = st.columns(5) if not MOBILE else [st.container() for _ in range(5)]
    tgt = c[0].number_input(f"Target ({unit})", min_value=0.01, value=float(tgt_d), step=0.25 if pct else 1.0,
                            key=f"od_t_{mkt}")
    stp = c[1].number_input(f"Stop ({unit})", min_value=0.01, value=float(tgt_d), step=0.25 if pct else 1.0,
                            key=f"od_s_{mkt}")
    entry = c[2].number_input("Entry price", min_value=0.0, value=round(last, 2), step=0.05,
                              key=f"od_e_{mkt}_{sym}_{round(last, 2)}")
    now_ist = datetime.now(IST)
    if india:
        times = [f"{h:02d}:{m:02d}" for h in range(9, 15) for m in range(0, 60, 5)
                 if "09:15" <= f"{h:02d}:{m:02d}" <= "14:55"]
        nxt = (now_ist + timedelta(minutes=5 - now_ist.minute % 5)).strftime("%H:%M")
        live = SS.market_hours() and nxt in times
        at = c[3].selectbox("Entry time", times, index=times.index(nxt) if live else times.index("09:30"),
                            key="od_at")
        slot = int(TO._slots(pd.DatetimeIndex([pd.Timestamp(f"2000-01-01 {at}")]), True)[0])
    else:
        nxt_utc = pd.Timestamp.now("UTC").tz_localize(None).ceil("5min")
        at = (nxt_utc + pd.Timedelta(hours=5, minutes=30)).strftime("%H:%M")
        c[3].text_input("Entry time (IST)", at, disabled=True, key="od_at_c")
        slot = int(TO._slots(pd.DatetimeIndex([nxt_utc]), False)[0])
    cost_in = c[4].number_input(f"Cost per trade ({'pts' if cost_unit == 'pts' else '% of price'})",
                                min_value=0.0, value=float(cost_d), step=0.5 if cost_unit == "pts" else 0.01,
                                key=f"od_c_{mkt}")
    if entry <= 0:
        return
    t_pts = entry * tgt / 100 if pct else tgt
    s_pts = entry * stp / 100 if pct else stp
    cost = cost_in if cost_unit == "pts" else entry * cost_in / 100
    hold_bars = None if hold.startswith("Till") else int(hold.split()[0]) // 5
    today = pd.Timestamp(now_ist.date()) if india else pd.Timestamp.now("UTC").tz_localize(None).normalize()
    r = TO.replays(bars, side, entry, t_pts, s_pts, slot, hold_bars, india, today)
    if not r or r.get("error"):
        st.warning(f"Cannot replay this: {r.get('error') if r else 'no candles left in the session'}.")
        return
    need = TO.break_even(t_pts, s_pts, cost)
    exp = r["target"] * t_pts - r["stop"] * s_pts + r["open"] * r["open_avg_pts"] - cost
    st.markdown(f"**{'BUY' if side > 0 else 'SELL'} {sym or mkt} at {entry:,.2f}, {at} IST** · target "
                f"{entry + side * t_pts:,.2f} ({t_pts:,.2f} pts) · stop {entry - side * s_pts:,.2f} "
                f"({s_pts:,.2f} pts) · {hold.lower()}")
    m = st.columns(4)
    m[0].metric("Target first", f"{100 * r['target']:.0f}%", border=True)
    m[1].metric("Stop first", f"{100 * r['stop']:.0f}%", border=True)
    m[2].metric("Neither (time ran out)", f"{100 * r['open']:.0f}%",
                f"avg {r['open_avg_pts']:+,.1f} pts then", delta_color="off", border=True)
    pu = "₹/share" if pct else "pts"
    m[3].metric("Expected per trade", f"{exp:+,.1f} {pu}", f"after {cost:,.1f} {pu} cost", delta_color="off",
                border=True)
    v = TO.verdict(r["target"], r["stop"], need)
    (st.success if "toward the target" in v else st.error if "toward the stop" in v else st.warning)(v)
    st.caption(f"Break-even: a {t_pts:,.1f} target with a {s_pts:,.1f} stop and {cost:,.1f} cost must win "
               f"{100 * need:.0f}% of the trades that reach one side. {r['n']:,} replays from {r['pool_days']} past "
               f"sessions ({source}), seed {r['seed']}: the same inputs always give the same numbers.")
    st.markdown(f"**What really happened: this trade at {at} on past days**")
    h = TO.history(bars, side, t_pts, s_pts, slot, hold_bars, india, today)
    if h.empty:
        st.caption("No past days with a candle at this time.")
    else:
        cols = st.columns(2)
        for col, (label, g) in zip(cols, (("Every past day", h),
                                          ("Momentum days only (last 30 min moved your way)", h[h["Momentum day"]]))):
            sm = TO.summary(g, cost)
            with col.container(border=True):
                st.markdown(f"**{label}**")
                if not sm:
                    st.caption("None.")
                    continue
                k = st.columns(4)
                k[0].metric("Days", sm["trades"])
                k[1].metric("Target", f"{100 * sm['target']:.0f}%")
                k[2].metric("Stop", f"{100 * sm['stop']:.0f}%")
                k[3].metric("Avg after cost", f"{sm['avg_pts']:+,.1f}")
        with st.expander(f"All {len(h)} past days"):
            data_table(h, "od_hist", name_col="Date", signed=("Points",), height=380)
    note("Replays: each next 5-minute candle is a real past candle from the same time of day (within 10 minutes), "
         "scaled to the price; inside a candle the stop is checked before the target. History: the same trade at "
         "that candle's open on each past day. This is the recent past, not a forecast: news, results and expiry "
         "days can do what these 60 sessions never did.")


def page_desk_review():
    """Admin only: the logged desk at every time of day, side by side, with what each pick did afterwards."""
    status_strip()
    st.header("Desk review")
    if not IS_ADMIN:
        st.error("Admins only.")
        return
    L = _desk_log(int(time.time() // 300))
    if L.empty:
        st.info("No desk log yet. The Trading Desk saves itself at 9:20, 9:45, 10:30, 12:00, 13:30 and 15:00 on market "
                "days while it is open; add [github] token in Secrets so the log survives app restarts.",
                icon=":material/history:")
        return
    dates = sorted(L["date"].astype(str).unique(), reverse=True)
    c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
    day = c1.selectbox("Day", dates, key="dr_day")
    c2.caption("Result = move in the pick's direction (CE up, PE down) from the price when it was logged. "
               "To close: that day's close (today: the live price). Next day: the next session's close, the check for "
               "the 15:00 picks. No costs or stops: a quick read of where the desk was right and wrong.")
    d = L[L["date"].astype(str) == day]
    checks = [c for c in DL.CHECKS if c in set(d["check"])]
    f = d[d["kind"] == "focus"]
    R = _review(f, _closes(tuple(sorted(set(f["name"]))))) if not f.empty else pd.DataFrame()

    v = d[d["kind"] == "verdict"].set_index("check")
    ix = d[d["kind"] == "index"]
    mood = []
    for c in checks:
        row = {"Time": c, "Mood": v.loc[c, "name"] if c in v.index else "",
               "Score": float(v.loc[c, "score"]) if c in v.index and pd.notna(v.loc[c, "score"]) else np.nan}
        for _, p_ in ix[ix["check"] == c].iterrows():
            row[p_["name"]] = f"{p_['side']} {p_['price']}".strip() if p_["side"] in ("CE", "PE") else p_["side"]
        if not R.empty:
            g = R[R["Time"] == c]
            row.update({"CE picks": int((g["Side"] == "CE").sum()), "PE picks": int((g["Side"] == "PE").sum()),
                        "Avg to close %": g["To close %"].mean(),
                        "Right %": 100 * (g["To close %"] > 0).mean() if g["To close %"].notna().any() else np.nan})
        mood.append(row)
    st.subheader("Each time of day")
    data_table(pd.DataFrame(mood), "dr_mood", name_col="Time", signed=("Score", "Avg to close %"), height=300)

    if not R.empty:
        st.subheader("Picks across the day")
        mat = []
        for (stock, side), g in R.groupby(["Stock", "Side"]):
            g = g.set_index("Time")
            first = next(c for c in checks if c in g.index)
            row = {"Stock": stock, "Side": side, "First seen": first}
            for c in checks:
                row[c] = f"{float(g.loc[c, 'Score']):+.0f} @ {float(g.loc[c, 'Price']):,.2f}" if c in g.index else ""
            row["Times listed"] = len(g)
            row["To close % (from first)"] = g.loc[first, "To close %"]
            row["Next day % (from first)"] = g.loc[first, "Next day %"]
            mat.append(row)
        M = pd.DataFrame(mat).sort_values(["Times listed", "To close % (from first)"], ascending=[False, False])
        data_table(M, "dr_matrix", name_col="Stock", signed=("To close % (from first)", "Next day % (from first)"),
                   height=520)
        st.caption("Cells: desk score @ price at that time (blank = not on the list then). Stocks listed at many times "
                   "are the desk's most persistent picks.")
        with st.expander("Every logged pick with its reasons"):
            data_table(R.round(2), "dr_all", name_col="Stock", signed=("To close %", "Next day %"), height=480)

    st.subheader("Paper trades: the tested setups")
    P_ = _paper_results(L)
    if P_.empty:
        st.caption("No paper trades logged yet: the gap fade / panic gap-down / sector overreaction picks are saved "
                   "after 9:20, Bank Nifty 5-STAR and the failed-break fade when they fire, while the Trading Desk "
                   "is open.")
    else:
        summ = []
        for setup, g in P_.groupby("Setup"):
            col = "Result pts" if setup.startswith("Bank Nifty") else "Result %"
            v = g[col].dropna() if col in g else pd.Series(dtype=float)
            summ.append({"Setup": setup, "Trades": len(g), "With result": len(v),
                         "Average": f"{v.mean():+.2f}{' pts' if 'pts' in col else '%'}" if len(v) else "—",
                         "Total": f"{v.sum():+.2f}{' pts' if 'pts' in col else '%'}" if len(v) else "—",
                         "Win %": round(100 * (v > 0).mean()) if len(v) else np.nan})
        data_table(pd.DataFrame(summ), "dr_paper_sum", name_col="Setup", height=220)
        with st.expander(f"All {len(P_)} paper trades"):
            data_table(P_.sort_values("Date", ascending=False).round(2), "dr_paper", name_col="Stock",
                       signed=tuple(c for c in ("Result %", "Result pts") if c in P_), height=420)
        st.caption("History to beat: gap fade +0.66% a trade, panic gap-down +1.36%, sector overreaction +0.71%, "
                   "5-STAR +29 pts, failed-break fade +26 pts, Gold Order Flow +0.31%. A few weeks of trades are needed before comparing.")

    st.subheader("All logged days")
    allf = L[L["kind"] == "focus"]
    if allf.empty:
        st.caption("No picks logged yet.")
        return
    RA = _review(allf, _closes(tuple(sorted(set(allf["name"])))))
    rows = []
    for c in DL.CHECKS:
        g = RA[RA["Time"] == c]
        for side in ("CE", "PE", "All"):
            h = g if side == "All" else g[g["Side"] == side]
            if h.empty:
                continue
            rows.append({"Time": c, "Side": side, "Picks": len(h), "Days": h["Date"].nunique(),
                         "Avg to close %": h["To close %"].mean(),
                         "Right to close %": 100 * (h["To close %"] > 0).mean(),
                         "Avg next day %": h["Next day %"].mean(),
                         "Right next day %": 100 * (h["Next day %"] > 0).mean()})
    if rows:
        data_table(pd.DataFrame(rows), "dr_alldays", name_col="Time", signed=("Avg to close %", "Avg next day %"),
                   height=420)
    st.caption("Read 'Right %' against 50%: above it the desk's picks at that time beat a coin flip so far. "
               "A few weeks of days are needed before these numbers mean much.")


def _sign_out():
    for k in list(st.session_state.keys()):
        del st.session_state[k]


# ---------------------------------------------------------------- Setup Finder (bot.py results)


def _bots_state() -> dict | None:
    """The live bots' latest readings (bots.py on the server writes them every 5 minutes in market hours)."""
    try:
        s = json.loads((PATHS.DATA / "bots" / "state.json").read_text())
    except Exception:
        return None
    try:  # only today's readings count
        if s.get("updated", "")[:10] != datetime.now(IST).strftime("%Y-%m-%d"):
            s["stale"] = True
    except Exception:
        pass
    return s


def _pct(x) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.3f}%"


def _tone_dot(t) -> str:
    return "🟢" if (t or 0) > 0 else "🔴" if (t or 0) < 0 else "⚪"


def _research_rows(top: list) -> pd.DataFrame:
    return pd.DataFrame([{"Verdict": {"pass": "✅ Pass", "watch": "👀 Watch", "fail": "✖ Fail"}[x["verdict"]],
                          "Rule": x["text"], "Unseen days / trade": _pct(x["test"].get("per_trade_pct")),
                          "Trades": x["test"].get("n", 0), "Win %": x["test"].get("win_pct"), "t": x["test"].get("t"),
                          "Tuning days / trade": _pct(x["train"].get("per_trade_pct")),
                          "Robust %": x["neighbours_positive_pct"]} for x in top or []])


def _passed_card(best: dict, label: str):
    te = best["test"]
    st.markdown(
        f"<div class='mv-idea' style='--mvc:var(--om-up);--mvg:var(--om-up-soft)'><div class='k'>{label} · passed on "
        f"unseen days</div><h3>{te['per_trade_pct']:+.2f}% a trade after costs · {te['win_pct']:.0f}% wins · "
        f"{te['n']} trades (t {te['t']})</h3><p>{best['text']}.</p><p class='d'>Robust: "
        f"{best['neighbours_positive_pct']:.0f}% of the rules one setting away also made money. Paper-trade it "
        "before real money.</p></div>", unsafe_allow_html=True)


def _bot_flags(b: dict, cols: list[str]):
    fl = (b or {}).get("flags") or []
    if (b or {}).get("note"):
        st.caption(b["note"])
    if not fl:
        st.caption("Nothing flagged right now.")
        return
    st.dataframe(pd.DataFrame([{"": _tone_dot(f.get("tone")), **{c: f.get(k, "") for c, k in cols}} for f in fl]),
                 hide_index=True, width="stretch", column_config={"Why": st.column_config.TextColumn(width="large")})


def _radar_table(rows: list) -> pd.DataFrame:
    return pd.DataFrame([{
        "Stock": r["stock"], "Sector": r["sector"], "Price": r["price"], "Chg %": r["chg"],
        "Move ATR": r["move_atr"], "Range ×ATR": r["range_x"], "Vol ×usual": r["vol_x"], "5m vol ×": r["spike_x"],
        "Candle ×": r["candle_x"], "15m ATR": r["jump_atr"], "Buying %": r["buying"], "Net ₹ Cr": r["net_cr"],
        "OI chg %": r["oi_chg"], "OI ×usual": r["oi_x"], "Book buy %": r["book_buy"], "O=H/L": r["ohl"],
        "Odds kept %": (r.get("odds") or {}).get("win"), "Odds n": (r.get("odds") or {}).get("n"),
        "Score": r["score"], "Flags": " · ".join(r["events"]), "TradingView": MX.tv_url(r["stock"])} for r in rows])


def _momentum_section():
    try:
        m = json.loads((PATHS.DATA / "bot" / "momentum.json").read_text())
    except Exception:
        return
    st.subheader("What makes a stock trend intraday")
    st.caption(f"{m.get('source', '5-minute candles')} · {m['stocks']} F&O stocks · {m['days']} days ({m['first_day']} to {m['last_day']}) · "
               f"judged on unseen days from {m['split']} · t-stats counted over days. Run {m['run_at'][:16].replace('T', ' ')}.")
    chk = st.segmented_control("Decision time", list(m["checks"]), default=list(m["checks"])[-1], key="mom_chk") \
        or list(m["checks"])[-1]
    c = m["checks"][chk]
    b = c["base"]
    st.markdown(MX.kpis([
        MX.kpi("Trend days", f"{c['base_trend_pct']}%", "open → 15:15 at least 1.5 ATR"),
        MX.kpi("Average entry now", f"{b['ret']:+.3f}%", "in the move's direction, to 15:15, after 0.12%",
               MX.tone_color(b["ret"])),
        MX.kpi("Rules tested", f"{c['rules_tested']:,}", "1-3 conditions"),
        MX.kpi("Passed", f"{c['rules_pass']}", "unseen days: +0.05%+, t 2+ over days",
               MX.UP if c["rules_pass"] else MX.NEUTRAL),
    ]), unsafe_allow_html=True)
    bk = pd.DataFrame([{"Reading": x["desc"], "Bucket": x["bucket"], "Trend-day lift": x["lift"],
                        "Trade %": x["all"]["ret"], "t (days)": x["all"]["t"], "Tuning %": x["tune"]["ret"],
                        "Unseen %": x["unseen"]["ret"], "More ATR after": x["all"]["more"], "Cases": x["all"]["n"]}
                       for x in c["buckets"]])
    t1, t2 = st.tabs(["What comes before big moves", "Rules judged on unseen days"])
    with t1:
        st.caption("Lift 2.0 = a trend day follows twice as often as on an average day. A reading can predict a big day "
                   "and still not pay when entered at this time: compare Trade % (after costs) in both periods.")
        st.dataframe(bk.sort_values("Trend-day lift", ascending=False), hide_index=True, width="stretch", height=460,
                     column_config={"Trend-day lift": st.column_config.ProgressColumn(min_value=0, max_value=4, format="%.2f×"),
                                    "Trade %": st.column_config.NumberColumn(format="%+.3f"),
                                    "Tuning %": st.column_config.NumberColumn(format="%+.3f"),
                                    "Unseen %": st.column_config.NumberColumn(format="%+.3f")})
    with t2:
        rr = c.get("rules") or []
        if rr:
            st.dataframe(pd.DataFrame([{"Verdict": {"pass": "✅ Pass", "watch": "👀 Watch", "fail": "✖ Fail"}[x["verdict"]],
                                        "Rule": x["rule"], "Unseen %/trade": x["unseen"]["ret"], "Unseen t (days)": x["unseen"]["t"],
                                        "Unseen trades": x["unseen"]["n"], "Unseen days": x["unseen"]["days"],
                                        "Win %": x["unseen"]["win"], "Tuning %": x["tune"]["ret"], "Tuning t": x["tune"]["t"]}
                                       for x in rr]), hide_index=True, width="stretch",
                         column_config={"Rule": st.column_config.TextColumn(width="large")})
        else:
            st.caption("No rule made money on the tuning days.")


def page_bot():
    status_strip()
    st.header("Bots")
    for _c in (MX.CSS, MX.FUNNEL_CSS, MX.DESK_CSS):
        st.markdown(_c, unsafe_allow_html=True)
    l, r = st.columns([3, 1], vertical_alignment="center")
    l.caption("The bots watch every F&O stock, the indices, sectors and VIX every 5 minutes: sudden changes against "
              "each stock's own usual, with the odds of what happened next on past days, and ideas only when the "
              "market, Nifty, sector and VIX agree.")
    if IS_ADMIN and r.button("Run research tonight", icon=":material/smart_toy:", width="stretch",
                             help="Re-runs the Setup Finder research after market hours."):
        PATHS.state("bot_request").touch()
        st.success("Requested: the server runs the research after market hours (results in about 10-20 minutes).")
    s = _bots_state()
    if not s:
        st.info("The bots run on the server (recorder). Their readings show here in market hours, updated every 5 "
                "minutes.", icon=":material/hourglass_top:")
    else:
        bt, h = s.get("bots", {}), s.get("health", {})
        radar, master = bt.get("radar") or {}, bt.get("master") or {}
        ideas = master.get("ideas") or []
        n_st = {k: sum(i["status"] == k for i in ideas) for k in ("passed", "odds", "watch")}
        fresh = not s.get("stale")
        upd = s.get("updated", "")[11:16]
        chk = (s.get("odds_check") or [{}])[-1]
        good = next((b for b in chk.get("bands", []) if b.get("band") in ("60%+", "55-60%")), None)
        st.markdown(MX.kpis([
            MX.kpi("Bots", "Running" if fresh else "Market closed", f"updated {upd} IST", MX.UP if fresh else MX.NEUTRAL, dot=True),
            MX.kpi("Stocks watched", f"{h.get('stocks_live', 0)}", f"last candle {h.get('last_candle') or '—'}"),
            MX.kpi("Sudden changes", f"{len(s.get('feed') or [])}", "today, each stock + kind once", MX.ACCENT),
            MX.kpi("Ideas", f"{n_st['passed']} · {n_st['odds']} · {n_st['watch']}", "tested · good odds · watch",
                   MX.UP if n_st["passed"] + n_st["odds"] else MX.NEUTRAL),
            MX.kpi("Odds from", f"{h.get('odds_days') or 0} days", "rebuilt every night with the new day"),
            MX.kpi("Odds check", f"{good['kept']:.0f}% kept" if good else "—",
                   f"{chk.get('day', '')}: 55%+ odds events" if good else "after the first close", MX.WARN),
        ]), unsafe_allow_html=True)

        mom = s.get("momentum") or {}
        _recs = {(t.get("source", "").split(" (")[0], t.get("symbol")): t for t in (s.get("trades") or [])}
        for _k, _mo in mom.items():
            for g in (_mo or {}).get("signals", []):
                g["live"] = _rec_live(_recs.get(("Index momentum bot", f"{_k} {g['time']}")))
        for _i in ideas:
            _t = next((t for t in (s.get("trades") or []) if t.get("symbol") == _i["stock"] and t.get("source", "").startswith("Master bot")), None)
            if _t:
                _i["plan"] = _plan_of(_t)
                _i["live"] = _rec_live(_t)
        if mom:
            st.markdown(MX.section("Index momentum bot", "price + money + breadth + ATR rising together = trade · Bank Nifty: "
                                   "bursts are faded · price against money and breadth = trap"), unsafe_allow_html=True)
            st.markdown("<div class='wl'>" + "".join(MX.momentum_card(k, v) for k, v in mom.items()) + "</div>",
                        unsafe_allow_html=True)
        st.markdown(MX.section("Master bot: ideas", master.get("note", "")), unsafe_allow_html=True)
        if ideas:
            st.markdown(MX.idea_cards(ideas[:12]), unsafe_allow_html=True)
            lab = {"passed": "✅ Tested", "odds": "🎯 Good odds", "watch": "👀 Watch"}
            with st.expander(f"All {len(ideas)} ideas as a table (with levels)", icon=":material/table_rows:"):
                st.dataframe(pd.DataFrame([{
                    "Status": lab.get(i["status"], i["status"]), "Stock": i["stock"], "Side": i["side"], "Since": i["time"],
                    "Entry": (i.get("plan") or {}).get("entry"), "Stop": (i.get("plan") or {}).get("sl"),
                    "Target 1": (i.get("plan") or {}).get("tp1"), "Target 2": (i.get("plan") or {}).get("tp2"),
                    "Risk %": (i.get("plan") or {}).get("risk_pct"), "Checks": i["agree"],
                    "Odds kept %": (i.get("odds") or {}).get("win"), "Sector": i["sector"], "Why": i["why"]} for i in ideas]),
                    hide_index=True, width="stretch", column_config={"Why": st.column_config.TextColumn(width="large")})
            st.caption("Plan for every idea: entry at the price shown · stop just beyond the last 30 minutes' swing "
                       "(0.3-0.6 of the daily ATR) · target 1 = 1R (half off, stop to entry) · target 2 = 2R · exit 15:15. "
                       "Every idea is recorded and scored at the close (Signal record below).")
        else:
            st.caption("No idea yet: no stock has the balance (market, Nifty, sector, VIX) agreeing with a tested rule "
                       "or good past odds.")

        st.markdown(MX.section("Radar: sudden changes now", "odds = past days, same kind of moment, to 15:15 after costs")
                    + MX.event_cards(radar.get("events") or []), unsafe_allow_html=True)
        c1, c2 = st.columns([1.25, 1]) if not MOBILE else (st.container(), st.container())
        with c1:
            st.markdown(MX.section("Live feed", "newest first") + MX.feed(s.get("feed") or []), unsafe_allow_html=True)
        with c2:
            st.markdown(MX.section("Odds check", "did the odds hold? (scored at 15:35)"), unsafe_allow_html=True)
            hist = s.get("odds_check") or []
            if hist:
                rows = [{"Day": x["day"], "Odds band": b["band"], "Events": b["n"], "Kept going %": b["kept"],
                         "Avg %": b["avg"]} for x in hist[-5:] for b in x.get("bands", [])]
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            else:
                st.caption("After the first close the bots compare each event's odds with what actually happened.")
            st.markdown(MX.section("System health"), unsafe_allow_html=True)
            st.markdown(MX.kpis([
                MX.kpi("Data feed", h.get("last_candle") or "—", "latest 5-min candle", MX.UP if fresh else MX.NEUTRAL, dot=True),
                MX.kpi("OI (recorder)", f"{h.get('oi_from_recorder', 0)}", "futures with live OI",
                       MX.UP if h.get("oi_from_recorder") else MX.WARN, dot=True),
                MX.kpi("Research", (h.get("research_run") or "—")[:10], "last nightly run"),
            ]), unsafe_allow_html=True)
            for e in h.get("errors") or []:
                st.caption(f"⚠ {e}")

        rows = radar.get("rows") or []
        if rows:
            st.markdown(MX.section("Every F&O stock, against its own usual", "sorted by score · click a column to sort"),
                        unsafe_allow_html=True)
            df = _radar_table(rows)
            st.dataframe(df, hide_index=True, width="stretch", height=480, column_config={
                "Buying %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                "Odds kept %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                "Chg %": st.column_config.NumberColumn(format="%+.2f"), "Move ATR": st.column_config.NumberColumn(format="%+.2f"),
                "OI chg %": st.column_config.NumberColumn(format="%+.2f"),
                "Flags": st.column_config.TextColumn(width="large"), "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗")})
            st.caption("×usual = against the same stock's last 20 days at the same time of day. Range ×ATR = today's "
                       "range vs its 14-day ATR. 5m vol × / Candle × = the latest 5-minute candle vs the same slot. "
                       "OI from the recorder's futures quotes (near + next month). Book buy % = buy share of the "
                       "order book.")

        t1, t2, t3, t4 = st.tabs(["Index bot", "Sector bot", "Sector movers", "F&O unusual"])
        with t1:
            _bot_flags(bt.get("index"), [("Index", "name"), ("Level", "value"), ("Signal", "signal"), ("Why", "text")])
        with t2:
            _bot_flags(bt.get("sector"), [("Sector", "name"), ("Net money", "value"), ("Why", "text")])
        with t3:
            _bot_flags(bt.get("movers"), [("Stock", "name"), ("Move", "value"), ("Why", "text")])
        with t4:
            sig = (bt.get("unusual") or {}).get("signals") or []
            if sig:
                st.markdown("**Tested rule signals today**")
                st.dataframe(pd.DataFrame(sig), hide_index=True, width="stretch")
            _bot_flags(bt.get("unusual"), [("Stock", "name"), ("Move", "value"), ("Sector", "sector"), ("Why", "text")])

    _signal_record()
    st.divider()
    _momentum_section()
    st.subheader("Setup Finder research")
    res = BOT.latest()
    if not res:
        st.info("No research yet: it runs on the server every evening after 16:30.", icon=":material/hourglass_top:")
        return
    if res.get("error"):
        st.warning(f"Last run failed ({res.get('run_at', '')[:16]}): {res['error']}. It tries again tomorrow.")
        return
    sr = res.get("stocks") or {}
    if "rules_tried" not in sr:
        st.caption("Results are from the old research format; the next nightly run refreshes them.")
        return
    st.caption(f"Last run {res['run_at'][:16].replace('T', ' ')} · {sr['rules_tried']:,} rules on all F&O stocks · "
               f"{sr['candles']:,} candles over {sr['days']} days · judged on unseen days from {sr['split']} · "
               f"{res.get('seconds', 0) // 60} min")
    if sr.get("best"):
        _passed_card(sr["best"], "F&O stocks")
    else:
        st.info("No stock rule passed on the unseen days, so the master bot only gives watch ideas. That is the honest "
                "result: the rules below looked good on the first days but did not hold up.", icon=":material/block:")
    df = _research_rows(sr.get("top"))
    if not df.empty:
        st.dataframe(df, hide_index=True, width="stretch", column_config={"Rule": st.column_config.TextColumn(width="large")})
    ix = res.get("indices") or {}
    if ix:
        st.subheader("Indices")
        for k, v in ix.items():
            with st.expander(f"{BOT.INDEX_NAMES.get(k, k)} · " + ("✅ rule passed" if v.get("best") else "no rule passed")):
                if v.get("best"):
                    _passed_card(v["best"], BOT.INDEX_NAMES.get(k, k))
                d = _research_rows(v.get("top"))
                if not d.empty:
                    st.dataframe(d, hide_index=True, width="stretch",
                                 column_config={"Rule": st.column_config.TextColumn(width="large")})
                nm = v.get("macd") or {}
                if nm:
                    st.caption("MACD crosses with and without money flow")
                    st.dataframe(pd.DataFrame([{"Crosses": {"all_crosses": "All crosses", "flow_backed": "Money flow agrees",
                                                            "flow_against": "Money flow disagrees"}[kk],
                                                "Unseen days / trade": _pct(vv["test"].get("per_trade_pct")),
                                                "Trades": vv["test"].get("n", 0), "Win %": vv["test"].get("win_pct"),
                                                "Tuning days / trade": _pct(vv["train"].get("per_trade_pct"))}
                                               for kk, vv in nm.items()]), hide_index=True, width="stretch")
    note("Bots: every 5 minutes in market hours. A setup fires at the first candle its conditions are true (9:30-14:30), "
         "no fixed time. Research rules combine move from the open in ATR, money-flow buying share, volume vs the "
         "usual by that time, range vs the usual day, sector and market money agreeing; stop 0.5 or 1 ATR, exit 15:20, "
         "0.12% costs (0.02% index). Tuned on the first 60% of days, judged on the last 40%. Pass = +0.05%+ a trade, "
         "t 2+, 40+ trades on unseen days and 60%+ of neighbours positive. Every master idea is logged with its "
         "result at the close.")



# ---------------------------------------------------------------- Market View: one page, every signal and reading


MV_CSS = """<style>
.mv-idea{border-radius:var(--r-md);padding:16px 18px;margin:4px 0 16px;border:1px solid var(--mvc);
  background:linear-gradient(135deg,var(--mvg),transparent 70%)}
.mv-idea .k{font-size:var(--fs-xs);letter-spacing:.06em;text-transform:uppercase;opacity:.7}
.mv-idea h3{margin:.15rem 0 .4rem;font-size:var(--fs-xl);color:var(--mvc)}
.mv-idea p{margin:.25rem 0;font-size:var(--fs-md);line-height:1.45}
.mv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px;margin:6px 0 10px}
.mv-card{border:1px solid rgba(148,163,184,.22);border-left:4px solid var(--mvc);border-radius:var(--r-md);
  padding:12px 14px;background:rgba(148,163,184,.06)}
.mv-card .t{font-size:var(--fs-xs);text-transform:uppercase;letter-spacing:.05em;opacity:.8;display:flex;
  justify-content:space-between;align-items:center;gap:8px}
.mv-card .v{font-size:var(--fs-xl);font-weight:600;margin:3px 0 1px;color:var(--mvc)}
.mv-card .d{font-size:var(--fs-sm);opacity:.72}
.mv-card .m{font-size:var(--fs-sm);margin-top:8px;line-height:1.45;color:var(--om-text-2)}
.mv-pt{padding-left:14px;position:relative;margin-top:3px}
.mv-pt:before{content:"›";position:absolute;left:2px;color:var(--om-faint)}
.mv-pt.lead{font-weight:600;color:var(--om-text);font-size:var(--fs-md)}
.mv-ev{font-size:var(--fs-2xs);padding:1px 8px;border-radius:999px;border:1px solid var(--evc);color:var(--evc);
  white-space:nowrap;text-transform:none;letter-spacing:0}
</style>"""
MV_EV_COLOR = {"tested": "var(--om-up)", "edge": "var(--om-accent)", "context": "var(--om-neutral)"}


def _mv_tone_color(tone: int) -> str:
    return UP if tone > 0 else DOWN if tone < 0 else "#94A3B8"


def _mv_card(r: dict) -> str:
    ev = r.get("evidence", "context")
    return (f"<div class='mv-card' style='--mvc:{_mv_tone_color(r['tone'])}'><div class='t'><span>{r['title']}</span>"
            f"<span class='mv-ev' style='--evc:{MV_EV_COLOR[ev]}'>{MV.EVIDENCE[ev]}</span></div>"
            f"<div class='v'>{r['value']}</div><div class='d'>{r.get('detail', '')}</div>"
            f"<div class='m'>{_mv_meaning(r['meaning'])}</div></div>")


def _mv_meaning(text: str) -> str:
    """One point per line, the first (most important) in bold."""
    parts = [x for x in text.split("\n") if x.strip()]
    return "".join(f"<div class='mv-pt{' lead' if i == 0 else ''}'>{_md_inline(x)}</div>" for i, x in enumerate(parts))


def nifty_flow_fig(today: pd.DataFrame, crosses: list, height: int = 560):
    """Nifty candles with MACD-cross markers, money into / out of the Nifty 50 stocks per candle (colour = side,
    strength = size) with the running total, and the MACD panel."""
    from plotly.subplots import make_subplots
    x = today["t"]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.48, 0.3, 0.22], vertical_spacing=0.025,
                        specs=[[{}], [{"secondary_y": True}], [{}]])
    fig.add_trace(go.Candlestick(x=x, open=today["Open"], high=today["High"], low=today["Low"], close=today["Close"],
                                 increasing_line_color=UP, decreasing_line_color=DOWN, name="Nifty 50"), 1, 1)
    for c in crosses:
        up = c["dir"] > 0
        backed = (c["flow30"] > 0) if up else (c["flow30"] < 0)
        fig.add_trace(go.Scatter(x=[c["t"]], y=[c["price"]], mode="markers+text", showlegend=False,
                                 marker=dict(symbol="triangle-up" if up else "triangle-down", size=14,
                                             color=(UP if up else DOWN) if backed else "#94A3B8",
                                             line=dict(width=1, color="#0B1220")),
                                 text=["MACD ↑" if up else "MACD ↓"], textposition="bottom center" if up else "top center",
                                 textfont=dict(size=10), hovertemplate=f"{c['t']}: MACD {'up' if up else 'down'}, "
                                 f"flow 30 min ₹{c['flow30']:+,.0f} Cr" + (" (backed)" if backed else " (not backed)")
                                 + "<extra></extra>"), 1, 1)
    if "net" in today and today["net"].notna().any():
        net = today["net"].fillna(0)
        mx = max(float(net.abs().max()), 1e-9)
        cols = [f"rgba(38,166,154,{0.35 + 0.65 * abs(v) / mx:.2f})" if v >= 0 else
                f"rgba(239,83,80,{0.35 + 0.65 * abs(v) / mx:.2f})" for v in net]
        fig.add_trace(go.Bar(x=x, y=net, marker_color=cols, name="Money per candle ₹ Cr",
                             hovertemplate="%{x}: ₹%{y:+,.1f} Cr<extra></extra>"), 2, 1)
        fig.add_trace(go.Scatter(x=x, y=today["cum"], name="Running total ₹ Cr", line=dict(color=GOLD, width=2),
                                 hovertemplate="%{x}: total ₹%{y:+,.0f} Cr<extra></extra>"), 2, 1, secondary_y=True)
    fig.add_trace(go.Bar(x=x, y=today["hist"], marker_color=np.where(today["hist"] >= 0, UP, DOWN), opacity=0.55,
                         name="MACD histogram"), 3, 1)
    fig.add_trace(go.Scatter(x=x, y=today["macd"], line=dict(color="#3B82F6", width=1.4), name="MACD"), 3, 1)
    fig.add_trace(go.Scatter(x=x, y=today["signal"], line=dict(color="#E8B33A", width=1.2), name="Signal"), 3, 1)
    fig.update_layout(template=plot_template(), height=height, showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_rangeslider_visible=False, bargap=0.15)
    fig.update_xaxes(type="category", nticks=12)
    fig.update_yaxes(title_text="Money ₹ Cr", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Total", row=2, col=1, secondary_y=True, showgrid=False)
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    return fig


def money_rotation_fig(secflow: pd.DataFrame, height: int = 380):
    """Where the money moves: sectors losing money (red, left) to sectors receiving it (green, right)."""
    links = A.rotation_links(secflow) if secflow is not None and not secflow.empty else []
    if not links:
        return None
    srcs = list(dict.fromkeys(a for a, _, _ in links))
    dsts = list(dict.fromkeys(b for _, b, _ in links))
    net = secflow.set_index("Sector")["Net Flow Cr"].to_dict()
    labels = [f"{x}  ₹{net.get(x, 0):+,.0f} Cr" for x in srcs] + [f"{x}  ₹{net.get(x, 0):+,.0f} Cr" for x in dsts]
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, pad=14, thickness=16, line=dict(width=0),
                  color=["rgba(239,83,80,.85)"] * len(srcs) + ["rgba(38,166,154,.85)"] * len(dsts)),
        link=dict(source=[srcs.index(a) for a, _, _ in links], target=[len(srcs) + dsts.index(b) for _, b, _ in links],
                  value=[v for _, _, v in links], color="rgba(38,166,154,.22)",
                  hovertemplate="%{source.label} → %{target.label}: ₹%{value:,.0f} Cr<extra></extra>")))
    fig.update_layout(template=plot_template(), height=height, margin=dict(l=10, r=10, t=10, b=10),
                      font=dict(size=12))
    return fig


_CHAIN_COLS = ["Strike"] + [f"{s} {c}" for s in ("CE", "PE") for c in
                             ("LTP", "Prev", "OI", "Prev OI", "Volume", "IV", "Delta", "Theta", "Gamma", "Vega", "Bid", "Ask",
                              "Bid Qty", "Ask Qty", "ID", "Chg OI", "Chg")]
_CHAIN_BACK = {c.lower().replace(" ", "_"): c for c in _CHAIN_COLS}
_CHAIN_NAME = {13: "NIFTY", 25: "BANKNIFTY", 27: "FINNIFTY", 442: "MIDCPNIFTY", 51: "SENSEX"}


def _recorder_chain(sid: int, max_age_min: int = 5):
    """The recorder's latest saved chain for an index (nearest expiry, ±25 strikes, saved every minute), if fresh:
    no Dhan call (Dhan's chain API allows one call every 3 seconds, which made the Market View wait ~9 s)."""
    name = _CHAIN_NAME.get(int(sid))
    d = PATHS.DATA / "option_chain" / "parts" / datetime.now(IST).strftime("%Y-%m-%d")
    files = sorted(d.glob("*.parquet")) if name and d.exists() else []
    for f in reversed(files[-3:]):
        try:
            c = pd.read_parquet(f)
        except Exception:
            continue
        c = c[c["index"] == name]
        if c.empty:
            continue
        t = pd.Timestamp(c["time"].max())
        if datetime.now(IST).replace(tzinfo=None) - t.to_pydatetime() > pd.Timedelta(minutes=max_age_min):
            return None
        c = c[(c["time"] == c["time"].max())]
        c = c[c["expiry"] == c["expiry"].min()]
        spot = float(c["spot"].iloc[0])
        ch = c.rename(columns=_CHAIN_BACK)[[k for k in _CHAIN_COLS if k in c.rename(columns=_CHAIN_BACK)]]
        ch = ch.sort_values("Strike").reset_index(drop=True)
        return spot, ch, D.max_pain(ch)
    return None


def _mv_chain(sid: int, seg: str):
    """Nearest-expiry chain for the Market View: the recorder's saved chain when fresh, else Dhan (cached 2 min)."""
    try:
        r = _recorder_chain(sid)
        if r is not None and not r[1].empty:
            return r
    except Exception:
        pass
    return _mv_chain_api(sid, seg)


@st.cache_data(ttl=120, show_spinner=False)
def _mv_chain_api(sid: int, seg: str):
    """Nearest-expiry chain from Dhan, reused for 2 minutes."""
    exps = [e for e in oc_expiries(sid, seg) if str(e) >= datetime.now(IST).strftime("%Y-%m-%d")]
    if not exps:
        return 0.0, pd.DataFrame(), None
    spot, ch = D.option_chain(sid, seg, exps[0], DCFG)
    return spot, ch, D.max_pain(ch)


@st.cache_resource(show_spinner=False)
def _seen_store() -> dict:
    return {"day": None, "seen": {}}


def _first_seen(key: str, price=None) -> tuple[str, float | None]:
    """When a signal (e.g. 'PE focus: TCS') first showed today, and its price then: shared by every viewer and kept in
    <data>/signals_seen/<day>.json, so a restart keeps the times (scanners without their own signal time)."""
    import threading
    now = datetime.now(IST)
    day = now.strftime("%Y-%m-%d")
    stt = _seen_store()
    f = PATHS.DATA / "signals_seen" / f"{day}.json"
    if stt["day"] != day:
        try:
            stt["seen"] = json.loads(f.read_text())
        except Exception:
            stt["seen"] = {}
        stt["day"] = day
    if key not in stt["seen"]:
        t_ = now.strftime("%H:%M") if SS.market_hours() else None
        if not t_:
            return "", None
        stt["seen"][key] = [t_, float(price) if price is not None and np.isfinite(price) else None]
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(stt["seen"]))
            os.replace(tmp, f)
        except Exception:
            pass
    t_, p_ = stt["seen"][key]
    return t_, p_


def _mv_signals(plan_rows: list, ce: pd.DataFrame, pe: pd.DataFrame, sc, picks: pd.DataFrame,
                bot_rows: list | None = None) -> pd.DataFrame:
    """Every signal from every scanner in one table, the tested ones first, each with its time (signal time, or the
    first time it showed today)."""
    import re as _re
    rows = []
    order = {"fired": 0, "closed": 1, "wait": 2, "none": 3, "nodata": 4}
    status = {"fired": "● SIGNAL", "closed": "Done today", "wait": "Waiting", "none": "None today", "nodata": "No data"}
    for r in sorted(plan_rows, key=lambda r: order[r["state"]]):
        rows.append({"Signal": r["name"], "Status": status[r["state"]], "Evidence": "Tested",
                     "Details": r["text"].replace("**", ""), "_o": order[r["state"]]})
    for b in bot_rows or []:
        rows.append({**b, "_o": 4})
    if sc is not None:
        _, v3, _ = sc
        for _, r in (v3 if v3 is not None else pd.DataFrame()).head(5).iterrows():
            ent, stp = r.get("Entry"), r.get("Stop")
            rows.append({"Signal": f"Breakout V3: {r.get('Stock', '')} {r.get('Side', '')}", "Status": "● SIGNAL",
                         "Evidence": "Small edge", "Time": str(r.get("Signal") or ""),
                         "Details": f"signal {r.get('Signal', '')}"
                                    + (f" · entry {float(ent):,.2f}" if ent is not None and pd.notna(ent) else "")
                                    + (f" · stop {float(stp):,.2f}" if stp is not None and pd.notna(stp) else "")
                                    + " · top-2 mover, 15-min breakout with volume, exit 15:20", "_o": 5})
    for df, side in ((ce, "CE / long"), (pe, "PE / short")):
        for _, r in (df if df is not None else pd.DataFrame()).iterrows():
            t_, p_ = _first_seen(f"{side} focus: {r['Stock']}", r.get("Price"))
            rows.append({"Signal": f"{side} focus: {r['Stock']} ({r['Chg %']:+.2f}%)", "Status": "Confluence",
                         "Evidence": "Context", "Time": t_,
                         "Details": (f"first seen {t_}" + (f" @ {p_:,.2f}" if p_ else "") + " · " if t_ else "")
                                    + str(r.get("Why", "")), "_o": 6})
    for _, r in (picks if picks is not None else pd.DataFrame()).head(5).iterrows():
        t_, p_ = _first_seen(f"Smart-money pick: {r.get('Stock', '')} {r.get('Side', '')}", r.get("Price"))
        rows.append({"Signal": f"Smart-money pick: {r.get('Stock', '')} {r.get('Side', '')}", "Status": "Confluence",
                     "Evidence": "Context", "Time": t_,
                     "Details": (f"first seen {t_}" + (f" @ {p_:,.2f}" if p_ else "") + " · " if t_ else "")
                                + "Top R-factor stock moving with a favoured sector", "_o": 7})
    for r in rows:  # every row gets a Time: its own, or the first time in its text
        if not r.get("Time"):
            m = _re.search(r"\b(\d{1,2}:\d{2})\b", f"{r['Signal']} {r.get('Details', '')}")
            r["Time"] = m.group(1) if m else ""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("_o", kind="stable").drop(columns="_o")
    return df[["Time"] + [c for c in df.columns if c != "Time"]]


@st.fragment(run_every=LIVE_EVERY)
def market_view_body(svc, t: pd.DataFrame):
    st.markdown(MV_CSS, unsafe_allow_html=True)
    sf = sector_flow_table()
    box = apex_live(_dhan_sig())
    share = AP.dominance(box["bars"])[0] if box.get("bars") is not None else None
    with _timed("unusual activity"):
        act = _activity_data(svc)
    R = act[0] if act else pd.DataFrame()
    per = act[2] if act else {}
    flow = A.flow_window(per, None) if per else pd.DataFrame()
    if not flow.empty:
        flow["Sector"] = flow["Stock"].map(U.FNO_SECTOR_OF).fillna("Other")
        flow = flow[flow["Stock"].isin(set(U.FNO_SECTOR_OF))]
    secflow = A.sector_flow(flow) if not flow.empty else pd.DataFrame()
    idx_b, fut_b = svc.idx_bars(), svc.ifut_bars()
    og = opening_signals()
    sc = _scan_now(svc)
    rf, _ = smart_money_stocks(svc)
    picks = best_picks(rf, sf) if not rf.empty and not sf.empty else pd.DataFrame()
    vix_b = idx_b.get("INDIAVIX")
    trend = []
    for k in ("NIFTY", "BANKNIFTY"):
        spot = idx_b.get(k)
        if spot is not None and not spot.empty:
            trend.append((k, TA.evaluate(k, spot, fut_b.get(k), vix_b, None, TA.days_to_expiry(k, spot.index.max()))))

    snaps = {k: _idx_snapshot(idx_b.get(k)) for k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "INDIAVIX")}
    adv = int((t["Chg %"] > 0).sum()) if not t.empty and "Chg %" in t else None
    dec = int((t["Chg %"] < 0).sum()) if not t.empty and "Chg %" in t else None
    buy_share = (flow["Inflow Cr"].sum() / (flow["Inflow Cr"].sum() + flow["Outflow Cr"].sum()) * 100
                 if not flow.empty else None)
    fut_money = float(sf["Smart money (Rs cr)"].sum()) if not sf.empty else None
    n, vx = snaps.get("NIFTY") or {}, snaps.get("INDIAVIX") or {}
    verdict = DK.regime(share, adv, dec, buy_share, fut_money, vx.get("chg"), n.get("from_open"), n.get("atr"))
    sec_flag = sf.set_index("Sector")["Flow"].to_dict() if not sf.empty else {}
    ce, pe = DK.focus(R, flow, sc[0] if sc is not None else pd.DataFrame(), picks, sec_flag)
    plans = []
    for k, name in (("NIFTY", "Nifty"), ("BANKNIFTY", "Bank Nifty")):
        x = snaps.get(k)
        tr = dict(trend).get(k)
        if x:
            plans.append(DK.index_plan(name, x["last"], TA.STEP.get(k, 50), verdict, tr, share if k == "NIFTY" else None))
    _tl = time.time()
    try:  # the desk log (Supabase) keeps recording when people use this page instead of the Trading Desk
        _log_desk(snaps, verdict, plans, ce, pe)
        if datetime.now(IST).weekday() < 5:
            _log_paper(svc, idx_b, og, datetime.now(IST).replace(tzinfo=None))
    except Exception as e:
        DL.STATUS["error"] = f"market view log: {e}"[:200]
    st.session_state.setdefault("_perf", {})["desk log"] = time.time() - _tl
    with _timed("index plans"):
        plan_rows = _plan_rows(svc, idx_b, og, trend)

    # ---- readings with what they mean
    idx_reads = [MV.index_read(name, idx_b.get(k), fut_b.get(k)) for k, name in
                 (("NIFTY", "Nifty 50"), ("BANKNIFTY", "Bank Nifty"), ("FINNIFTY", "Fin Nifty"), ("SENSEX", "Sensex"))]
    chains, chain_px = [], []
    _tc = time.time()
    for k, sid in (("NIFTY", 13), ("BANKNIFTY", 25)):
        try:
            spot, ch, mp = _mv_chain(sid, "IDX_I")
            chains.append(MV.chain_read(TREND_NAMES.get(k, k), spot, ch, mp))
            chain_px.append((spot, mp))
        except Exception:
            chains.append(None)
            chain_px.append((None, None))
    st.session_state.setdefault("_perf", {})["option chains"] = time.time() - _tc
    market = [MV.vix_read(snaps.get("INDIAVIX")), MV.buildup_read(share), MV.breadth_read(adv, dec),
              MV.futures_money_read(sf)]
    money = [MV.flow_read(secflow), MV.activity_read(R)]
    every = [r for r in idx_reads + market + money + chains if r]

    bot_rows = []
    try:
        bs = _bots_state()
        if bs and not bs.get("stale"):
            for i in ((bs.get("bots") or {}).get("master") or {}).get("ideas") or []:
                ok = i["status"] == "passed"
                bot_rows.append({"Signal": f"Master bot: {i['side']} {i['stock']}", "Time": str(i.get("time") or ""),
                                 "Status": "● SIGNAL" if ok else "Good odds" if i["status"] == "odds" else "Watch",
                                 "Evidence": "Tested" if ok else "Past odds" if i["status"] == "odds" else "Context",
                                 "Details": f"since {i['time']} @ {float(i['price']):,.2f}"
                                 + (f", stop {float(i['stop']):,.2f}" if i.get("stop") else "")
                                 + f", checks {i['agree']} · {i['why']}"})
    except Exception:
        pass
    # index funnel (all five indices), the Bank Nifty failed-break fade, trend day / Gap & go, momentum bot (cached)
    with _timed("index bots"):
        _ib = _index_bots(svc)
    ix_rows, bn_fb, gaps = _ib["ix_rows"], _ib["bn_fb"], _ib["gaps"]
    for _k, (_dt, _gg) in gaps.items():
        g = (_gg or {}).get("signal")
        if g:
            g["live"] = _sig_live(_k, g["side"], g.get("plan"), g["time"], svc)
            pl = g.get("plan") or {}
            bot_rows.append({"Signal": f"Gap & go: {IF.INDEXES[_k]} {g['side']}", "Status": "● SIGNAL", "Evidence": "Small edge",
                             "Details": f"broke the first hour's {'high' if g['side'] == 'LONG' else 'low'} at {g['time']} @ "
                                        f"{g['price']:,.0f} with breadth {_gg['breadth']:.0f}% vs yesterday"
                                        + (f" · stop {pl['sl']:,.0f} · targets {pl['tp1']:,.0f} / {pl['tp2']:,.0f}" if pl else "")})
    moms = _ib["moms"]
    for _k, _mo in moms.items():
        for g in (_mo or {}).get("signals", []):
            g["live"] = _sig_live(_k, g["side"], g["plan"], g["time"], svc)
            pl = g["plan"]
            bot_rows.append({"Signal": f"Index momentum bot ({g.get('stage', 'CONFIRMED').lower()}): {IF.INDEXES[_k]} {g['side']}",
                             "Status": "● SIGNAL",
                             "Evidence": "Small edge",
                             "Details": f"{g['time']} @ {g['price']:,.0f} · stop {pl['sl']:,.0f} · targets {pl['tp1']:,.0f} / "
                                        f"{pl['tp2']:,.0f} · {g['why']}"})
    for r in ix_rows:
        if r.get("signal"):
            r["signal"]["live"] = _sig_live(r["key"], r["signal"]["side"], r["signal"].get("plan"), r["signal"]["time"], svc)
    if bn_fb and bn_fb.get("signal"):
        bn_fb["signal"]["live"] = _sig_live("BANKNIFTY", bn_fb["signal"]["side"], bn_fb["signal"].get("plan"), bn_fb["signal"]["time"], svc)
    ix_edge = {"NIFTY": "Small edge", "MIDCPNIFTY": "Small edge"}  # best in the first test (Nifty +0.25%, 61% wins)
    for r in ix_rows:
        if r.get("signal"):
            g = r["signal"]
            bot_rows.append({"Signal": f"Index funnel: {r['name']} {g['side']}", "Status": "● SIGNAL",
                             "Evidence": ix_edge.get(r["key"], "Context"),
                             "Details": f"all steps passed at {g['time']} @ {g['price']:,.0f} (ATR, range, index money, "
                                        "breadth) · exit 15:15" + (" · weak on Bank Nifty: prefer the failed-break fade"
                                                                   if r["key"] == "BANKNIFTY" else "")})
    if bn_fb and bn_fb.get("signal") and not any(r.get("name") == "Bank Nifty failed-break fade" for r in plan_rows):
        g = bn_fb["signal"]
        bot_rows.append({"Signal": f"Bank Nifty failed-break fade: {g['side']}", "Status": "● SIGNAL", "Evidence": "Small edge",
                         "Details": f"broke yesterday's {'high' if g['side'] == 'SHORT' else 'low'} {g['level']:,.0f} and closed "
                                    f"back inside at {g['time']} @ {g['price']:,.0f} · exit 15:15 · first test +67 pts, 61% wins"})
    # ---- 1. the trade idea (master-bot passed ideas count as tested signals)
    passed = [r for r in bot_rows if r["Status"] == "● SIGNAL" and r["Signal"].startswith("Master bot")]
    idea_rows = plan_rows + ([{"name": "Master bot (tested rule + balance agree)", "state": "fired", "where": "",
                               "text": "; ".join(r["Signal"].split(": ", 1)[1] + " (" + r["Details"].split(" · ")[0] + ")"
                                                 for r in passed)}] if passed else [])
    idea = MV.trade_idea(idea_rows, verdict, every)
    now = datetime.now(IST)
    sig = _mv_signals(plan_rows, ce, pe, sc, picks, bot_rows)
    st.markdown(MX.CSS, unsafe_allow_html=True)

    try:
        _nb = idx_b.get("NIFTY")
        asof = (pd.DatetimeIndex(_nb.index)[-1] + pd.Timedelta(minutes=5)).strftime("%H:%M") if _nb is not None and len(_nb) else "—"
    except Exception:
        asof = "—"
    st.markdown(f"<div class='mx-quiet' style='margin:-6px 0 6px'>Live data as of <b>{asof} IST</b> · refreshes every "
                "minute in market hours</div>", unsafe_allow_html=True)
    # ---- 1. pulse: the indices at a glance
    names = (("NIFTY", "Nifty 50"), ("BANKNIFTY", "Bank Nifty"), ("FINNIFTY", "Fin Nifty"), ("SENSEX", "Sensex"))
    read_of = {r["title"]: r for r in idx_reads if r}
    tiles = [MX.pulse_tile(nm, snaps.get(k), read_of.get(nm), idx_b.get(k)) for k, nm in names]
    tiles.append(MX.pulse_tile("India VIX", snaps.get("INDIAVIX"), None, None, invert=True))
    st.markdown(MX.pulse(tiles), unsafe_allow_html=True)

    # ---- 2. mood gauge + the trade idea
    bull = sum(1 for r in every if r["tone"] > 0)
    bear = sum(1 for r in every if r["tone"] < 0)
    st.markdown("<div class='mx-hero'>" + MX.gauge(verdict.get("score"), verdict.get("label", "Waiting for data"),
                                                   bull, bear, len(every) - bull - bear)
                + MX.idea_panel(idea, f"{now:%a %d %b %H:%M} IST", _md_inline) + "</div>", unsafe_allow_html=True)

    # ---- 3. signals as chips
    n_live = int((sig["Status"] == "● SIGNAL").sum()) if not sig.empty else 0
    st.markdown(MX.section("Signals", f"{n_live} live · as of {asof} · hover a card for details") + MX.signal_cards(sig),
                unsafe_allow_html=True)

    # ---- trend-day banners (measured from yesterday's close: catches gap days)
    for _k, (_dt, _gg) in gaps.items():
        if _dt and (_dt["trend_day"] or (_gg or {}).get("signal") or abs(_dt.get("gap_atr") or 0) >= 0.3):
            st.markdown(MX.trend_banner(IF.INDEXES[_k], _dt, _gg, _k), unsafe_allow_html=True)
    if any(moms.values()):
        st.markdown(MX.FUNNEL_CSS, unsafe_allow_html=True)
        st.markdown(MX.section("Index momentum bot", "price + money + breadth + ATR rising together · trap = price against "
                               "money and breadth · details on Bots"), unsafe_allow_html=True)
        st.markdown("<div class='wl'>" + "".join(MX.momentum_card(k, v) for k, v in moms.items() if v) + "</div>",
                    unsafe_allow_html=True)
    # ---- index setups: the funnel for each index + the Bank Nifty fade
    if ix_rows:
        fb_txt = ""
        if bn_fb:
            g = bn_fb.get("signal")
            pl = (g or {}).get("plan") or {}
            fb_txt = (f"Bank Nifty failed-break fade: <b>{g['side']}</b> at {g['time']} @ {g['price']:,.0f}"
                      + (f" · stop {pl['sl']:,.0f} · targets {pl['tp1']:,.0f} / {pl['tp2']:,.0f}" if pl else "")
                      + MX.live_html(g.get("live")) if g else
                      f"Bank Nifty failed-break fade: waiting (yesterday {bn_fb['pdl']:,.0f} – {bn_fb['pdh']:,.0f})")
        st.markdown(MX.FUNNEL_CSS, unsafe_allow_html=True)
        st.markdown(MX.DESK_CSS, unsafe_allow_html=True)
        st.markdown(MX.section("Index setups", "funnel steps per index · details on "
                    "Momentum Funnel → Indices") + "<div class='wl'>" + "".join(
                        MX.index_card(r, weak=r["key"] == "BANKNIFTY") for r in ix_rows) + "</div>"
                    + (f"<div class='mx-quiet' style='margin-top:8px;color:var(--om-text-3)'>{fb_txt}</div>" if fb_txt else ""),
                    unsafe_allow_html=True)

    # ---- sudden changes from the radar bot (server)
    try:
        bs2 = _bots_state()
        ev = (((bs2 or {}).get("bots") or {}).get("radar") or {}).get("events") or [] if bs2 and not bs2.get("stale") else []
        fp = ((bs2 or {}).get("funnel") or {}).get("top") or [] if bs2 and not bs2.get("stale") else []
        if fp:
            _tr = {t["symbol"]: t for t in _today_trades() if t.get("source") == "Momentum funnel"}
            for _f in fp:
                _t = _tr.get(_f["Stock"])
                _f["entry_time"] = _t["time"] if _t else _first_seen(f"Funnel pick: {_f['Stock']}", _f.get("price"))[0]
                if _t:
                    _f.update({k: _t[k] for k in ("entry", "sl", "tp1", "tp2", "risk_pct")})
                    _f["live"] = _sig_live(_f["Stock"], _t["side"], _plan_of(_t), _t["time"], svc) or _rec_live(_t)
            st.markdown(MX.FUNNEL_CSS, unsafe_allow_html=True)
            st.markdown(MX.section("Momentum Funnel picks", "all 5 steps · ranked by score · details on Momentum Funnel")
                        + MX.watch_cards(fp[:4], show_why=True), unsafe_allow_html=True)
        if ev:
            st.markdown(MX.section("Sudden changes", f"radar bot · updated {bs2.get('updated', '')[11:16]} · full list on Bots")
                        + MX.event_cards(ev, 6), unsafe_allow_html=True)
    except Exception:
        pass

    # ---- 4. market internals as meters
    rd = {r["title"]: r for r in every}
    tip = lambda t: (rd.get(t) or {}).get("meaning", "")  # noqa: E731
    parts = []
    if share is not None and not (isinstance(share, float) and np.isnan(share)):
        parts.append(MX.meter_split("Nifty build-up", share, 100 - share, "bulls adding", "bears adding",
                                    f"{share:.0f}% bullish", tip("Nifty build-up (who is adding positions)")))
    if adv is not None and dec is not None and adv + dec:
        parts.append(MX.meter_split("F&O breadth", adv, dec, f"{adv} up", f"{dec} down",
                                    f"{adv / (adv + dec) * 100:.0f}% up", tip("F&O breadth")))
    if buy_share is not None and np.isfinite(buy_share):
        parts.append(MX.meter_split("Money flow", buy_share, 100 - buy_share, "buying", "selling",
                                    f"{buy_share:.0f}% buying", "Turnover of F&O stocks split by where each candle closed"))
    if fut_money is not None:
        parts.append(MX.meter_diverging("Fresh futures money", fut_money, max(abs(fut_money), 2000),
                                        f"₹{fut_money:+,.0f} Cr", "shorts", "longs", tip("Fresh futures money")))
    vx_snap = snaps.get("INDIAVIX") or {}
    parts.append(MX.meter_level("India VIX", vx_snap.get("last"), vx_snap.get("chg"), 10, 25, tip("India VIX (fear)")))
    if not R.empty and "Smart" in R:
        nb, ns = int((R["Smart"] >= 40).sum()), int((R["Smart"] <= -40).sum())
        parts.append(MX.meter_split("Unusual activity", nb, ns, f"{nb} bullish", f"{ns} bearish",
                                    f"{nb} ▲ · {ns} ▼", tip("Unusual activity")))
    if parts:
        st.markdown(MX.section("Market internals", f"as of {asof} · green = buyers · red = sellers") + MX.meters(parts),
                    unsafe_allow_html=True)

    # ---- 5. where the money goes: sector heatmap, Nifty 50 flow candle by candle
    heat = MX.heatmap(secflow)
    if heat:
        st.markdown(MX.section("Sector money", f"as of {asof} · size = turnover · colour = net money in / out") + heat,
                    unsafe_allow_html=True)
        rot = money_rotation_fig(secflow, 300 if MOBILE else 340)
        if rot is not None:
            with st.expander("Money path: from which sectors to which", icon=":material/swap_horiz:"):
                st.plotly_chart(rot, width="stretch", key="mv_rotation", config={"displayModeBar": False})
    _tn = time.time()
    nf_today, nf_cross, nf_read = MV.flow_macd(idx_b.get("NIFTY"), MV.index_flow(per, (index_defs().get("NIFTY") or {})
                                                                                   .get("w", {})))
    if not nf_today.empty:
        lead = (nf_read or {}).get("meaning", "").split("\n")[0]
        st.markdown(MX.section("Nifty 50 money flow × MACD", (nf_read or {}).get("value", "")), unsafe_allow_html=True)
        if lead:
            st.markdown(f"<div class='mx-quiet' style='margin:-4px 0 4px;color:var(--om-text-3)'>{_md_inline(lead)}</div>",
                        unsafe_allow_html=True)
        st.plotly_chart(nifty_flow_fig(nf_today, nf_cross, 420 if MOBILE else 500), width="stretch",
                        key="mv_nifty_flow", config={"displayModeBar": False})

    st.session_state.setdefault("_perf", {})["nifty flow chart"] = time.time() - _tn
    # ---- 6. option chains
    ch_tiles = [MX.chain_tile(r, px_[0], px_[1]) for r, px_ in zip(chains, chain_px)]
    if any(ch_tiles):
        st.markdown(MX.section("Option writers", "◆ max pain · bar = spot between support and resistance")
                    + MX.chains(ch_tiles), unsafe_allow_html=True)

    # ---- the detail, folded away
    with st.expander("All signals as a table", icon=":material/table_rows:"):
        if not sig.empty:
            st.dataframe(sig, hide_index=True, width="stretch",
                         column_config={"Details": st.column_config.TextColumn(width="large")})
        st.caption("Tested = made money after costs in testing (trade these). Small edge = real but thin. "
                   "Context = not tested as a signal: use it to choose the side, not as an entry.")
    with st.expander("What each reading means", icon=":material/menu_book:"):
        st.markdown("<div class='mv-grid'>" + "".join(_mv_card(r) for r in every) + "</div>", unsafe_allow_html=True)
    st.caption("Refreshes every minute in market hours. For information only, not investment advice.")


def page_view():
    status_strip()
    st.header("Market View")
    if not DHAN_DATA:
        st.info("Connect Dhan for the Market View: it needs live index, futures, OI and stock data.",
                icon=":material/link:")
        return
    ft, _ = safe(fno_table)
    t = ft[0] if ft else pd.DataFrame()
    svc = get_scan_service("dhan", _dhan_sig(), SS.VERSION)
    idx = index_defs()
    svc.set_universe(tuple(sorted(set(scan_universe("All F&O stocks")) | {m for d in idx.values() for m in d["w"]})))
    svc.set_indices({**{k: d["id"] for k, d in idx.items()}, "INDIAVIX": 21})
    svc.touch()
    market_view_body(svc, t)


# ---------------------------------------------------------------- AI Desk: six agents over every market


@st.cache_data(ttl=900, show_spinner=False)
def _desk_live() -> dict:
    """The desk computed here when the server's agents.py has no fresh result (e.g. on Streamlit Cloud)."""
    import agents as AG
    daily, hourly = AG.load_data()
    if len(daily) < 10:
        raise RuntimeError("market data unavailable right now (Yahoo)")
    st_ = DA.run_desk(daily, hourly, AG.news, AG.fear_greed())
    return json.loads(json.dumps(st_, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def _desk_state() -> dict | None:
    try:
        s = json.loads((PATHS.DATA / "agents" / "state.json").read_text())
        if (datetime.now(IST) - datetime.fromisoformat(s["updated"])).total_seconds() < 3600 and "Indian indices" in json.dumps(s.get("breadth", {})):
            return s
    except Exception:
        pass
    try:
        with st.spinner("The desk is reading every market (about a minute the first time)…"):
            return _desk_live()
    except Exception as e:
        st.warning(f"AI Desk: {e}")
        return None


def page_agents():
    status_strip()
    st.header("AI Desk")
    for _c in (MX.CSS, MX.DESK_CSS):
        st.markdown(_c, unsafe_allow_html=True)
    s = _desk_state()
    if not s:
        return
    rows, a = s.get("rows", []), s.get("atlas", {})
    by = lambda call: [r for r in rows if r["nova"]["call"] == call]  # noqa: E731
    setups = [r for r in rows if r["status"] == "SETUP"]
    hi = [r for r in rows if r.get("orion") and r["orion"].get("high_impact")]
    hype = [r for r in rows if r["luna"]["hype"]]
    tit = [r for r in rows if r.get("titan")]
    rej = [r for r in tit if not r["titan"]["pass"]]
    fng = s.get("fng") or {}
    st.caption(f"Six agents read {len(rows)} markets: Indian indices and stocks first, then crypto, forex, commodities and the rupee. "
               f"Updated {s.get('updated', '')[11:16]} IST · paper calls only, not tested setups.")
    st.markdown(MX.agent_cards({
        "ATLAS": (a.get("regime", "—"), " · ".join(a.get("notes", [])[:3])),
        "VEGA": (f"{len(setups)} setups found", (setups[0]["name"] + ": " + setups[0]["setup"]) if setups else "No clean setup now."),
        "ORION": (f"{len(hi)} high-impact", (hi[0]["orion"]["high_impact"][0]["title"][:90]) if hi else "No high-impact catalyst on the setups."),
        "LUNA": (f"{len(hype)} crowded / hype", f"Crypto fear & greed {fng.get('value')} ({fng.get('label')})" if fng else "Crowd readings per market."),
        "TITAN": (f"{len(rej)} rejected · {len(tit) - len(rej)} passed", "Position size, max loss, correlation, exposure, R/R, volatility."),
        "NOVA": (f"{len(by('TRADE'))} TRADE", "All five reports, one decision. No consensus, no trade."),
    }) + MX.nova_counts(s.get("calls", {})), unsafe_allow_html=True)

    st.markdown(MX.section("NOVA: trade", "setup + market + news + crowd agree, and TITAN passed")
                + MX.decision_cards(by("TRADE")), unsafe_allow_html=True)
    c1, c2 = st.columns(2) if not MOBILE else (st.container(), st.container())
    with c1:
        st.markdown(MX.section("Wait: signals conflict") + MX.decision_cards(by("WAIT"), risk=False, limit=8),
                    unsafe_allow_html=True)
    with c2:
        st.markdown(MX.section("Rejected", "no trade is also a decision") + MX.decision_cards(by("REJECT"), limit=8),
                    unsafe_allow_html=True)

    st.markdown(MX.section("Every market", "VEGA's chart read with LUNA's crowd and NOVA's call"), unsafe_allow_html=True)
    tabs = st.tabs(list(DA.UNIVERSE))
    for tab, cls in zip(tabs, DA.UNIVERSE):
        with tab:
            xs = [r for r in rows if r["class"] == cls]
            br = (s.get("breadth") or {}).get(cls)
            st.caption(f"ATLAS bias for {cls.lower()}: {['bearish', 'neutral', 'bullish'][a.get('bias', {}).get(cls, 0) + 1]}"
                       + (f" · {br:.0f}% above their 50-day average" if br is not None else ""))
            if xs:
                st.dataframe(pd.DataFrame([{
                    "Market": r["name"], "Price": r["price"], "1d %": r["chg_1d"], "5d %": r["chg_5d"],
                    "20d %": r["chg_20d"], "Trend": {1: "▲ up", -1: "▼ down", 0: "sideways"}[r["trend"]],
                    "Last 60 days": r.get("spark") or [], "Setup": r["setup"] or "—",
                    "ATR ×avg": r["atr_x"], "Vol ×avg": r["vol_x"], "RSI": r["rsi"], "Support": r["support"],
                    "Resistance": r["resistance"], "Crowd": r["luna"]["label"], "NOVA": r["nova"]["call"],
                    "TradingView": MX.tv_url(r["symbol"])} for r in xs]),
                    hide_index=True, width="stretch", column_config={
                        "Price": st.column_config.NumberColumn(format="%.4g"),
                        "1d %": st.column_config.NumberColumn(format="%+.2f"), "5d %": st.column_config.NumberColumn(format="%+.2f"),
                        "20d %": st.column_config.NumberColumn(format="%+.2f"),
                        "Last 60 days": st.column_config.LineChartColumn(width="small"),
                        "ATR ×avg": st.column_config.NumberColumn(format="%.2f"), "Vol ×avg": st.column_config.NumberColumn(format="%.2f"),
                        "RSI": st.column_config.NumberColumn(format="%.0f"),
                        "Support": st.column_config.NumberColumn(format="%.4g"), "Resistance": st.column_config.NumberColumn(format="%.4g"),
                        "Setup": st.column_config.TextColumn(width="medium"), "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗")})
    news_rows = [(r, h) for r in rows if r.get("orion") for h in r["orion"].get("headlines", [])]
    if news_rows:
        with st.expander("ORION: headlines behind the setups", icon=":material/newspaper:"):
            for r, h in news_rows[:30]:
                tag = "🟢" if h["score"] > 0 else "🔴" if h["score"] < 0 else "⚪"
                st.markdown(f"{tag} **{r['name']}** · [{h['title']}]({h.get('url') or '#'})" + (" · ⚡ high impact" if h["impact"] else ""))

    rec = s.get("record") or {}
    st.markdown(MX.section("Paper record", "every TRADE call: target first = win, stop first = loss, 3 days = time-out"),
                unsafe_allow_html=True)
    if rec:
        st.markdown(MX.kpis([
            MX.kpi("Calls", f"{rec.get('calls', 0)}", f"{rec.get('open', 0)} open"),
            MX.kpi("Closed", f"{rec.get('closed', 0)}", "scored"),
            MX.kpi("Wins", f"{rec.get('wins', 0)}", f"{(rec['wins'] / rec['closed'] * 100):.0f}% of closed" if rec.get("closed") else "—", MX.UP),
            MX.kpi("Average", f"{rec['avg_r']:+.2f}R" if rec.get("avg_r") is not None else "—", "per closed call",
                   MX.tone_color(rec.get("avg_r") or 0)),
        ]), unsafe_allow_html=True)
        rc = s.get("recent_calls") or []
        if rc:
            px_now = {r["symbol"]: r["price"] for r in rows}
            def _rnow(c):
                p_ = px_now.get(c["symbol"])
                risk = abs(c["entry"] - c["stop"])
                return round(c["side"] * (p_ - c["entry"]) / risk, 2) if p_ and risk else None
            st.dataframe(pd.DataFrame([{"Time": c["time"][:16].replace("T", " "), "Market": c["name"],
                                        "Side": "LONG" if c["side"] > 0 else "SHORT", "Entry": c["entry"],
                                        "Now": px_now.get(c["symbol"]), "R now": None if c.get("result") else _rnow(c),
                                        "Stop": c["stop"], "Target": c["target"], "R/R": c["rr"],
                                        "Result": c.get("result") or "open", "R": c.get("r"),
                                        "TradingView": MX.tv_url(c["symbol"])} for c in rc]), hide_index=True, width="stretch",
                         column_config={"R now": st.column_config.NumberColumn(format="%+.2f"),
                                        "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗")})
    else:
        st.caption("The record starts with the first TRADE call on the server.")
    note("ATLAS: Nifty and Bank Nifty vs their 50-day average, India VIX level and 5-day change, the rupee (USD/INR) "
         "→ risk-on / mixed / risk-off for Indian indices and stocks; crypto follows Bitcoin's trend; the dollar index "
         "is context for commodities, forex and the rupee. VEGA: daily EMA 20/50/200 trend + hourly "
         "trend, 20-day breakout / breakdown with volume, pullback to the 20-day average, support / resistance from swing "
         "points, ATR and volume vs their averages. ORION: headline words (bullish / bearish, high-impact catalysts). "
         "LUNA: RSI extremes, 5-day move z-score, class breadth, crypto Fear & Greed; a crowded move counts against. "
         "TITAN: 1% risk of ₹10 lakh per trade, stop beyond support / resistance (0.75-2 ATR), all stops ≤ 4%, R/R ≥ 1.5, "
         "ATR ≤ 1.8x its average, correlation ≤ 0.75, max 6 trades / 2 per class. NOVA: TRADE needs a VEGA setup, 3 of "
         "4 agents agreeing, none against and TITAN passing.")


# ---------------------------------------------------------------- Momentum funnel: simple step-by-step watchlist


_OI_CHECKS = _memo("oi_checks")


def _oi_since_last(key: str, co: dict, fo: dict) -> dict | None:
    """OI change since the previous check of this index (kept for the day in server memory; a check every minute+)."""
    now = time.time()
    hist = _OI_CHECKS.setdefault(key, [])
    cur = {"t": now, "ce": co.get("ce_oi"), "pe": co.get("pe_oi"), "fut": fo.get("oi")}
    if hist and datetime.fromtimestamp(hist[-1]["t"], IST).date() != datetime.now(IST).date():
        hist.clear()
    prev = next((h for h in reversed(hist) if now - h["t"] >= 55), None)
    if not hist or now - hist[-1]["t"] >= 55:
        hist.append(cur)
        del hist[:-500]
    if not prev:
        return None
    d = lambda a, b: (a - b) if a is not None and b is not None else None  # noqa: E731
    return {"mins": (now - prev["t"]) / 60, "ce": d(cur["ce"], prev["ce"]), "pe": d(cur["pe"], prev["pe"]),
            "fut": d(cur["fut"], prev["fut"]), "checks": len(hist)}


def _money_fig(t: pd.DataFrame, name: str):
    from plotly.subplots import make_subplots
    x = t.index.strftime("%H:%M")
    per = t["net"].diff().fillna(t["net"])
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45], vertical_spacing=0.04,
                        specs=[[{}], [{"secondary_y": True}]])
    fig.add_trace(go.Candlestick(x=x, open=t["Open"], high=t["High"], low=t["Low"], close=t["Close"],
                                 increasing_line_color=UP, decreasing_line_color=DOWN, name=name), 1, 1)
    mx = max(float(per.abs().max()), 1e-9)
    fig.add_trace(go.Bar(x=x, y=per, name="Money per candle ₹ Cr", marker_color=[
        f"rgba(38,166,154,{0.35 + 0.65 * abs(v) / mx:.2f})" if v >= 0 else f"rgba(239,83,80,{0.35 + 0.65 * abs(v) / mx:.2f})"
        for v in per], hovertemplate="%{x}: ₹%{y:+,.1f} Cr<extra></extra>"), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=t["net"], name="Running total ₹ Cr", line=dict(color="#E8B33A", width=2),
                             hovertemplate="%{x}: ₹%{y:+,.0f} Cr<extra></extra>"), 2, 1, secondary_y=True)
    fig.update_layout(template=plot_template(), height=430, margin=dict(l=8, r=8, t=10, b=8), showlegend=False,
                      xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def _oi_strike_fig(near: pd.DataFrame, spot: float):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=near["Strike"], y=near["CE OI"], name="Call OI", marker_color="rgba(239,83,80,.75)"))
    fig.add_trace(go.Bar(x=near["Strike"], y=near["PE OI"], name="Put OI", marker_color="rgba(38,166,154,.75)"))
    fig.add_trace(go.Scatter(x=near["Strike"], y=near["CE Chg OI"], name="Call OI added today", mode="lines+markers",
                             line=dict(color="#F87171", dash="dot")))
    fig.add_trace(go.Scatter(x=near["Strike"], y=near["PE Chg OI"], name="Put OI added today", mode="lines+markers",
                             line=dict(color="#34D399", dash="dot")))
    fig.add_vline(x=spot, line_color="#3B82F6", line_dash="dash", annotation_text="spot")
    fig.update_layout(template=plot_template(), height=320, barmode="group", margin=dict(l=8, r=8, t=24, b=8),
                      legend=dict(orientation="h", y=1.12), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def _fut_oi_fig(per: pd.DataFrame):
    col = {"Long build-up": UP, "Short covering": "#5CC8FF", "Short build-up": DOWN, "Long unwinding": "#FF9F43", "": "#94A3B8"}
    fig = go.Figure()
    fig.add_trace(go.Bar(x=per["t"], y=per["d_oi"], marker_color=[col[b] for b in per["buildup"]], name="OI change",
                         customdata=per["buildup"], hovertemplate="%{x}: %{y:+,.0f} · %{customdata}<extra></extra>"))
    fig.add_trace(go.Scatter(x=per["t"], y=per["oi"], name="OI", yaxis="y2", line=dict(color="#E8B33A", width=2)))
    fig.update_layout(template=plot_template(), height=260, margin=dict(l=8, r=8, t=10, b=8), showlegend=False,
                      yaxis2=dict(overlaying="y", side="right", showgrid=False),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def _index_detail(key: str, sid: int, ib: dict, fb: dict, bars: dict, weights: dict):
    t = IF.index_table(ib.get(key), bars, weights.get(key, {}), ib.get("INDIAVIX"), today_only=True)
    if t.empty:
        st.caption("No candles yet today.")
        return
    r = t.iloc[-1]
    spot, side = float(r["Close"]), int(r["side"])
    fut = fb.get(key)
    fo = LV.futures_oi(fut) if fut is not None else {}
    try:
        cspot, ch, mp = _mv_chain(sid, "IDX_I")
    except Exception:
        cspot, ch, mp = 0.0, pd.DataFrame(), None
    co = LV.chain_oi(ch, cspot or spot, mp)
    since = _oi_since_last(key, co, fo)
    oi = LV.oi_step(side, fo, co)
    ftoday, fprev, fdays = LV.sessions(fut) if fut is not None else (pd.DataFrame(), pd.DataFrame(), [])
    vps = {}
    if not fprev.empty:
        vps["yesterday"] = LV.volume_profile(fprev)
    if fdays and len(fdays) >= 5:
        f5 = LV._clean(fut)
        vps["5 days"] = LV.volume_profile(f5[f5.index.normalize() >= fdays[-5]])
    _, iprev, _ = LV.sessions(ib.get(key))
    piv = LV.pivots(iprev)
    lad = LV.ladder(spot, piv, vps, co, side)
    steps = [bool(r[f"step{i}"]) for i in (1, 2, 3, 4)] + [oi["pass"]]
    allp = all(steps)
    verdict = (("LONG" if side > 0 else "SHORT") + " · all 5 steps pass") if allp else f"{sum(steps)}/5 steps"
    pl = lad.get("plan") or {}
    st.markdown(MX.kpis([
        MX.kpi("Setup", verdict, "ATR · range · index money · breadth · OI", (MX.UP if side > 0 else MX.DOWN) if allp else MX.NEUTRAL),
        MX.kpi("Index money", f"₹{r['net']:+,.0f} Cr" if r["net"] == r["net"] else "—",
               f"{r['buy_share']:.0f}% buying · 15 min ago ₹{r['net_before']:+,.0f} Cr" if r["buy_share"] == r["buy_share"] else "",
               MX.tone_color(r["net"] if r["net"] == r["net"] else 0)),
        MX.kpi("Futures OI", f"{fo['oi_chg_pct']:+.2f}%" if fo else "—",
               f"{fo.get('buildup_day', '')} · 15 min: {fo.get('buildup_15m', '') or 'flat'}" if fo else "no futures data",
               MX.ACCENT),
        MX.kpi("Option writers", f"PCR {co['pcr']:.2f}" if co else "—",
               (f"puts added {co['pe_chg_near'] / 1e5:,.1f}L · calls {co['ce_chg_near'] / 1e5:,.1f}L (near spot)" if co else "no chain"),
               MX.UP if co.get("writers", 0) > 0 else MX.DOWN if co.get("writers", 0) < 0 else MX.NEUTRAL),
        MX.kpi("OI since last check", (f"CE {since['ce'] / 1e5:+,.1f}L · PE {since['pe'] / 1e5:+,.1f}L" if since and since["ce"] is not None else "—"),
               (f"{since['mins']:.0f} min ago · futures {since['fut']:+,.0f}" if since and since.get("fut") is not None
                else f"{since['mins']:.0f} min ago" if since else "next check in a minute"), MX.WARN),
        MX.kpi("Plan (next levels)", (f"{pl['rr']:.1f}R" + ("" if pl["rr"] >= 1.5 else " · skip")) if pl.get("rr") else "—",
               (f"stop {pl['stop']:,.0f} ({pl['stop_at']}) · target {pl['target']:,.0f} ({pl['target_at']})"
                + ("" if pl["rr"] >= 1.5 else " · target too close for the risk")) if pl.get("rr") else "needs a move and levels",
               (MX.UP if pl["rr"] >= 1.5 else MX.WARN) if pl.get("rr") else MX.NEUTRAL),
    ]), unsafe_allow_html=True)
    st.caption("Step 5 · OI: " + oi["text"])
    if key == "BANKNIFTY":
        fbk = LV.failed_break(ib.get(key)) or {}
        sg = fbk.get("signal")
        pl = (sg or {}).get("plan") or {}
        msg = (f"**Failed-break fade: {sg['side']}** at {sg['time']} @ {sg['price']:,.0f}"
               + (f" · **stop {pl['sl']:,.0f} · target 1 {pl['tp1']:,.0f} · target 2 {pl['tp2']:,.0f}**" if pl else "")
               + " (broke yesterday's "
               f"{'high' if sg['side'] == 'SHORT' else 'low'} {sg['level']:,.0f} and closed back inside) · exit 15:15"
               if sg else f"Failed-break fade: no signal yet (yesterday high {fbk.get('pdh', 0):,.0f} / low "
               f"{fbk.get('pdl', 0):,.0f}; broke high: {'yes' if fbk.get('broke_high') else 'no'}, low: "
               f"{'yes' if fbk.get('broke_low') else 'no'})")
        (st.success if sg else st.info)(msg + ". The best Bank Nifty variant so far (first test: +0.12% ≈ 67 pts a trade, "
                                        "61% wins, both halves positive, 33 trades); the plain funnel is ~zero on Bank Nifty.",
                                        icon=":material/swap_vert:")
    c1, c2 = st.columns([1.7, 1]) if not MOBILE else (st.container(), st.container())
    with c1:
        st.plotly_chart(_money_fig(t, IF.INDEXES[key]), width="stretch", key=f"ixm_{key}", config={"displayModeBar": False})
        st.caption("Bottom: money into (green) / out of (red) the index's stocks per 5-minute candle, weighted by index "
                   "weight; gold line = running total.")
    with c2:
        st.markdown(MX.LADDER_CSS, unsafe_allow_html=True)
        st.markdown(MX.level_ladder(lad["levels"], spot, lad["support"], lad["resistance"]), unsafe_allow_html=True)
    c3, c4 = st.columns(2) if not MOBILE else (st.container(), st.container())
    with c3:
        if co.get("near") is not None and not co["near"].empty:
            st.markdown(MX.section("Option OI by strike", f"support {co['support'][:1]} · resistance {co['resistance'][:1]}"),
                        unsafe_allow_html=True)
            st.plotly_chart(_oi_strike_fig(co["near"], cspot or spot), width="stretch", key=f"ixo_{key}",
                            config={"displayModeBar": False})
    with c4:
        if fo.get("per") is not None:
            st.markdown(MX.section("Futures OI through the day", "bar colour = build-up"), unsafe_allow_html=True)
            st.plotly_chart(_fut_oi_fig(fo["per"]), width="stretch", key=f"ixf_{key}", config={"displayModeBar": False})


# ---------------------------------------------------------------- live state of running signals


def _today_bars(key: str, svc) -> pd.DataFrame:
    """Today's 5-minute bars for an index key or an F&O stock name (live, from the scan service)."""
    if svc is None:
        return pd.DataFrame()
    try:
        b = svc.idx_bars().get(key)
        if b is None:
            b = svc.bars()[0].get(key)
    except Exception:
        return pd.DataFrame()
    if b is None or b.empty:
        return pd.DataFrame()
    b = b[~b.index.duplicated(keep="last")].sort_index()
    return b[b.index.normalize() == b.index.normalize().max()]


def _sig_live(key: str, side, plan: dict | None, time_: str, svc) -> dict | None:
    """Live price, move since the signal, best / worst, stop now and the exit advice (funnel.manage)."""
    if not plan or not time_:
        return None
    b = _today_bars(key, svc)
    if b.empty:
        return None
    after = b[b.index.strftime("%H:%M") >= time_]
    s = side if isinstance(side, int) else (1 if str(side).upper() in ("LONG", "BUY") else -1)
    return FN.manage(s, float(plan["entry"]), float(plan["sl"]), float(plan["tp1"]), float(plan["tp2"]), after) or None


def _today_trades() -> list:
    try:
        return json.loads((PATHS.DATA / "bots" / "trades" / f"{datetime.now(IST):%Y-%m-%d}.json").read_text())
    except Exception:
        return []


def _rec_live(t: dict | None) -> dict | None:
    """Live block from a server trade record (updated every 5 minutes by the bots)."""
    if not t or t.get("ltp") is None:
        return None
    s = int(t["side"])
    return {"ltp": t["ltp"], "move_pts": s * (t["ltp"] - t["entry"]), "move_pct": s * (t["ltp"] / t["entry"] - 1) * 100,
            "r_now": t.get("r_now"), "best_r": t.get("best_r"), "worst_r": t.get("worst_r"), "stop_now": t.get("stop_now"),
            "advice": t.get("advice"), "as_of": t.get("as_of", ""), "exit_r": t.get("m_r")}


def _plan_of(t: dict) -> dict:
    return {k: t[k] for k in ("entry", "sl", "tp1", "tp2", "risk_pct")}


def _signal_record(source_filter: str | None = None):
    """Today's signals with entry / stop / targets and their result so far, and the record of all past days (the
    server's bots log every signal and score it at the close)."""
    d = PATHS.DATA / "bots" / "trades"
    files = sorted(d.glob("*.json")) if d.exists() else []
    allt = []
    for f in files[-60:]:
        try:
            allt += json.loads(f.read_text())
        except Exception:
            pass
    if source_filter:
        allt = [t for t in allt if source_filter in t.get("source", "")]
    st.markdown(MX.section("Signal record", "every signal with its plan, tracked live and scored at the close (server)"),
                unsafe_allow_html=True)
    if not allt:
        st.caption("The record starts with the first signal the server's bots log (market hours).")
        return
    df = pd.DataFrame(allt)
    today = datetime.now(IST).strftime("%Y-%m-%d")
    closed = df[df["status"] == "closed"] if "status" in df else df.iloc[0:0]
    st.markdown(MX.kpis([
        MX.kpi("Signals today", f"{int((df['day'] == today).sum())}", f"{int(((df['day'] == today) & (df.get('status') == 'open')).sum())} open"),
        MX.kpi("Closed (all days)", f"{len(closed)}", f"{df['day'].nunique()} days recorded"),
        MX.kpi("Win rate", f"{(closed['pct'] > 0).mean() * 100:.0f}%" if len(closed) else "—", "after 0.12% costs", MX.UP),
        MX.kpi("Average", f"{closed['r'].mean():+.2f}R" if len(closed) else "—",
               f"{closed['pct'].mean():+.2f}% a trade" if len(closed) else "", MX.tone_color(closed["r"].mean() if len(closed) else 0)),
    ]), unsafe_allow_html=True)
    if len(closed):
        g = closed.groupby("source").agg(Signals=("r", "size"), Win=("pct", lambda x: (x > 0).mean() * 100),
                                         AvgR=("r", "mean"), AvgPct=("pct", "mean")).reset_index()
        st.dataframe(g.rename(columns={"source": "Setup", "Win": "Win %", "AvgR": "Avg R", "AvgPct": "Avg %"}), hide_index=True,
                     width="stretch", column_config={"Win %": st.column_config.NumberColumn(format="%.0f"),
                                                     "Avg R": st.column_config.NumberColumn(format="%+.2f"),
                                                     "Avg %": st.column_config.NumberColumn(format="%+.2f")})
    tv = df.sort_values(["day", "time"], ascending=False).head(120)
    st.dataframe(pd.DataFrame({"Day": tv["day"], "Time": tv["time"], "Setup": tv["source"], "Symbol": tv["symbol"],
                               "Side": np.where(tv["side"] > 0, "LONG", "SHORT"), "Entry": tv["entry"], "Stop": tv["sl"],
                               "Target 1": tv["tp1"], "Target 2": tv["tp2"], "Status": tv.get("status"),
                               "LTP": tv.get("ltp"), "R now": tv.get("r_now"), "Best R": tv.get("best_r"),
                               "Advice": tv.get("advice"), "Managed exit": tv.get("m_exit"), "Managed R": tv.get("m_r"),
                               "Outcome (target/stop)": tv.get("outcome"), "R": tv.get("r"), "% after costs": tv.get("pct"),
                               "TradingView": tv["symbol"].map(MX.tv_url)}),
                 hide_index=True, width="stretch", height=360,
                 column_config={"R": st.column_config.NumberColumn(format="%+.2f"),
                                "R now": st.column_config.NumberColumn(format="%+.2f"),
                                "Best R": st.column_config.NumberColumn(format="%+.2f"),
                                "Managed R": st.column_config.NumberColumn(format="%+.2f"),
                                "Advice": st.column_config.TextColumn(width="large"),
                                "% after costs": st.column_config.NumberColumn(format="%+.2f"), "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗")})


def _noise_band_results():
    """Nightly noise-band research (noise_research.py on the server's year of 5-minute candles)."""
    try:
        nb = json.loads((PATHS.DATA / "bot" / "noise_band.json").read_text())
    except Exception:
        nb = None
    st.markdown(MX.section("Noise band (Zarattini et al. 2024)", "the paper's intraday momentum strategy on 5-min "
                           "candles, and the band as a filter on the momentum bot · re-run every night"), unsafe_allow_html=True)
    if not nb:
        st.caption("Runs on the server after 16:30 on the year of Dhan 5-minute candles; the first result appears after "
                   "tonight's run. Hourly 2023-26 test: Nifty +9% before realistic costs, about zero after.")
        return
    rows, frows = [], []
    for k, v in (nb.get("indices") or {}).items():
        g = pd.DataFrame(v.get("grid") or [])
        if not g.empty:
            for cost in (0.02, 0.04):
                gg = g[g["cost"] == cost].dropna(subset=["total_pct"])
                if gg.empty:
                    continue
                best = gg.sort_values("total_pct").iloc[-1]
                d14 = gg[(gg["lookback"] == 14) & (gg["band"] == 1.0)]
                rows.append({"Index": IF.INDEXES.get(k, k), "Cost": f"{cost:.2f}%", "Days": v.get("days"),
                             "Paper default (14 d, 1x) %": float(d14["total_pct"].iloc[0]) if len(d14) else None,
                             "Cells positive": f"{int((gg['total_pct'] > 0).sum())}/{len(gg)}",
                             "Best cell": f"{int(best['lookback'])} d × {best['band']}x", "Best %": best["total_pct"],
                             "Best Sharpe": best.get("sharpe")})
        f = v.get("filter") or {}
        if f.get("outside"):
            frows.append({"Index": IF.INDEXES.get(k, k), "Bursts": f["all"]["n"],
                          "Outside band: n": f["outside"]["n"], "Outside: % to close": f["outside"]["to_close"],
                          "Outside win %": f["outside"]["win"], "Inside band: n": f["inside"]["n"],
                          "Inside: % to close": f["inside"]["to_close"], "Inside win %": f["inside"]["win"]})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Paper default (14 d, 1x) %": st.column_config.NumberColumn(format="%+.2f"),
                                    "Best %": st.column_config.NumberColumn(format="%+.2f")})
    if frows:
        st.markdown("**As a filter on the momentum bot's bursts** (result to 15:15 after 0.04% cost)")
        st.dataframe(pd.DataFrame(frows), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%+.3f") for c in
                                    ("Outside: % to close", "Inside: % to close")})
    st.caption(f"{nb.get('source', '')} · run {nb.get('run_at', '')[:16]} · total % = sum of daily returns, unlevered.")


def index_funnel_body():
    svc = get_scan_service("dhan", _dhan_sig(), SS.VERSION)
    idx = index_defs()
    svc.set_universe(tuple(sorted(set(scan_universe("All F&O stocks")) | {m for d in idx.values() for m in d["w"]})))
    svc.set_indices({**{k: d["id"] for k, d in idx.items()}, "INDIAVIX": 21})
    svc.touch()
    bars, _ = svc.bars()
    ib = svc.idx_bars()
    w_all = {k: d.get("w", {}) for k, d in idx.items()}
    _ib = _index_bots(svc)
    rows = _ib["ix_rows"]
    if not rows:
        st.info("Loading index and constituent candles…", icon=":material/hourglass_top:")
        return
    st.markdown(MX.section("Index funnel now", "1 ATR active · 2 range expanding · 3 index money (its stocks, weighted) "
                           "with the move and growing · 4 breadth ≥ 60% of the weight with the move"), unsafe_allow_html=True)
    for r in rows:
        if r.get("signal"):
            r["signal"]["live"] = _sig_live(r["key"], r["signal"]["side"], r["signal"].get("plan"), r["signal"]["time"], svc)
    st.markdown("<div class='wl'>" + "".join(MX.index_card(r, weak=r["key"] == "BANKNIFTY") for r in rows) + "</div>",
                unsafe_allow_html=True)
    for k in ("NIFTY", "BANKNIFTY"):
        try:
            dt_, gg_ = _ib["gaps"].get(k, (None, None))
            if (gg_ or {}).get("signal"):
                gg_["signal"]["live"] = _sig_live(k, gg_["signal"]["side"], gg_["signal"].get("plan"), gg_["signal"]["time"], svc)
            st.markdown(MX.trend_banner(IF.INDEXES[k], dt_, gg_, k), unsafe_allow_html=True)
        except Exception:
            pass
    st.caption("Signal = the first 5-minute candle of the day (9:30-14:00) where all four steps pass; trade it in the "
               "move's direction (futures), exit at 15:15. India VIX is shown but not a step (it did not help in the test).")
    st.markdown(MX.section("Nifty & Bank Nifty: money, OI and levels", "OI checked every refresh · pivots, volume profile "
                           "and option OI in one ladder"), unsafe_allow_html=True)
    fb = svc.ifut_bars()
    w = {k: d.get("w", {}) for k, d in idx.items()}
    tn, tb = st.tabs(["Nifty 50", "Bank Nifty"])
    with tn:
        _index_detail("NIFTY", 13, ib, fb, bars, w)
    with tb:
        _index_detail("BANKNIFTY", 25, ib, fb, bars, w)
    try:
        bt = json.loads((PATHS.DATA / "bot" / "index_funnel.json").read_text())
    except Exception:
        bt = None
    st.markdown(MX.section("Backtest", (bt or {}).get("source", "first test: Yahoo, 52 days (11 Aug - 4 Nov 2026)")),
                unsafe_allow_html=True)
    if bt:
        st.dataframe(pd.DataFrame([{"Index": IF.INDEXES.get(k, k), "Days": v.get("days"),
                                    **{f"Step {i} %/trade": (v.get(f"step{i}") or {}).get("ret") for i in (1, 2, 3, 4)},
                                    "Signals": (v.get("step4") or {}).get("n"), "Win %": (v.get("step4") or {}).get("win"),
                                    "t": (v.get("step4") or {}).get("t")} for k, v in bt["indices"].items()]),
                     hide_index=True, width="stretch")
        st.caption("Each step's signals after 0.02% costs, held to 15:15. Step 3 (index money) adds the most.")
        if bt.get("banknifty"):
            st.markdown(MX.section("Bank Nifty variants", "the plain funnel is ~zero on Bank Nifty"), unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{"Variant": k, "Trades": v.get("n"), "%/trade": v.get("ret"), "≈ pts": v.get("pts"),
                                        "Win %": v.get("win"), "t": v.get("t"), "1st half %": v.get("first_half"),
                                        "2nd half %": v.get("second_half")} for k, v in bt["banknifty"].items()]),
                         hide_index=True, width="stretch")
    else:
        st.dataframe(pd.DataFrame([
            {"Index": "Nifty 50", "Signals": 28, "%/trade": 0.252, "Win %": 61, "t": 2.6, "1st half": 0.146, "2nd half": 0.358},
            {"Index": "Sensex", "Signals": 27, "%/trade": 0.08, "Win %": 52, "t": None, "1st half": None, "2nd half": None},
            {"Index": "Midcap Select", "Signals": 22, "%/trade": 0.197, "Win %": 59, "t": None, "1st half": None, "2nd half": None},
            {"Index": "Fin Nifty", "Signals": 26, "%/trade": 0.047, "Win %": 46, "t": None, "1st half": None, "2nd half": None},
            {"Index": "Bank Nifty", "Signals": 27, "%/trade": -0.002, "Win %": 46, "t": 0.0, "1st half": 0.082, "2nd half": -0.080},
        ]), hide_index=True, width="stretch")
        st.markdown(MX.section("Bank Nifty variants", "first test, Yahoo 52 days"), unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([
            {"Variant": "funnel (steps 1-4)", "Trades": 27, "%/trade": -0.002, "≈ pts": -1, "Win %": 48, "1st half %": 0.082, "2nd half %": -0.080},
            {"Variant": "funnel from 10:00", "Trades": 20, "%/trade": 0.029, "≈ pts": 16, "Win %": 50, "1st half %": 0.090, "2nd half %": -0.032},
            {"Variant": "Nifty 50 money as leader", "Trades": 28, "%/trade": 0.039, "≈ pts": 21, "Win %": 54, "1st half %": 0.080, "2nd half %": -0.002},
            {"Variant": "funnel + Nifty money", "Trades": 25, "%/trade": 0.046, "≈ pts": 26, "Win %": 52, "1st half %": 0.125, "2nd half %": -0.028},
            {"Variant": "failed break of yesterday's high/low, faded", "Trades": 33, "%/trade": 0.121, "≈ pts": 67, "Win %": 61, "1st half %": 0.109, "2nd half %": 0.133},
        ]), hide_index=True, width="stretch")
        st.caption("First test on 52 days of Yahoo data (steps 1-4, 0.02% costs, exit 15:15): all indices together "
                   "+0.11% a signal by day (t 1.5); ATR alone +0.03%, adding index money +0.12%. Promising, not proven: the "
                   "server re-runs it every night on a year of Dhan data and this table switches to that result.")
    _noise_band_results()
    _signal_record("Gap & go")
    _signal_record("Index funnel")
    _signal_record("Bank Nifty")


def page_funnel():
    status_strip()
    st.header("Momentum Funnel")
    for _c in (MX.CSS, MX.FUNNEL_CSS, MX.DESK_CSS):
        st.markdown(_c, unsafe_allow_html=True)
    if not DHAN_DATA:
        need_dhan()
        return
    view = st.segmented_control("Funnel", ["F&O stocks", "Indices"], default="F&O stocks", key="fn_view",
                                label_visibility="collapsed") or "F&O stocks"
    if view == "Indices":
        index_funnel_body()
        return
    with st.expander("Settings", icon=":material/tune:"):
        c1, c2, c3, c4 = st.columns(4)
        day_x = c1.slider("Step 1: ATR 9:15→now vs usual, at least", 1.0, 2.5, 1.2, 0.05, key="fn_day")
        now_x = c2.slider("Step 1: ATR last 15 min vs usual, at least", 0.5, 2.5, 1.0, 0.05, key="fn_now")
        rng_x = c3.slider("Step 2: range 9:15→now vs usual, at least", 1.0, 3.0, 1.2, 0.05, key="fn_rng")
        sec_rise = c4.toggle("Step 3: sector money must also be rising", False, key="fn_secrise")
    svc = get_scan_service("dhan", _dhan_sig(), SS.VERSION)
    idx = index_defs()
    svc.set_universe(tuple(sorted(set(scan_universe("All F&O stocks")) | {m for d in idx.values() for m in d["w"]})))
    svc.set_indices({**{k: d["id"] for k, d in idx.items()}, "INDIAVIX": 21})
    svc.touch()
    bars, _ = svc.bars()
    act = _activity_data(svc)
    if not bars or not act:
        st.info("Loading today's 5-minute candles for every F&O stock…", icon=":material/hourglass_top:")
        return
    t, sec = _funnel_now(svc, bars, act[2], {"day_x": day_x, "now_x": now_x, "range_x": rng_x, "sector_rising": sec_rise})
    if t.empty:
        st.info("Not enough candles yet: the funnel starts after the first few minutes.", icon=":material/hourglass_top:")
        return
    n1, n2, n3, n4, n5 = (int(t[f"step{i}"].sum()) for i in (1, 2, 3, 4, 5))
    sug = t[t["step5"]].sort_values("score", ascending=False).copy()
    _tr = {x["symbol"]: x for x in _today_trades() if x.get("source") == "Momentum funnel"}
    if len(sug):
        lives, cols, ets = [], {k: [] for k in ("entry", "sl", "tp1", "tp2", "risk_pct")}, []
        for _, r_ in sug.iterrows():
            _t = _tr.get(r_["Stock"])
            ets.append(_t["time"] if _t else _first_seen(f"Funnel pick: {r_['Stock']}", r_.get("price"))[0])
            for k in cols:
                cols[k].append(_t[k] if _t else r_[k])
            lives.append((_sig_live(r_["Stock"], _t["side"], _plan_of(_t), _t["time"], svc) or _rec_live(_t)) if _t else None)
        for k, v in cols.items():
            sug[k] = v
        sug["live"] = lives
        sug["entry_time"] = ets
    mk = float(t["mkt_move"].iloc[0])
    left, right = st.columns([1, 1.6]) if not MOBILE else (st.container(), st.container())
    with left:
        st.markdown(MX.funnel([
            ("F&O stocks", len(t), f"latest candle {t['time'].max()}"),
            ("Step 1 · ATR active", n1, f"day ≥ {day_x:.2f}× and last 15 min ≥ {now_x:.2f}× usual"),
            ("Step 2 · range expanding", n2, f"range 9:15→now ≥ {rng_x:.2f}× usual"),
            ("Step 3 · sector money", n3, "sector net money in the move's direction"),
            ("Step 4 · stock money", n4, "stock net money with the move and still growing"),
            ("Step 5 · with the market", n5, f"market {mk:+.2f}% from the open · no wide day yesterday"),
        ]), unsafe_allow_html=True)
    with right:
        st.markdown(MX.section("Watchlist: best to trade now", f"all 5 steps · ranked by score · "
                               f"{int((sug['side'] > 0).sum())} long · {int((sug['side'] < 0).sum())} short"),
                    unsafe_allow_html=True)
        st.markdown(MX.watch_cards(sug.to_dict("records"), show_why=True,
                                   empty="No stock passes all 5 steps right now."), unsafe_allow_html=True)
    wl = sug
    onw = t[t["step4"] & ~t["step5"]]
    if not onw.empty:
        with st.expander(f"On watch: {len(onw)} passed steps 1-4 but not step 5", icon=":material/visibility:"):
            st.caption("Moving against the market, or the day after a wide day: in the momentum study these lost.")
            st.markdown(MX.watch_cards(onw.to_dict("records"), show_why=True), unsafe_allow_html=True)
    if not wl.empty and st.button("Add these to Watchlist & Alerts", icon=":material/playlist_add:", key="fn_add"):
        syms = [U.fno_yahoo(s_) for s_ in wl["Stock"]]
        store["watchlist"] = list(dict.fromkeys(store.get("watchlist", []) + syms))
        save_store(store)
        st.success(f"Added {len(syms)} stocks to your watchlist.")

    st.markdown(MX.section("Sector money", "step 3 uses this: net money in (green) or out (red) of each sector"),
                unsafe_allow_html=True)
    hm = sec.rename(columns={"sec_net": "Net Flow Cr", "sec_in": "Inflow Cr", "sec_out": "Outflow Cr"})
    st.markdown(MX.heatmap(hm[["Sector", "Net Flow Cr", "Inflow Cr", "Outflow Cr"]]), unsafe_allow_html=True)

    st.markdown(MX.section("Every F&O stock, step by step", "✓ passed · ✗ failed"), unsafe_allow_html=True)
    show = st.segmented_control("Show", ["Passed step 1", "All"], default="Passed step 1", key="fn_show") or "Passed step 1"
    v = t if show == "All" else t[t["step1"]]
    ok = lambda b: "✓" if b else "✗"  # noqa: E731
    st.dataframe(pd.DataFrame({
        "Stock": v["Stock"], "Side": np.where(v["side"] > 0, "▲ long", np.where(v["side"] < 0, "▼ short", "—")),
        "Price": v["price"], "From open %": v["move_pct"], "Chg %": v["chg_pct"],
        "ATR 9:15→now ×usual": v["day_x"], "ATR last 15m ×usual": v["now_x"], "1 ATR": v["step1"].map(ok),
        "Range ×usual": v["range_x"], "2 Range": v["step2"].map(ok),
        "Sector": v["Sector"], "Sector net ₹Cr": v["sec_net"], "3 Sector": v["step3"].map(ok),
        "Stock net ₹Cr": v["net"], "Net 15m ago": v["net_before"], "Buying %": v.get("buy_share"),
        "4 Stock": v["step4"].map(ok), "With market": v["mkt_with"].map(ok), "Calm yesterday": v["calm_yday"].map(ok),
        "5 Market": v["step5"].map(ok), "Watchlist": v["Watch"],
        "Room to 20d ATR": v["room_atr"], "Score": v["score"], "Why": v["why"], "TradingView": v["Stock"].map(MX.tv_url)}),
        hide_index=True, width="stretch", height=520,
        column_config={"Price": st.column_config.NumberColumn(format="%.2f"),
                       "From open %": st.column_config.NumberColumn(format="%+.2f"),
                       "Chg %": st.column_config.NumberColumn(format="%+.2f"),
                       "ATR 9:15→now ×usual": st.column_config.NumberColumn(format="%.2f×"),
                       "ATR last 15m ×usual": st.column_config.NumberColumn(format="%.2f×"),
                       "Range ×usual": st.column_config.NumberColumn(format="%.2f×"),
                       "Room to 20d ATR": st.column_config.NumberColumn(format="%.1f"),
                       "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                       "Why": st.column_config.TextColumn(width="large"), "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗"),
                       "Sector net ₹Cr": st.column_config.NumberColumn(format="%+.0f"),
                       "Stock net ₹Cr": st.column_config.NumberColumn(format="%+.1f"),
                       "Net 15m ago": st.column_config.NumberColumn(format="%+.1f"),
                       "Buying %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%")})
    st.caption("Trade plan: entry at the signal price · stop just beyond the last 30 minutes' swing low (long) / high "
               "(short), 0.3-0.6 of the daily ATR · target 1 = 1R (half off, stop to entry), target 2 = 2R · exit 15:15. "
               "First backtest of the 5 steps with this plan (46 days, Yahoo, 0.12% costs): about break-even overall "
               "(+0.04% a trade, 51% wins); the day's first 3-5 signals +0.18% to +0.21%, but not in both halves of the "
               "period. Not proven yet: the live record below decides.")
    _signal_record("Momentum funnel")
    note("Step 1: average 5-minute true range from 9:15 to the latest candle vs the same window on the last 20 days, "
         "and the last 3 candles vs the same 15 minutes on those days. Side = up or down from today's open. Step 2: "
         "high-low from 9:15 to now vs the usual high-low of that window. Step 3: the sector's net money (turnover split "
         "by where each candle closed) is in the same direction. Step 4: the stock's net money is in that direction and "
         "beyond its value 15 minutes ago. Step 5: moving with the market (against it lost at every time in the momentum "
         "study) and not the day after a wide day (yesterday's range ≥ 1.25 ATR). Watchlist ranked by a score: ATR 20, range 15, last 15 min 10, money share 20, sector share "
         "10, with market 15, room to the 20-day high/low 5, quiet yesterday 5 (wide yesterday -10). The server stores "
         "a snapshot every 5 minutes for testing. A watchlist, not a tested signal yet.")


def _closing_history() -> list:
    d = PATHS.DATA / "closing"
    out = []
    for f in (sorted(d.glob("*.json")) if d.exists() else [])[-120:]:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return out


def page_closing():
    """Closing picks: buy (or sell) near the close for the next day, from what the last 15-30 minutes added."""
    status_strip()
    for _c in (MX.CSS, MX.FUNNEL_CSS, MX.DESK_CSS):
        st.markdown(_c, unsafe_allow_html=True)
    st.markdown(MX.section("Closing Picks", "buy near the close, exit next day · live read from 14:45, picks fixed with "
                           "the data up to 15:15 and recorded for testing"), unsafe_allow_html=True)
    s = _bots_state() or {}
    hist = _closing_history()
    today = datetime.now(IST).strftime("%Y-%m-%d")
    read = s.get("closing") if not s.get("stale") else None
    rec_today = next((h for h in hist if h.get("day") == today), None)
    cur = rec_today or read
    ltps = {}
    if cur and cur.get("day") == today:
        try:
            svc = get_scan_service("dhan", _dhan_sig(), SS.VERSION)
            for r in cur.get("indices", []) + cur.get("stocks", []):
                k = r.get("key") or r.get("symbol")
                b = _today_bars(k, svc)
                if not b.empty:
                    ltps[k] = float(b["Close"].iloc[-1])
        except Exception:
            pass
    if not cur:
        last = hist[-1] if hist else None
        st.info("The live read starts at 14:45 on market days and the picks are fixed at 15:15 (server bots)."
                + (f" Showing the last recorded picks ({last['day']})." if last else ""), icon=":material/schedule:")
        cur = last
    if cur:
        when = ("recorded at " + cur.get("time", "")) if cur.get("final") or cur is rec_today else f"live read as of {cur.get('time', '')} (fixed at 15:15)"
        st.caption(f"{cur.get('day')} · {when}")
        st.markdown(MX.section("Indices", "tested: a close in the top 20% of the day's range → higher next open "
                               "(Nifty 70%, Bank Nifty 69% of days over 10 years)"), unsafe_allow_html=True)
        st.markdown(MX.closing_cards(cur.get("indices", []), "index", ltps, "No index read yet."), unsafe_allow_html=True)
        stk = cur.get("stocks", [])
        st.markdown(MX.section("Stocks: late buying", "untested · biggest last-30-minute inflow, closing near the high, "
                               "sector money with it"), unsafe_allow_html=True)
        st.markdown(MX.closing_cards([r for r in stk if r.get("side", 0) > 0], "stock", ltps, "No stock with strong late buying."),
                    unsafe_allow_html=True)
        sells = [r for r in stk if r.get("side", 0) < 0]
        if sells:
            with st.expander(f"Stocks: late selling ({len(sells)}), for sell / avoid"):
                st.markdown(MX.closing_cards(sells, "stock", ltps), unsafe_allow_html=True)
    # ---- record
    st.markdown(MX.section("Closing record", "every pick with the next day's open and close (after costs: index 0.02%, "
                           "stocks 0.12%)"), unsafe_allow_html=True)
    rows = []
    for h in hist:
        for r in h.get("indices", []):
            rows.append({"Day": h["day"], "Kind": "Index", "Symbol": r.get("key"), "Verdict": r.get("verdict"),
                         "Side": int(r.get("side") or 0), "Tested": bool(r.get("tested")), "Price": r.get("price"),
                         "Next day": r.get("next_day"), "Open %": r.get("open_pct"), "Close %": r.get("close_pct"),
                         "Why": ", ".join(r.get("confirmations") or [])})
        for r in h.get("stocks", []):
            rows.append({"Day": h["day"], "Kind": "Stock", "Symbol": r.get("symbol"),
                         "Verdict": "BUY" if r.get("side", 0) > 0 else "SELL", "Side": int(r.get("side") or 0), "Tested": False,
                         "Price": r.get("price"), "Next day": r.get("next_day"), "Open %": r.get("open_pct"),
                         "Close %": r.get("close_pct"), "Why": r.get("why")})
    if not rows:
        st.caption("The record starts with the first 15:15 picks the server stores.")
    else:
        df = pd.DataFrame(rows)
        done = df[df["Open %"].notna()]

        def _k(x, title, sub):
            if x.empty:
                return MX.kpi(title, "—", sub)
            return MX.kpi(title, f"{x['Open %'].mean():+.2f}%", f"{len(x)} picks · {(x['Open %'] > 0).mean() * 100:.0f}% up at "
                          f"open · close {x['Close %'].mean():+.2f}%", MX.tone_color(x["Open %"].mean()))
        st.markdown(MX.kpis([
            _k(done[(done["Kind"] == "Index") & done["Tested"] & (done["Side"] > 0)], "Index BUY (tested)", "next open"),
            _k(done[(done["Kind"] == "Index") & (done["Side"] == 0)], "Index NO TRADE days", "as long, for comparison"),
            _k(done[(done["Kind"] == "Stock") & (done["Side"] > 0)], "Stock BUY", "untested"),
            _k(done[(done["Kind"] == "Stock") & (done["Side"] < 0)], "Stock SELL", "untested"),
        ]), unsafe_allow_html=True)
        df = df.sort_values(["Day", "Kind"], ascending=[False, True])
        df["TradingView"] = df["Symbol"].map(lambda x: MX.tv_url(x, "D"))
        st.dataframe(df.drop(columns=["Side"]), hide_index=True, width="stretch", height=380,
                     column_config={"Price": st.column_config.NumberColumn(format="%.2f"),
                                    "Open %": st.column_config.NumberColumn(format="%+.2f"),
                                    "Close %": st.column_config.NumberColumn(format="%+.2f"),
                                    "Why": st.column_config.TextColumn(width="large"),
                                    "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗")})
    st.caption("How to use: buy at 15:15-15:25 (index futures or a stock), exit at the next day's open or by the next "
               "close. The index rule has 10 years of daily evidence behind it (small edge: about +0.14-0.20% at the next "
               "open vs +0.10% on any day). Stock picks did not carry over in the first 58-day test, so they are recorded "
               "here to be tested on the live record before you trust them. Overnight positions carry gap risk.")


def _btc_paper_section():
    """BTC NY trend pullback (btc_sniper.py, run by the server's agents every minute 13:25-21:15 London), paper."""
    import btc_sniper as BS
    d_ = PATHS.DATA / "crypto_paper"
    try:
        stt = json.loads((d_ / "btc_state.json").read_text())
    except Exception:
        stt = {}
    try:
        rec = json.loads((d_ / "record.json").read_text())
    except Exception:
        rec = []
    _d = datetime.now(BS.LDN).replace(second=0, microsecond=0)
    _ist = lambda h, m: _d.replace(hour=h, minute=m).astimezone(IST).strftime("%H:%M")  # noqa: E731
    st.markdown(MX.section("BTC sniper · paper", f"NY-session trend pullback · 1 trade a day at most · checked every minute "
                           f"{_ist(13, 30)}-{_ist(18, 0)} IST (13:30-18:00 London) · research lead, not proven"),
                unsafe_allow_html=True)
    g = stt.get("signal")
    today = stt.get("day") == datetime.now(BS.LDN).strftime("%Y-%m-%d")
    if g and today:
        c = MX.UP if g["side"] > 0 else MX.DOWN
        r_ = stt.get("r") or 0
        body = (f"<b style='color:{c}'>{'BUY' if g['side'] > 0 else 'SELL'} BTC</b> at {g['entry']:,.2f} · ⏱ {g['entry_at_ist']} IST "
                f"({g['entry_at']} London) · stop {g['sl']:,.2f} ({g['stop_pct']:.2f}%) · target {g['tp']:,.2f} (3R) · exit by "
                f"{_ist(21, 0)} IST (21:00 London) if neither<br>Now {stt.get('price', 0):,.2f} · <b style='color:{MX.tone_color(r_)}'>{r_:+.2f}R</b> "
                f"({stt.get('pct', 0):+.2f}%) · {stt.get('state', '')}"
                + (f" at {stt['exit_at']} London" if stt.get("exit_at") else "") + f" · checked {stt.get('checked', '')[11:]} London")
    else:
        tr = {1: "1-hour trend up", -1: "1-hour trend down", 0: "no 1-hour trend"}.get(stt.get("trend"), "")
        body = (f"<b>{_md_inline(stt.get('state', 'starts at 13:25 London (18:55 IST) on the server'))}</b>"
                + (f" · BTC {stt['price']:,.2f} · VWAP {stt['vwap']:,.2f} · {tr} · as of {stt.get('as_of_ist', '')} IST"
                   if today and stt.get("price") else ""))
    st.markdown(f"<div class='mx-idea' style='--c:var(--om-accent);margin:6px 0'>{body}</div>", unsafe_allow_html=True)
    # Bank Nifty EBP 1h, held overnight (bots.py, every 5 minutes in market hours)
    try:
        bn = json.loads((PATHS.DATA / "bots" / "bn_ebp.json").read_text())
    except Exception:
        bn = {}
    st.markdown(MX.section("Bank Nifty EBP 1h · paper (held overnight)", "engulfing bar on 1-hour candles · limit at its "
                           "50% · stop at its wick · target the 20-hour swing · up to 2 days · tested +0.40R a trade, "
                           "worst -12.7R on a gap"), unsafe_allow_html=True)
    bt_ = bn.get("trades", [])
    live_ = [t_ for t_ in bt_ if t_.get("status") in ("waiting for the limit", "open")]
    if live_:
        for t_ in live_:
            c_ = MX.UP if t_["side"] > 0 else MX.DOWN
            if t_["status"] == "waiting for the limit":
                msg = (f"<b style='color:{c_}'>{'BUY' if t_['side'] > 0 else 'SELL'} LIMIT</b> {t_['limit']:,.2f} (EBP at "
                       f"{str(t_['signal_at'])[5:16]}) · stop {t_['sl']:,.2f} · target {t_['tp']:,.2f} · valid 3 hours")
            else:
                msg = (f"<b style='color:{c_}'>IN TRADE {'LONG' if t_['side'] > 0 else 'SHORT'}</b> from {t_['entry']:,.2f} at "
                       f"{str(t_['entry_at'])[5:16]} · stop {t_['sl']:,.2f} · target {t_['tp']:,.2f} · now {t_['last']:,.2f} · "
                       f"<b style='color:{MX.tone_color(t_['r'])}'>{t_['r']:+.2f}R ({t_['pts']:+,.0f} pts)</b>")
            st.markdown(f"<div class='mx-idea' style='--c:{c_};margin:6px 0'>{msg}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='mx-quiet'>No EBP setup open · checked {bn.get('updated', 'from the next market hour')}"
                    f"{' · last finished hour ' + str(bn['last_hour'])[5:16] if bn.get('last_hour') else ''}</div>",
                    unsafe_allow_html=True)
    # crash-candle buys (crash_buy.py, every minute, 24/7; gold weekdays)
    try:
        cs = json.loads((d_ / "crash_state.json").read_text())
    except Exception:
        cs = {}
    st.markdown(MX.section("Wild-move setups · paper", "crash buy (BTC, gold): buy after a sudden 5-min crash, fixed "
                           "target / stop, 4 h max · burst momentum (BTC, ETH, SOL): buy one candle after a giant up-candle, "
                           "stop at its low, 1 h hold · all tested 2023-26, positive in both halves · checked every minute"),
                unsafe_allow_html=True)
    for t_ in bn.get("trades", []):          # Bank Nifty EBP trades join the per-setup record
        if t_.get("status") in ("stop", "target", "time", "open"):
            rec.append({"day": str(t_["signal_at"])[:10], "setup": "Bank Nifty EBP 1h (overnight)", "side": t_["side"],
                        "entry_at_ist": str(t_.get("entry_at", ""))[5:16], "entry": t_.get("entry"), "sl": t_["sl"], "tp": t_["tp"],
                        "result": t_["status"], "exit_at": str(t_.get("exit_at") or "")[5:16], "r": t_["r"],
                        "pct": round(t_["pts"] / t_["entry"] * 100, 3) if t_.get("entry") else None})
    try:
        for x_ in json.loads((PATHS.DATA / "bots" / "v3_record.json").read_text()):
            rec.append({**x_, "setup": " ".join(x_["setup"].split(" ")[:-1]), "result": (
                "time" if str(x_.get("result", "")).startswith("Closed") else "stop" if str(x_.get("result", "")).startswith(("Stopped", "Trailed"))
                else "open")})
    except Exception:
        pass
    tested = {"V3 early pick": ("+0.59% a trade", "57%"), "V3 (top 2, filters)": ("-0.05% (54 days)", "48%"),
              "Bank Nifty EBP 1h (overnight)": ("+0.40R", "27%"), "BTC crash buy": ("+0.21R", "52%"), "Gold crash buy": ("+0.12R", "60%"), BS.NAME: ("+0.09R", "36%"),
              "BTC burst momentum": ("+0.15R (+0.21%)", ""), "ETH burst momentum": ("+0.13R (+0.36%)", ""),
              "SOL burst momentum": ("+0.24R (+0.61%)", "")}
    cards = []
    for key, v in cs.items():
        open_ = [x for x in rec if x["setup"].startswith(v.get("name", "?")) and x.get("result") == "open"]
        trig = v.get("trigger_pct")
        word = "rises" if "momentum" in v.get("name", "") else "falls"
        line = (f"buys if a 5-min candle {word} ≥ <b>{abs(trig):.2f}%</b> (now {v.get('price', 0):,.2f}, last candle "
                f"{(v.get('ret') or 0):+.2f}%)" if trig else "building the 20-day history")
        if v.get("pending"):
            line += " · <b>crash signal: buying at the next candle's open</b>"
        for t_ in open_:
            line += (f"<br><b style='color:{MX.UP}'>IN TRADE</b> bought {t_['entry']:,.2f} at {t_['entry_at_ist']} IST · stop "
                     f"{t_['sl']:,.2f} · " + (f"target {t_['tp']:,.2f}" if t_.get("tp") else "exit after 1 hour")
                     + f" · {t_['r']:+.2f}R")
        cards.append(f"<div class='mx-idea' style='--c:var(--om-accent);margin:6px 0'><b>{MX._e(v.get('name', key))}</b> · {line}"
                     f" · checked {pd.Timestamp(v['checked']).tz_localize('UTC').tz_convert(IST):%H:%M} IST</div>" if v.get("checked") else "</div>")
    st.markdown("".join(cards) or "<div class='mx-quiet'>Starts on the server within minutes.</div>", unsafe_allow_html=True)
    done = [x for x in rec if x.get("result") in ("stop", "target", "time")]
    if done:
        fam = lambda s_: next((k for k in tested if s_.startswith(k)), s_)  # noqa: E731
        g = pd.DataFrame(done).assign(Setup=lambda d: d["setup"].map(fam)).groupby("Setup")["r"].agg(
            Trades="size", Win=lambda r: (r > 0).mean() * 100, AvgR="mean", TotalR="sum").reset_index()
        g["Tested avg"] = g["Setup"].map(lambda k: tested.get(k, ("", ""))[0])
        g["Tested win"] = g["Setup"].map(lambda k: tested.get(k, ("", ""))[1])
        g["≈ ₹ at ₹1,000 a trade"] = g["TotalR"] * 1000
        st.dataframe(g.rename(columns={"Win": "Win %", "AvgR": "Avg R", "TotalR": "Total R"}), hide_index=True, width="stretch",
                     column_config={"Win %": st.column_config.NumberColumn(format="%.0f"),
                                    "Avg R": st.column_config.NumberColumn(format="%+.2f"),
                                    "Total R": st.column_config.NumberColumn(format="%+.1f"),
                                    "≈ ₹ at ₹1,000 a trade": st.column_config.NumberColumn(format="%+,.0f")})
    if rec:
        with st.expander(f"Crypto & gold paper record ({len(rec)} trades)", icon=":material/currency_bitcoin:"):
            st.dataframe(pd.DataFrame(rec[::-1]).reindex(columns=["day", "setup", "side", "entry_at_ist", "entry", "sl", "tp",
                                                                  "result", "exit_at", "r", "pct"]).rename(columns={
                "day": "Day", "setup": "Setup", "side": "Side", "entry_at_ist": "Entry (IST)", "entry": "Entry", "sl": "Stop",
                "tp": "Target", "result": "Result", "exit_at": "Exit", "r": "R", "pct": "% move"}),
                hide_index=True, width="stretch")


def page_auto():
    """Auto Trader (paper): six agents turn the bots' signals into sized paper trades (server: bots.py + autotrader.py)."""
    import autotrader as AT
    status_strip()
    for _c in (MX.CSS, MX.FUNNEL_CSS, MX.AUTO_CSS):
        st.markdown(_c, unsafe_allow_html=True)
    d_ = PATHS.DATA / "autotrader"
    try:
        acc = json.loads((d_ / "account.json").read_text())
    except Exception:
        acc = {"start": AT.RULES["capital"], "equity": AT.RULES["capital"], "history": []}
    files = sorted(d_.glob("20*.json")) if d_.exists() else []
    today = datetime.now(IST).strftime("%Y-%m-%d")
    book = None
    for f in reversed(files):
        try:
            book = json.loads(f.read_text())
            break
        except Exception:
            continue
    start_cap = float(acc.get("start", AT.RULES["capital"]))
    st.markdown(MX.section("Auto Trader · paper account", "six agents trade the bots' signals with fixed risk rules · "
                           "no real orders"), unsafe_allow_html=True)
    if not book:
        st.info("The paper account starts with the first signal in market hours (the server's bots run it every 5 minutes).",
                icon=":material/smart_toy:")
        book = {"funnel": {}, "pnl": 0.0, "equity": start_cap, "equity_start": start_cap, "decisions": {}, "day": today}
    day = book.get("day") or (files[-1].stem if files else today)
    is_today = day == today
    pnl, eq, eq0 = float(book.get("pnl") or 0), float(book.get("equity") or start_cap), float(book.get("equity_start") or start_cap)
    st.caption(("Today" if is_today else f"Last trading day {day}") + (f" · updated {book.get('updated')}" if book.get("updated") else ""))
    st.markdown(MX.agent_pipeline(book.get("funnel"), pnl, eq, eq0), unsafe_allow_html=True)
    hist = [h for h in acc.get("history", []) if h["day"] != day]
    total = eq - start_cap
    closed_days = hist + [{"day": day, "pnl": pnl, "equity": eq, **{k: (book.get("funnel") or {}).get(k, 0) for k in ("wins", "losses")}}]
    wins = sum(h.get("wins", 0) for h in closed_days)
    losses = sum(h.get("losses", 0) for h in closed_days)
    st.markdown(MX.kpis([
        MX.kpi("Account", f"₹{eq:,.0f}", f"started ₹{start_cap:,.0f}", MX.tone_color(total)),
        MX.kpi("Total P&L", f"₹{total:+,.0f}", f"{total / start_cap * 100:+.2f}% · {len(closed_days)} day{'s' if len(closed_days) != 1 else ''}", MX.tone_color(total)),
        MX.kpi("Today" if is_today else day, f"₹{pnl:+,.0f}", f"{pnl / eq0 * 100 if eq0 else 0:+.2f}%", MX.tone_color(pnl)),
        MX.kpi("Wins / losses", f"{wins} / {losses}", f"{wins / (wins + losses) * 100:.0f}% wins" if wins + losses else "—"),
    ]), unsafe_allow_html=True)
    decs = list((book.get("decisions") or {}).values())
    taken = sorted([x for x in decs if x.get("pos")], key=lambda x: x.get("time", ""), reverse=True)
    st.markdown(MX.section("Positions", f"{sum(1 for x in taken if not (x.get('mark') or {}).get('closed'))} open · "
                           f"{len(taken)} today · marked every 5 minutes"), unsafe_allow_html=True)
    st.markdown(MX.position_cards(taken), unsafe_allow_html=True)
    _btc_paper_section()
    # equity curve over the days
    if closed_days:
        import plotly.graph_objects as go
        xs = ["start"] + [h["day"] for h in closed_days]
        ys = [start_cap] + [h["equity"] for h in closed_days]
        fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers", line=dict(width=2.5, color="#22c55e" if total >= 0 else "#ef4444"),
                                   fill="tozeroy", fillcolor="rgba(34,197,94,.08)" if total >= 0 else "rgba(239,68,68,.08)",
                                   hovertemplate="%{x}<br>₹%{y:,.0f}<extra></extra>"))
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis=dict(range=[min(ys) * 0.995, max(ys) * 1.005], tickformat=",.0f", gridcolor="rgba(128,128,128,.15)"),
                          xaxis=dict(type="category", showgrid=False))
        st.markdown(MX.section("Equity curve", "account value at each day's close"), unsafe_allow_html=True)
        st.plotly_chart(fig, width="stretch", key="auto_equity", config={"displayModeBar": False})
    st.markdown(MX.section("Agent decisions", "every signal the bots gave today: traded or rejected, and why"),
                unsafe_allow_html=True)
    if decs:
        df = pd.DataFrame([{"Time": x.get("time"), "Setup": x["source"], "Symbol": x["symbol"],
                            "Side": "BUY" if x["side"] > 0 else "SELL", "Decision": "TRADE" if x.get("ok") else "REJECTED",
                            "Agent": x.get("stage"), "Why": x.get("why"), "Qty": (x.get("pos") or {}).get("qty"),
                            "Entry": x.get("entry"), "Stop": x.get("sl"), "R": (x.get("mark") or {}).get("r"),
                            "P&L ₹": (x.get("mark") or {}).get("pnl"),
                            "TradingView": MX.tv_url(str(x["symbol"]).split(" ")[0])} for x in decs]).sort_values("Time", ascending=False)
        st.dataframe(df, hide_index=True, width="stretch", height=360,
                     column_config={"Why": st.column_config.TextColumn(width="large"),
                                    "Entry": st.column_config.NumberColumn(format="%.2f"),
                                    "Stop": st.column_config.NumberColumn(format="%.2f"),
                                    "R": st.column_config.NumberColumn(format="%+.2f"),
                                    "P&L ₹": st.column_config.NumberColumn(format="%+.0f"),
                                    "TradingView": st.column_config.LinkColumn("TradingView", display_text="Open ↗")})
    else:
        st.caption("No signal yet today.")
    if hist:
        with st.expander(f"Daily record ({len(hist)} days)", icon=":material/calendar_month:"):
            st.dataframe(pd.DataFrame(hist[::-1]).rename(columns={"day": "Day", "pnl": "P&L ₹", "equity": "Account ₹", "trades": "Trades",
                                                                   "wins": "Wins", "losses": "Losses", "signals": "Signals"}),
                         hide_index=True, width="stretch")
    r_ = AT.RULES
    st.markdown(MX.section("Rules", "the risk manager's limits"), unsafe_allow_html=True)
    st.markdown(f"- Capital ₹{r_['capital']:,.0f} (paper) · risk **{r_['risk_pct']}%** of the account per trade (entry → stop × quantity)\n"
                f"- At most **{r_['max_open']}** positions open, one per symbol · no new trades after **{r_['last_entry']}** · "
                f"stop for the day at **-{r_['max_day_loss_pct']}%**\n"
                f"- Trades only: {', '.join(AT.TRADE_SOURCES)} · stop {r_['min_stop_pct']}-{r_['max_stop_pct']}% away · "
                f"reward:risk ≥ 1.5\n- Exits: half at target 1 then stop to entry and trail, target 2, stop, momentum slowing "
                f"before target 1, 15:15 · costs {r_['cost_index_pct']}% index / {r_['cost_stock_pct']}% stocks per round trip")
    st.caption("Paper trading only: no orders are sent to Dhan. Index quantities are in index units (points × quantity), "
               "not lots. Judge it after a few weeks, not a day.")


PAGE_DEFS = [  # (url, function, menu title, icon)
    ("view", page_view, "Market View", ":material/dashboard_customize:"),
    ("funnel", page_funnel, "Momentum Funnel", ":material/filter_alt:"),
    ("agents", page_agents, "AI Desk", ":material/groups:"),
    ("closing", page_closing, "Closing Picks", ":material/nightlight:"),
    ("auto", page_auto, "Auto Trader", ":material/robot_2:"),
    ("bot", page_bot, "Bots", ":material/smart_toy:"),
    ("dashboard", page_dashboard, "Trading Desk", ":material/space_dashboard:"),
    ("apex", page_apex, "Index Build-up", ":material/bar_chart:"),
    ("smart", page_smart_money, "Smart Money Sectors", ":material/insights:"),
    ("scanners", page_scanners, "Signals & Scanners", ":material/radar:"),
    ("options", page_option_chain, "Option Chain", ":material/table_chart:"),
    ("odds", page_odds, "Trade Odds", ":material/casino:"),
    ("fno", page_fno, "F&O Stocks", ":material/candlestick_chart:"),
    ("oi", page_oi, "OI Analysis", ":material/stacked_bar_chart:"),
    ("sectors", page_sectors, "Sectors", ":material/donut_small:"),
    ("indices", page_indices, "NSE Indices", ":material/account_balance:"),
    ("global", page_global, "Global Markets", ":material/public:"),
    ("mcx", page_mcx, "MCX Commodities", ":material/diamond:"),
    ("cdsfut", page_cdsfut, "Currency Futures", ":material/payments:"),
    ("portfolio", page_portfolio, "Portfolio", ":material/account_balance_wallet:"),
    ("dhan", page_dhan, "Dhan Connect", ":material/link:"),
    ("chart", page_details, "Chart & Details", ":material/show_chart:"),
    ("screener", page_screener, "Screener", ":material/filter_alt:"),
    ("watchlist", page_watchlist, "Watchlist & Alerts", ":material/notifications:"),
    ("account", page_account, "Account", ":material/manage_accounts:"),
    ("research", page_research, "Research notes", ":material/lock:"),
    ("review", page_desk_review, "Desk review", ":material/fact_check:"),
]
# Start page: Market View, or set NAVV_START_PAGE (e.g. fno, crypto) to open somewhere else.
_start = os.environ.get("NAVV_START_PAGE", "view")
if _start not in {d[0] for d in PAGE_DEFS}:
    _start = "view"
P = {u: st.Page(f, title=t, icon=i, url_path=u, default=(u == _start)) for u, f, t, i in PAGE_DEFS}
nav = st.navigation({  # grouped by what you are doing: today's trading, the market, tools, your account
    "Today": [P["view"], P["auto"], P["funnel"], P["closing"], P["agents"], P["dashboard"], P["scanners"], P["bot"], P["options"]],
    "Markets": [P["indices"], P["sectors"], P["smart"], P["apex"], P["fno"], P["oi"], P["global"], P["mcx"], P["cdsfut"]],
    "Tools": [P["chart"], P["screener"], P["watchlist"], P["odds"]],
    "Account": [P["account"]] + ([P["portfolio"], P["dhan"], P["review"], P["research"]] if IS_ADMIN else []),
}, position="top")

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
                     help="Live prices stream tick by tick on their own; this refreshes the rest of the page. "
                          "Pages with only Indian market data pause outside market hours.")
    # Each refresh reruns the whole page (every table and indicator), so refreshing faster than every 30 s made the
    # app feel slow and jumpy, and a slow page could be reloaded again before it had finished. Live prices are
    # unaffected: they stream on their own.
    _every_opts = [30, 60, 120, 300, 600]
    if st.session_state.get("every") not in _every_opts:
        st.session_state.pop("every", None)  # a value from an older version (5-15 s) is no longer offered
    every = st.select_slider("Refresh every", options=_every_opts, value=300 if PUBLIC else 120,
                             format_func=lambda s: f"{s}s" if s < 60 else f"{s // 60} min", key="every",
                             disabled=not auto)
    if st.button("Refresh now", width="stretch"):
        YAHOO_STATE["down_until"] = 0.0  # an explicit refresh tries Yahoo and Dhan again straight away
        _dhan_down()["until"] = 0.0
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

_BOOT.empty()
st.session_state["_booted"] = True
if DHAN_DATA and PUBLIC and os.environ.get("OMNIPULS_RECORDER") != "1":  # Docker: recorder.py records instead
    try:
        _chain_recorder()
    except Exception:
        pass
if DHAN_DATA:  # start loading scanner data in the background so the Scanners page is ready when opened
    try:
        get_scan_service("dhan", _dhan_sig(), SS.VERSION).set_universe(scan_universe(
            st.session_state.get("scan_uni", "All F&O stocks")))
    except Exception:
        pass
SELF_REFRESH = {"view", "dashboard", "scanners", "smart", "apex"}  # these refresh their own sections; a full rerun only reloads
NO_REFRESH = {"account", "dhan", "research", "review"}  # forms and notes: a rerun only interrupts typing
INDIAN_ONLY = {"fno", "oi", "sectors", "indices", "options", "odds", "portfolio"}  # nothing changes after the close
_page = getattr(nav, "url_path", "")
if (auto and _page not in SELF_REFRESH | NO_REFRESH
        and not (_page in INDIAN_ONLY and not SS.market_hours())):
    @st.fragment(run_every=every)
    def _tick():
        # timed from when the last full run finished, so a slow page can't be refreshed again the moment it loads
        if time.time() - st.session_state.get("_last_full", time.time()) >= every - 1:
            st.rerun(scope="app")
    _tick()

_t_run = time.time()
st.session_state["_perf"] = {}
nav.run()
st.session_state["_last_full"] = time.time()
try:  # how long each page takes on the server (Supabase app_perf), at most one row a minute per page and viewer
    _secs = time.time() - _t_run
    _pk = f"_perf_at_{_page}"
    if CS.enabled() and time.time() - st.session_state.get(_pk, 0) >= 60:
        st.session_state[_pk] = time.time()
        _row = {"page": _page or "home", "secs": round(_secs, 2), "market": bool(SS.market_hours()),
                "sections": {k: round(v, 2) for k, v in (st.session_state.get("_perf") or {}).items()}}
        CS.upsert_rows("app_perf", [_row], "id")
except Exception:
    pass
if _NOTES:  # every method / research text of this page, out of the way until asked for
    with st.expander("How it works: method and research", icon=":material/info:"):
        for kind, args, kw in _NOTES:
            (st.caption if kind == "caption" else st.markdown)(*args, **kw)
        st.caption("Full rules of every setup: research/FINAL_SETUPS.md in the repository.")

if DSTAT.get("error"):
    sb_status.caption(f":orange[{DSTAT['error'][:160]}]")
elif _twelve_key() and time.time() < YAHOO_STATE["down_until"]:
    _tw = TW.usage()
    sb_status.caption(f"Yahoo not answering: global prices from Twelve Data ({_tw['loaded']} of {_tw['active']} "
                      f"loaded, {_tw['used']}/{_tw['limit']} credits today"
                      + (", paused until the daily reset at 05:30 IST" if _tw["paused"] else "") + ").")
