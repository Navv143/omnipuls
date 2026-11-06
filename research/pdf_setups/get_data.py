"""Data for the PDF setups test: Yahoo intraday (2m / 5m / 15m: 60 days, 1h: 2 years) for Indian indices, commodity
futures (MCX follows COMEX / NYMEX) and FX, plus the cached 3.5 years of 5-minute PAXG (gold) and BTC.

Usage: python research/pdf_setups/get_data.py <scratchpad dir>  ->  <dir>/pdf_data.pkl {(market, tf): OHLCV (tz-aware)}
"""
import pickle
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKERS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "GOLD": "GC=F", "SILVER": "SI=F", "CRUDE": "CL=F",
           "NATGAS": "NG=F", "COPPER": "HG=F", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
           "USDINR": "INR=X"}
TFS = {"2m": "60d", "5m": "60d", "15m": "60d", "1h": "730d"}


def get(t, tf, period):
    for k in range(4):
        try:
            d = yf.download(t, interval=tf, period=period, progress=False, auto_adjust=False)
            if len(d):
                if isinstance(d.columns, pd.MultiIndex):
                    d = d.droplevel(1, axis=1)
                return d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        except Exception as e:
            print(t, tf, e)
        time.sleep(3 * (k + 1))
    return None


def main(out):
    out = Path(out)
    data = {}
    for m, t in TICKERS.items():
        for tf, p in TFS.items():
            if tf == "2m" and m not in ("NIFTY", "BANKNIFTY"):
                continue
            d = get(t, tf, p)
            if d is not None:
                data[(m, tf)] = d
                print(m, tf, len(d), d.index.min(), d.index.max(), flush=True)
            time.sleep(1)
    for m, f in (("PAXG_GOLD", "paxg5m.pkl"), ("BTC", "btc5m.pkl")):
        d = pd.read_pickle(out / f)
        data[(m, "5m")] = d
        for tf, rule in (("15m", "15min"), ("1h", "1h")):
            data[(m, tf)] = d.resample(rule).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                                  "Volume": "sum"}).dropna(subset=["Close"])
    pickle.dump(data, open(out / "pdf_data.pkl", "wb"))
    print("saved", len(data))


if __name__ == "__main__":
    main(sys.argv[1])
