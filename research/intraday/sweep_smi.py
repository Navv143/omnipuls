"""Nifty liquidity sweep + "smart money" volume (net and cumulative volume built from the constituent stocks).

Nifty index bars have no volume, so per 5-min bar:
  net  = sum over stocks of turnover * (close - open) / (high - low)      (buying minus selling pressure, Rs)
  cvd  = cumulative net since 09:15 (resets daily)
  net_z = net / average |net| of the same time slot over the previous 20 days
Levels (as nifty_sweep_backtest.py): previous-day high/low and the 9:15-9:30 range high/low, each used once a day.
Sweep (fade) at a level L (bearish example): high goes 5-60 pts above L and the candle closes back below L.
  volume filter 'fakeout': cumulative volume did NOT confirm the poke (cvd below its max of the last N bars while price
  made the N-bar high)  OR  the sweep candle's net volume is negative (selling into the poke).
Break (follow): first close beyond L by >= 5 pts; volume filter 'confirmed': cvd at a new N-bar high and net_z >= 1.
Entry at the signal candle's close, stop beyond the candle (+5 pts, risk <= 60 pts), target 2R, square-off 15:15,
entries 9:30-14:30, max 2 trades/day. Points are Nifty points; costs applied later.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot, NSLOT, INDEXES


def volume_features(d: Data) -> dict:
    si = [i for i in d.stock_idx]
    O, H, L, C, V = (a[si] for a in (d.O, d.H, d.L, d.C, d.V))
    with np.errstate(all="ignore"):
        rng = H - L
        press = np.where(rng > 0, (C - O) / rng, 0.0)
        turn = np.nan_to_num(C * V)
        net = np.nansum(turn * np.nan_to_num(press), axis=0)  # [day, slot]
        gross = np.nansum(turn, axis=0)
    cvd = np.cumsum(net, axis=1)
    absn = pd.DataFrame(np.abs(net))  # rows = days, cols = slots
    avg_abs = absn.rolling(20, min_periods=10).mean().shift(1).values
    net_z = net / np.where(avg_abs > 0, avg_abs, np.nan)
    return {"net": net, "cvd": cvd, "net_z": net_z, "turnover": gross}


def run(d: Data, vf: dict, mode="sweep", vol_filter=None, use_day=True, use_or=True, n_div=12, min_sweep=5.0,
        max_sweep=60.0, sl_buffer=5.0, max_risk=60.0, rr=2.0, max_trades=2, z_break=1.0):
    s = d.idx("NIFTY 50")
    O, H, L, C = d.O[s], d.H[s], d.L[s], d.C[s]
    cvd, net, nz = vf["cvd"], vf["net"], vf["net_z"]
    e0, e1, sq = slot("09:30"), slot("14:30"), slot("15:15")
    out = []
    for day in range(1, len(d.days)):
        pdh, pdl = d.dhigh[s, day - 1], d.dlow[s, day - 1]
        orh, orl = np.nanmax(H[day, :3]), np.nanmin(L[day, :3])
        levels = []
        if use_day:
            levels += [("PDH", pdh, -1), ("PDL", pdl, 1)]
        if use_or:
            levels += [("ORH", orh, -1), ("ORL", orl, 1)]
        used = set()
        pos, n_tr = None, 0
        for t in range(e0, NSLOT):
            if not np.isfinite(C[day, t]):
                continue
            # manage position
            if pos is not None and t > pos["t"]:
                px = why = None
                sd = pos["side"]
                if (sd > 0 and L[day, t] <= pos["stop"]) or (sd < 0 and H[day, t] >= pos["stop"]):
                    px, why = (min(O[day, t], pos["stop"]) if sd > 0 else max(O[day, t], pos["stop"])), "stop"
                elif (sd > 0 and H[day, t] >= pos["tgt"]) or (sd < 0 and L[day, t] <= pos["tgt"]):
                    px, why = (max(O[day, t], pos["tgt"]) if sd > 0 else min(O[day, t], pos["tgt"])), "target"
                if px is None and t >= sq:
                    px, why = C[day, t], "square-off"
                if px is not None:
                    out.append({**pos["info"], "exit": px, "exit_slot": t, "reason": why,
                                "pts": sd * (px - pos["entry"])})
                    pos = None
            if t >= sq:
                break
            if not (t < e1 and pos is None and n_tr < max_trades):
                continue
            lo = max(0, t - n_div)
            prior_cvd_max = np.max(cvd[day, lo:t]) if t > lo else -np.inf
            prior_cvd_min = np.min(cvd[day, lo:t]) if t > lo else np.inf
            prior_hi = np.nanmax(H[day, lo:t]) if t > lo else -np.inf
            prior_lo = np.nanmin(L[day, lo:t]) if t > lo else np.inf
            for name, lv, fade_side in levels:
                if name in used or not np.isfinite(lv):
                    continue
                sig = None
                if mode == "sweep":
                    if fade_side < 0 and lv + min_sweep <= H[day, t] <= lv + max_sweep and C[day, t] < lv:
                        div = H[day, t] >= prior_hi and cvd[day, t] < prior_cvd_max
                        fake = div or net[day, t] < 0
                        sig = (-1, H[day, t] + sl_buffer, fake, div)
                    elif fade_side > 0 and lv - max_sweep <= L[day, t] <= lv - min_sweep and C[day, t] > lv:
                        div = L[day, t] <= prior_lo and cvd[day, t] > prior_cvd_min
                        fake = div or net[day, t] > 0
                        sig = (1, L[day, t] - sl_buffer, fake, div)
                    if sig is None:
                        continue
                    used.add(name)
                    side, stop, fake, div = sig
                    if vol_filter == "fakeout" and not fake:
                        continue
                    if vol_filter == "divergence" and not div:
                        continue
                    if vol_filter == "no_fakeout" and fake:
                        continue
                else:  # break: follow a close beyond the level
                    if fade_side < 0 and C[day, t] >= lv + min_sweep and C[day, t - 1] < lv + min_sweep:
                        conf = cvd[day, t] >= prior_cvd_max and nz[day, t] >= z_break
                        sig = (1, min(L[day, t], lv) - sl_buffer, conf)
                    elif fade_side > 0 and C[day, t] <= lv - min_sweep and C[day, t - 1] > lv - min_sweep:
                        conf = cvd[day, t] <= prior_cvd_min and nz[day, t] <= -z_break
                        sig = (-1, max(H[day, t], lv) + sl_buffer, conf)
                    if sig is None:
                        continue
                    used.add(name)
                    side, stop, conf = sig
                    if vol_filter == "confirmed" and not conf:
                        continue
                    if vol_filter == "unconfirmed" and conf:
                        continue
                entry = C[day, t]
                risk = side * (entry - stop)
                if not (0 < risk <= max_risk):
                    continue
                pos = {"side": side, "entry": entry, "stop": stop, "tgt": entry + side * rr * risk, "t": t,
                       "info": {"date": d.days[day], "side": side, "level": name, "entry": entry, "risk": risk,
                                "entry_slot": t + 1, "net_z": nz[day, t]}}
                n_tr += 1
                break
        if pos is not None:
            last = np.where(np.isfinite(C[day]))[0][-1]
            out.append({**pos["info"], "exit": C[day, last], "exit_slot": last, "reason": "eod",
                        "pts": pos["side"] * (C[day, last] - pos["entry"])})
    return pd.DataFrame(out)
