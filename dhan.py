"""DhanHQ v2 API client for Omnipuls.

Covers: profile/token, market quotes (LTP, OHLC, depth, OI, circuits), daily and
intraday history, option chain with greeks, holdings, positions, funds, orders,
trades, and instrument lists (indices, NSE equities, F&O futures, MCX, currency).

Credentials come from environment variables DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN,
or from dhan_config.json next to this file (written by the app's Dhan page).
Nothing here places, changes or cancels orders.
"""
from __future__ import annotations

import io
import json
import os
import pickle
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

try:  # check HTTPS certificates against the operating system's store (needed behind antivirus/proxy inspection)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

BASE = "https://api.dhan.co/v2"
MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
HERE = Path(__file__).resolve().parent
CONFIG = HERE / "dhan_config.json"
CACHE = HERE / "dhan_cache"
IST = timezone(timedelta(hours=5, minutes=30))

# Seconds between calls per API family (Dhan limits: quote 1/s, data 5/s, option chain 1 per 3 s)
GAP = {"quote": 1.05, "data": 0.22, "oc": 3.1, "other": 0.06}
_last: dict[str, float] = {}
_locks = {k: threading.Lock() for k in GAP}

# Dhan index security IDs that are stable and documented; others are looked up by name.
KNOWN_INDEX_IDS = {"Nifty 50": 13, "Nifty Bank": 25, "Nifty Fin Service": 27, "Nifty Financial Services": 27,
                   "Nifty Midcap Select": 442, "Sensex": 51, "India VIX": 21}

INDEX_ALIASES = {
    "Nifty 50": ["NIFTY", "NIFTY50"],
    "Nifty Bank": ["BANKNIFTY", "NIFTYBANK"],
    "Sensex": ["SENSEX"],
    "Nifty Fin Service": ["FINNIFTY", "NIFTYFINSERVICE", "NIFTYFINANCIALSERVICES"],
    "Nifty Financial Services": ["FINNIFTY", "NIFTYFINSERVICE", "NIFTYFINANCIALSERVICES"],
    "Nifty Midcap Select": ["MIDCPNIFTY", "NIFTYMIDSELECT", "NIFTYMIDCAPSELECT"],
    "Nifty Midcap 100": ["NIFTYMIDCAP100", "NIFTYMIDCAP"],
    "Nifty Next 50": ["NIFTYNEXT50", "NIFTYNXT50", "NIFTYJR"],
    "Nifty Midcap 50": ["NIFTYMIDCAP50"],
    "Nifty Smallcap 100": ["NIFTYSMALLCAP100", "NIFTYSMLCAP100"],
    "Nifty 100": ["NIFTY100"], "Nifty 200": ["NIFTY200"], "Nifty 500": ["NIFTY500"],
    "India VIX": ["INDIAVIX"],
    "Nifty IT": ["NIFTYIT"], "Nifty Auto": ["NIFTYAUTO"], "Nifty Pharma": ["NIFTYPHARMA"],
    "Nifty Healthcare": ["NIFTYHEALTHCARE", "NIFTYHEALTHCAREINDEX"], "Nifty FMCG": ["NIFTYFMCG"],
    "Nifty Metal": ["NIFTYMETAL"], "Nifty Realty": ["NIFTYREALTY"], "Nifty Energy": ["NIFTYENERGY"],
    "Nifty Oil & Gas": ["NIFTYOILGAS", "NIFTYOILANDGAS"], "Nifty Media": ["NIFTYMEDIA"],
    "Nifty PSU Bank": ["NIFTYPSUBANK"], "Nifty Private Bank": ["NIFTYPVTBANK", "NIFTYPRIVATEBANK"],
    "Nifty Infrastructure": ["NIFTYINFRA", "NIFTYINFRASTRUCTURE"],
    "Nifty Consumer Durables": ["NIFTYCONSRDURBL", "NIFTYCONSUMERDURABLES"],
    "Nifty Consumption": ["NIFTYCONSUMPTION", "NIFTYINDIACONSUMPTION"],
    "Nifty Commodities": ["NIFTYCOMMODITIES"], "Nifty PSE": ["NIFTYPSE"], "Nifty CPSE": ["NIFTYCPSE"],
    "Nifty MNC": ["NIFTYMNC"], "Nifty Services": ["NIFTYSERVSECTOR", "NIFTYSERVICESSECTOR"],
    "Nifty Capital Markets": ["NIFTYCAPITALMARKETS", "NIFTYCAPITALMKT"],
    "Nifty India Defence": ["NIFTYINDIADEFENCE", "NIFTYINDDEFENCE"],
    "Nifty Chemicals": ["NIFTYCHEMICALS"],
}

MCX_ITEMS = {"GOLD": "Gold", "GOLDM": "Gold Mini", "SILVER": "Silver", "SILVERM": "Silver Mini",
             "CRUDEOIL": "Crude Oil", "CRUDEOILM": "Crude Oil Mini", "NATURALGAS": "Natural Gas",
             "NATGASMINI": "Natural Gas Mini", "COPPER": "Copper", "ZINC": "Zinc", "ALUMINIUM": "Aluminium",
             "LEAD": "Lead"}
CDS_ITEMS = {"USDINR": "USD/INR", "EURINR": "EUR/INR", "GBPINR": "GBP/INR", "JPYINR": "JPY/INR",
             "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY"}


class DhanError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message

    @property
    def friendly(self) -> str:
        c = self.code
        if c in ("DH-901", "401", "807"):
            return "Your Dhan access token is invalid or expired. Generate a new one on web.dhan.co and paste it in **Dhan Connect**."
        if c in ("DH-902", "806"):
            return "Dhan Data APIs are not active on your account. Subscribe under My Profile → Access DhanHQ APIs on web.dhan.co."
        if c in ("DH-904", "805", "429"):
            return "Dhan rate limit reached. The app slows down automatically; set a longer refresh if this repeats."
        return self.message or c

# ---------------------------------------------------------------- config


SECRET_KEYS = ("client_id", "access_token", "pin", "totp_secret")
NEVER_SAVED = ("pin", "totp_secret")  # kept only in Secrets / environment, never written to dhan_config.json


def secrets_config() -> dict:
    """[dhan] client_id / access_token (or pin + totp_secret for automatic tokens) from Streamlit secrets."""
    try:
        import streamlit as st
        sec = st.secrets.get("dhan")
        return {k: str(v) for k, v in dict(sec or {}).items() if k in SECRET_KEYS and v}
    except Exception:
        return {}


def load_config() -> dict:
    """Secrets first, then a token pasted in the app (dhan_config.json), then environment variables."""
    cfg = dict(secrets_config())
    cfg["_secret_token"] = cfg.get("access_token", "")
    try:
        cfg.update(json.loads(CONFIG.read_text()))
    except Exception:
        pass
    if os.environ.get("DHAN_CLIENT_ID"):
        cfg["client_id"] = os.environ["DHAN_CLIENT_ID"]
    if os.environ.get("DHAN_ACCESS_TOKEN"):
        cfg["access_token"] = os.environ["DHAN_ACCESS_TOKEN"]
    for key, env in (("pin", "DHAN_PIN"), ("totp_secret", "DHAN_TOTP_SECRET")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def save_config(cfg: dict):
    CONFIG.write_text(json.dumps({k: v for k, v in cfg.items() if not k.startswith("_") and k not in NEVER_SAVED},
                                 indent=2))


def configured(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return bool(cfg.get("client_id") and cfg.get("access_token"))

# ---------------------------------------------------------------- transport


def _throttle(kind: str):
    with _locks[kind]:
        wait = _last.get(kind, 0) + GAP[kind] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[kind] = time.monotonic()


def _headers(cfg: dict) -> dict:
    return {"access-token": cfg.get("access_token", ""), "client-id": str(cfg.get("client_id", "")),
            "Content-Type": "application/json", "Accept": "application/json"}


def _raise_for(resp: requests.Response, body):
    if isinstance(body, dict) and (body.get("errorCode") or body.get("errorType") or body.get("status") == "failure"):
        code = str(body.get("errorCode") or body.get("errorType") or resp.status_code)
        msg = body.get("errorMessage") or body.get("remarks") or json.dumps(body)[:200]
        if isinstance(body.get("data"), dict) and not body.get("errorCode"):
            # data-API style error: {"data": {"805": "message"}, "status": "failure"}
            k, v = next(iter(body["data"].items()), (code, msg))
            code, msg = str(k), str(v)
        raise DhanError(code, str(msg))
    if resp.status_code >= 400:
        raise DhanError(str(resp.status_code), resp.text[:200] or resp.reason)


def call(method: str, path: str, kind: str = "other", payload=None, cfg: dict | None = None, retries: int = 2):
    cfg = cfg or load_config()
    if not configured(cfg):
        raise DhanError("NOCONFIG", "Dhan is not connected. Add your Client ID and access token in Dhan Connect.")
    for attempt in range(retries + 1):
        _throttle(kind)
        try:
            resp = requests.request(method, BASE + path, headers=_headers(cfg), json=payload, timeout=20)
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(1.5)
                continue
            raise DhanError("NETWORK", f"Could not reach Dhan: {e}")
        try:
            body = resp.json()
        except ValueError:
            body = None
        try:
            _raise_for(resp, body)
        except DhanError as e:
            if e.code in ("DH-904", "805", "429") and attempt < retries:
                time.sleep(2 + attempt * 2)
                continue
            raise
        return body
    return None

# ---------------------------------------------------------------- account


def profile(cfg=None) -> dict:
    return call("GET", "/profile", cfg=cfg) or {}


def data_active(prof: dict) -> bool:
    return str(prof.get("dataPlan", "")).lower() == "active"


def renew_token(cfg=None) -> str | None:
    """Ask Dhan for a fresh 24-hour token (works only while the current one is valid)."""
    cfg = cfg or load_config()
    _throttle("other")
    h = _headers(cfg)
    h["dhanClientId"] = str(cfg.get("client_id", ""))
    resp = requests.get(BASE + "/RenewToken", headers=h, timeout=20)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    _raise_for(resp, body)
    token = body.get("token") or body.get("accessToken") or (body.get("data") or {}).get("accessToken") \
        if isinstance(body, dict) else None
    if token:
        cfg["access_token"] = token
        cfg["renewed_at"] = datetime.now(IST).isoformat(timespec="seconds")
        save_config(cfg)
    return token


def can_auto_token(cfg: dict) -> bool:
    """Client ID, Dhan PIN and the TOTP secret are set, so tokens can be made without a daily login."""
    return bool(cfg.get("client_id") and cfg.get("pin") and cfg.get("totp_secret"))


def totp_now(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 code, the same one an authenticator app shows for this secret."""
    import base64
    import hashlib
    import hmac
    import struct
    import time as _time
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    msg = struct.pack(">Q", int((at if at is not None else _time.time()) // step))
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def generate_token(cfg: dict) -> tuple[str, datetime]:
    """A fresh 24-hour access token from Client ID + PIN + TOTP (Dhan's generateAccessToken). Returns (token, expiry)."""
    params = {"dhanClientId": str(cfg["client_id"]), "pin": str(cfg["pin"]), "totp": totp_now(str(cfg["totp_secret"]))}
    _throttle("other")
    resp = requests.post("https://auth.dhan.co/app/generateAccessToken", params=params, timeout=20)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    token = body.get("accessToken") if isinstance(body, dict) else None
    if not resp.ok or not token:
        msg = (body.get("message") or body.get("errorMessage") or body.get("remarks")) if isinstance(body, dict) else ""
        raise DhanError("TOTP", f"Dhan did not issue a token ({resp.status_code}): {msg or str(body)[:200]}. "
                                "Check the PIN and TOTP secret in Secrets, and that this PC's clock is correct.")
    try:
        expiry = datetime.fromisoformat(str(body.get("expiryTime"))[:19]).replace(tzinfo=IST)
    except ValueError:
        expiry = datetime.now(IST) + timedelta(hours=23)
    cfg["access_token"] = token
    cfg["token_expiry"] = expiry.isoformat(timespec="seconds")
    save_config(cfg)
    return token, expiry


def holdings(cfg=None) -> list:
    return _as_list(call("GET", "/holdings", cfg=cfg))


def positions(cfg=None) -> list:
    return _as_list(call("GET", "/positions", cfg=cfg))


def funds(cfg=None) -> dict:
    b = call("GET", "/fundlimit", cfg=cfg) or {}
    if "availabelBalance" in b and "availableBalance" not in b:
        b["availableBalance"] = b["availabelBalance"]
    return b


def orders(cfg=None) -> list:
    return _as_list(call("GET", "/orders", cfg=cfg))


def trades(cfg=None) -> list:
    return _as_list(call("GET", "/trades", cfg=cfg))


def _as_list(b) -> list:
    if b is None:
        return []
    if isinstance(b, list):
        return b
    if isinstance(b, dict) and isinstance(b.get("data"), list):
        return b["data"]
    return []

# ---------------------------------------------------------------- market data


def quotes(pairs: list[tuple[str, int]], cfg=None) -> dict:
    """Full quote for many instruments. pairs: [(segment, security_id)]. Returns {(seg, id): quote}."""
    out = {}
    pairs = list(dict.fromkeys((s, int(i)) for s, i in pairs))
    for start in range(0, len(pairs), 1000):
        chunk = pairs[start:start + 1000]
        body = {}
        for seg, sid in chunk:
            body.setdefault(seg, []).append(sid)
        res = call("POST", "/marketfeed/quote", "quote", body, cfg) or {}
        data = res.get("data", {}) if isinstance(res, dict) else {}
        for seg, items in (data or {}).items():
            if isinstance(items, dict):
                for sid, q in items.items():
                    if isinstance(q, dict):
                        out[(seg, int(sid))] = q
    return out


def _bars(res: dict, intraday: bool) -> pd.DataFrame:
    if not isinstance(res, dict) or not res.get("timestamp"):
        return pd.DataFrame()
    df = pd.DataFrame({
        "Open": res.get("open"), "High": res.get("high"), "Low": res.get("low"), "Close": res.get("close"),
        "Volume": res.get("volume") or [0] * len(res["timestamp"]),
    })
    if res.get("open_interest") and len(res["open_interest"]) == len(df):
        df["OI"] = res["open_interest"]
    ts = pd.to_datetime(pd.Series(res["timestamp"]), unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df.index = pd.DatetimeIndex(ts) if intraday else pd.DatetimeIndex(ts.dt.tz_localize(None).dt.normalize())
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.astype(float)


def daily(seg: str, sid: int, instrument: str, start: date, end: date, oi: bool = False, cfg=None) -> pd.DataFrame:
    body = {"securityId": str(sid), "exchangeSegment": seg, "instrument": instrument, "expiryCode": 0,
            "oi": oi, "fromDate": start.isoformat(), "toDate": end.isoformat()}
    return _bars(call("POST", "/charts/historical", "data", body, cfg), intraday=False)


def intraday(seg: str, sid: int, instrument: str, interval: int, days: int, cfg=None) -> pd.DataFrame:
    """interval in minutes: 1, 5, 15, 25 or 60. Max 90 days per request."""
    now = datetime.now(IST)
    frames = []
    remaining = days
    end = now + timedelta(days=1)
    while remaining > 0:
        span = min(remaining, 89)
        start = end - timedelta(days=span)
        body = {"securityId": str(sid), "exchangeSegment": seg, "instrument": instrument, "interval": str(interval),
                "oi": instrument.startswith(("FUT", "OPT")), "fromDate": start.strftime("%Y-%m-%d 00:00:00"),
                "toDate": end.strftime("%Y-%m-%d 23:59:59")}
        frames.append(_bars(call("POST", "/charts/intraday", "data", body, cfg), intraday=True))
        end, remaining = start, remaining - span
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames).sort_index().loc[lambda d: ~d.index.duplicated()] if frames else pd.DataFrame()


def _hist_file(seg, sid, days, oi) -> Path:
    return CACHE / f"d_{seg}_{sid}_{days}{'_oi' if oi else ''}.pkl"


def history_peek(seg: str, sid: int, days: int = 400, oi: bool = False):
    """Today's cached daily bars if already downloaded, else None (no network)."""
    try:
        stamp, df = pickle.loads(_hist_file(seg, sid, days, oi).read_bytes())
        return df if stamp == datetime.now(IST).date() else None
    except Exception:
        return None


def history_cached(seg: str, sid: int, instrument: str, days: int = 400, oi: bool = False, cfg=None) -> pd.DataFrame:
    """Daily bars up to yesterday, cached on disk for the day (today's bar comes from live quotes)."""
    CACHE.mkdir(exist_ok=True)
    f = _hist_file(seg, sid, days, oi)
    today = datetime.now(IST).date()
    try:
        stamp, df = pickle.loads(f.read_bytes())
        if stamp == today:
            return df
    except Exception:
        pass
    try:
        df = daily(seg, sid, instrument, today - timedelta(days=days), today, oi=oi, cfg=cfg)
    except DhanError as e:
        if e.code != "DH-907":  # DH-907 = no data for this instrument: remember that for today
            raise
        df = pd.DataFrame()
    df = df[df.index.date < today] if not df.empty else df
    try:
        f.write_bytes(pickle.dumps((today, df)))
    except Exception:
        pass
    return df


def expiries(sid: int, seg: str, cfg=None) -> list[str]:
    res = call("POST", "/optionchain/expirylist", "oc", {"UnderlyingScrip": int(sid), "UnderlyingSeg": seg}, cfg)
    return list((res or {}).get("data") or [])


def option_chain(sid: int, seg: str, expiry: str, cfg=None) -> tuple[float, pd.DataFrame]:
    res = call("POST", "/optionchain", "oc", {"UnderlyingScrip": int(sid), "UnderlyingSeg": seg, "Expiry": expiry}, cfg)
    data = (res or {}).get("data") or {}
    rows = []
    for strike, legs in (data.get("oc") or {}).items():
        row = {"Strike": float(strike)}
        for side in ("ce", "pe"):
            leg = (legs or {}).get(side) or {}
            g = leg.get("greeks") or {}
            p = side.upper() + " "
            row.update({
                p + "LTP": leg.get("last_price"), p + "Prev": leg.get("previous_close_price"),
                p + "OI": leg.get("oi"), p + "Prev OI": leg.get("previous_oi"), p + "Volume": leg.get("volume"),
                p + "IV": leg.get("implied_volatility"), p + "Delta": g.get("delta"), p + "Theta": g.get("theta"),
                p + "Gamma": g.get("gamma"), p + "Vega": g.get("vega"), p + "Bid": leg.get("top_bid_price"),
                p + "Ask": leg.get("top_ask_price"), p + "Bid Qty": leg.get("top_bid_quantity"),
                p + "Ask Qty": leg.get("top_ask_quantity"), p + "ID": leg.get("security_id"),
            })
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Strike").reset_index(drop=True)
        for side in ("CE", "PE"):
            df[f"{side} Chg OI"] = df[f"{side} OI"].fillna(0) - df[f"{side} Prev OI"].fillna(0)
            df[f"{side} Chg"] = df[f"{side} LTP"] - df[f"{side} Prev"]
    return float(data.get("last_price") or 0), df

# ---------------------------------------------------------------- instruments

_COLMAP = {
    "SEM_EXM_EXCH_ID": "EXCH_ID", "SEM_SEGMENT": "SEGMENT", "SEM_SMST_SECURITY_ID": "SECURITY_ID",
    "SEM_INSTRUMENT_NAME": "INSTRUMENT", "SM_SYMBOL_NAME": "SYMBOL_NAME", "SEM_TRADING_SYMBOL": "TRADING_SYMBOL",
    "SEM_CUSTOM_SYMBOL": "DISPLAY_NAME", "SEM_SERIES": "SERIES", "SEM_LOT_UNITS": "LOT_SIZE",
    "SEM_EXPIRY_DATE": "EXPIRY", "SM_EXPIRY_DATE": "EXPIRY", "SEM_STRIKE_PRICE": "STRIKE_PRICE",
    "SEM_OPTION_TYPE": "OPTION_TYPE", "SEM_EXCH_INSTRUMENT_TYPE": "INSTRUMENT_TYPE", "SEM_TICK_SIZE": "TICK_SIZE",
}
_SEG_FILTER = {  # segment -> (exchange, segment letter, instruments) for filtering the full master
    "IDX_I": (None, None, {"INDEX"}), "NSE_EQ": ("NSE", "E", None), "NSE_FNO": ("NSE", "D", None),
    "NSE_CURRENCY": ("NSE", "C", None), "MCX_COMM": ("MCX", "M", None), "BSE_EQ": ("BSE", "E", None),
}


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().upper() for c in df.columns]
    df = df.rename(columns={k: v for k, v in _COLMAP.items() if k in df.columns})
    if "SECURITY_ID" not in df.columns:
        sid = [c for c in df.columns if "SECURITY_ID" in c and "UNDERLYING" not in c]
        if sid:
            df = df.rename(columns={sid[0]: "SECURITY_ID"})
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip()
    return df


def _parse_list(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8", "ignore").lstrip()
    if text.startswith(("[", "{")):
        j = json.loads(text)
        if isinstance(j, dict):
            j = j.get("data", j)
        return _norm_cols(pd.DataFrame(j))
    return _norm_cols(pd.read_csv(io.StringIO(text), low_memory=False))


# Derivative contract lists are large; they list contracts months ahead, so a week-old copy is still correct
# for picking the nearest unexpired contract. Other lists refresh daily.
MAX_AGE_DAYS = {"NSE_FNO": 7, "MCX_COMM": 7, "NSE_CURRENCY": 7, "BSE_FNO": 7}


def instruments(seg: str, cfg=None) -> pd.DataFrame:
    """Instrument list for one segment, cached on disk."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"instr_{seg}.pkl"
    today = datetime.now(IST).date()
    try:
        stamp, df = pickle.loads(f.read_bytes())
        if (today - stamp).days < MAX_AGE_DAYS.get(seg, 1) and not df.empty:
            return df
    except Exception:
        stamp, df = None, pd.DataFrame()
    fresh = pd.DataFrame()
    try:
        cfg = cfg or load_config()
        _throttle("other")
        r = requests.get(f"{BASE}/instrument/{seg}", headers=_headers(cfg), timeout=120)
        if r.ok and len(r.content) > 100:
            fresh = _parse_list(r.content)
    except Exception:
        pass
    if fresh.empty or "SECURITY_ID" not in fresh.columns:
        fresh = _from_master(seg)
    if fresh.empty:
        if not df.empty:
            return df  # yesterday's copy is better than nothing
        raise DhanError("INSTRUMENTS", f"Could not download Dhan's instrument list for {seg}.")
    try:
        f.write_bytes(pickle.dumps((today, fresh)))
    except Exception:
        pass
    return fresh


def _from_master(seg: str) -> pd.DataFrame:
    f = CACHE / "master.pkl"
    today = datetime.now(IST).date()
    master = None
    try:
        stamp, master = pickle.loads(f.read_bytes())
        if stamp != today:
            master = None
    except Exception:
        pass
    if master is None:
        try:
            r = requests.get(MASTER_URL, timeout=300)
            r.raise_for_status()
            master = _parse_list(r.content)
            f.write_bytes(pickle.dumps((today, master)))
        except Exception:
            return pd.DataFrame()
    exch, segl, instr = _SEG_FILTER.get(seg, (None, None, None))
    m = master
    if instr:
        m = m[m.get("INSTRUMENT", pd.Series(dtype=str)).isin(instr)]
    if exch:
        m = m[m.get("EXCH_ID", pd.Series(dtype=str)) == exch]
    if segl:
        m = m[m.get("SEGMENT", pd.Series(dtype=str)) == segl]
    return m.copy()


def _key(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def _underlying(df: pd.DataFrame) -> pd.Series:
    if "UNDERLYING_SYMBOL" in df.columns:
        u = df["UNDERLYING_SYMBOL"].replace({"nan": None, "": None})
        if u.notna().any():
            return u.fillna(df.get("TRADING_SYMBOL", df.get("SYMBOL_NAME")).astype(str).str.split("-").str[0])
    col = "TRADING_SYMBOL" if "TRADING_SYMBOL" in df.columns else "SYMBOL_NAME"
    return df[col].astype(str).str.split("-").str[0]


def _expiry(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df.get("EXPIRY"), errors="coerce").dt.date


def index_ids(cfg=None) -> dict:
    """{label: security_id} for the index labels in INDEX_ALIASES."""
    out = dict(KNOWN_INDEX_IDS)
    try:
        df = instruments("IDX_I", cfg)
    except DhanError:
        return out
    names = {}
    for _, r in df.iterrows():
        for col in ("SYMBOL_NAME", "TRADING_SYMBOL", "DISPLAY_NAME", "UNDERLYING_SYMBOL"):
            if col in r and str(r[col]) not in ("nan", ""):
                k = _key(r[col])
                names.setdefault(k, int(float(r["SECURITY_ID"])))
                names.setdefault(k.removesuffix("INDEX"), int(float(r["SECURITY_ID"])))
    for label, aliases in INDEX_ALIASES.items():
        if label in out:
            continue
        for a in aliases:
            if a in names:
                out[label] = names[a]
                break
    return out


def equity_ids(cfg=None) -> dict:
    """{NSE symbol: security_id} for NSE equities (EQ series)."""
    df = instruments("NSE_EQ", cfg)
    if "SERIES" in df.columns:
        df = df[df["SERIES"].isin(["EQ", "BE"]) | (df["SERIES"] == "nan")]
    out = {}
    for col in ("UNDERLYING_SYMBOL", "TRADING_SYMBOL", "SYMBOL_NAME"):
        if col in df.columns:
            for s, i in zip(df[col], df["SECURITY_ID"]):
                if s and s != "nan":
                    out.setdefault(str(s).upper(), int(float(i)))
    return out


def nearest_futures(seg: str, instrument: str, symbols: list[str] | None = None, cfg=None) -> dict:
    """{underlying: {"id", "expiry", "lot", "name"}} for the nearest unexpired future of each underlying."""
    df = instruments(seg, cfg)
    if "INSTRUMENT" in df.columns:
        df = df[df["INSTRUMENT"] == instrument]
    if df.empty:
        return {}
    df = df.assign(_u=_underlying(df).str.upper(), _e=_expiry(df))
    today = datetime.now(IST).date()
    df = df[df["_e"].notna() & (df["_e"] >= today)]
    if symbols:
        df = df[df["_u"].isin([s.upper() for s in symbols])]
    df = df.sort_values("_e").drop_duplicates("_u")
    out = {}
    for _, r in df.iterrows():
        lot = pd.to_numeric(r.get("LOT_SIZE"), errors="coerce")
        out[r["_u"]] = {"id": int(float(r["SECURITY_ID"])), "expiry": r["_e"],
                        "lot": None if pd.isna(lot) else int(lot),
                        "name": r.get("DISPLAY_NAME") or r.get("TRADING_SYMBOL") or r["_u"]}
    return out


def live_futures(seg: str, instrument: str, symbols: list[str] | None = None, n: int = 2, cfg=None) -> dict:
    """{underlying: [{"id", "expiry"}, ...]} for the n nearest unexpired futures (near and next month by default)."""
    df = instruments(seg, cfg)
    if "INSTRUMENT" in df.columns:
        df = df[df["INSTRUMENT"] == instrument]
    if df.empty:
        return {}
    df = df.assign(_u=_underlying(df).str.upper(), _e=_expiry(df))
    df = df[df["_e"].notna() & (df["_e"] >= datetime.now(IST).date())]
    if symbols:
        df = df[df["_u"].isin([s.upper() for s in symbols])]
    out: dict = {}
    for _, r in df.sort_values("_e").iterrows():
        lst = out.setdefault(r["_u"], [])
        if len(lst) < n:
            lst.append({"id": int(float(r["SECURITY_ID"])), "expiry": r["_e"]})
    return out


def fno_underlyings(cfg=None) -> dict:
    """{stock symbol: lot size} for stock futures, from Dhan's F&O instrument list."""
    fut = nearest_futures("NSE_FNO", "FUTSTK", cfg=cfg)
    return {u: v["lot"] for u, v in fut.items()}

# ---------------------------------------------------------------- helpers


def quote_to_bar(q: dict) -> dict | None:
    """Today's bar from a full quote."""
    if not q:
        return None
    o = q.get("ohlc") or {}
    ltp = q.get("last_price")
    if ltp in (None, 0):
        return None
    return {"Open": o.get("open") or ltp, "High": max(o.get("high") or ltp, ltp),
            "Low": min(o.get("low") or ltp, ltp) if o.get("low") else ltp,
            "Close": ltp, "Volume": q.get("volume") or 0, "PrevClose": o.get("close")}


def trade_date(q: dict) -> date | None:
    t = (q or {}).get("last_trade_time")
    if isinstance(t, (int, float)) and t > 0:
        return datetime.fromtimestamp(t, IST).date()
    t = str(t or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            d = datetime.strptime(t[:19], fmt).date()
            return d if d.year > 2000 else None
        except ValueError:
            continue
    return None


# Session hours (IST) per segment: (open, close)
SESSIONS = {"MCX_COMM": ((9, 0), (23, 55)), "NSE_CURRENCY": ((9, 0), (17, 0)), "BSE_CURRENCY": ((9, 0), (17, 0))}
EQ_SESSION = ((9, 15), (15, 30))


def market_live(seg: str = "NSE_EQ", now: datetime | None = None) -> bool:
    """True while the segment's regular session is running (holidays not considered)."""
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    (oh, om), (ch, cm) = SESSIONS.get(seg, EQ_SESSION)
    t = now.hour * 60 + now.minute
    return oh * 60 + om <= t <= ch * 60 + cm


def last_session_date(seg: str = "NSE_EQ", now: datetime | None = None) -> date:
    """Date of the current session, or of the most recent one before now."""
    now = now or datetime.now(IST)
    (oh, om), _ = SESSIONS.get(seg, EQ_SESSION)
    d = now.date()
    if now.weekday() >= 5 or now.hour * 60 + now.minute < oh * 60 + om:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def session_date(q: dict, seg: str = "NSE_EQ") -> date:
    """The trading day a quote belongs to."""
    return trade_date(q) or last_session_date(seg)


def max_pain(chain: pd.DataFrame) -> float | None:
    if chain is None or chain.empty:
        return None
    k = chain["Strike"].to_numpy()
    ce = chain["CE OI"].fillna(0).to_numpy()
    pe = chain["PE OI"].fillna(0).to_numpy()
    pain = [(ce * (x - k).clip(min=0)).sum() + (pe * (k - x).clip(min=0)).sum() for x in k]
    return float(k[int(pd.Series(pain).idxmin())])
