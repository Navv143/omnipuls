"""Breakout V3 (scanners.version3): why the top 9:30 pick works and what the others lack.
Every session: rank all F&O stocks at 9:30 (ATR %, 9:15-9:30 range, opening RVOL, gap), keep the top 10, and record
each one's first 15-min opening-range breakout until 12:00 (with / without the volume and Nifty filters) and its
result (entry next open, stop 0.5 ATR, trail 1 ATR, exit 15:20), with its rank and readings.
Usage: python research/v3_study.py stocks_5m.pkl indices_5m.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scanners as SC  # noqa: E402
import universe as U  # noqa: E402

COST = 0.12


def run(bars: dict, nifty: pd.DataFrame) -> pd.DataFrame:
    days = sorted(set(nifty.index.normalize()))
    out = []
    for d in days[6:]:
        S = SC.prepare({k: v for k, v in bars.items() if k in U.FNO_SECTOR_OF}, d)
        if len(S) < 50:
            continue
        N = SC.Stock("NIFTY 50", nifty, d)
        v_all, ranked = SC.version3(S, N if N.ok else None, top=10, filters=False)
        if v_all is None or v_all.empty:
            continue
        rk = {s: i + 1 for i, s in enumerate(ranked["Stock"])}
        info = ranked.set_index("Stock")
        nmove = None
        if N.ok:
            nb = N.today
            nmove = (nb["Close"].iloc[-1] / N.prev_close - 1) * 100
        for _, r in v_all.iterrows():
            s = r["Stock"]
            side = 1 if str(r["Side"]).startswith("BUY") else -1
            st = S[s]
            out.append({"day": d, "stock": s, "rank": rk.get(s), "side": side, "signal": r["Signal"],
                        "pnl": r["P&L %"] - COST, "status": r["Status"], "vol_ok": r["Volume x"] >= 1.5 if pd.notna(r["Volume x"]) else False,
                        "vol_x": r["Volume x"], "nifty_ok": r["Nifty OK"] == "Yes", "a_plus": r["A+"] == "Yes",
                        "block": r["Block deal?"] == "Yes", "score": r["Score"], "atr_pct": info.at[s, "ATR %"],
                        "orr_pct": info.at[s, "9:15-9:30 range %"], "rvol": info.at[s, "RVOL"], "gap_pct": info.at[s, "Gap %"],
                        "gap_with": side * info.at[s, "Gap %"], "nifty_day": nmove,
                        "sector": U.FNO_SECTOR_OF.get(s)})
    return pd.DataFrame(out)


if __name__ == "__main__":
    bars = pickle.load(open(sys.argv[1], "rb"))
    ix = pickle.load(open(sys.argv[2], "rb"))
    t = run(bars, ix["NIFTY"])
    t.to_csv(Path(sys.argv[1]).with_name("v3_study.csv"), index=False)
    print(len(t), "breakouts from the top-10 ranked,", t["day"].nunique(), "days")
