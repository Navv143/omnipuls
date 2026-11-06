"""Crude oil and natural gas, intraday, for option trades (7 Nov 2026). No MCX option price history exists yet, so this
tests what option trades depend on, on the futures (hourly, IST, Jun 2024 - Nov 2026, cmd.pkl from get_data.py):
1. when the day's movement happens (share of price variance by IST window, both halves)
2. the weekly US inventory reports (crude Wed, natural gas Thu, 10:30 New York = 20:00 IST summer / 21:00 winter):
   the 2-hour move after the report vs the same window on other days
3. whether the report-hour move continues (to the next hour / to the close) or reverses
Contract-roll jumps (> 8% in a 2-hour window) are dropped. Results: research/COMMODITY_STUDY.md."""
import pickle

import numpy as np
import pandas as pd

D = pickle.load(open("cmd.pkl", "rb"))


def event_bar(day):
    ny = pd.Timestamp(f"{day.date()} 10:30").tz_localize("America/New_York").tz_convert("Asia/Kolkata")
    return (ny - pd.Timedelta(minutes=30)).strftime("%H:%M")


for k, dow in (("CRUDE", 2), ("NATGAS", 3)):
    h = D[k]["1h"]
    h = h[h.index.minute == 30]
    r = np.log(h.Close / h.Close.shift())
    r = r[h.index.to_series().diff() <= pd.Timedelta("1h")]
    hr = r.index.strftime("%H:%M")
    mid = r.index[len(r) // 2]
    for nm, (a, b) in {"Asia": ("09:30", "13:30"), "London": ("13:30", "18:30"), "US": ("18:30", "23:31")}.items():
        tot = lambda z: (z ** 2).sum()  # noqa: E731
        m = (hr >= "09:30") & (hr <= "23:30")
        w = (hr >= a) & (hr < b)
        print(k, nm, "variance share h1 %.1f%% h2 %.1f%%" % (tot(r[w & (r.index < mid)]) / tot(r[m & (r.index < mid)]) * 100,
                                                              tot(r[w & (r.index >= mid)]) / tot(r[m & (r.index >= mid)]) * 100))
    rows = []
    for day, g in h.groupby(h.index.normalize()):
        hm = g.index.strftime("%H:%M")
        i = np.flatnonzero(hm == event_bar(day))
        if not len(i) or i[0] < 1 or i[0] + 2 >= len(g):
            continue
        i = i[0]
        pre, ev = g.Close.iloc[i - 1], g.Close.iloc[i]
        mv2 = (g.Close.iloc[i + 1] / pre - 1) * 100
        if abs(mv2) > 8:
            continue
        rows.append((day, day.dayofweek == dow, abs(mv2), (ev / pre - 1) * 100, (g.Close.iloc[-1] / ev - 1) * 100))
    t = pd.DataFrame(rows, columns=["day", "event", "abs2h", "m1", "to_close"])
    e, o = t[t.event], t[~t.event]
    print(k, "report 2h |move| median %.2f%% vs other days %.2f%% (%.2fx)" % (e.abs2h.median(), o.abs2h.median(),
                                                                         e.abs2h.median() / o.abs2h.median()))
    big = e[e.m1.abs() >= 1.0]
    f = -np.sign(big.m1) * big.to_close
    print(k, "report hour >= 1%%: n=%d, fade to close %+.2f%% (win %.0f%%)" % (len(big), f.mean(), (f > 0).mean() * 100))
