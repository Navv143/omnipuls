"""Trading setups validated in Omnipuls research (research/ folder), as pure functions the app can call.

All rules decide at 9:15 from the opening price and the previous close, enter at the open, exit at 15:15-15:25
or at the stop. Results quoted are after 0.12% round-trip costs, on daily bars 2013-2026 (see research/README).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SETUPS = {
    "gap_fade": {
        "name": "Gap fade: the 2 biggest gaps of 3%+",
        "rule": "Each morning take the two F&O stocks with the largest opening gap of at least 3% (either side). "
                "Buy gap-downs, short gap-ups at the open. Stop 1% from entry. Exit at the close (15:15-15:25).",
        "stats": "2013-2026: 3,239 trades (~235/yr), win 33%, avg +0.61% per trade, profit factor 1.90, "
                 "profitable every year 2013-2025, worst losing run 18 trades. Caution: only +0.08% per trade "
                 "in 2026 so far (6 of 10 months flat or negative); verify on intraday data before trading it.",
        "stop": 0.01,
    },
    "panic_gap": {
        "name": "Panic gap-down reversal",
        "rule": "Only on days Nifty opens 0.5%+ lower: buy the two F&O stocks with the biggest gap-down of 3%+. "
                "Stop 1.5%. Exit at the close.",
        "stats": "2013-2026: 369 trades (~27/yr), win 45%, avg +1.27% per trade, profit factor 2.57, "
                 "profitable in 10 of 14 years, and still +0.62% per trade in 2026. The safest one to start with.",
        "stop": 0.015,
    },
    "sector_overreaction": {
        "name": "Sector overreaction",
        "rule": "Buy F&O stocks that gap down 2.5%+ and at least 2.5% more than their sector index (2 a day). "
                "Stop 1.5%. Exit at the close.",
        "stats": "2013-2026: 1,796 trades (~130/yr), win 37%, avg +0.54% per trade, profit factor 1.61, "
                 "13 of 14 years profitable.",
        "stop": 0.015,
    },
}


def gap_table(rows: list[dict]) -> pd.DataFrame:
    """rows: dicts with sym, sector, open (or live price at 9:15), prev_close, ltp, sector_gap (optional)."""
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["gap"] = t["open"] / t["prev_close"] - 1
    t["abs_gap"] = t["gap"].abs()
    t["now_vs_open"] = t["ltp"] / t["open"] - 1
    if "sector_gap" not in t:
        t["sector_gap"] = np.nan
    t["gap_vs_sector"] = t["gap"] - t["sector_gap"]
    return t


def signals(t: pd.DataFrame, nifty_gap: float) -> dict[str, pd.DataFrame]:
    """Today's candidates for each setup, with side, entry (open) and stop."""
    out = {}
    if t is None or t.empty:
        return {k: pd.DataFrame() for k in SETUPS}

    def finish(df, side, stop):
        df = df.copy()
        df["side"] = np.where(side > 0, "BUY", "SHORT") if np.ndim(side) else ("BUY" if side > 0 else "SHORT")
        sgn = np.where(df["side"] == "BUY", 1, -1)
        df["entry"] = df["open"]
        df["stop_px"] = df["open"] * (1 - sgn * stop)
        df["pnl_now%"] = sgn * df["now_vs_open"] * 100
        df["stopped"] = np.where(sgn > 0, df["low"] <= df["stop_px"], df["high"] >= df["stop_px"]) \
            if {"low", "high"} <= set(df.columns) else False
        return df

    g = t[t["abs_gap"] >= 0.03].sort_values("abs_gap", ascending=False).head(2)
    out["gap_fade"] = finish(g, np.where(g["gap"] < 0, 1, -1), SETUPS["gap_fade"]["stop"])
    if nifty_gap is not None and nifty_gap <= -0.005:
        g = t[t["gap"] <= -0.03].sort_values("gap").head(2)
    else:
        g = t.iloc[0:0]
    out["panic_gap"] = finish(g, 1, SETUPS["panic_gap"]["stop"])
    g = t[(t["gap"] <= -0.025) & (t["gap_vs_sector"] <= -0.025)].sort_values("gap").head(2)
    out["sector_overreaction"] = finish(g, 1, SETUPS["sector_overreaction"]["stop"])
    return out


def btc_trend(closes: pd.Series, n: int = 100) -> dict:
    """BTC trend filter: long only while the daily close is above its n-day average."""
    c = closes.dropna()
    if len(c) < n + 1:
        return {}
    ma = c.rolling(n).mean()
    return {"price": float(c.iloc[-1]), "ma": float(ma.iloc[-1]), "long": bool(c.iloc[-1] > ma.iloc[-1]),
            "distance%": float((c.iloc[-1] / ma.iloc[-1] - 1) * 100)}
