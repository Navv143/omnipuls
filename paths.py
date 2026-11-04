"""Where Omnipuls keeps the files it writes (accounts, preferences, watchlists, the Dhan token, logs, caches).

By default that is the app folder, as always. Set OMNIPULS_STATE to another folder (the Docker setup uses a volume)
so the files survive when the code is replaced by an update. Recorded market data goes to OMNIPULS_DATA (default:
<state>/market_data).
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = Path(os.environ.get("OMNIPULS_STATE") or HERE)
STATE.mkdir(parents=True, exist_ok=True)
DATA = Path(os.environ.get("OMNIPULS_DATA") or STATE / "market_data")


def state(name: str) -> Path:
    """A file or folder in the state folder."""
    return STATE / name
