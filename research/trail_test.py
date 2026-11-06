"""Exit rules on past setup trades (5-min bars, Sep-Nov 2026): hold to 15:20 vs breakeven / trailing stops.
Entry next bar open after the signal bar, stop checked first, cost 0.12% a round trip."""
import pickle, numpy as np, pandas as pd
bars = pickle.load(open("fno60.pkl", "rb"))[0]
COST = 0.12
def run(g, i0, side, e, risk, A, rule):
    stop = e - side * risk; best = e
    for j in range(i0, len(g)):
        o, h, l, c = g.Open.iloc[j], g.High.iloc[j], g.Low.iloc[j], g.Close.iloc[j]
        if g.index[j].strftime("%H:%M") >= "15:20": return o
        if (side > 0 and l <= stop) or (side < 0 and h >= stop):
            return min(o, stop) if side > 0 else max(o, stop)
        best = max(best, h) if side > 0 else min(best, l)
        fav = side * (best - e)
        if rule == "be1R" and fav >= risk: stop = e if side > 0 and stop < e or side < 0 and stop > e else stop
        if rule == "be1R_trail1R" and fav >= risk:
            ns = best - side * risk; stop = max(stop, ns) if side > 0 else min(stop, ns)
        if rule == "trail1ATR":
            ns = best - side * 1.0 * A; stop = max(stop, ns) if side > 0 else min(stop, ns)
        if rule == "trail0.5ATR_after0.5":
            if fav >= 0.5 * A:
                ns = best - side * 0.5 * A; stop = max(stop, ns) if side > 0 else min(stop, ns)
        if rule == "lock50%_after1R" and fav >= risk:
            ns = e + side * 0.5 * fav; stop = max(stop, ns) if side > 0 else min(stop, ns)
    return g.Close.iloc[-1]
RULES = ["hold to 15:20", "be1R", "be1R_trail1R", "lock50%_after1R", "trail0.5ATR_after0.5", "trail1ATR"]
def test(ev, name, risk_atr):
    out = []
    for _, r in ev.iterrows():
        df = bars.get(r.sym)
        if df is None: continue
        g = df[df.index.normalize() == pd.Timestamp(r.day)]
        hm = g.index.strftime("%H:%M"); idx = np.flatnonzero(hm > r.t)
        if not len(idx): continue
        i0 = idx[0]; e = g.Open.iloc[i0]; side = int(r.side); risk = risk_atr * r.A
        row = {"day": r.day}
        for ru in RULES:
            x = run(g, i0, side, e, risk, r.A, ru)
            row[ru] = side * (x / e - 1) * 100 - COST
        out.append(row)
    t = pd.DataFrame(out); mid = t.day.sort_values().iloc[len(t) // 2]
    print(f"\n{name}: {len(t)} trades")
    print(pd.DataFrame({ru: {"avg %": t[ru].mean(), "win %": (t[ru] > 0).mean() * 100, "h1": t[ru][t.day < mid].mean(),
          "h2": t[ru][t.day >= mid].mean(), "worst day avg": t.groupby("day")[ru].mean().min()} for ru in RULES}).T.round(3))
ig = pd.read_pickle("ignition.pkl")
test(ig, "Ignition (stop 0.4 ATR)", 0.4)
gr = pd.read_pickle("grinder_paths.pkl"); gr = gr[gr.grinder.astype(bool)].copy()
gr = gr.rename(columns={"T": "t", "dir": "side"}); gr["A"] = gr["atr_pct"] / 100 * 1  # placeholder, fixed below
# grinder ATR in price: atr_pct of the price at T
def priceA(r):
    df = bars.get(r.sym); g = df[df.index.normalize() == pd.Timestamp(r.day)] if df is not None else None
    if g is None or g.empty: return np.nan
    return float(g.Close.iloc[0]) * r.atr_pct / 100
gr["A"] = gr.apply(priceA, axis=1); gr = gr.dropna(subset=["A"])
test(gr, "Grinder (stop 1 ATR)", 1.0)
