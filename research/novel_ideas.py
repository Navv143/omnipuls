"""Ten out-of-the-box ideas, written down BEFORE testing; each checked GROSS (no costs) and NET, on an early period
(train) and a later one (test). An idea only counts if it holds in BOTH periods with the same sign.

A  Hour-of-day map           BTC, gold (PAXG) 2023-2026 (UTC hours); Nifty, Bank Nifty 2023-2026 (1h bars, IST)
B  Crypto funding hours      BTC: the hour before / after 00, 08, 16 UTC vs other hours
C  Gold London fix           PAXG: the hour before / after the 10:30 and 15:00 London fixes
D  London -> New York        gold, BTC, EUR/USD, GBP/USD: does NY (13-16 UTC) reverse or continue London (07-12 UTC)?
E  BTC weekend -> Monday     weekend move (Fri 21:00 -> Sun 21:00 UTC) vs Monday's move
F  Narrow rally fades        5 indices (5-min, 60 days): index > 0.3% from open but weighted breadth with it < 45%
                             -> fade for 60 min; broad (> 70%) -> follow for 60 min
G  Heavyweights lead         5 indices: top-5 heavyweights' last-15-min move minus the index's -> next 15 min
H  Variance ratio regime     5 indices: VR(6) over 60 bars; after a 6-bar move > 1 ATR, follow when VR > 1.2, fade
                             when VR < 0.8, hold 6 bars
I  Quiet first hour          Nifty, Bank Nifty 2023-2026 (1h): first-hour range < 0.6x its 20-day average -> trade the
                             break of the first-hour range, exit 15:15; vs normal days
J  Morning leaders           180 F&O stocks (5-min, 60 days): top / bottom 5 by 9:15-10:15 move vs Nifty, held
                             10:15-15:15 (momentum) - and the reverse

Usage: python research/novel_ideas.py <scratchpad dir>   (paxg5m.pkl, btc5m.pkl, yahoo1h.pkl, yahoo_idx5m.pkl,
       fno60_new.pkl, pdf_data.pkl)
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import index_funnel as IF    # noqa: E402
import indices as IX         # noqa: E402

AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


def tstat(x):
    x = pd.Series(x).dropna()
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else np.nan


def line(name, gross, cost, split):
    """gross: Series of % returns per trade indexed by time; cost: % a round trip; split: train / test boundary."""
    g = gross.dropna()
    if len(g) < 10:
        return f"  {name:58s} n={len(g)}"
    tr, te = g[g.index < split], g[g.index >= split]
    net = g - cost
    pf = net[net > 0].sum() / -net[net < 0].sum() if (net < 0).any() else np.inf
    ok = len(tr) > 5 and len(te) > 5 and np.sign(tr.mean()) == np.sign(te.mean()) and abs(tstat(tr)) > 1.5 and abs(tstat(te)) > 1
    return (f"  {name:58s} n={len(g):5d} gross {g.mean():+.3f}% (t {tstat(g):+.1f}) | train {tr.mean():+.3f}% / test "
            f"{te.mean():+.3f}% | net {net.mean():+.3f}% PF {pf:.2f} win {(net > 0).mean() * 100:.0f}%"
            + ("  <== HOLDS" if ok else ""))


def utc(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    return d[~d.index.duplicated()].sort_index().dropna(subset=["Close"])


def ist(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    d = d[(d.index.second == 0)]
    return d[~d.index.duplicated()].sort_index().dropna(subset=["Close"])


# ---------------------------------------------------------------- A, B, C, D, E: global sessions

def idea_A(btc, gold, y1h):
    say("\nA  HOUR-OF-DAY MAP (mean % move of each hour; train 2023-2024, test 2025-2026; only hours that hold shown)")
    split = pd.Timestamp("2025-01-01")
    for name, d, cost in (("BTC", btc, 0.08), ("Gold (PAXG)", gold, 0.03)):
        h = d.resample("1h").agg(AGG).dropna(subset=["Close"])
        r = (h["Close"] / h["Open"] - 1) * 100
        r = r[r.index.dayofweek < 5] if name.startswith("Gold") else r
        shown = 0
        for hr in range(24):
            x = r[r.index.hour == hr]
            ln = line(f"{name} {hr:02d}:00-{hr + 1:02d}:00 UTC (long)", x, cost, split)
            if "HOLDS" in ln:
                say(ln)
                shown += 1
        if not shown:
            say(f"  {name}: no hour holds in both periods")
    for k in ("NIFTY", "BANKNIFTY"):
        d = ist(y1h[k])
        r = (d["Close"] / d["Open"] - 1) * 100
        shown = 0
        for slot, x in r.groupby(r.index.strftime("%H:%M")):
            ln = line(f"{k} {slot} hour (long)", x, 0.02, pd.Timestamp("2025-06-01"))
            if "HOLDS" in ln:
                say(ln)
                shown += 1
        if not shown:
            say(f"  {k}: no hour holds in both periods")


def idea_B(btc):
    say("\nB  CRYPTO FUNDING HOURS (BTC; funding at 00 / 08 / 16 UTC)")
    split = pd.Timestamp("2025-01-01")
    h = btc.resample("1h").agg(AGG).dropna(subset=["Close"])
    r = (h["Close"] / h["Open"] - 1) * 100
    before = r[r.index.hour.isin([23, 7, 15])]
    after = r[r.index.hour.isin([0, 8, 16])]
    other = r[~r.index.hour.isin([23, 7, 15, 0, 8, 16])]
    say(line("hour BEFORE funding (long)", before, 0.08, split))
    say(line("hour AFTER funding (long)", after, 0.08, split))
    say(line("other hours (long)", other, 0.08, split))
    # does the hour before funding reverse in the hour after?
    b = before.copy()
    b.index = b.index + pd.Timedelta(hours=1)
    j = pd.concat([b.rename("b"), after.rename("a")], axis=1).dropna()
    fade = -np.sign(j["b"]) * j["a"]
    say(line("fade the pre-funding hour in the hour after", fade, 0.08, split))


def idea_C(gold):
    say("\nC  GOLD LONDON FIX (PAXG; London time)")
    split = pd.Timestamp("2025-01-01")
    g = gold.copy()
    g.index = g.index.tz_localize("UTC").tz_convert("Europe/London").tz_localize(None)
    g = g[g.index.dayofweek < 5]
    for fix in ("10:30", "15:00"):
        hh, mm = int(fix[:2]), int(fix[3:])
        rows = []
        for day, z in g.groupby(g.index.normalize()):
            t = day + pd.Timedelta(hours=hh, minutes=mm)
            a, b, c = z[z.index <= t - pd.Timedelta(minutes=60)], z[z.index <= t], z[z.index <= t + pd.Timedelta(minutes=60)]
            if len(a) and len(b) and len(c) and b.index[-1] > a.index[-1] and c.index[-1] > b.index[-1]:
                rows.append({"t": t, "pre": (b["Close"].iloc[-1] / a["Close"].iloc[-1] - 1) * 100,
                             "post": (c["Close"].iloc[-1] / b["Close"].iloc[-1] - 1) * 100})
        x = pd.DataFrame(rows).set_index("t")
        say(line(f"hour before the {fix} fix (long)", x["pre"], 0.03, split))
        say(line(f"hour after the {fix} fix (long)", x["post"], 0.03, split))
        say(line(f"fade the pre-fix hour after the {fix} fix", -np.sign(x["pre"]) * x["post"], 0.03, split))
        say(line(f"follow the pre-fix hour after the {fix} fix", np.sign(x["pre"]) * x["post"], 0.03, split))


def idea_D(series: dict):
    say("\nD  LONDON (07-12 UTC) -> NEW YORK (13-16 UTC): fade vs follow London, only when London moved > 0.5 daily ATR")
    for name, (d, cost, split) in series.items():
        rows = []
        dd = d.resample("1D").agg(AGG).dropna(subset=["Close"])
        pc = dd["Close"].shift()
        tr = pd.concat([dd["High"] - dd["Low"], (dd["High"] - pc).abs(), (dd["Low"] - pc).abs()], axis=1).max(axis=1)
        atr = (tr.rolling(14).mean() / dd["Close"] * 100).shift()
        for day, z in d.groupby(d.index.normalize()):
            if day.dayofweek >= 5 and "BTC" not in name:
                continue

            def px(hh):
                w = z[z.index < day + pd.Timedelta(hours=hh)]
                return float(w["Close"].iloc[-1]) if len(w) else np.nan
            p7, p12, p13, p16 = px(7), px(12), px(13), px(16)
            a = atr.get(day, np.nan)
            if not all(np.isfinite([p7, p12, p13, p16, a])):
                continue
            lm = (p12 / p7 - 1) * 100
            if abs(lm) < 0.5 * a:
                continue
            rows.append({"t": day, "lon": lm, "ny": (p16 / p13 - 1) * 100})
        x = pd.DataFrame(rows).set_index("t") if rows else pd.DataFrame(columns=["lon", "ny"])
        if len(x) < 10:
            say(f"  {name}: too few days")
            continue
        say(line(f"{name}: FADE London in NY", -np.sign(x["lon"]) * x["ny"], cost, split))
        say(line(f"{name}: FOLLOW London in NY", np.sign(x["lon"]) * x["ny"], cost, split))


def idea_E(btc):
    say("\nE  BTC WEEKEND -> MONDAY (weekend = Fri 21:00 -> Sun 21:00 UTC, Monday = Sun 21:00 -> Mon 21:00)")
    split = pd.Timestamp("2025-01-01")
    c = btc["Close"].resample("1h").last().dropna()
    rows = []
    for t in c.index[(c.index.dayofweek == 6) & (c.index.hour == 21)]:
        f, s, m = t - pd.Timedelta(days=2), t, t + pd.Timedelta(days=1)
        if f in c.index and m in c.index:
            rows.append({"t": t, "wk": (c[s] / c[f] - 1) * 100, "mon": (c[m] / c[s] - 1) * 100})
    x = pd.DataFrame(rows).set_index("t")
    say(line("fade the weekend on Monday", -np.sign(x["wk"]) * x["mon"], 0.08, split))
    say(line("follow the weekend on Monday", np.sign(x["wk"]) * x["mon"], 0.08, split))
    big = x[x["wk"].abs() > x["wk"].abs().median()]
    say(line("fade a BIG weekend move on Monday", -np.sign(big["wk"]) * big["mon"], 0.08, split))

# ---------------------------------------------------------------- F, G, H: Indian indices intraday


def idea_FGH(idx5, stocks, W):
    say("\nF / G / H  INDIAN INDICES, 5-min, 60 days (train = first half of the days, test = second half)")
    F_n, F_b, G_, H_f, H_r = [], [], [], [], []
    for k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"):
        ix = ist(idx5[k])
        ix = ix[(ix.index.strftime("%H:%M") >= "09:15") & (ix.index.strftime("%H:%M") < "15:30")]
        t = IF.index_table(ix, stocks, W.get(k, {}), None)
        c = ix["Close"]
        day = ix.index.normalize()
        fwd12 = (c.groupby(day).shift(-12) / c - 1) * 100            # next 60 min
        fwd3 = (c.groupby(day).shift(-3) / c - 1) * 100              # next 15 min
        fwd6 = (c.groupby(day).shift(-6) / c - 1) * 100
        hm = ix.index.strftime("%H:%M")
        win = (hm >= "10:00") & (hm <= "14:00")
        mv = t["move_pct"].reindex(ix.index)
        bw = t["breadth_with"].reindex(ix.index)
        side = np.sign(mv)
        # F: one signal per day per kind (first bar that qualifies)
        narrow = win & (mv.abs() > 0.3) & (bw < 45)
        broad = win & (mv.abs() > 0.3) & (bw > 70)
        for mask, store, sgn in ((narrow, F_n, -1), (broad, F_b, 1)):
            m = pd.Series(mask, index=ix.index)
            first = m & (m.astype(int).groupby(day).cumsum() == 1)
            store.append((sgn * side * fwd12)[first].rename(k))
        # G: heavyweights' last-15-min move minus the index's
        top = sorted(W.get(k, {}).items(), key=lambda kv: -kv[1])[:5]
        hw = None
        for s, w in top:
            b = stocks.get(s)
            if b is None:
                continue
            r3 = (b["Close"] / b["Close"].groupby(b.index.normalize()).shift(3) - 1).reindex(ix.index) * 100
            hw = r3 * w if hw is None else hw + r3 * w
        if hw is not None:
            hw = hw / sum(w for _, w in top)
            gap = hw - (c / c.groupby(day).shift(3) - 1) * 100
            thr = gap.abs().quantile(0.9)
            sig = (gap.abs() > thr) & win
            G_.append((np.sign(gap) * fwd3)[sig].rename(k))
        # H: variance ratio regime
        r1 = c.pct_change()
        r6 = c.pct_change(6)
        vr = r6.rolling(60).var() / (6 * r1.rolling(60).var())
        pc = c.shift()
        trr = pd.concat([ix["High"] - ix["Low"], (ix["High"] - pc).abs(), (ix["Low"] - pc).abs()], axis=1).max(axis=1)
        atr = trr.rolling(14).mean()
        big = (c - c.shift(6)).abs() > atr * 1.0 * np.sqrt(6)
        mvs = np.sign(c - c.shift(6))
        H_f.append((mvs * fwd6)[big & (vr > 1.2) & win].rename(k))
        H_r.append((-mvs * fwd6)[big & (vr < 0.8) & win].rename(k))

    def cat(lst):
        s = pd.concat(lst).sort_index()
        return s[~s.index.duplicated()] if len(s) else s
    allx = cat(F_n + F_b + G_ + H_f + H_r)
    days = sorted(set(allx.index.normalize()))
    split = days[len(days) // 2] if days else None
    say(line("F  narrow rally (breadth < 45%) -> FADE 60 min", pd.concat(F_n).sort_index(), 0.02, split))
    say(line("F  broad move (breadth > 70%) -> FOLLOW 60 min", pd.concat(F_b).sort_index(), 0.02, split))
    if G_:
        say(line("G  heavyweights lead -> index next 15 min", pd.concat(G_).sort_index(), 0.02, split))
    say(line("H  big 30-min move, VR > 1.2 (trending) -> FOLLOW 30 min", pd.concat(H_f).sort_index(), 0.02, split))
    say(line("H  big 30-min move, VR < 0.8 (choppy) -> FADE 30 min", pd.concat(H_r).sort_index(), 0.02, split))


def idea_I(y1h):
    say("\nI  QUIET FIRST HOUR -> AFTERNOON BREAK (1h bars, 2023-2026; break of the first-hour range, exit 15:15)")
    split = pd.Timestamp("2025-06-01")
    for k in ("NIFTY", "BANKNIFTY"):
        d = ist(y1h[k])
        rows = []
        days = sorted(set(d.index.normalize()))
        fh = {}
        for day in days:
            z = d[d.index.normalize() == day]
            if len(z) < 5:
                continue
            fh[day] = float(z["High"].iloc[0] - z["Low"].iloc[0]) / float(z["Open"].iloc[0]) * 100
            avg = np.mean([fh[x] for x in list(fh)[-21:-1]]) if len(fh) > 20 else np.nan
            if not np.isfinite(avg):
                continue
            hi, lo = float(z["High"].iloc[0]), float(z["Low"].iloc[0])
            for i in range(1, len(z) - 1):
                cl = float(z["Close"].iloc[i])
                if cl > hi or cl < lo:
                    s = 1 if cl > hi else -1
                    e = float(z["Open"].iloc[i + 1])
                    x = float(z["Close"].iloc[-1])
                    rows.append({"t": day, "q": fh[day] / avg, "r": s * (x / e - 1) * 100})
                    break
        x = pd.DataFrame(rows).set_index("t")
        say(line(f"{k} quiet first hour (< 0.6x usual) -> trade the break", x[x["q"] < 0.6]["r"], 0.02, split))
        say(line(f"{k} normal first hour -> trade the break", x[x["q"] >= 0.6]["r"], 0.02, split))


def idea_J(stocks, nifty):
    say("\nJ  MORNING LEADERS (180 F&O stocks, 5-min, 60 days): 9:15-10:15 move vs Nifty, held 10:15-15:15")
    n = ist(nifty)
    rows = []
    for day in sorted(set(n.index.normalize()))[1:]:
        nz = n[n.index.normalize() == day]
        if len(nz) < 70:
            continue
        n_m = (nz[nz.index < day + pd.Timedelta(hours=10, minutes=15)]["Close"].iloc[-1] / nz["Open"].iloc[0] - 1) * 100
        rs = {}
        for s, b in stocks.items():
            z = b[b.index.normalize() == day]
            if len(z) < 70:
                continue
            m = z[z.index < day + pd.Timedelta(hours=10, minutes=15)]
            a = z[z.index >= day + pd.Timedelta(hours=10, minutes=15)]
            e_ = a[a.index < day + pd.Timedelta(hours=15, minutes=15)]
            if m.empty or e_.empty:
                continue
            rs[s] = ((m["Close"].iloc[-1] / z["Open"].iloc[0] - 1) * 100 - n_m,
                     (e_["Close"].iloc[-1] / a["Open"].iloc[0] - 1) * 100)
        if len(rs) < 50:
            continue
        srt = sorted(rs.items(), key=lambda kv: kv[1][0])
        lead = np.mean([v[1] for _, v in srt[-5:]])
        lag = np.mean([v[1] for _, v in srt[:5]])
        rows.append({"t": day, "mom": (lead - lag) / 2, "lead": lead, "lag": -lag})
    x = pd.DataFrame(rows).set_index("t")
    split = x.index[len(x) // 2]
    say(line("long top-5 leaders + short bottom-5 (momentum)", x["mom"], 0.12, split))
    say(line("  long leaders only", x["lead"], 0.12, split))
    say(line("  short laggards only", x["lag"], 0.12, split))
    say(line("REVERSE: long laggards + short leaders", -x["mom"], 0.12, split))


def main(argv):
    S = Path(argv[1])
    btc, gold = utc(pd.read_pickle(S / "btc5m.pkl")), utc(pd.read_pickle(S / "paxg5m.pkl"))
    y1h = pd.read_pickle(S / "yahoo1h.pkl")
    idx5 = pd.read_pickle(S / "yahoo_idx5m.pkl")
    st, _ = pickle.load(open(S / "fno60_new.pkl", "rb"))
    stocks = {s: ist(df) for s, df in st.items() if df is not None and len(df)}
    W = {k: d.get("w", {}) for k, d in IX.load().items()}
    pdd = pd.read_pickle(S / "pdf_data.pkl")
    say("TEN NEW IDEAS: gross (no costs) and net; train vs test; '<== HOLDS' = same sign in both, t > 1.5 / > 1")
    idea_A(btc, gold, y1h)
    idea_B(btc)
    idea_C(gold)
    idea_D({"Gold (PAXG)": (gold, 0.03, pd.Timestamp("2025-01-01")), "BTC": (btc, 0.08, pd.Timestamp("2025-01-01")),
            "EUR/USD": (utc(pdd[("EURUSD", "1h")]), 0.01, pd.Timestamp("2025-06-01")),
            "GBP/USD": (utc(pdd[("GBPUSD", "1h")]), 0.01, pd.Timestamp("2025-06-01"))})
    idea_E(btc)
    idea_FGH(idx5, stocks, W)
    idea_I(y1h)
    idea_J(stocks, idx5["NIFTY"])
    (S / "novel_ideas.txt").write_text("\n".join(OUT))


if __name__ == "__main__":
    main(sys.argv)
