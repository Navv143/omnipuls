"""9 EMA / VWAP crossover on 5-min index bars (VWAP weighted by constituent-stock turnover; the index has no volume)."""
import numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from engine import Data, slot, NSLOT
import sweep_smi as SM, five_star as FS, momentum as MO, optmodel as M
d = Data(); vf = SM.volume_features(d); turn = vf["turnover"]; nz = vf["net_z"]
vr = turn / pd.DataFrame(turn).rolling(20, min_periods=10).mean().shift(1).values
vix = pd.DataFrame(d.C[d.idx("INDIA VIX")].reshape(-1)).ffill().bfill().values.reshape(d.C.shape[1], d.C.shape[2])

def ema9(d, s):
    C = d.C[s].reshape(-1); idx = np.where(np.isfinite(C))[0]
    e = np.full(len(C), np.nan); e[idx] = pd.Series(C[idx]).ewm(span=9, adjust=False).mean().to_numpy()
    return e.reshape(d.C[s].shape)

def run(sym, mode, filt=None, first="09:30", last="15:00", sq="15:15", rr=2.0):
    s = d.idx(sym); O, H, L, C = d.O[s], d.H[s], d.L[s], d.C[s]
    E = ema9(d, s); V = FS.indicators(d, sym, turn)["vwap"]
    f, la, xs = slot(first), slot(last), slot(sq); out = []
    for day in range(len(d.days)):
        pos = None
        for t in range(f, NSLOT):
            if not np.isfinite(C[day, t]): continue
            # manage
            if pos is not None:
                sd = pos["side"]; px = why = None
                if t >= xs: px, why = C[day, t], "15:15"
                elif pos["stop"] is not None and ((sd > 0 and L[day, t] <= pos["stop"]) or (sd < 0 and H[day, t] >= pos["stop"])):
                    px, why = (min(O[day, t], pos["stop"]) if sd > 0 else max(O[day, t], pos["stop"])), "stop"
                elif pos["tgt"] is not None and ((sd > 0 and H[day, t] >= pos["tgt"]) or (sd < 0 and L[day, t] <= pos["tgt"])):
                    px, why = (max(O[day, t], pos["tgt"]) if sd > 0 else min(O[day, t], pos["tgt"])), "target"
                if px is not None:
                    out.append({**pos["info"], "exit_slot": t, "exit": px, "reason": why, "pts": sd * (px - pos["entry"])}); pos = None
            if t >= xs: break
            if not (np.isfinite(E[day, t - 1]) and np.isfinite(V[day, t - 1]) and np.isfinite(V[day, t])): continue
            up = E[day, t] > V[day, t] and E[day, t - 1] <= V[day, t - 1]
            dn = E[day, t] < V[day, t] and E[day, t - 1] >= V[day, t - 1]
            side = 1 if up else (-1 if dn else 0)
            if side == 0: continue
            if pos is not None:  # opposite crossover: exit (and reverse)
                if pos["side"] != side:
                    out.append({**pos["info"], "exit_slot": t, "exit": C[day, t], "reason": "opposite cross",
                                "pts": pos["side"] * (C[day, t] - pos["entry"])}); pos = None
                else:
                    continue
            if t > la: continue
            if filt is not None and not filt(day, t, side): continue
            e = C[day, t]
            stop = tgt = None
            if mode != "sar":
                stop = L[day, t] if side > 0 else H[day, t]
                risk = side * (e - stop)
                if risk <= 0: continue
                tgt = e + side * rr * risk if mode == "stop_2R" else None
            pos = {"side": side, "entry": e, "stop": stop, "tgt": tgt,
                   "info": {"date": d.days[day], "side": side, "entry": e, "signal_slot": t, "entry_slot": t + 1}}
        if pos is not None:
            li = np.where(np.isfinite(C[day]))[0][-1]
            out.append({**pos["info"], "exit_slot": li, "exit": C[day, li], "reason": "eod", "pts": pos["side"] * (C[day, li] - pos["entry"])})
    return pd.DataFrame(out)

def dte(dd):
    wd = 3 if dd < pd.Timestamp("2025-09-01") else 1; n, x = 0, dd
    while True:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: n += 1
        if x.weekday() == wd: return n

def stats(t, lab, cost, sym):
    net = t.pts - cost; a = t.date < "2022"; ys = net.groupby(t.date.dt.year).sum(); eq = net.cumsum()
    di = np.array([d.days.get_loc(x) for x in t.date]); iv = vix[di, t.signal_slot.values] / 100
    D = np.full(len(t), 12.0) if sym == "NIFTY BANK" else np.array([dte(x) for x in t.date])
    o, _ = M.option_return(t.entry.values, t.exit.values, t.side.values, D, t.entry_slot.values, np.maximum(t.exit_slot.values, t.entry_slot.values), iv, cost=0.02)
    return {"setup": lab, "trades/yr": round(len(t) / 11.2), "win%": round(100 * (t.pts > 0).mean(), 1),
            "pts gross": round(t.pts.mean(), 1), f"net pts": round(net.mean(), 1), "t": round(net.mean() / net.std() * np.sqrt(len(t)), 2),
            "2015-21": round(net[a].mean(), 1), "2022-26": round(net[~a].mean(), 1), "yrs +": f"{(ys > 0).sum()}/{len(ys)}",
            "total pts": round(net.sum()), "max DD": round((eq - eq.cummax()).min()),
            "options %": round(100 * o.mean(), 1)}

rows = []
for sym, cost in (("NIFTY 50", 6), ("NIFTY BANK", 12)):
    m = MO.measures(d, sym)
    rsi, rx, body = m["rsi"], m["rng_x"], m["body"]
    F = {"none": None,
         "1.5x volume + net volume with trade": lambda day, t, sd: vr[day, t] >= 1.5 and sd * nz[day, t] >= 0,
         "+ RSI 65/35 + momentum candle": lambda day, t, sd: vr[day, t] >= 1.5 and sd * nz[day, t] >= 0 and
             (rsi[day, t] >= 65 if sd > 0 else rsi[day, t] <= 35) and rx[day, t] >= 1.5 and sd * body[day, t] >= 0.5}
    for mode, mlab in (("sar", "always in, reverse on cross"), ("stop_2R", "stop at cross candle, 2R target"),
                       ("stop_cross", "stop at cross candle, exit on opposite cross")):
        for fname, fn in F.items():
            if mode == "sar" and fname != "none": continue
            t = run(sym, mode, fn)
            if len(t) < 30: continue
            rows.append({"index": sym, **stats(t, f"{mlab} | filter: {fname}", cost, sym)}); print(rows[-1], flush=True)
out = pd.DataFrame(rows); out.to_csv("ema9_vwap_results.csv", index=False)
pd.set_option("display.width", 280, "display.max_columns", 30)
print(out.to_string(index=False))
