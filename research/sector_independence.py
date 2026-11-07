"""Which sectors do NOT move with Nifty / BankNifty?

1. Daily, 3 years: NSE sector indices vs Nifty and BankNifty - correlation, beta, % of days the sector closes the
   opposite way, and how often it is up on a Nifty down day (> 0.5% down) and down on a Nifty up day.
2. Intraday, last 60 days (5-min F&O stocks, equal weight per sector): correlation of 5-min returns with Nifty and % of
   days the sector's day move is opposite to Nifty's.

Usage: python research/sector_independence.py <fno60_new.pkl>
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U      # noqa: E402

IDX = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "IT": "^CNXIT", "PHARMA": "^CNXPHARMA", "FMCG": "^CNXFMCG",
       "AUTO": "^CNXAUTO", "METAL": "^CNXMETAL", "REALTY": "^CNXREALTY", "ENERGY": "^CNXENERGY", "PSU BANK": "^CNXPSUBANK",
       "MEDIA": "^CNXMEDIA", "INFRA": "^CNXINFRA", "PSE": "^CNXPSE", "FIN SERVICE": "NIFTY_FIN_SERVICE.NS",
       "MIDCAP 100": "NIFTY_MIDCAP_100.NS", "CONSUMPTION": "^CNXCONSUM", "COMMODITIES": "^CNXCMDT"}


def daily():
    px = {}
    for k, t in IDX.items():
        d = yf.download(t, period="3y", interval="1d", progress=False, auto_adjust=False)
        if len(d):
            d = d.droplevel(1, axis=1) if isinstance(d.columns, pd.MultiIndex) else d
            cl = d["Close"]
            px[k] = cl.iloc[:, 0] if isinstance(cl, pd.DataFrame) else cl
    r = pd.DataFrame(px).pct_change().dropna(how="all") * 100
    rows = []
    for k in r.columns:
        if k == "NIFTY":
            continue
        z = r[list(dict.fromkeys([k, "NIFTY", "BANKNIFTY"]))].dropna()
        if len(z) < 100:
            continue
        n, s = z["NIFTY"], z[k]
        rows.append({"sector index": k, "days": len(z), "corr Nifty": round(s.corr(n), 2),
                     "corr BankNifty": round(s.corr(z["BANKNIFTY"]), 2), "beta Nifty": round(s.cov(n) / n.var(), 2),
                     "opposite day %": round((np.sign(s) != np.sign(n)).mean() * 100),
                     "up on Nifty down day %": round((s[n < -0.5] > 0).mean() * 100),
                     "down on Nifty up day %": round((s[n > 0.5] < 0).mean() * 100),
                     "avg on Nifty down day": round(s[n < -0.5].mean(), 2),
                     "avg on Nifty up day": round(s[n > 0.5].mean(), 2)})
    return pd.DataFrame(rows).sort_values("corr Nifty")


def intraday(stocks, nifty):
    rets, day_mv = {}, {}
    for s, df in stocks.items():
        if s not in U.FNO_SECTOR_OF or df is None or not len(df):
            continue
        c = df["Close"].dropna()
        c.index = pd.DatetimeIndex(c.index).tz_localize(None) if c.index.tz is not None else c.index
        rets[s] = c.pct_change()
        day_mv[s] = c.groupby(c.index.normalize()).last().pct_change()
    R, D = pd.DataFrame(rets), pd.DataFrame(day_mv)
    sec = pd.Series(U.FNO_SECTOR_OF)
    nr = nifty.pct_change()
    nd = nifty.groupby(nifty.index.normalize()).last().pct_change()
    rows = []
    for k in sorted(set(sec[R.columns])):
        cols = [s for s in R.columns if sec[s] == k]
        sr, sd = R[cols].mean(axis=1), D[cols].mean(axis=1)
        z = pd.concat([sr, nr], axis=1).dropna()
        zd = pd.concat([sd, nd], axis=1).dropna()
        rows.append({"F&O sector": k, "stocks": len(cols), "5-min corr Nifty": round(z.iloc[:, 0].corr(z.iloc[:, 1]), 2),
                     "day corr Nifty": round(zd.iloc[:, 0].corr(zd.iloc[:, 1]), 2),
                     "opposite day %": round((np.sign(zd.iloc[:, 0]) != np.sign(zd.iloc[:, 1])).mean() * 100),
                     "avg |day move| %": round(zd.iloc[:, 0].abs().mean() * 100, 2)})
    return pd.DataFrame(rows).sort_values("5-min corr Nifty")


def main(argv):
    stocks, idx = pickle.load(open(argv[1], "rb"))
    n = idx["NIFTY"]
    n = n.droplevel(1, axis=1) if isinstance(n.columns, pd.MultiIndex) else n
    nc = n["Close"].dropna()
    nc.index = pd.DatetimeIndex(nc.index).tz_localize(None) if nc.index.tz is not None else nc.index
    pd.set_option("display.width", 250)
    print("DAILY, 3 YEARS (sector indices):")
    print(daily().to_string(index=False))
    print("\nINTRADAY, 60 DAYS (F&O stocks by sector, equal weight):")
    print(intraday(stocks, nc).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv)
