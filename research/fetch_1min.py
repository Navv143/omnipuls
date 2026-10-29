"""Download 1-minute bars for every F&O stock (and Nifty) for the last N days into research/cache/m1_<id>.pkl.
  .venv\\Scripts\\python research\\fetch_1min.py --days 40
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dhan as D  # noqa: E402
import universe as U  # noqa: E402

CACHE = HERE / "cache"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=40)
    a = ap.parse_args()
    ids = {k: v for k, v in D.equity_ids().items() if k in U.FNO_SECTOR_OF}
    t0 = time.time()
    (CACHE / "m1_IDX_13.pkl").write_bytes(pickle.dumps(D.intraday("IDX_I", 13, "INDEX", 1, a.days)))
    for i, (s, sid) in enumerate(sorted(ids.items()), 1):
        try:
            (CACHE / f"m1_{sid}.pkl").write_bytes(pickle.dumps(D.intraday("NSE_EQ", sid, "EQUITY", 1, a.days)))
        except Exception as e:
            print(f"  {s}: {e}")
        if i % 50 == 0:
            print(f"  {i}/{len(ids)} ({time.time() - t0:.0f}s)", flush=True)
    print(f"done in {time.time() - t0:.0f}s")
