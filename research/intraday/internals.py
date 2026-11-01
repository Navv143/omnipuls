"""Index internals every 5 minutes, from the constituent stocks, and reversal events.

Event: the index makes a new 12-bar (1-hour) high or low on a bar between 09:45 and 14:30 (bar open time).
Trade (fade): entry at that bar's close, stop beyond the bar's extreme + 0.1 x daily ATR, target rr x risk,
exit 15:15. Every feature uses only bars up to and including the event bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot, NSLOT

NIFTY50 = ("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL CIPLA "
           "COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR ICICIBANK INDIGO "
           "INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT MM MARUTI MAXHEALTH NESTLEIND NTPC ONGC POWERGRID RELIANCE SBILIFE "
           "SHRIRAMFIN SBIN SUNPHARMA TCS TATACONSUM TMPV TATASTEEL TECHM TITAN TRENT ULTRACEMCO WIPRO").split()
BANKS = ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK"]
HEAVY = {"NIFTY 50": ["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "BHARTIARTL", "TCS", "LT", "ITC"],
         "NIFTY BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"]}


def _roll_max(a, n):  # rolling max over previous n bars within the day (excluding current), [day, slot]
    out = np.full_like(a, np.nan)
    for t in range(1, a.shape[1]):
        out[:, t] = np.nanmax(a[:, max(0, t - n):t], axis=1)
    return out


def _roll_min(a, n):
    out = np.full_like(a, np.nan)
    for t in range(1, a.shape[1]):
        out[:, t] = np.nanmin(a[:, max(0, t - n):t], axis=1)
    return out


def build(d: Data, index: str):
    members = NIFTY50 if index == "NIFTY 50" else BANKS
    mi = [d.idx(x) for x in members]
    O, H, L, C, V = (a[mi] for a in (d.O, d.H, d.L, d.C, d.V))
    pc = d.prev_close[mi][:, :, None]
    with np.errstate(all="ignore"):
        turn = np.nan_to_num(C * V)
        tp = (H + L + C) / 3
        vwap = np.cumsum(np.nan_to_num(tp) * np.nan_to_num(V), axis=2) / np.cumsum(np.nan_to_num(V), axis=2)
        valid = np.isfinite(C)
        n_valid = valid.sum(0)
        f = {}
        f["breadth_up"] = np.where(valid, C > pc, False).sum(0) / n_valid           # % up on the day
        f["breadth_vwap"] = np.where(valid, C > vwap, False).sum(0) / n_valid        # % above own VWAP
        dh = np.fmax.accumulate(np.nan_to_num(H, nan=-np.inf), axis=2)
        dl = np.fmin.accumulate(np.nan_to_num(L, nan=np.inf), axis=2)
        new_hi = np.where(valid, H >= dh, False); new_lo = np.where(valid, L <= dl, False)
        f["pct_new_hi"] = new_hi.sum(0) / n_valid
        f["pct_new_lo"] = new_lo.sum(0) / n_valid
        rng = H - L
        rng_avg = np.stack([pd.DataFrame(r.reshape(-1)).rolling(20, min_periods=10).mean().shift(1).values.reshape(r.shape)
                            for r in rng])
        f["range_x"] = np.nanmedian(rng / rng_avg, axis=0)                           # range expansion of members
        press = np.where(rng > 0, (C - O) / rng, 0)
        net = np.nansum(turn * np.nan_to_num(press), axis=0)
        tsum = turn.sum(0)
        avg_t = pd.DataFrame(tsum).rolling(20, min_periods=10).mean().shift(1).values
        f["vol_x"] = tsum / avg_t                                                     # volume x avg (same slot)
        f["vol_x_6"] = pd.DataFrame(f["vol_x"].T).rolling(6, min_periods=1).mean().values.T
        absn = pd.DataFrame(np.abs(net)).rolling(20, min_periods=10).mean().shift(1).values
        f["net_z"] = net / absn
        cvd = np.cumsum(net, axis=1)
        f["cvd"] = cvd
        hv = [members.index(x) for x in HEAVY[index] if x in members]
        rest = [i for i in range(len(members)) if i not in hv]
        r6 = C / np.concatenate([np.full(C.shape[:2] + (6,), np.nan), C[:, :, :-6]], axis=2) - 1
        f["heavy_minus_rest"] = np.nanmean(r6[hv], axis=0) - np.nanmean(r6[rest], axis=0)
    # index itself
    s = d.idx(index)
    iC, iH, iL, iO = d.C[s], d.H[s], d.L[s], d.O[s]
    datr = d.atr[s][:, None]
    w = turn.sum(0)
    itp = (iH + iL + iC) / 3
    ivwap = np.cumsum(np.nan_to_num(itp * w), axis=1) / np.cumsum(w, axis=1)
    f["idx_vwap_dist"] = (iC - ivwap) / datr
    f["idx_day_move"] = (iC - iO[:, [0]]) / datr
    c12 = np.concatenate([np.full((iC.shape[0], 12), np.nan), iC[:, :-12]], axis=1)
    f["idx_move_12"] = (iC - c12) / datr
    flat = iC.reshape(-1); ok = np.isfinite(flat)
    ch = np.diff(np.where(ok, flat, np.nan), prepend=np.nan)
    ch = pd.Series(ch).fillna(0).to_numpy()
    rma = lambda x: pd.Series(x).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    rsi = 100 - 100 / (1 + rma(np.maximum(ch, 0)) / np.maximum(rma(np.maximum(-ch, 0)), 1e-9))
    f["idx_rsi"] = rsi.reshape(iC.shape)
    f["hi12"] = _roll_max(iH, 12); f["lo12"] = _roll_min(iL, 12)
    f["cvd_max12"] = _roll_max(cvd, 12); f["cvd_min12"] = _roll_min(cvd, 12)
    f["bv_max12"] = _roll_max(f["breadth_vwap"], 12); f["bv_min12"] = _roll_min(f["breadth_vwap"], 12)
    return f


def events(d: Data, index: str, f: dict, rr=2.0, first="09:45", last="14:30", sq="15:15", buf=0.1):
    s = d.idx(index)
    O, H, L, C = d.O[s], d.H[s], d.L[s], d.C[s]
    datr = d.atr[s]
    f0, la, xs = slot(first), slot(last), slot(sq)
    rows = []
    for day in range(len(d.days)):
        busy = -1
        for t in range(f0, la + 1):
            if t <= busy or not np.isfinite(C[day, t]) or not np.isfinite(f["hi12"][day, t]):
                continue
            up = H[day, t] > f["hi12"][day, t]
            dn = L[day, t] < f["lo12"][day, t]
            if up == dn:
                continue
            side = -1 if up else 1  # fade
            e = C[day, t]
            stop = (H[day, t] + buf * datr[day]) if side < 0 else (L[day, t] - buf * datr[day])
            risk = side * (e - stop)
            if not risk > 0:
                continue
            tgt = e + side * rr * risk
            px = why = None
            xt = t
            for u in range(t + 1, NSLOT):
                if not np.isfinite(O[day, u]):
                    continue
                xt = u
                if u >= xs:
                    px, why = C[day, u], "15:15"; break
                if (side > 0 and L[day, u] <= stop) or (side < 0 and H[day, u] >= stop):
                    px, why = (min(O[day, u], stop) if side > 0 else max(O[day, u], stop)), "stop"; break
                if (side > 0 and H[day, u] >= tgt) or (side < 0 and L[day, u] <= tgt):
                    px, why = (max(O[day, u], tgt) if side > 0 else min(O[day, u], tgt)), "target"; break
            if px is None:
                li = np.where(np.isfinite(C[day]))[0][-1]; px, why, xt = C[day, li], "eod", li
            sd = side
            row = {"date": d.days[day], "slot": t, "side": side, "entry": e, "risk": risk, "exit": px, "exit_slot": xt,
                   "reason": why, "pts": side * (px - e), "R": side * (px - e) / risk}
            # features oriented so that positive = supports the fade
            pushdir = -side  # direction of the push being faded (+1 = new high)
            row.update({
                "breadth_up_dir": pushdir * (f["breadth_up"][day, t] - 0.5),
                "breadth_vwap_dir": pushdir * (f["breadth_vwap"][day, t] - 0.5),
                "breadth_div": -pushdir * (f["breadth_vwap"][day, t] - (f["bv_max12"][day, t] if pushdir > 0 else f["bv_min12"][day, t])),
                "pct_new_ext": f["pct_new_hi"][day, t] if pushdir > 0 else f["pct_new_lo"][day, t],
                "range_x": f["range_x"][day, t], "vol_x": f["vol_x"][day, t], "vol_x_6": f["vol_x_6"][day, t],
                "net_z_dir": pushdir * f["net_z"][day, t],
                "cvd_div": float((f["cvd"][day, t] < f["cvd_max12"][day, t]) if pushdir > 0 else (f["cvd"][day, t] > f["cvd_min12"][day, t])),
                "heavy_dir": pushdir * f["heavy_minus_rest"][day, t],
                "vwap_dist_dir": pushdir * f["idx_vwap_dist"][day, t], "day_move_dir": pushdir * f["idx_day_move"][day, t],
                "move12_dir": pushdir * f["idx_move_12"][day, t],
                "rsi_dir": pushdir * (f["idx_rsi"][day, t] - 50), "slot_t": t, "risk_atr": risk / datr[day]})
            rows.append(row)
            busy = xt  # one fade at a time
    return pd.DataFrame(rows)
