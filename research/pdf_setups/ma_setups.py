"""Two more PDF setups, on Indian indices, F&O stocks and MCX commodities, several timeframes.

A. Pawan Sharma triple SMMA: SMMA(11) crosses SMMA(21) on the chart timeframe; take it only if price is on the same side
   of the higher-timeframe SMMA(21) (2m / 5m chart -> 15m HTF, 15m chart -> 1h HTF, 1h chart -> daily HTF; the last
   COMPLETED HTF candle, no look-ahead). Entry within the first 4 candles after the cross (the first one where the HTF filter
   agrees), at the next candle's open. No crosses before 9:30, no new trades after 14:30. Stop: index 0.13% (= the PDF's
   30-35 Nifty points), stocks / commodities the recent swing (5 candles). Exit: the opposite cross ('cross-to-cross') or
   target 2R. Ablation: no HTF filter.
B. NK Singh Hilega-Milega: RSI(9), red = WMA(21) of RSI, green = EMA(3) of RSI, 50 MA on price.
   Long: RSI > 50, red below RSI, green above red, close above the 50 MA, close above the previous candle's high.
   Short: the mirror. Signal = the first candle where all hold. Entry at the next open; hard stop at the 5-candle swing;
   exit on a close back through the 50 MA or when the red line crosses back over RSI. No entries in the first 20 minutes
   or after 14:30. The PDF's literal 'green crosses ABOVE RSI' for longs is run as a variant. Ablation: no 50 MA filter.
Intraday: out at 15:20 (MCX 23:20). Swing: no time exit (15m / 1h). Costs a round trip: index 0.03%, stocks 0.12%,
commodities 0.03%. One position at a time per instrument.

Usage: python research/pdf_setups/ma_setups.py <pdf_data.pkl> <fno60_new.pkl> <yahoo1h.pkl>
"""
import pickle
import sys

import numpy as np
import pandas as pd

AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
SESS = {"IN": ("09:15", "15:30", "15:20"), "MCX": ("09:00", "23:30", "23:20")}
HTF = {"2m": "15min", "5m": "15min", "15m": "60min", "1h": "1D"}


def ist(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def smma(x, n):
    return x.ewm(alpha=1 / n, adjust=False).mean()


def wma(x, n):
    w = np.arange(1, n + 1)
    return x.rolling(n).apply(lambda v: (v * w).sum() / w.sum(), raw=True)


def rsi(c, n):
    d = c.diff()
    up, dn = smma(d.clip(lower=0), n), smma(-d.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def htf_line(d, tf, kind):
    """SMMA(21) of the higher timeframe, value of the last completed HTF candle at each chart candle."""
    rule = HTF[tf]
    off = "15min" if kind == "IN" and rule != "1D" else None
    h = d["Close"].resample(rule, offset=off).last().dropna() if off else d["Close"].resample(rule).last().dropna()
    line = smma(h, 21)
    step = pd.Timedelta(rule) if rule != "1D" else pd.Timedelta(days=1)
    line.index = line.index + step               # known only once that HTF candle is complete
    return line.reindex(d.index, method="ffill")


def simulate(d, sigs, cost, exit_hm, intraday, exit_long, exit_short, target_r=None):
    """sigs: list of (i_signal, side, stop). Entry next open; stop first, then target, then close-based exit -> next open."""
    o, h, l, c = (d[k].values for k in ("Open", "High", "Low", "Close"))
    hm = d.index.strftime("%H:%M").values
    day = d.index.normalize().values
    n, out, busy_until = len(d), [], -1
    for i_s, side, stop in sigs:
        i = i_s + 1
        if i <= busy_until or i >= n or day[i] != day[i_s] or (intraday and hm[i] >= exit_hm):
            continue
        e = float(o[i])
        risk = side * (e - stop)
        if risk <= 0:
            continue
        tg = e + side * target_r * risk if target_r else None
        x, j = None, i
        while j < n:
            if intraday and (hm[j] >= exit_hm or day[j] != day[i]):
                x = float(o[j]) if day[j] == day[i] else float(c[j - 1])
                break
            if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
                x = min(o[j], stop) if side > 0 else max(o[j], stop)
                break
            if tg is not None and ((side > 0 and h[j] >= tg) or (side < 0 and l[j] <= tg)):
                x = max(o[j], tg) if side > 0 else min(o[j], tg)
                break
            if (exit_long[j] if side > 0 else exit_short[j]) and j + 1 < n:
                x = float(o[j + 1])
                j += 1
                break
            j += 1
        if x is None:
            x, j = float(c[-1]), n - 1
        busy_until = j
        out.append({"day": pd.Timestamp(day[i]), "side": side, "pct": side * (x / e - 1) * 100 - cost,
                    "risk_pct": risk / e * 100, "bars": j - i})
    return out


def triple_smma(d, tf, kind, cost, intraday, use_htf=True, exit_rule="cross"):
    op, _, ex = SESS[kind]
    f, s = smma(d["Close"], 11), smma(d["Close"], 21)
    line = htf_line(d, tf, kind)
    above = (f > s).values
    cross = np.r_[0, np.diff(above.astype(int))]          # +1 bull cross, -1 bear cross
    c, lo, hi = d["Close"].values, d["Low"].rolling(5).min().values, d["High"].rolling(5).max().values
    hm = d.index.strftime("%H:%M").values
    sigs = []
    for k in np.nonzero(cross)[0]:
        side = int(cross[k])
        if hm[k] < ("09:30" if kind == "IN" else "09:15"):
            continue
        for m in range(k, min(k + 4, len(d))):
            if hm[m] > "14:30" and kind == "IN" or (m > k and cross[m] != 0):
                break
            if not use_htf or np.isnan(line.iloc[m]) or (c[m] > line.iloc[m] if side > 0 else c[m] < line.iloc[m]):
                if use_htf and np.isnan(line.iloc[m]):
                    break
                if kind == "IN" and len(d) and d.attrs.get("index"):
                    stop = c[m] * (1 - side * 0.0013)
                else:
                    stop = lo[m] if side > 0 else hi[m]
                sigs.append((m, side, stop))
                break
    ex_l, ex_s = (cross == -1), (cross == 1)
    if exit_rule == "cross":
        return simulate(d, sigs, cost, ex, intraday, ex_l, ex_s)
    return simulate(d, sigs, cost, ex, intraday, np.zeros(len(d), bool), np.zeros(len(d), bool), target_r=2.0)


def hilega(d, kind, cost, intraday, use_ma=True, literal=False):
    op, _, ex = SESS[kind]
    r = rsi(d["Close"], 9)
    red, green = wma(r, 21), r.ewm(span=3, adjust=False).mean()
    ma = d["Close"].rolling(50).mean()
    c, ph, pl = d["Close"], d["High"].shift(), d["Low"].shift()
    gl = (green > r) if literal else (green > red)
    gs = (green < r) if literal else (green < red)
    L = (r > 50) & (red < r) & gl & (c > ph) & ((c > ma) if use_ma else True)
    S = (r < 50) & (red > r) & gs & (c < pl) & ((c < ma) if use_ma else True)
    Lf, Sf = (L & ~L.shift(fill_value=False)).values, (S & ~S.shift(fill_value=False)).values
    hm = d.index.strftime("%H:%M").values
    first = "09:35" if kind == "IN" else "09:20"
    lo, hi = d["Low"].rolling(5).min().values, d["High"].rolling(5).max().values
    sigs = [(i, 1 if Lf[i] else -1, lo[i] if Lf[i] else hi[i]) for i in range(len(d))
            if (Lf[i] or Sf[i]) and first <= hm[i] <= ("14:30" if kind == "IN" else "22:30")]
    ex_l = ((c < ma) | (red > r)).values if use_ma else (red > r).values
    ex_s = ((c > ma) | (red < r)).values if use_ma else (red < r).values
    return simulate(d, sigs, cost, ex, intraday, ex_l, ex_s)


def stat(t):
    if len(t) < 10:
        return None
    p = t["pct"]
    half = t["day"].sort_values().iloc[len(t) // 2]
    eq = p.cumsum()
    return {"n": len(p), "win%": round((p > 0).mean() * 100), "avg %": round(p.mean(), 3),
            "t": round(p.mean() / p.std() * np.sqrt(len(p)), 2), "total %": round(p.sum(), 1),
            "h1": round(p[t["day"] < half].mean(), 3), "h2": round(p[t["day"] >= half].mean(), 3),
            "maxDD %": round((eq - eq.cummax()).min(), 1), "avg bars": round(t["bars"].mean(), 1)}


def session(df, kind):
    d = ist(df)
    op, cl, _ = SESS[kind]
    hm = d.index.strftime("%H:%M")
    return d[(hm >= op) & (hm < cl) & (d.index.dayofweek < 5)]


def main(argv):
    data = pd.read_pickle(argv[1])
    stocks, _ = pickle.load(open(argv[2], "rb"))
    y1h = pd.read_pickle(argv[3])
    st5 = {s: session(df, "IN") for s, df in stocks.items() if df is not None and len(df)}
    jobs = []
    for m in ("NIFTY", "BANKNIFTY"):
        for tf in ("2m", "5m", "15m", "1h"):
            jobs.append((m, tf, "IN", 0.03, {m: session(data[(m, tf)], "IN")}, True))
    jobs.append(("F&O STOCKS", "5m", "IN", 0.12, st5, False))
    jobs.append(("F&O STOCKS", "15m", "IN", 0.12, {s: df.resample("15min", offset="15min").agg(AGG).dropna(subset=["Close"])
                                                   for s, df in st5.items()}, False))
    jobs.append(("F&O STOCKS", "1h", "IN", 0.12, {s: session(df, "IN") for s, df in y1h.items()
                                                  if s not in ("NIFTY", "BANKNIFTY") and len(df)}, False))
    for tf in ("5m", "15m", "1h"):
        jobs.append(("MCX (COMEX/NYMEX)", tf, "MCX", 0.03,
                     {m: session(data[(m, tf)], "MCX") for m in ("GOLD", "SILVER", "CRUDE", "NATGAS")}, False))
    rows = []
    for grp, tf, kind, cost, dfs, is_index in jobs:
        variants = {}
        for name, d in dfs.items():
            if len(d) < 200:
                continue
            d.attrs["index"] = is_index
            modes = [("intraday", True)] + ([("swing", False)] if tf in ("15m", "1h") else [])
            for mode, intra in modes:
                for v, fn in (
                        ("SMMA: PDF (HTF filter, cross exit)", lambda: triple_smma(d, tf, kind, cost, intra)),
                        ("SMMA: HTF filter, 2R target", lambda: triple_smma(d, tf, kind, cost, intra, exit_rule="2R")),
                        ("SMMA: NO HTF filter", lambda: triple_smma(d, tf, kind, cost, intra, use_htf=False)),
                        ("H-M: PDF (50 MA filter)", lambda: hilega(d, kind, cost, intra)),
                        ("H-M: literal green>RSI", lambda: hilega(d, kind, cost, intra, literal=True)),
                        ("H-M: NO 50 MA filter", lambda: hilega(d, kind, cost, intra, use_ma=False))):
                    variants.setdefault((mode, v), []).extend(fn())
        for (mode, v), tr in variants.items():
            st = stat(pd.DataFrame(tr))
            if st:
                rows.append({"group": grp, "tf": tf, "mode": mode, "setup": v, **st})
        print(grp, tf, "done", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(argv[1].replace("pdf_data.pkl", "ma_setups_results.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 1000)
    print(res.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv)
