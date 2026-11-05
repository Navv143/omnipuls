import sys, pickle, warnings, time; warnings.filterwarnings("ignore"); sys.path.insert(0, "research")
import numpy as np, pandas as pd, strategy_lab as L, algo_lab as A, sniper_study as SN
S = sys.argv[1]
MK = {"BTC": (lambda: pickle.load(open(f"{S}/btc5m.pkl", "rb")), 0.05), "ETH": (lambda: SN._load_zip_dir(f"{S}/ETHUSDT"), 0.05),
      "SOL": (lambda: SN._load_zip_dir(f"{S}/SOLUSDT"), 0.06), "GOLD": (lambda: pickle.load(open(f"{S}/paxg5m.pkl", "rb")), 0.02)}
V = []
for lv, hi, lo, wins, ok in (("Asia range", "asia_h", "asia_l", ((420, 720, "London"), (810, 1200, "NY")), "day"),
                             ("London range", "ldn_h", "ldn_l", ((810, 1200, "NY"),), "day"),
                             ("Prev day H/L", "pdh", "pdl", ((420, 1200, "07-20"),), "day"),
                             ("Prev 4H candle H/L", "h4_ph", "h4_pl", ((0, 1440, "24h"),), "h4_key"),
                             ("Prev 1H candle H/L", "h1_ph", "h1_pl", ((420, 1200, "07-20"),), "h1_key")):
    for a, b, wn in wins:
        for mode, tg in (("fade", "rr"), ("fade", "other"), ("break", "rr")):
            for bias in (None, "bias4h"):
                V.append((f"{lv} {mode}{'→other side' if tg == 'other' else ' 2R'} [{wn}]{' +4H bias' if bias else ''}",
                          lambda x, hi=hi, lo=lo, a=a, b=b, mode=mode, tg=tg, bias=bias, ok=ok: A.sweep_levels(x, hi, lo, (a, b), mode, 2.0, tg, bias, ok)))
V += [("VP prev day: fade VAH/VAL → POC", lambda x: A.vp_fade(x)),
      ("VP prev day: fade VAH/VAL → POC +4H bias", lambda x: A.vp_fade(x, bias="bias4h")),
      ("VP prev day: 80% rule", lambda x: A.vp_80(x)),
      ("VP Asia session: fade edges → POC [London-NY]", lambda x: A.vp_fade(x, "apoc", "avah", "aval", (420, 1200))),
      ("VP Asia session: fade edges +4H bias", lambda x: A.vp_fade(x, "apoc", "avah", "aval", (420, 1200), "bias4h"))]
for f_, s_, tf in ((9, 21, 1), (20, 50, 1), (9, 21, 3), (20, 50, 3)):
    for bias in (None, "bias4h"):
        V.append((f"EMA {f_}/{s_} cross {'5m' if tf == 1 else '15m'}{' +4H bias' if bias else ''}",
                  lambda x, f_=f_, s_=s_, tf=tf, bias=bias: A.ema_cross(x, f_, s_, tf, bias)))
V += [("EMA 9/21 cross + VWAP side 5m", lambda x: A.ema_cross(x, 9, 21, 1, None, True)),
      ("EMA 9/21 cross + VWAP side + 4H bias 5m", lambda x: A.ema_cross(x, 9, 21, 1, "bias4h", True)),
      ("VWAP cross with EMA9>21", lambda x: A.vwap_cross(x)),
      ("VWAP cross with EMA9>21 +4H bias", lambda x: A.vwap_cross(x, "bias4h")),
      ("HTF bias (4H+1H) + 5m EMA20 pullback 2R", lambda x: A.htf_pullback(x, 2.0)),
      ("HTF bias (4H+1H) + 5m EMA20 pullback 3R", lambda x: A.htf_pullback(x, 3.0))]
rows = []
for m, (load, C) in MK.items():
    t0 = time.time()
    raw = load()
    if m == "GOLD":
        raw = raw[raw.index.dayofweek < 5]
    x = A.add_profiles(A.prep(raw))
    print(f"{m}: prepared in {time.time() - t0:.0f}s", flush=True)
    for name, fn in V:
        side, st, tg = fn(x)
        t = L.simulate(x, side, np.asarray(st, float), np.asarray(tg, float), C, 2, 1200)
        if len(t) < 20:
            rows.append({"market": m, "setup": name, "n": len(t)})
            continue
        h = t["day"] < "2025-01-01"
        y = t.groupby(t["day"].dt.year)["r"].mean()
        rows.append({"market": m, "setup": name, "n": len(t), "per_wk": round(len(t) / ((t.day.max() - t.day.min()).days / 7), 1),
                     "win": round((t.r > 0).mean() * 100), "avgR": round(t.r.mean(), 3), "tune": round(t[h].r.mean(), 3),
                     "test": round(t[~h].r.mean(), 3), "yrs_pos": f"{(y > 0).sum()}/{len(y)}",
                     "t": round(t.r.mean() / t.r.std() * np.sqrt(len(t)), 2), "stop%": round(t.stop_pct.median(), 2)})
    pd.DataFrame(rows).to_csv(f"{S}/algo_results.csv", index=False)
print("done")
