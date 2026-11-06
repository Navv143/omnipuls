"""The app's side of engine.py: a ScanService look-alike that reads <data>/engine/state.pkl.

Every page keeps calling svc.bars(), svc.idx_bars(), svc.oi(), svc.progress() ... as before, but nothing is downloaded
or recomputed in the page process: the engine process wrote it. A newer file is loaded in a background thread while
the previous one keeps serving, so no viewer waits for the reload. If the file is missing or older than `max_age`
seconds (engine down), a normal ScanService is started and used until the engine is back.
"""
from __future__ import annotations

import pickle
import threading
import time
from pathlib import Path


class EngineService:
    source = "dhan"

    def __init__(self, path: Path, fallback_factory, max_age: float = 180.0):
        self.path, self._factory, self.max_age = Path(path), fallback_factory, max_age
        self._state: dict | None = None
        self._mtime = 0.0
        self._loading = False
        self._lock = threading.Lock()
        self._fb = None
        self._uni: set | None = None
        self._ids: dict = {}
        self.touched = time.time()

    # ---------------------------------------------------------------- state
    def _read(self, mtime: float):
        try:
            with open(self.path, "rb") as f:
                st = pickle.load(f)
            with self._lock:
                if mtime >= self._mtime:
                    self._state, self._mtime = st, mtime
        except Exception:
            pass
        finally:
            self._loading = False

    def _live(self) -> dict | None:
        """The engine's state when it is fresh, else None (and the fallback loader is started)."""
        try:
            m = self.path.stat().st_mtime
        except OSError:
            m = 0.0
        if not m or time.time() - m > self.max_age:
            self._start_fallback()
            return None
        if m > self._mtime:
            if self._state is None:                  # first load: wait for it
                self._read(m)
            elif not self._loading:                  # newer file: load it in the background, keep serving the old one
                self._loading = True
                threading.Thread(target=self._read, args=(m,), daemon=True, name="engine-load").start()
        if self._state is not None and self._fb is not None:   # engine is back: stop the fallback loader
            try:
                self._fb.stop()
            except Exception:
                pass
            self._fb = None
        return self._state

    def _start_fallback(self):
        if self._fb is None:
            self._fb = self._factory()
            if self._uni:
                self._fb.set_universe(sorted(self._uni))
            if self._ids:
                self._fb.set_indices(self._ids)
        self._fb.touch()

    @property
    def engine_live(self) -> bool:
        return self._live() is not None

    # ---------------------------------------------------------------- ScanService API
    def set_universe(self, syms):
        self._uni = set(syms)
        if self._fb is not None:
            self._fb.set_universe(syms)

    def set_indices(self, ids: dict):
        self._ids = dict(ids)
        if self._fb is not None:
            self._fb.set_indices(ids)

    def touch(self):
        self.touched = time.time()
        if self._fb is not None:
            self._fb.touch()

    def stop(self):
        if self._fb is not None:
            self._fb.stop()

    def bars(self):
        st = self._live()
        if st is None:
            return self._fb.bars()
        b = st["bars"]
        if self._uni and not self._uni >= set(b):      # a page asked for a smaller universe (e.g. Nifty 100)
            b = {k: v for k, v in b.items() if k in self._uni}
        return b, st["nifty"]

    def idx_bars(self):
        st = self._live()
        return self._fb.idx_bars() if st is None else st["idx"]

    def ifut_bars(self):
        st = self._live()
        return self._fb.ifut_bars() if st is None else st["ifut"]

    def oi(self):
        st = self._live()
        return self._fb.oi() if st is None else st["oi"]

    def snapshots(self):
        st = self._live()
        return self._fb.snapshots() if st is None else st["snaps"]

    def progress(self):
        st = self._live()
        if st is None:
            return self._fb.progress()
        if self._uni and not self._uni >= set(st["bars"]):
            return sum(1 for s in self._uni if s in st["bars"]), len(self._uni)
        return st["progress"]

    def freshness(self):
        st = self._live()
        return self._fb.freshness() if st is None else st["freshness"]

    @property
    def activity(self):
        """(R, E, per, session) as the app's _activity_data computes it, or None (engine down or not ready)."""
        st = self._live()
        return None if st is None else st.get("activity")

    @property
    def scans(self):
        """{"session", "radar", "v3", "rf"} from the engine, or None."""
        st = self._live()
        return None if st is None else st.get("scans")

    @property
    def plan(self):
        """{"fade", "five", "trend", "gold"} from the engine (regular setups' heavy parts), or None."""
        st = self._live()
        return None if st is None else st.get("plan")

    def _attr(self, k: str, default=None):
        st = self._live()
        return getattr(self._fb, k, default) if st is None else st.get(k, default)

    status = property(lambda self: self._attr("status", "starting"))
    error = property(lambda self: self._attr("error", ""))
    oi_status = property(lambda self: self._attr("oi_status", "off"))
    last_pass = property(lambda self: self._attr("last_pass", 0.0))
    last_snap = property(lambda self: self._attr("last_snap", 0.0))
    tf = property(lambda self: self._attr("tf", 3))

    @property
    def snaps(self):
        st = self._live()
        if st is None:
            return self._fb.snaps
        return range(st.get("n_snaps", 0))           # pages only count them
