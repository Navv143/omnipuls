"""Technical indicators and screener metrics. Pure pandas, no network."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI (same as TradingView)."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(loss != 0, 100.0)
    return out.where(gain.notna())


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["Close"].shift()
    return pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def bollinger(close: pd.Series, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n).std(ddof=0)
    return mid + k * sd, mid, mid - k * sd


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP: resets each calendar day (for intraday bars)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    vol = df["Volume"].fillna(0)
    day = pd.Index(df.index).normalize() if isinstance(df.index, pd.DatetimeIndex) else np.zeros(len(df))
    pv = (tp * vol).groupby(day).cumsum()
    cv = vol.groupby(day).cumsum()
    return (pv / cv.replace(0, np.nan)).fillna(tp)


def supertrend(df: pd.DataFrame, n=10, mult=3.0):
    """Returns (line, direction) where direction is 1 for up-trend, -1 for down-trend."""
    a = atr(df, n)
    hl2 = (df["High"] + df["Low"]) / 2
    upper = (hl2 + mult * a).to_numpy()
    lower = (hl2 - mult * a).to_numpy()
    close = df["Close"].to_numpy()
    fu, fl = upper.copy(), lower.copy()
    direction = np.ones(len(df))
    line = np.full(len(df), np.nan)
    for i in range(1, len(df)):
        if np.isnan(a.iloc[i]):
            continue
        fu[i] = upper[i] if (np.isnan(fu[i - 1]) or upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (np.isnan(fl[i - 1]) or lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if direction[i - 1] == 1:
            direction[i] = -1 if close[i] < fl[i] else 1
        else:
            direction[i] = 1 if close[i] > fu[i] else -1
        line[i] = fl[i] if direction[i] == 1 else fu[i]
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def pivots(prev_high: float, prev_low: float, prev_close: float) -> dict:
    """Classic floor pivots from the previous session."""
    p = (prev_high + prev_low + prev_close) / 3
    r = prev_high - prev_low
    return {
        "R3": prev_high + 2 * (p - prev_low), "R2": p + r, "R1": 2 * p - prev_low,
        "Pivot": p,
        "S1": 2 * p - prev_high, "S2": p - r, "S3": prev_low - 2 * (prev_high - p),
    }


def pct(a, b):
    try:
        if b is None or a is None or b == 0 or np.isnan(a) or np.isnan(b):
            return np.nan
        return (a / b - 1) * 100
    except TypeError:
        return np.nan


def screener_row(df: pd.DataFrame) -> dict | None:
    """Compute all screener metrics from daily OHLCV (about 1 year of bars)."""
    df = df.dropna(subset=["Close"])
    if len(df) < 2:
        return None
    c, h, l, o = df["Close"], df["High"], df["Low"], df["Open"]
    v = df["Volume"].fillna(0) if "Volume" in df else pd.Series(0, index=df.index)
    last, prev = float(c.iloc[-1]), float(c.iloc[-2])
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    r = rsi(c)
    ml, ms, _ = macd(c)
    a = atr(df)
    st_line, st_dir = supertrend(df)
    win = df.tail(252)
    hi52, lo52 = float(win["High"].max()), float(win["Low"].min())
    avg_vol20 = float(v.iloc[-21:-1].mean()) if len(v) > 21 else float(v.iloc[:-1].mean() or 0)
    vol_ratio = float(v.iloc[-1]) / avg_vol20 if avg_vol20 else np.nan

    def back(n):
        return float(c.iloc[-1 - n]) if len(c) > n else np.nan

    has200 = len(c) >= 200
    trend = "Sideways"
    if has200 and last > e20.iloc[-1] > e50.iloc[-1] > e200.iloc[-1]:
        trend = "Strong up"
    elif has200 and last < e20.iloc[-1] < e50.iloc[-1] < e200.iloc[-1]:
        trend = "Strong down"
    elif last > e50.iloc[-1]:
        trend = "Up"
    elif last < e50.iloc[-1]:
        trend = "Down"

    # crosses within the last 5 bars
    s50, s200 = sma(c, 50), sma(c, 200)
    diff = (s50 - s200).tail(6)
    golden = has200 and len(diff.dropna()) == 6 and (diff.iloc[0] <= 0) and (diff.iloc[-1] > 0)
    death = has200 and len(diff.dropna()) == 6 and (diff.iloc[0] >= 0) and (diff.iloc[-1] < 0)
    mdiff = (ml - ms).tail(4)
    macd_bull = len(mdiff.dropna()) == 4 and (mdiff.iloc[:-1] <= 0).any() and mdiff.iloc[-1] > 0
    macd_bear = len(mdiff.dropna()) == 4 and (mdiff.iloc[:-1] >= 0).any() and mdiff.iloc[-1] < 0

    rsi_v = float(r.iloc[-1]) if pd.notna(r.iloc[-1]) else np.nan
    gap = pct(float(o.iloc[-1]), prev)
    chg = pct(last, prev)
    from_hi = pct(last, hi52)
    from_lo = pct(last, lo52)

    tags = []
    if not np.isnan(vol_ratio) and vol_ratio >= 2:
        tags.append("Volume spike")
    if not np.isnan(rsi_v):
        if rsi_v < 30:
            tags.append("Oversold")
        elif rsi_v > 70:
            tags.append("Overbought")
    if not np.isnan(from_hi) and from_hi >= -2:
        tags.append("Near 52W high")
    if not np.isnan(from_lo) and from_lo <= 3:
        tags.append("Near 52W low")
    if golden:
        tags.append("Golden cross")
    if death:
        tags.append("Death cross")
    if macd_bull:
        tags.append("MACD bull cross")
    if macd_bear:
        tags.append("MACD bear cross")
    if not np.isnan(gap) and gap >= 1:
        tags.append("Gap up")
    if not np.isnan(gap) and gap <= -1:
        tags.append("Gap down")
    if len(st_dir) > 2 and st_dir.iloc[-1] != st_dir.iloc[-2]:
        tags.append("Supertrend flip " + ("up" if st_dir.iloc[-1] == 1 else "down"))

    # simple technical score: -5 (very bearish) to +5 (very bullish)
    score = 0
    score += 1 if last > e20.iloc[-1] else -1
    score += 1 if last > e50.iloc[-1] else -1
    if has200:
        score += 1 if last > e200.iloc[-1] else -1
    score += 1 if ml.iloc[-1] > ms.iloc[-1] else -1
    score += 1 if st_dir.iloc[-1] == 1 else -1

    return {
        "Price": last,
        "Chg": last - prev,
        "Chg %": chg,
        "Open": float(o.iloc[-1]),
        "Prev Close": prev,
        "Gap %": gap,
        "Day High": float(h.iloc[-1]),
        "Day Low": float(l.iloc[-1]),
        "Volume": float(v.iloc[-1]),
        "Vol x Avg": vol_ratio,
        "RSI": rsi_v,
        "ATR %": float(a.iloc[-1]) / last * 100 if pd.notna(a.iloc[-1]) and last else np.nan,
        "1W %": pct(last, back(5)),
        "1M %": pct(last, back(21)),
        "3M %": pct(last, back(63)),
        "1Y %": pct(last, back(min(251, len(c) - 1))),
        "From 52W High %": from_hi,
        "From 52W Low %": from_lo,
        "52W High": hi52,
        "52W Low": lo52,
        "EMA20": float(e20.iloc[-1]),
        "EMA50": float(e50.iloc[-1]),
        "EMA200": float(e200.iloc[-1]) if has200 else np.nan,
        "Trend": trend,
        "Supertrend": "Up" if st_dir.iloc[-1] == 1 else "Down",
        "Score": score,
        "Signals": ", ".join(tags),
        "Spark": [float(x) for x in c.tail(30)],
    }
