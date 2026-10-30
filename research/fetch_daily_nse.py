"""Only the NSE daily files from fetch.py (F&O stocks + indices, eod2_data on GitHub) into research/data/nse."""
import sys
import time
import urllib.parse
from pathlib import Path

import truststore

truststore.inject_into_ssl()
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fetch as F  # noqa: E402
import universe as U  # noqa: E402

stat = {}
for n in sorted(U.FNO_SECTOR_OF) + F.INDICES:
    fn = F.OUT / "nse" / (n.replace(" ", "_").replace("&", "and") + ".csv")
    r = F.get(F.EOD.format(urllib.parse.quote(n.lower())), fn)
    stat.setdefault(r, []).append(n)
    if r == "ok":
        time.sleep(0.4)
for k, v in stat.items():
    print(k, len(v), v[:30] if k not in ("ok", "cached") else "")
