"""Multi-timeframe bars from 1-minute data (Nifty / Bank Nifty futures 2015-2023 with real volume; BTC 1-min)."""
from __future__ import annotations

import numpy as np
import pandas as pd

import swing1m as S1


def load_index_1m(sym: str) -> pd.DataFrame:
    """1-min futures bars, index = bar START time (file times are bar end minutes)."""
    df = S1.load(sym)
    df["dt"] = df["dt"] - pd.Timedelta(minutes=1)
    df = df[(df.dt.dt.time >= pd.Timestamp("09:15").time()) & (df.dt.dt.time < pd.Timestamp("15:30").time())]
    return df.set_index("dt")[["o", "h", "l", "c", "v"]]


def resample(m1: pd.DataFrame, minutes: int, session_anchor="09:15") -> pd.DataFrame:
    """Session-anchored bars (09:15, 09:15+k ...), label = bar start. Works for 24h data with anchor '00:00'."""
    idx = m1.index
    day = idx.normalize()
    hh, mm = map(int, session_anchor.split(":"))
    base = day + pd.Timedelta(hours=hh, minutes=mm)
    k = ((idx - base) // pd.Timedelta(minutes=minutes)).astype(int)
    lab = base + pd.to_timedelta(k * minutes, unit="m")
    agg = m1.groupby(lab).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum"))
    return agg.dropna()


def load_btc_1m(start="2019-01-01") -> pd.DataFrame:
    hist = pd.read_csv("/home/claude/research/data/btc_1min_hist.csv.gz")
    late = pd.read_csv("/home/claude/research/data/btc_1min_latest.csv")
    df = pd.concat([hist, late])
    tcol = [c for c in df.columns if "time" in c.lower()][0]
    df["dt"] = pd.to_datetime(df[tcol], unit="s")
    df = df.drop_duplicates("dt").set_index("dt").sort_index()
    df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})
    return df.loc[start:, ["o", "h", "l", "c", "v"]].astype(float)
