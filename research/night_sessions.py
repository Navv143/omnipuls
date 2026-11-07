"""Night (IST evening) event setups for gold, BTC, crude and natural gas, fixed in advance; gross and net; train = first
half of the period, test = second. All times New York (ET), so daylight saving is handled; IST shown in the notes.

N1 US 08:30 ET data candle (18:00 / 19:00 IST): the 08:30-08:45 move; when it is >= 2x its usual size (20-day median
   of the same slot): FOLLOW or FADE from 08:45 for 1h / 2h.
N2 US 10:00 ET data candle (19:30 / 20:30 IST): same on 10:00-10:15.
N3 US stock open: the 09:30-10:00 move; FOLLOW / FADE from 10:00 to 11:30 and to 16:00.
N4 London close: the London session's move (03:00-11:00 ET); FOLLOW / FADE from 11:30 to 16:00 ET.
N5 Gold COMEX settlement (13:30 ET): the 12:30-13:30 move; FOLLOW / FADE 13:30-15:30.
N6 Weekly US oil / gas report (crude Wed, gas Thu 10:30 ET, inside the 10:00 hourly candle): FOLLOW / FADE the 10:00
   hour's move over the next 2 hours (11:00-13:00 ET); also only when the hour is >= 1.5x usual.
Data: BTC and gold (PAXG) 5-min 2023-2026; crude / natural gas 1-hour futures Jun 2024 - Nov 2026 (Yahoo).
Costs: BTC 0.08%, gold 0.03%, crude / gas 0.03%.

Usage: python research/night_sessions.py <scratchpad dir>
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


def et(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    d.index = idx.tz_convert("America/New_York").tz_localize(None)
    return d[~d.index.duplicated()].sort_index().dropna(subset=["Close"])


def tstat(x):
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else np.nan


def line(name, x, cost):
    x = x.dropna()
    if len(x) < 15:
        return f"  {name:66s} n={len(x)}"
    split = x.index[len(x) // 2]
    tr, te = x[x.index < split], x[x.index >= split]
    net = x - cost
    pf = net[net > 0].sum() / -net[net < 0].sum() if (net < 0).any() else np.inf
    hold = (tr.mean() - cost > 0) and (te.mean() - cost > 0) and tstat(tr) > 1.0 and tstat(te) > 1.0
    return (f"  {name:66s} n={len(x):4d} gross {x.mean():+.3f}% (t {tstat(x):+.1f}) | net train {tr.mean() - cost:+.3f} / "
            f"test {te.mean() - cost:+.3f} | net {net.mean():+.3f}% PF {pf:.2f} win {(net > 0).mean() * 100:.0f}%"
            + ("  <== HOLDS" if hold else ""))


def px_at(z, t, field="Close", before=True):
    w = z[z.index < t] if before else z[z.index >= t]
    if w.empty:
        return np.nan
    return float(w[field].iloc[-1] if before else w["Open"].iloc[0])


def window_events(d, start, end, weekdays=True):
    """Per day: move start->end (% of start); returns DataFrame indexed by day with px at start, end."""
    rows = []
    for day, z in d.groupby(d.index.normalize()):
        if weekdays and day.dayofweek >= 5:
            continue
        a, b = px_at(z, day + start), px_at(z, day + end)
        if np.isfinite(a) and np.isfinite(b) and (z.index < day + start).any() and (z.index >= day + end).any():
            rows.append({"day": day, "mv": (b / a - 1) * 100, "z": z})
    return rows


def fwd(z, day, t0, t1):
    a = px_at(z, day + t0, before=False)
    b = px_at(z, day + t1)
    return (b / a - 1) * 100 if np.isfinite(a) and np.isfinite(b) else np.nan


def impulse(d, name, cost, slot, holds, big=2.0):
    s0 = pd.Timedelta(hours=int(slot[:2]), minutes=int(slot[3:]))
    s1 = s0 + pd.Timedelta(minutes=15)
    ev = window_events(d, s0, s1)
    if not ev:
        return
    mv = pd.Series({e["day"]: e["mv"] for e in ev})
    usual = mv.abs().rolling(20, min_periods=10).median().shift(1)
    for h in holds:
        fo, fa = {}, {}
        for e in ev:
            u = usual.get(e["day"], np.nan)
            if not np.isfinite(u) or abs(e["mv"]) < big * u:
                continue
            r = fwd(e["z"], e["day"], s1, s1 + pd.Timedelta(hours=h))
            fo[e["day"]] = np.sign(e["mv"]) * r
            fa[e["day"]] = -np.sign(e["mv"]) * r
        say(line(f"{name}: big {slot} ET candle -> FOLLOW {h}h", pd.Series(fo, dtype=float), cost))
        say(line(f"{name}: big {slot} ET candle -> FADE {h}h", pd.Series(fa, dtype=float), cost))


def session_fade(d, name, cost, a, b, c, e_, tag):
    A, B = pd.Timedelta(hours=a[0], minutes=a[1]), pd.Timedelta(hours=b[0], minutes=b[1])
    C, E = pd.Timedelta(hours=c[0], minutes=c[1]), pd.Timedelta(hours=e_[0], minutes=e_[1])
    ev = window_events(d, A, B)
    fo, fa = {}, {}
    for e in ev:
        r = fwd(e["z"], e["day"], C, E)
        fo[e["day"]] = np.sign(e["mv"]) * r
        fa[e["day"]] = -np.sign(e["mv"]) * r
    say(line(f"{name}: {tag} -> FOLLOW", pd.Series(fo, dtype=float), cost))
    say(line(f"{name}: {tag} -> FADE", pd.Series(fa, dtype=float), cost))


def eia(h, name, cost, weekday):
    """h: 1h ET bars. The 10:00 hour on the report weekday; follow / fade 11:00-13:00."""
    rows = {}
    usual = []
    for day, z in h.groupby(h.index.normalize()):
        if day.dayofweek != weekday:
            continue
        bar = z[z.index == day + pd.Timedelta(hours=10)]
        if bar.empty:
            continue
        mv = (float(bar["Close"].iloc[0]) / float(bar["Open"].iloc[0]) - 1) * 100
        r = fwd(z, day, pd.Timedelta(hours=11), pd.Timedelta(hours=13))
        u = np.median(usual[-20:]) if len(usual) >= 8 else np.nan
        usual.append(abs(mv))
        rows[day] = (mv, r, u)
    x = pd.DataFrame(rows, index=["mv", "r", "u"]).T
    say(line(f"{name}: report hour -> FOLLOW 2h", np.sign(x["mv"]) * x["r"], cost))
    say(line(f"{name}: report hour -> FADE 2h", -np.sign(x["mv"]) * x["r"], cost))
    b = x[x["mv"].abs() >= 1.5 * x["u"]]
    say(line(f"{name}: BIG report hour (>= 1.5x usual) -> FOLLOW 2h", np.sign(b["mv"]) * b["r"], cost))
    say(line(f"{name}: BIG report hour (>= 1.5x usual) -> FADE 2h", -np.sign(b["mv"]) * b["r"], cost))


def main(argv):
    S = Path(argv[1])
    btc, gold = et(pd.read_pickle(S / "btc5m.pkl")), et(pd.read_pickle(S / "paxg5m.pkl"))
    pdd = pd.read_pickle(S / "pdf_data.pkl")
    say("NIGHT EVENT SETUPS (ET times; IST = ET + 9:30 in US summer, + 10:30 in US winter)")
    for name, d, cost in (("Gold", gold, 0.03), ("BTC", btc, 0.08)):
        say(f"\n--- {name} 2023-2026 ---")
        say("N1 / N2: data release candles")
        impulse(d, name, cost, "08:30", (1, 2))
        impulse(d, name, cost, "10:00", (1, 2))
        say("N3: US stock open")
        session_fade(d, name, cost, (9, 30), (10, 0), (10, 0), (11, 30), "09:30-10:00 move, 10:00-11:30")
        session_fade(d, name, cost, (9, 30), (10, 0), (10, 0), (16, 0), "09:30-10:00 move, 10:00-16:00")
        say("N4: London close")
        session_fade(d, name, cost, (3, 0), (11, 0), (11, 30), (16, 0), "London 03:00-11:00 move, 11:30-16:00")
        if name == "Gold":
            say("N5: COMEX settlement")
            session_fade(d, name, cost, (12, 30), (13, 30), (13, 30), (15, 30), "12:30-13:30 move, 13:30-15:30")
    say("\n--- N6: weekly US reports (1-hour futures, Jun 2024 - Nov 2026) ---")
    eia(et(pdd[("CRUDE", "1h")]), "Crude (Wed report)", 0.03, 2)
    eia(et(pdd[("NATGAS", "1h")]), "Natural gas (Thu report)", 0.03, 3)
    (S / "night_sessions.txt").write_text("\n".join(OUT))


if __name__ == "__main__":
    main(sys.argv)
