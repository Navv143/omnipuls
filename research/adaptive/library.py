"""Strategy library: every strategy -> trades with date, sym, side, entry, exit, entry_slot, exit_slot, gross (fraction).
Costs and option returns are added in one place (add_costs). All entries use only information available at the time."""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")
from engine import Data, slot, walk, NSLOT
import strategies as S
import sweep_smi as SM
import five_star as FS
import five_star2 as F2
import momentum as MO
import internals as IN
import optmodel as M

IDX_COST, STK_COST = 0.0003, 0.0010


def _std(t: pd.DataFrame, sym=None) -> pd.DataFrame:
    t = t.copy()
    if sym is not None:
        t["sym"] = sym
    if "side" in t and not pd.api.types.is_numeric_dtype(t["side"]):
        t["side"] = np.where(t["side"].astype(str).str.lower().str.startswith(("l", "b")), 1, -1)
    if "gross" not in t:
        t["gross"] = t["side"] * (t["exit"] / t["entry"] - 1)
    for c in ("entry_slot", "exit_slot"):
        if c not in t:
            t[c] = np.nan
    return t[["date", "sym", "side", "entry", "exit", "entry_slot", "exit_slot", "gross"]]


def build_all(d: Data) -> dict:
    vf = SM.volume_features(d)
    turn, nz = vf["turnover"], vf["net_z"]
    vr = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
    fn = IN.build(d, "NIFTY 50")
    lib = {}
    # ---------------- index strategies (Nifty and Bank Nifty)
    for sym, tag in (("NIFTY 50", "NIFTY"), ("NIFTY BANK", "BANKNIFTY")):
        s = d.idx(sym)
        ind = FS.indicators(d, sym, turn)
        m = MO.measures(d, sym)
        mL = (m["rsi"] >= 65) & (m["rng_x"] >= 1.5) & (m["body"] >= 0.5) & (fn["breadth_vwap"] >= 0.6)
        mS = (m["rsi"] <= 35) & (m["rng_x"] >= 1.5) & (m["body"] <= -0.5) & (fn["breadth_vwap"] <= 0.4)

        def fs(**kw):
            t = F2.run(d, sym, ind, vr, nz, **kw)
            t["exit"] = t["entry"] + t["side"] * t["pts"]
            return _std(t, tag)
        lib[f"{tag} momentum (6 rules)"] = fs(vol_thr=1.5, net_align=True, exit_mode="trail", mom_long=mL, mom_short=mS)
        lib[f"{tag} momentum, up to 3/day"] = fs(vol_thr=1.5, net_align=True, exit_mode="trail", mom_long=mL, mom_short=mS, max_trades=3)
        lib[f"{tag} 5-STAR + volume + net vol, 3/day"] = fs(vol_thr=1.5, net_align=True, exit_mode="trail", max_trades=3)
        lib[f"{tag} 5-STAR raw trail, 3/day"] = fs(vol_thr=-1, exit_mode="trail", max_trades=3)
        for mode, vfil, lab in (("sweep", None, "sweep fade"), ("sweep", "fakeout", "sweep fade + volume"),
                                ("break", "confirmed", "level break follow + volume"), ("break", None, "level break follow")):
            t = SM.run(d, vf, mode, vfil, True, True, sym=sym, scale=1.0 if tag == "NIFTY" else 2.3)
            t["exit"] = t["entry"] + t["side"] * t["pts"]
            lib[f"{tag} {lab}"] = _std(t, tag)
        t = S.index_orb(d, sym)
        t["entry_slot"] = np.nan
        lib[f"{tag} 15-min ORB follow"] = _std(t.assign(side=np.where(t.side == "long", 1, -1)), tag)
        ev = IN.events(d, sym, IN.build(d, sym))
        lib[f"{tag} fade new 1-hour high/low"] = _std(ev.rename(columns={"slot": "entry_slot"}), tag)
    # ---------------- F&O stock strategies
    for lab, kw in (("STOCKS gap fade at 9:20", dict(kind="fade", entry="09:20")),
                    ("STOCKS gap-and-go at 9:20", dict(kind="go", entry="09:20"))):
        t = S.gap_setup(d, lab_kind := kw["kind"], 0.03, 2, 0.01, kw["entry"])
        lib[lab] = _std(t.assign(side=np.where(t.side == "long", 1, -1), entry_slot=1))
    for lab, kw in (("STOCKS top-movers ORB follow", dict(vol_filter=False, nifty_filter=False)),
                    ("STOCKS top-movers ORB fade", dict(vol_filter=False, nifty_filter=False, fade=True))):
        t = S.v3(d, **kw)
        t["entry_slot"] = [slot(x) + 1 for x in t["signal"]]
        lib[lab] = _std(t)
    ev = pd.read_parquet("/home/claude/bt/pdh_events_sim.parquet")
    ev = ev.sort_values(["date", "signal_slot"]).groupby("date").head(3)
    syms = d.syms
    for lab, col, sgn in (("STOCKS prev-day high/low break follow", "g_atr05", 1), ("STOCKS prev-day high/low break fade", "g_fade_atr05", -1)):
        x = ev.assign(sym=[syms[i] for i in ev.s], side=ev.side * sgn, gross=ev[col], exit=np.nan,
                      entry=np.nan, exit_slot=np.nan)
        lib[lab] = x[["date", "sym", "side", "entry", "exit", "entry_slot", "exit_slot", "gross"]]
    return lib


def add_costs(d: Data, lib: dict) -> dict:
    vix = pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1], d.C.shape[2])
    rv = pd.DataFrame(np.log(d.dclose / d.prev_close).T).rolling(20, min_periods=15).std().shift(1).values.T
    dte_m = M.dte_table(d.days)
    def wk(dd):
        wd = 3 if dd < pd.Timestamp("2025-09-01") else 1; n, x = 0, dd
        while True:
            x += pd.Timedelta(days=1)
            if x.weekday() < 5: n += 1
            if x.weekday() == wd: return n
    dpos = {x: i for i, x in enumerate(d.days)}
    out = {}
    for name, t in lib.items():
        t = t.dropna(subset=["gross"]).copy()
        t["side"] = pd.to_numeric(t["side"]).astype(int)
        t["date"] = pd.to_datetime(t["date"])
        index = name.startswith(("NIFTY", "BANKNIFTY"))
        t["net"] = t["gross"] - (IDX_COST if index else STK_COST)
        di = np.array([dpos.get(x, -1) for x in t["date"]])
        es = np.nan_to_num(t["entry_slot"].to_numpy(dtype=float), nan=6).clip(0, 74).astype(int)
        xs = np.nan_to_num(t["exit_slot"].to_numpy(dtype=float), nan=73).clip(0, 74).astype(int)
        xs = np.maximum(xs, es)
        if index:
            iv = vix[di, es] / 100
            bn_monthly = name.startswith("BANKNIFTY") & (t["date"] >= "2024-11-20")
            dte = np.where(bn_monthly, dte_m[di], [wk(x) for x in t["date"]])
        else:
            si = np.array([d.syms.index(s) for s in t["sym"]])
            iv = np.maximum(rv[si, di] * np.sqrt(252) * 1.15, 0.18)
            dte = dte_m[di]
        # option P&L from the underlying move (exit price implied by the gross return)
        e = np.ones(len(t)); x = 1 + t["side"].to_numpy() * t["gross"].to_numpy()
        t["opt"], _ = M.option_return(e, x, t["side"].to_numpy(), dte.astype(float), es, xs, iv, cost=0.02)
        out[name] = t
    return out
