"""User accounts for Omnipuls: user IDs and salted, hashed passwords.

Accounts come from two places:
  * Streamlit secrets ([users.<id>] tables), which survive restarts on Streamlit Cloud;
  * users.json next to the app, written when accounts are added or passwords changed in the app.
A users.json entry overrides the secrets entry with the same ID. Last sign-in and
preferences live in user_state.json. Passwords are never stored in files; only a
PBKDF2-SHA256 hash with a random salt. After 5 wrong passwords an ID is locked for 5 minutes.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
USERS_FILE = HERE / "users.json"
STATE_FILE = HERE / "user_state.json"
ITERATIONS = 240_000
MAX_FAILS, LOCK_SECONDS = 5, 300
ROLES = ("admin", "user")
_lock = threading.Lock()
_fails: dict[str, tuple[int, float]] = {}  # user -> (failures, locked_until)


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def normalize(user_id: str) -> str:
    return str(user_id).strip().lower()

# ---------------------------------------------------------------- storage


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


@functools.lru_cache(maxsize=64)
def _hash_plain(uid: str, password: str) -> tuple[str, str]:
    """Hash for a plain password written in secrets. Salt is derived from the ID so the result is stable."""
    salt = hashlib.sha256(("omnipuls:" + uid).encode()).digest()[:16]
    return salt.hex(), _hash(password, salt)


def secret_users() -> dict:
    """Accounts defined in Streamlit secrets: [users.<id>] with name, role and password (or salt + hash)."""
    try:
        import streamlit as st
        raw = st.secrets.get("users")
    except Exception:
        return {}
    out = {}
    for uid, u in dict(raw or {}).items():
        u, uid = dict(u), normalize(uid)
        if u.get("hash") and u.get("salt"):
            salt, h = str(u["salt"]), str(u["hash"])
        elif u.get("password"):
            salt, h = _hash_plain(uid, str(u["password"]))
        else:
            continue
        role = u.get("role", "user") if u.get("role", "user") in ROLES else "user"
        out[uid] = {"name": str(u.get("name") or uid), "role": role, "salt": salt, "hash": h, "source": "secrets"}
    return out


def load() -> dict:
    users = secret_users()
    for uid, u in _read(USERS_FILE).items():
        sec = users.get(uid, {})
        # same password and role already in Secrets: the account survives restarts, so say so
        saved = bool(sec) and sec.get("salt") == u.get("salt") and sec.get("hash") == u.get("hash") \
            and sec.get("role") == u.get("role", sec.get("role"))
        users[uid] = {**sec, **u, "source": "secrets" if saved else "app"}
    state = _read(STATE_FILE)
    for uid, u in users.items():
        u.update({"last_login": state.get(uid, {}).get("last_login"), "prefs": state.get(uid, {}).get("prefs", {})})
    return users


def has_users() -> bool:
    return bool(load())


def check_user_id(user_id: str) -> str | None:
    if not re.fullmatch(r"[a-z0-9._-]{3,32}", normalize(user_id)):
        return "User ID must be 3–32 characters: letters, numbers, dot, dash or underscore."
    return None


def check_password(pw: str) -> str | None:
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if pw.isdigit() or pw.isalpha():
        return "Use a mix of letters and numbers (or symbols) in the password."
    return None


def create(user_id: str, password: str, role: str = "user", name: str = "") -> str | None:
    """Returns an error message, or None when created."""
    uid = normalize(user_id)
    err = check_user_id(uid) or check_password(password)
    if err:
        return err
    if role not in ROLES:
        return "Unknown role."
    with _lock:
        if uid in load():
            return "That user ID already exists."
        users = _read(USERS_FILE)
        salt = secrets.token_bytes(16)
        users[uid] = {"name": name.strip() or uid, "role": role, "salt": salt.hex(), "hash": _hash(password, salt),
                      "created": datetime.now().isoformat(timespec="seconds")}
        _write(USERS_FILE, users)
    return None


def locked_for(user_id: str) -> int:
    fails, until = _fails.get(normalize(user_id), (0, 0.0))
    return max(0, int(until - time.time()))


def verify(user_id: str, password: str) -> dict | None:
    """Returns the user record on success, None otherwise (and counts the failure)."""
    uid = normalize(user_id)
    if locked_for(uid):
        return None
    u = load().get(uid)
    # Hash even for unknown users so response time doesn't reveal which IDs exist
    salt = bytes.fromhex(u["salt"]) if u else b"omnipuls-no-user"
    ok = u is not None and hmac.compare_digest(_hash(password, salt), u["hash"])
    if not ok:
        fails, _ = _fails.get(uid, (0, 0.0))
        fails += 1
        _fails[uid] = (fails, time.time() + LOCK_SECONDS if fails >= MAX_FAILS else 0.0)
        return None
    _fails.pop(uid, None)
    with _lock:
        state = _read(STATE_FILE)
        state.setdefault(uid, {})["last_login"] = datetime.now().isoformat(timespec="seconds")
        try:
            _write(STATE_FILE, state)
        except Exception:
            pass
    return {"id": uid, "name": u["name"], "role": u["role"]}


def set_password(user_id: str, new_password: str) -> str | None:
    err = check_password(new_password)
    if err:
        return err
    uid = normalize(user_id)
    with _lock:
        merged = load()
        if uid not in merged:
            return "No such user."
        users = _read(USERS_FILE)
        rec = users.get(uid) or {k: merged[uid][k] for k in ("name", "role")}
        salt = secrets.token_bytes(16)
        rec.update(salt=salt.hex(), hash=_hash(new_password, salt))
        users[uid] = rec
        _write(USERS_FILE, users)
    return None


def _only_in_secrets(uid: str) -> bool:
    return uid in secret_users() and uid not in _read(USERS_FILE)


def set_role(user_id: str, role: str) -> str | None:
    uid = normalize(user_id)
    with _lock:
        merged = load()
        if uid not in merged or role not in ROLES:
            return "No such user or role."
        if _only_in_secrets(uid):
            return "This user is defined in the app's Secrets; change the role there."
        if merged[uid]["role"] == "admin" and role != "admin" and sum(u["role"] == "admin" for u in merged.values()) == 1:
            return "Keep at least one admin."
        users = _read(USERS_FILE)
        users[uid]["role"] = role
        _write(USERS_FILE, users)
    return None


def delete(user_id: str) -> str | None:
    uid = normalize(user_id)
    with _lock:
        merged = load()
        if uid not in merged:
            return "No such user."
        if uid in secret_users():
            return "This user is defined in the app's Secrets; remove them there."
        if merged[uid]["role"] == "admin" and sum(u["role"] == "admin" for u in merged.values()) == 1:
            return "You can't delete the only admin."
        users = _read(USERS_FILE)
        users.pop(uid, None)
        _write(USERS_FILE, users)
    return None


def secrets_entry(user_id: str) -> str:
    """TOML lines that recreate this account in Streamlit secrets (password stored as a hash)."""
    uid = normalize(user_id)
    u = load().get(uid)
    if not u:
        return ""
    return (f'[users.{uid}]\nname = "{u["name"]}"\nrole = "{u["role"]}"\n'
            f'salt = "{u["salt"]}"\nhash = "{u["hash"]}"\n')


def get_pref(user_id: str, name: str, default=None):
    return _read(STATE_FILE).get(normalize(user_id), {}).get("prefs", {}).get(name, default)


def set_pref(user_id: str, name: str, value) -> None:
    uid = normalize(user_id)
    with _lock:
        state = _read(STATE_FILE)
        state.setdefault(uid, {}).setdefault("prefs", {})[name] = value
        _write(STATE_FILE, state)
