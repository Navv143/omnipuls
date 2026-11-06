"""Intraday commodity setups on hourly bars (IST, Yahoo front-month futures, Jun 2024 - Nov 2026). MCX day 09:30-23:30.
Entry next bar open after the signal bar closes, stop checked first inside each bar, exit at 23:30 (last bar close).
Cost per round trip: gold/silver 0.03%, crude/natgas/copper 0.04%."""
import pickle, numpy as np, pandas as pd
D = pickle.load(open("cmd.pkl", "rb"))
COST = {"GOLD": .03, "SILVER": .03, "CRUDE": .04, "NATGAS": .04, "COPPER": .04}

def days(h):
    h = h[(h.index.strftime("%H:%M") >= "09:30") & (h.index.strftime("%H:%M") <= "22:30")]
    return {d: g for d, g in h.groupby(h.index.normalize()) if len(g) >= 12}

def trade(g, i, side, stop, cost, tgt=None):
    """enter at bar i open; stop/target checked bar by bar from i; exit last close."""
    e = g.Open.iloc[i]
    if side * (e - stop) <= 0: return None
    for j in range(i, len(g)):
        lo, hi = g.Low.iloc[j], g.High.iloc[j]
        if (side > 0 and lo <= stop) or (side < 0 and hi >= stop):
            x = stop; break
        if tgt is not None and ((side > 0 and hi >= tgt) or (side < 0 and lo <= tgt)):
            x = tgt; break
    else:
        x = g.Close.iloc[-1]
    pct = side * (x / e - 1) * 100 - cost
    return pct, pct / (abs(e - stop) / e * 100)

def setups(k):
    h = D[k]["1h"]; dd = D[k]["1d"]
    datr = (dd.High - dd.Low).rolling(14).mean().shift()   # daily range average known before the day
    pdh, pdl, pdc = dd.High.shift(), dd.Low.shift(), dd.Close.shift()
    cost = COST[k]; out = []
    for d, g in days(h).items():
        if d not in datr.index or not np.isfinite(datr.get(d, np.nan)): continue
        A = datr[d]; hm = g.index.strftime("%H:%M")
        def rec(name, r, side):
            if r: out.append((d, name, side) + r)
        # I1 Asia range 09:30-13:30 -> breakout close 13:30-20:30
        def range_break(name, a, b, last="20:30", maxrisk=1.0):
            m = (hm >= a) & (hm < b)
            if m.sum() < 2: return
            H, L = g.High[m].max(), g.Low[m].min()
            if (H - L) > maxrisk * A: return
            for i in np.flatnonzero((hm >= b) & (hm <= last)):
                c = g.Close.iloc[i]
                sd = 1 if c > H else -1 if c < L else 0
                if sd and i + 1 < len(g):
                    rec(name, trade(g, i + 1, sd, L if sd > 0 else H, cost), sd)
                    rec(name + " (fade)", trade(g, i + 1, -sd, c + sd * 0.5 * A if True else 0, cost), -sd)
                    return
        range_break("Asia range break", "09:30", "13:30")
        range_break("Morning 2h ORB", "09:30", "11:30", "20:30", 0.8)
        range_break("London range break", "13:30", "17:30", "21:30")
        # I4 prior-day high/low break, and failed break
        if d in pdh.index and np.isfinite(pdh[d]):
            H, L = pdh[d], pdl[d]
            done = False
            for i in np.flatnonzero((hm >= "10:30") & (hm <= "21:30")):
                c = g.Close.iloc[i]
                sd = 1 if c > H else -1 if c < L else 0
                if sd and i + 1 < len(g):
                    rec("Prior-day H/L break", trade(g, i + 1, sd, c - sd * 0.4 * A, cost), sd)
                    done = True; break
            # failed break: high above PDH, close back below PDH -> short to PDC-ish, stop at the bar's high
            for i in np.flatnonzero((hm >= "10:30") & (hm <= "21:30")):
                b = g.iloc[i]
                if b.High > H and b.Close < H and i + 1 < len(g):
                    rec("Failed PDH/PDL break (fade)", trade(g, i + 1, -1, b.High + 0.05 * A, cost), -1); break
                if b.Low < L and b.Close > L and i + 1 < len(g):
                    rec("Failed PDH/PDL break (fade)", trade(g, i + 1, 1, b.Low - 0.05 * A, cost), 1); break
        # I6 / I7 NY continuation or fade of the day's move (09:30 open -> 18:30 close)
        i18 = np.flatnonzero(hm == "18:30")
        if len(i18):
            i = i18[0]; mv = g.Close.iloc[i - 1] - g.Open.iloc[0]
            if abs(mv) > 0.5 * A:
                sd = int(np.sign(mv))
                rec("Day move > 0.5 ATR: NY continue", trade(g, i, sd, g.Open.iloc[i] - sd * 0.5 * A, cost), sd)
                rec("Day move > 0.5 ATR: NY fade", trade(g, i, -sd, g.Open.iloc[i] + sd * 0.5 * A, cost), -sd)
        # I8 gap from yesterday's close at 09:30: fade / follow, exit 13:30? -> keep EOD
        if d in pdc.index and np.isfinite(pdc[d]):
            gp = g.Open.iloc[0] - pdc[d]
            if abs(gp) > 0.25 * A:
                sd = -int(np.sign(gp))
                rec("Gap > 0.25 ATR at 09:30: fade", trade(g, 0, sd, g.Open.iloc[0] - sd * 0.5 * A, cost), sd)
    t = pd.DataFrame(out, columns=["day", "setup", "side", "pct", "R"]); t["mkt"] = k
    return t

def stats(t):
    w = t.pct > 0; mid = t.day.sort_values().iloc[len(t) // 2]
    q = t.groupby(t.day.dt.to_period("Q")).R.mean()
    return pd.Series({"n": len(t), "win%": round(w.mean() * 100), "avg%": round(t.pct.mean(), 3), "avgR": round(t.R.mean(), 2),
                      "PF": round(t.pct[w].sum() / max(-t.pct[~w].sum(), 1e-9), 2),
                      "h1 R": round(t.R[t.day < mid].mean(), 2), "h2 R": round(t.R[t.day >= mid].mean(), 2),
                      "Q +": f"{(q > 0).sum()}/{len(q)}"})

if __name__ == "__main__":
    T = pd.concat([setups(k) for k in D]); T.to_pickle("intra_trades.pkl")
    pd.set_option("display.width", 220); pd.set_option("display.max_rows", 300)
    print(T.groupby(["setup", "mkt"]).apply(stats).to_string())
    # time-of-day drift: average hourly return by IST hour, per market, both halves
    print("\nAverage return % by IST hour bar (h1 | h2)")
    for k in D:
        h = D[k]["1h"]; r = (h.Close / h.Open - 1) * 100; hr = h.index.strftime("%H:%M"); mid = h.index[len(h) // 2]
        a = r[h.index < mid].groupby(hr[h.index < mid]).mean(); b = r[h.index >= mid].groupby(hr[h.index >= mid]).mean()
        z = pd.DataFrame({"h1": a, "h2": b}).round(3)
        z = z[(np.sign(z.h1) == np.sign(z.h2)) & ((z.h1.abs() > 0.02) & (z.h2.abs() > 0.02))]
        print(k, z.T.to_dict())
