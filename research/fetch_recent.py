"""Top up research/cache with the latest sessions (5-minute bars) and download futures OI for the last ~40 days.

Run after momentum_dhan.py has cached the 5-year history. Writes research/cache/recent_<secid>.pkl (stock + Nifty
bars for the last 5 days) and research/cache/oi_<SYMBOL>.pkl (near + next month futures OI, 5-minute).
  .venv\\Scripts\\python research\\fetch_recent.py
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dhan as D  # noqa: E402
import scan_service as SS  # noqa: E402
import universe as U  # noqa: E402

CACHE = HERE / "cache"

if __name__ == "__main__":
    ids = {k: v for k, v in D.equity_ids().items() if k in U.FNO_SECTOR_OF}
    fut = D.live_futures("NSE_FNO", "FUTSTK", list(ids), n=2)
    t0 = time.time()
    (CACHE / "recent_IDX_13.pkl").write_bytes(pickle.dumps(D.intraday("IDX_I", 13, "INDEX", 5, 5)))
    for i, (s, sid) in enumerate(sorted(ids.items()), 1):
        try:
            (CACHE / f"recent_{sid}.pkl").write_bytes(pickle.dumps(D.intraday("NSE_EQ", sid, "EQUITY", 5, 5)))
            frames = [SS._naive(D.intraday("NSE_FNO", c["id"], "FUTSTK", 5, 45)) for c in fut.get(s, [])]
            frames = [f[["OI", "Volume"]] for f in frames if not f.empty and "OI" in f]
            if frames:
                (CACHE / f"oi_{s.replace('&', '_and_')}.pkl").write_bytes(pickle.dumps(SS.combine_oi(frames)))
        except Exception as e:
            print(f"  {s}: {e}")
        if i % 25 == 0:
            print(f"  {i}/{len(ids)} ({time.time() - t0:.0f}s)", flush=True)
    print(f"done in {time.time() - t0:.0f}s")
