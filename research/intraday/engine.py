"""Backtest engine on the [field, symbol, day, slot] cube of 5-minute bars (slots 09:15..15:25)."""
from __future__ import annotations

import numpy as np
import pandas as pd

import universe as U

EXTRA_SECTOR = {"ADANIPOWER": "Oil, Gas & Power", "ENRIN": "Capital Goods & Infra", "HYUNDAI": "Auto",
                "LTM": "IT", "MM": "Auto", "TATACAP": "Financial Services", "TMCV": "Auto"}
INDEXES = ("NIFTY 50", "NIFTY BANK", "INDIA VIX")
NSLOT = 75


def slot(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return (h * 60 + m - (9 * 60 + 15)) // 5


class Data:
    def __init__(self, path="/home/claude/bt/cube.npz"):
        z = np.load(path)
        c = z["cube"].astype(np.float64)
        c[:4][c[:4] <= 0] = np.nan
        self.syms = [str(s) for s in z["syms"]]
        self.days = pd.DatetimeIndex(z["days"])
        ni = self.syms.index("NIFTY 50")
        nbars = np.isfinite(c[3, ni]).sum(1)
        keep = nbars >= 60  # drop special/partial sessions (muhurat, half days, last partial day)
        keep[-1] = keep[-1] and nbars[-1] >= 74
        c = c[:, :, keep]
        self.days = self.days[keep]
        self.O, self.H, self.L, self.C, self.V = c
        self.stock_idx = [i for i, s in enumerate(self.syms) if s not in INDEXES]
        self.sector = {s: U.FNO_SECTOR_OF.get(s, EXTRA_SECTOR.get(s, "Other")) for s in self.syms}
        self._daily()

    def _daily(self):
        O, H, L, C, V = self.O, self.H, self.L, self.C, self.V
        has = np.isfinite(C).any(2)
        fi = np.argmax(np.isfinite(O), axis=2)
        li = NSLOT - 1 - np.argmax(np.isfinite(C[..., ::-1]), axis=2)
        self.dopen = np.where(has, np.take_along_axis(O, fi[..., None], 2)[..., 0], np.nan)
        self.dclose = np.where(has, np.take_along_axis(C, li[..., None], 2)[..., 0], np.nan)
        with np.errstate(all="ignore"):
            self.dhigh = np.nanmax(H, 2)
            self.dlow = np.nanmin(L, 2)
            self.dvol = np.nansum(V, 2)
        pc = pd.DataFrame(self.dclose.T).shift(1).values.T  # previous session close (NaN if stock missing yesterday)
        self.prev_close = pc
        with np.errstate(all="ignore"):
            self.gap = self.dopen / pc - 1
            tr = np.nanmax(np.stack([self.dhigh - self.dlow, np.abs(self.dhigh - pc), np.abs(self.dlow - pc)]), 0)
        self.atr = pd.DataFrame(tr.T).rolling(14, min_periods=14).mean().shift(1).values.T  # known before today
        # bad data guard: an overnight jump of 20%+ (corporate action / bad print) blocks the stock for 20 sessions
        bad = np.abs(self.gap) > 0.2
        block = pd.DataFrame(bad.T).rolling(21, min_periods=1).max().values.T.astype(bool)
        self.valid = has & np.isfinite(pc) & np.isfinite(self.atr) & ~block
        # opening range 09:15-09:30 = first three 5-minute bars
        with np.errstate(all="ignore"):
            self.or_high = np.nanmax(H[..., :3], 2)
            self.or_low = np.nanmin(L[..., :3], 2)
            self.or_vol = np.nansum(V[..., :3], 2)
            self.or_open = O[..., 0]
            self.rvol = self.or_vol / pd.DataFrame(self.or_vol.T).rolling(20, min_periods=20).mean().shift(1).values.T
            self.or_range_pct = (self.or_high - self.or_low) / self.or_open
        self.valid &= np.isfinite(self.or_high) & np.isfinite(O[..., 0]) & (np.isfinite(C).sum(2) >= 60)
        self._slotavg = {}

    def slot_avg_vol(self, n=10):
        if n not in self._slotavg:
            S, D, T = self.V.shape
            v = self.V.transpose(0, 2, 1).reshape(S * T, D)
            a = pd.DataFrame(v.T).rolling(n, min_periods=n).mean().shift(1).values.T
            self._slotavg[n] = a.reshape(S, T, D).transpose(0, 2, 1)
        return self._slotavg[n]

    def idx(self, sym):
        return self.syms.index(sym)


# ---------------------------------------------------------------- trade walking

def walk(d: Data, s: int, day: int, side: int, entry_slot: int, entry_px: float, stop_px: float | None,
         trail: float | None = None, target_px: float | None = None, exit_slot: int = slot("15:20")):
    """Walk 5-minute bars from entry_slot. Stop checked against the level known before each bar (conservative:
    the bar's own new extreme only moves the trail for the NEXT bar). Bar opening through the stop fills at the open.
    If stop and target are both inside one bar, the stop is assumed first."""
    O, H, L, C = d.O[s, day], d.H[s, day], d.L[s, day], d.C[s, day]
    best = entry_px
    for t in range(entry_slot, NSLOT):
        if not np.isfinite(O[t]):
            continue
        if t >= exit_slot:
            return O[t], "time", t
        lvl = stop_px
        if trail is not None:
            tl = best - side * trail
            lvl = tl if lvl is None else (max(lvl, tl) if side > 0 else min(lvl, tl))
        if lvl is not None:
            if side > 0 and L[t] <= lvl:
                return min(O[t], lvl), ("stop" if lvl == stop_px else "trail"), t
            if side < 0 and H[t] >= lvl:
                return max(O[t], lvl), ("stop" if lvl == stop_px else "trail"), t
        if target_px is not None:
            if side > 0 and H[t] >= target_px:
                return max(O[t], target_px), "target", t
            if side < 0 and L[t] <= target_px:
                return min(O[t], target_px), "target", t
        best = max(best, H[t]) if side > 0 else min(best, L[t])
    last = np.where(np.isfinite(C))[0]
    return C[last[-1]], "eod", last[-1]


def trade_row(d, s, day, side, entry, exit_px, how, risk_pct, **extra):
    g = side * (exit_px / entry - 1)
    return {"date": d.days[day], "sym": d.syms[s], "side": "long" if side > 0 else "short", "entry": entry,
            "exit": exit_px, "exit_by": how, "gross": g, "risk_pct": risk_pct, **extra}


# ---------------------------------------------------------------- reporting

def stats(t: pd.DataFrame, cost: float, label: str = "") -> dict:
    if t is None or len(t) == 0:
        return {"setup": label, "trades": 0}
    net = t["gross"] - cost
    R = net / t["risk_pct"]
    daily = net.groupby(t["date"]).mean()  # equal capital split across the day's trades
    eq = daily.cumsum()
    yrs = net.groupby(t["date"].dt.year).mean()
    span = (t["date"].max() - t["date"].min()).days / 365.25 or 1
    allday_sharpe = daily.reindex(pd.bdate_range(t["date"].min(), t["date"].max()), fill_value=0)
    return {"setup": label, "trades": len(t), "per yr": round(len(t) / span), "win%": round(100 * (net > 0).mean(), 1),
            "avg net %": round(100 * net.mean(), 3), "avg R": round(R.mean(), 3),
            "PF": round(net[net > 0].sum() / -net[net <= 0].sum(), 2) if (net <= 0).any() else np.inf,
            "t-stat": round(net.mean() / net.std() * np.sqrt(len(net)), 2) if len(net) > 2 else np.nan,
            "yrs +": f"{(yrs > 0).sum()}/{len(yrs)}", "max DD %": round(100 * (eq - eq.cummax()).min(), 1),
            "sharpe": round(allday_sharpe.mean() / allday_sharpe.std() * np.sqrt(252), 2) if allday_sharpe.std() > 0 else np.nan}


def by_year(t: pd.DataFrame, cost: float) -> pd.Series:
    return (100 * (t["gross"] - cost)).groupby(t["date"].dt.year).mean().round(3)
