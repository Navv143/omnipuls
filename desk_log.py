"""Daily log of the Trading Desk (verdict, index plans, CE / PE focus with their OI readings) so the parts with no
history (futures buildup, sector futures money) can be judged after a few weeks.

Saved six times a day (9:20, 9:45, 10:30, 12:00, 13:30 and 15:00 IST, the first desk view after each; 15:00 doubles
as the next-day watchlist) to desk_log.csv next to the app, and, when
Secrets has [github] token (+ optional repo / branch), appended to desk_log/<YYYY-MM>.csv on the `logs` branch of the
private repo: Streamlit Cloud forgets local files on every restart, and it deploys only `main`, so writing to
`logs` never restarts the app. research/desk_log_eval.py scores the logged picks.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import threading
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
LOCAL = HERE / "desk_log.csv"
CHECKS = ("09:20", "09:45", "10:30", "12:00", "13:30", "15:00")
FIELDS = ["date", "check", "logged_at", "kind", "name", "side", "price", "chg_pct", "score", "why", "extra"]
_lock = threading.Lock()
STATUS = {"last": "", "error": ""}


def due(now: datetime, done: set) -> str | None:
    """The checkpoint to log now (the latest passed, not yet logged today), during market hours on weekdays."""
    if now.weekday() >= 5 or now.strftime("%H:%M") > "15:30":
        return None
    hhmm = now.strftime("%H:%M")
    passed = [c for c in CHECKS if hhmm >= c and (now.strftime("%Y-%m-%d"), c) not in done]
    return passed[-1] if passed else None


def rows_from(now: datetime, check: str, verdict: dict, plans: list, ce, pe) -> list[dict]:
    base = {"date": now.strftime("%Y-%m-%d"), "check": check, "logged_at": now.strftime("%H:%M")}
    out = [{**base, "kind": "verdict", "name": verdict.get("label", ""), "side": "", "price": "", "chg_pct": "",
            "score": verdict.get("score", ""), "why": "; ".join(f"{p['reading']}: {p['value']}" for p in verdict.get("parts", [])),
            "extra": ""}]
    for p in plans:
        out.append({**base, "kind": "index", "name": p["index"], "side": p["side"], "price": p.get("strike") or "",
                    "chg_pct": "", "score": "", "why": p["text"], "extra": ""})
    for side, df in (("CE", ce), ("PE", pe)):
        for _, r in df.iterrows():
            out.append({**base, "kind": "focus", "name": r["Stock"], "side": side, "price": round(float(r["Price"]), 2),
                        "chg_pct": round(float(r["Chg %"]), 2), "score": float(r["Score"]), "why": r["Why"],
                        "extra": r.get("Buildup", "") or ""})
    return out


def _to_csv(rows: list[dict], header: bool) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    if header:
        w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _github_append(rows: list[dict], cfg: dict):
    token, repo, branch = cfg["token"], cfg.get("repo", "Navv143/omnipuls"), cfg.get("branch", "logs")
    path = f"desk_log/{rows[0]['date'][:7]}.csv"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    r = requests.get(url, params={"ref": branch}, headers=h, timeout=20)
    old, sha = "", None
    if r.status_code == 200:
        body = r.json()
        sha = body["sha"]
        old = base64.b64decode(body["content"]).decode("utf-8")
    elif r.status_code != 404:
        raise RuntimeError(f"GitHub read {r.status_code}: {r.text[:160]}")
    text = old + _to_csv(rows, header=not old)
    payload = {"message": f"desk log {rows[0]['date']} {rows[0]['check']}", "branch": branch,
               "content": base64.b64encode(text.encode("utf-8")).decode()}
    if sha:
        payload["sha"] = sha
    w = requests.put(url, headers=h, data=json.dumps(payload), timeout=20)
    if w.status_code not in (200, 201):
        raise RuntimeError(f"GitHub write {w.status_code}: {w.text[:160]}")


def save(rows: list[dict], github: dict | None):
    """Write locally now and to GitHub in the background (the page never waits on it)."""
    if not rows:
        return
    with _lock:
        new = not LOCAL.exists()
        with LOCAL.open("a", encoding="utf-8", newline="") as fh:
            fh.write(_to_csv(rows, header=new))
    STATUS["last"] = f"{rows[0]['date']} {rows[0]['check']}"
    if github and github.get("token"):
        def run():
            try:
                _github_append(rows, github)
                STATUS["error"] = ""
            except Exception as e:
                STATUS["error"] = str(e)[:200]
        threading.Thread(target=run, daemon=True, name="desk-log").start()


def load(github: dict | None) -> "pd.DataFrame":
    """Every logged row: the GitHub `logs` branch (all months) when a token is set, plus this machine's file."""
    import pandas as pd
    frames = []
    if github and github.get("token"):
        repo, branch = github.get("repo", "Navv143/omnipuls"), github.get("branch", "logs")
        h = {"Authorization": f"Bearer {github['token']}", "Accept": "application/vnd.github+json"}
        try:
            r = requests.get(f"https://api.github.com/repos/{repo}/contents/desk_log", params={"ref": branch},
                             headers=h, timeout=20)
            if r.status_code == 200:
                for f in r.json():
                    if f.get("name", "").endswith(".csv"):
                        c = requests.get(f["url"], params={"ref": branch}, headers=h, timeout=20).json()
                        frames.append(pd.read_csv(io.StringIO(base64.b64decode(c["content"]).decode("utf-8"))))
            elif r.status_code != 404:
                STATUS["error"] = f"GitHub read {r.status_code}"
        except Exception as e:
            STATUS["error"] = str(e)[:200]
    if LOCAL.exists():
        try:
            frames.append(pd.read_csv(LOCAL))
        except Exception:
            pass
    if not frames:
        return pd.DataFrame(columns=FIELDS)
    d = pd.concat(frames, ignore_index=True)
    return d.drop_duplicates(["date", "check", "kind", "name", "side"], keep="last")


def setup_rows(now: datetime, sig: dict, names: dict) -> list[dict]:
    """The tested opening setups' signals of the day (paper trades): entry = opening price, stop as the rule says."""
    base = {"date": now.strftime("%Y-%m-%d"), "check": "09:15", "logged_at": now.strftime("%H:%M"), "kind": "setup"}
    out = []
    for key, df in (sig or {}).items():
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            out.append({**base, "name": r["sym"], "side": "CE" if str(r["side"]).upper().startswith("BUY") else "PE",
                        "price": round(float(r["entry"]), 2), "chg_pct": round(float(r["gap"]) * 100, 2),
                        "score": "", "why": names.get(key, key), "extra": f"stop {float(r['stop_px']):.2f}"})
    return out


def star_row(now: datetime, sg: dict, final: bool) -> list[dict]:
    """Bank Nifty 5-STAR paper trade: the signal when it fires, and its result once the trade has closed."""
    return [{"date": now.strftime("%Y-%m-%d"), "check": sg["time"], "logged_at": now.strftime("%H:%M"),
             "kind": "5star_final" if final else "5star", "name": "BANKNIFTY", "side": "CE" if sg["side"] > 0 else "PE",
             "price": round(sg["entry"], 2), "chg_pct": "", "score": round(sg["pts"], 1) if final else "",
             "why": sg["state"] if final else f"stop {sg['stop0']:.1f}", "extra": f"exit {sg['exit']}" if final else ""}]


def fade_row(now: datetime, tr: dict, final: bool) -> list[dict]:
    """Bank Nifty failed-break fade paper trade: when it fires, and its result once closed (points before cost)."""
    return [{"date": now.strftime("%Y-%m-%d"), "check": tr["time"], "logged_at": now.strftime("%H:%M"),
             "kind": "fade_final" if final else "fade", "name": "BANKNIFTY", "side": "CE" if tr["side"] > 0 else "PE",
             "price": round(tr["entry"], 2), "chg_pct": "", "score": round(tr["pts"], 1) if final else "",
             "why": tr["state"] if final else f"stop {tr['stop']:.1f} target {tr['target']:.1f}",
             "extra": f"{tr['level']}; exit {tr['exit']:.1f} at {tr['exit_time']}" if final else tr["level"]}]


def gold_row(now: datetime, tr: dict, final: bool) -> list[dict]:
    """Gold Order Flow paper trade: when it opens, and its result (% before cost) once closed. Times in IST."""
    import pandas as pd
    ist = lambda t: (t + pd.Timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    return [{"date": ist(tr["signal_time"])[:10], "check": ist(tr["signal_time"])[11:], "logged_at": now.strftime("%H:%M"),
             "kind": "gold_flow_final" if final else "gold_flow", "name": "GOLD", "side": "CE" if tr["side"] > 0 else "PE",
             "price": round(tr["entry"], 2), "chg_pct": "", "score": round(tr["pct"], 3) if final else "",
             "why": tr["state"] if final else f"{tr['kind']} stop {tr['stop']:.1f} target {tr['target']:.1f}",
             "extra": f"exit {tr['exit']:.1f} at {ist(tr['exit_time'])}" if final else ""}]
