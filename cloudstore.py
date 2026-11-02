"""Keeps the app's small saved files in Supabase, so they survive Streamlit Cloud restarts.

Streamlit Cloud wipes the app folder whenever the app restarts, redeploys or wakes from sleep, which lost accounts
added in the app, passwords changed, preferences and watchlists. With [supabase] url and key in Secrets, every save of
those files is also written to the `app_files` table, and a file missing after a restart is restored from it.
Without the Secrets nothing changes: files stay local only.

Table (supabase/schema.sql): app_files(name text primary key, body jsonb, updated_at timestamptz), row level security
on with no policies, so only the server-side secret key can read it (never the public/publishable key).
Secrets: [supabase] url = "https://<project>.supabase.co", key = "<secret key: sb_secret_... or the service_role key>".
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import requests

TABLE = "app_files"
TIMEOUT = 8
_cfg = {"url": "", "key": ""}
_tried: set = set()         # file names already looked up in this process (a restore is tried once per file)
_lock = threading.Lock()
STATUS = {"error": "", "saved": 0, "restored": 0, "last_save": 0.0}


def configure(url: str | None, key: str | None):
    _cfg["url"] = str(url or os.environ.get("SUPABASE_URL") or "").rstrip("/")
    _cfg["key"] = str(key or os.environ.get("SUPABASE_KEY") or "")


def enabled() -> bool:
    return bool(_cfg["url"] and _cfg["key"])


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": _cfg["key"], "Authorization": f"Bearer {_cfg['key']}", "Content-Type": "application/json"}
    h.update(extra or {})
    return h


def _put(name: str, data):
    r = requests.post(f"{_cfg['url']}/rest/v1/{TABLE}", params={"on_conflict": "name"},
                      headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                      data=json.dumps([{"name": name, "body": data}]), timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase save {name}: {r.status_code} {r.text[:150]}")


def save(name: str, data):
    """Write a file's contents to Supabase in the background (the page never waits on it)."""
    if not enabled():
        return

    def run():
        try:
            with _lock:  # saves of the same file stay in order
                _put(name, data)
            STATUS.update(error="", last_save=time.time())
            STATUS["saved"] += 1
        except Exception as e:
            STATUS["error"] = str(e)[:200]

    threading.Thread(target=run, daemon=True, name="cloudstore-save").start()


def load(name: str):
    """A file's saved contents, or None when there are none (or Supabase can't be reached)."""
    if not enabled():
        return None
    try:
        r = requests.get(f"{_cfg['url']}/rest/v1/{TABLE}", params={"name": f"eq.{name}", "select": "body"},
                         headers=_headers(), timeout=TIMEOUT)
        if r.status_code >= 300:
            raise RuntimeError(f"Supabase load {name}: {r.status_code} {r.text[:150]}")
        rows = r.json()
        return rows[0]["body"] if rows else None
    except Exception as e:
        STATUS["error"] = str(e)[:200]
        return None


def restore(path: Path) -> bool:
    """If `path` is missing (e.g. after a cloud restart), write it back from Supabase. Tried once per file per
    process, so it costs one quick lookup after a restart and nothing afterwards."""
    path = Path(path)
    if path.exists() or not enabled() or path.name in _tried:
        return False
    _tried.add(path.name)
    data = load(path.name)
    if data is None:
        return False
    try:
        tmp = path.with_suffix(".restore.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)
        STATUS["restored"] += 1
        return True
    except Exception as e:
        STATUS["error"] = f"restore {path.name}: {e}"[:200]
        return False
