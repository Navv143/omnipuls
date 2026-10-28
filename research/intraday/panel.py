"""Feature panel for every (stock, day), using only bars completed before the decision slot k.
k=1 -> decide at 09:20 (after the 09:15 bar), enter at the 09:20 bar open.  k=3 -> decide/enter at 09:30."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot

EXIT = slot("15:20")


def roll(a, n, fn="mean", shift=1):
    df = pd.DataFrame(a.T)
    r = getattr(df.rolling(n, min_periods=n), fn)()
    return r.shift(shift).values.T


def build(d: Data, k: int) -> pd.DataFrame:
    O, H, L, C, V = d.O, d.H, d.L, d.C, d.V
    with np.errstate(all="ignore"):
        hi_k = np.nanmax(H[..., :k], 2)
        lo_k = np.nanmin(L[..., :k], 2)
        last_k = C[..., k - 1]
        vol_k = np.nansum(V[..., :k], 2)
        entry = O[..., k]
        o0 = O[..., 0]
        pc = d.prev_close
        atrp = d.atr / pc
        f = {}
        f["gap"] = d.gap
        f["gap_atr"] = d.gap / atrp
        f["ret_k"] = last_k / o0 - 1
        f["ret_k_atr"] = f["ret_k"] / atrp
        f["day_ret_atr"] = (last_k / pc - 1) / atrp
        f["range_k_atr"] = (hi_k - lo_k) / pc / atrp
        f["pos_k"] = (last_k - lo_k) / (hi_k - lo_k)
        f["open_pos_k"] = (o0 - lo_k) / (hi_k - lo_k)
        f["rvol_k"] = vol_k / roll(vol_k, 20)
        f["rvol_k_5"] = vol_k / roll(vol_k, 5)
        f["atr_pct"] = atrp
        dret = d.dclose / pc - 1
        f["vol20"] = roll(dret, 20, "std", shift=1)
        f["atr_vs_vol"] = atrp / f["vol20"]
        f["prev_ret_atr"] = np.roll(dret, 1, axis=1) / atrp
        f["prev_oc_atr"] = np.roll(d.dclose / d.dopen - 1, 1, axis=1) / atrp
        prev_pos = (d.dclose - d.dlow) / (d.dhigh - d.dlow)
        f["prev_close_pos"] = np.roll(prev_pos, 1, axis=1)
        c5 = pd.DataFrame(d.dclose.T).shift(1)
        f["ret5_atr"] = (c5 / c5.shift(5) - 1).values.T / atrp
        f["ret20_atr"] = (c5 / c5.shift(20) - 1).values.T / atrp
        hh = pd.DataFrame(d.dhigh.T).rolling(20).max().shift(1).values.T
        ll = pd.DataFrame(d.dlow.T).rolling(20).min().shift(1).values.T
        f["dist_hi20_atr"] = (last_k / hh - 1) / atrp
        f["dist_lo20_atr"] = (last_k / ll - 1) / atrp
        f["above_prev_high"] = (last_k > np.roll(d.dhigh, 1, axis=1)).astype(float)
        f["below_prev_low"] = (last_k < np.roll(d.dlow, 1, axis=1)).astype(float)
        f["prev_vol_ratio"] = np.roll(d.dvol, 1, axis=1) / roll(d.dvol, 20, shift=2)
        # market context
        ni, bi, vi = d.idx("NIFTY 50"), d.idx("NIFTY BANK"), d.idx("INDIA VIX")
        S, D = d.gap.shape
        for name, j in (("nifty", ni), ("bank", bi)):
            f[f"{name}_gap"] = np.broadcast_to(d.gap[j], (S, D))
            f[f"{name}_ret_k"] = np.broadcast_to(C[j, :, k - 1] / O[j, :, 0] - 1, (S, D))
        f["vix_prev"] = np.broadcast_to(np.roll(d.dclose[vi], 1), (S, D))
        f["vix_open_chg"] = np.broadcast_to(C[vi, :, k - 1] / np.roll(d.dclose[vi], 1) - 1, (S, D))
        f["rel_ret_k"] = f["ret_k"] - f["nifty_ret_k"]
        # sector context (average of the other stocks in the sector)
        secs = np.array([d.sector[s] for s in d.syms])
        dr = last_k / pc - 1
        sec_dr = np.full_like(dr, np.nan)
        sec_gap = np.full_like(dr, np.nan)
        for sec in set(secs):
            m = np.where(secs == sec)[0]
            for arr, out in ((dr, sec_dr), (d.gap, sec_gap)):
                tot, cnt = np.nansum(arr[m], 0), np.isfinite(arr[m]).sum(0)
                for j in m:
                    c = cnt - np.isfinite(arr[j])
                    out[j] = np.where(c > 0, (tot - np.nan_to_num(arr[j])) / np.maximum(c, 1), np.nan)
        f["vs_sector_atr"] = (dr - sec_dr) / atrp
        f["sector_day"] = sec_dr
        f["gap_vs_sector"] = d.gap - sec_gap
        # cross-sectional ranks of the day
        for c in ("ret_k_atr", "rvol_k", "gap_atr", "range_k_atr"):
            f[c + "_xr"] = pd.DataFrame(np.where(d.valid, f[c], np.nan)).rank(axis=0, pct=True).values
        f["dow"] = np.broadcast_to(d.days.dayofweek.values, (S, D)).astype(float)
        # outcomes (NOT features)
        y = {}
        y["entry"] = entry
        y["exit"] = O[..., EXIT]
        y["ret_eod"] = y["exit"] / entry - 1
        y["ret_eod_atr"] = y["ret_eod"] / atrp
        y["mfe_up"] = np.nanmax(H[..., k:EXIT], 2) / entry - 1
        y["mfe_dn"] = 1 - np.nanmin(L[..., k:EXIT], 2) / entry
        y["iv"] = np.maximum(f["vol20"] * np.sqrt(252) * 1.15, 0.18)
    valid = d.valid & np.isfinite(entry) & np.isfinite(y["exit"]) & np.isfinite(atrp)
    valid[[d.idx(x) for x in ("NIFTY 50", "NIFTY BANK", "INDIA VIX")]] = False
    si, di = np.where(valid)
    cols = {c: np.asarray(v)[si, di] for c, v in {**f, **y}.items()}
    out = pd.DataFrame(cols)
    out.insert(0, "date", d.days[di])
    out.insert(1, "sym", np.array(d.syms)[si])
    out["s"], out["d"] = si, di
    return out


FEATURES = None  # set after build: all columns except ids/outcomes


def feature_cols(p: pd.DataFrame):
    skip = {"date", "sym", "s", "d", "entry", "exit", "ret_eod", "ret_eod_atr", "mfe_up", "mfe_dn", "iv"}
    return [c for c in p.columns if c not in skip]
