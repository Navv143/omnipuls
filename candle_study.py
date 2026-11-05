"""Candle study: what do the day's top gainers and top losers have in common, candle by candle - and can it be seen in
time to trade? (the Setup Finder's mandatory checklist)

Data: the last ~6 months of 1-minute candles of every F&O stock and Nifty from Dhan (cached in <bot>/cache_m1, later
runs fetch only the last days), resampled to 3, 5 and 15 minutes. Local test: --yahoo (60 days of 5-minute candles).
All sizes are in ATR (14-day average daily range), so they follow each stock's current price and volatility.

Day labels: top 10 gainers and top 10 losers of the F&O list (close vs yesterday's close), "big" = >= 1.5 ATR.
At each decision time (09:30, 09:45, 10:00, 10:30, 11:00), with only the candles closed by then, every stock is read in
the direction of its move so far ("its way") and checked against the CHECKLIST below.

Output, per timeframe and decision time:
1. common: how many of the day's toppers had each item (read in their final direction) vs all other stocks -> lift;
2. predictive: among stocks showing the item (read in their direction so far), how often they end as toppers that way,
   and the rest of the day from the next candle's open (after 0.12% costs), by month (rotation) and train / test halves;
3. checklist score: items that were common AND predictive in the first months, summed; tested on the later months;
   top 2 stocks a day by score, walk-forward.
-> <data>/bot/candle_study.json and Supabase bot_results ("candle_study ...").
Run on the server: python candle_study.py            local: python candle_study.py --yahoo fno60.pkl
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
COST = 0.12
DAYS = 180
TIMES = ("09:30", "09:45", "10:00", "10:30", "11:00")
TFS = (3, 5, 15)

CHECKLIST = {
    # before the open (known at 9:15)
    "gap_way":       "gapped >= 0.5 ATR its way",
    "gap_against":   "opened against its way, then turned (gap >= 0.3 ATR the other way)",
    "nr7":           "yesterday was the narrowest range of 7 days (coiled)",
    "yday_close_way": "yesterday closed in the top (bottom) 25% of its range",
    "near_20d":      "opened within 0.5 ATR of the 20-day high (low)",
    "yday_vol":      "yesterday's volume >= 1.5x its 20-day average",
    # first candle of the day (on this timeframe)
    "first_body":    "first candle closed its way with a body >= 0.3 ATR",
    "first_vol":     "first candle volume >= 2x the usual first candle",
    "first_clv":     "first candle closed in its top (bottom) 25%",
    "open_extreme":  "open = low (high): never traded 0.05 ATR against the open",
    # by the decision time
    "move_05":       "already >= 0.5 ATR from yesterday's close",
    "move_10":       "already >= 1.0 ATR from yesterday's close",
    "rvol_15":       "volume so far >= 1.5x the usual for the time",
    "rvol_3":        "volume so far >= 3x the usual for the time",
    "vwap_all":      "every candle closed beyond VWAP",
    "higher_lows":   ">= 70% of candles made higher lows (lower highs)",
    "beat_nifty":    "beat Nifty since the open by >= 0.5%",
    "sector_with":   "its sector's average move >= 0.3 ATR the same way",
    "sector_top2":   "top 2 of its sector its way",
    "pdh_break":     "traded beyond yesterday's high (low)",
    "orb_break":     "closed beyond the first 15 minutes' range",
    "top10_now":     "among the 10 biggest movers (ATR) right now",
    # the big players' footprints (what a chart reader rarely measures)
    "trap_first":    "first went >= 0.2 ATR the other way (beyond yesterday's close), then reversed: a trap",
    "strong_closes": "candles closed in their top (bottom) third on average (CLV >= 0.65)",
    "vol_with":      ">= 65% of the volume traded on candles going its way",
    "wick_reject":   "long rejection wicks the other way (lower wicks >= 1.5x upper wicks)",
    "absorption":    "a >= 2x-volume candle with a small body (< 30% of range) the other way that did not fall (absorbed)",
}


FOOTPRINTS = ["trap_first", "absorption", "strong_closes", "gap_against", "vol_with", "wick_reject"]


def log(m):
    print(f"{datetime.now(IST):%H:%M:%S} candle study: {m}", flush=True)


# ---------------------------------------------------------------- data

def load_dhan_1m(days: int = DAYS) -> tuple[dict, pd.DataFrame]:
    import bot as B
    import dhan as D
    cfg = D.load_config()
    cache = B.BOT_DIR / "cache_m1"
    cache.mkdir(parents=True, exist_ok=True)
    out, nifty = {}, None
    for i, (sym, seg, sid, ins) in enumerate(B.universe(cfg), 1):
        if seg == "IDX_I" and sym not in ("NIFTY", "NIFTY 50"):
            continue
        f = cache / f"{sym.replace('&', '_and_')}.parquet"
        old = pd.read_parquet(f) if f.exists() else pd.DataFrame()
        span = 7 if not old.empty and (pd.Timestamp.now() - old.index.max()).days < 6 else days
        try:
            new = D.intraday(seg, sid, ins, 1, span, cfg)
        except Exception as e:
            log(f"{sym}: {getattr(e, 'friendly', e)}")
            new = pd.DataFrame()
        df = pd.concat([old, new]) if not old.empty and not new.empty else (new if old.empty else old)
        if df.empty:
            continue
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[df.index >= pd.Timestamp.now() - pd.Timedelta(days=days + 5)]
        df[["Open", "High", "Low", "Close", "Volume"]].astype("float32").to_parquet(f)
        if seg == "IDX_I":
            nifty = df
        else:
            out[sym] = str(f)                                 # read back one stock at a time (memory)
        if i % 25 == 0:
            log(f"1-minute candles: {i} symbols")
        time.sleep(0.25)
    return out, nifty


def resample(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    x = df[(df.index.strftime("%H:%M") >= "09:15") & (df.index.strftime("%H:%M") <= "15:29")]
    if tf == 1:
        return x
    g = x.groupby(x.index.normalize())
    parts = []
    for _, d in g:
        r = d.resample(f"{tf}min", origin=d.index[0].normalize() + pd.Timedelta(hours=9, minutes=15), label="left",
                       closed="left").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        parts.append(r.dropna(subset=["Close"]))
    return pd.concat(parts) if parts else x.iloc[:0]


# ---------------------------------------------------------------- features

def stock_rows(sym: str, x: pd.DataFrame, tf: int, nifty_open: dict, nifty_at: dict, last_only: bool = False,
               times=TIMES) -> list[dict]:
    """One row per stock, day and decision time: the checklist read in the direction so far, plus labels."""
    import universe as U
    hm_all = x.index.strftime("%H:%M")
    dd = x.index.normalize()
    day = x.groupby(dd).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"), v=("Volume", "sum"))
    pc = day["c"].shift()
    tr = pd.concat([day["h"] - day["l"], (day["h"] - pc).abs(), (day["l"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift()
    rng = day["h"] - day["l"]
    nr7 = (rng <= rng.rolling(7).min()).shift()
    hi20, lo20 = day["h"].rolling(20).max().shift(), day["l"].rolling(20).min().shift()
    vavg = day["v"].rolling(20).mean().shift()
    cumv = x["Volume"].groupby(dd).cumsum()
    cum_tab = cumv.groupby([dd, hm_all]).last().unstack()
    cum_avg = cum_tab.rolling(20, min_periods=10).mean().shift()
    first_v = x["Volume"].groupby(dd).first()
    first_avg = first_v.rolling(20, min_periods=10).mean().shift()
    slot = x["Volume"].groupby([dd, hm_all]).last().unstack().rolling(20, min_periods=10).mean().shift()
    rows = []
    sector = U.FNO_SECTOR_OF.get(sym, "Other")
    groups = list(x.groupby(dd))
    for k, (d0, g) in enumerate(groups):
        if k < 21 or (last_only and k != len(groups) - 1):
            continue
        A, P = atr.loc[d0], pc.loc[d0]
        if not (np.isfinite(A) and A > 0 and np.isfinite(P)):
            continue
        O, C = g["Open"].iloc[0], g["Close"].iloc[-1]
        ghm = np.asarray(g.index.strftime("%H:%M"))
        o, h, l, c, v = (g[k_].to_numpy() for k_ in ("Open", "High", "Low", "Close", "Volume"))
        yh, yl, yc = day["h"].shift().loc[d0], day["l"].shift().loc[d0], P
        f15 = ghm < "09:30"
        orh, orl = h[f15].max() if f15.any() else h[0], l[f15].min() if f15.any() else l[0]
        tp_ = (h + l + c) / 3
        vw = np.cumsum(tp_ * v) / np.maximum(np.cumsum(v), 1)
        day_pct = (C / P - 1) * 100
        for T in times:
            m = ghm < T
            n = int(m.sum())
            if n < 1 or n >= len(g):
                continue
            ci = c[n - 1]
            mv = (ci - P) / A
            sd = 1 if mv >= 0 else -1
            hh, ll = h[:n], l[:n]
            rngs = np.maximum(hh - ll, 1e-9)
            clv = (c[:n] - ll) / rngs
            body = c[:n] - o[:n]
            up_w = hh - np.maximum(o[:n], c[:n])
            lo_w = np.minimum(o[:n], c[:n]) - ll
            usual = cum_avg.at[d0, ghm[n - 1]] if (d0 in cum_avg.index and ghm[n - 1] in cum_avg.columns) else np.nan
            sl = slot.loc[d0].reindex(ghm[:n]).to_numpy() if d0 in slot.index else np.full(n, np.nan)
            vol_with = v[:n][np.sign(body) == sd].sum() / max(v[:n].sum(), 1)
            if sd > 0:
                trap = ll.min() <= min(P, O) - 0.2 * A and ci > O
                absorbed = any((v[j] >= 2 * sl[j]) and abs(body[j]) < 0.3 * rngs[j] and c[j] >= o[j] - 0.1 * A and lo_w[j] > up_w[j]
                               for j in range(n) if np.isfinite(sl[j]))
                wick = lo_w.sum() >= 1.5 * max(up_w.sum(), 1e-9)
                hl = np.mean(ll[1:] >= ll[:-1]) if n > 1 else 1.0
            else:
                trap = hh.max() >= max(P, O) + 0.2 * A and ci < O
                absorbed = any((v[j] >= 2 * sl[j]) and abs(body[j]) < 0.3 * rngs[j] and c[j] <= o[j] + 0.1 * A and up_w[j] > lo_w[j]
                               for j in range(n) if np.isfinite(sl[j]))
                wick = up_w.sum() >= 1.5 * max(lo_w.sum(), 1e-9)
                hl = np.mean(hh[1:] <= hh[:-1]) if n > 1 else 1.0
            n_ret = (nifty_at.get((d0, T), np.nan) / nifty_open.get(d0, np.nan) - 1) * 100
            e = o[n]                                              # next candle's open
            row = {
                "entry": e, "entry_ts": g.index[n],
                "day": d0, "sym": sym, "sector": sector, "tf": tf, "T": T, "sd": sd, "mv": mv, "A": A,
                "gap_pct": (O / P - 1) * 100, "vwap_now": bool((ci - vw[n - 1]) * sd > 0),
                "atr_pct": A / P * 100, "day_pct": day_pct, "day_atr": (C - P) / A,
                "rest_pct": sd * (C / e - 1) * 100 - COST,
                "gap_way": sd * (O - P) / A >= 0.5, "gap_against": sd * (O - P) / A <= -0.3,
                "nr7": bool(nr7.loc[d0]) if pd.notna(nr7.loc[d0]) else False,
                "yday_close_way": ((yc - yl) / max(yh - yl, 1e-9) >= 0.75) if sd > 0 else ((yc - yl) / max(yh - yl, 1e-9) <= 0.25),
                "near_20d": ((hi20.loc[d0] - O) / A <= 0.5) if sd > 0 else ((O - lo20.loc[d0]) / A <= 0.5),
                "yday_vol": day["v"].shift().loc[d0] >= 1.5 * vavg.loc[d0] if np.isfinite(vavg.loc[d0]) else False,
                "first_body": sd * (c[0] - o[0]) / A >= 0.3,
                "first_vol": first_v.loc[d0] >= 2 * first_avg.loc[d0] if np.isfinite(first_avg.loc[d0]) else False,
                "first_clv": ((c[0] - l[0]) / max(h[0] - l[0], 1e-9) >= 0.75) if sd > 0 else ((c[0] - l[0]) / max(h[0] - l[0], 1e-9) <= 0.25),
                "open_extreme": ((O - ll.min()) / A <= 0.05) if sd > 0 else ((hh.max() - O) / A <= 0.05),
                "move_05": abs(mv) >= 0.5, "move_10": abs(mv) >= 1.0,
                "rvol_15": (cumv.loc[g.index[n - 1]] / usual >= 1.5) if usual and usual > 0 else False,
                "rvol_3": (cumv.loc[g.index[n - 1]] / usual >= 3) if usual and usual > 0 else False,
                "vwap_all": bool(np.all((c[:n] - vw[:n]) * sd > 0)),
                "higher_lows": hl >= 0.7,
                "beat_nifty": sd * ((ci / O - 1) * 100 - n_ret) >= 0.5 if np.isfinite(n_ret) else False,
                "pdh_break": (hh.max() > yh) if sd > 0 else (ll.min() < yl),
                "orb_break": (T > "09:30") and ((ci > orh) if sd > 0 else (ci < orl)),
                "trap_first": bool(trap), "strong_closes": (clv.mean() >= 0.65) if sd > 0 else (clv.mean() <= 0.35),
                "vol_with": vol_with >= 0.65, "wick_reject": bool(wick), "absorption": bool(absorbed),
            }
            rows.append(row)
    return rows


def add_cross(t: pd.DataFrame) -> pd.DataFrame:
    g = t.groupby(["tf", "day", "T", "sector"])
    t["sec_mv"] = g["mv"].transform("mean")
    t["sector_with"] = (t["sec_mv"] * t["sd"] >= 0.3) & (g["mv"].transform("size") >= 4)
    t["w"] = t["mv"] * t["sd"]
    t["sector_top2"] = t.groupby(["tf", "day", "T", "sector", "sd"])["w"].rank(ascending=False) <= 2
    t["top10_now"] = t.groupby(["tf", "day", "T"])["mv"].transform(lambda s: s.abs().rank(ascending=False)) <= 10
    dayrank = t.drop_duplicates(["day", "sym"])[["day", "sym", "day_pct"]].copy()
    dayrank["gain_rank"] = dayrank.groupby("day")["day_pct"].rank(ascending=False)
    dayrank["loss_rank"] = dayrank.groupby("day")["day_pct"].rank(ascending=True)
    t = t.merge(dayrank[["day", "sym", "gain_rank", "loss_rank"]], on=["day", "sym"])
    t["topper"] = (t["gain_rank"] <= 10) | (t["loss_rank"] <= 10)
    t["final_dir"] = np.sign(t["day_pct"]).replace(0, 1)
    t["topper_way"] = ((t["gain_rank"] <= 10) & (t["sd"] > 0)) | ((t["loss_rank"] <= 10) & (t["sd"] < 0))
    t["big_way"] = t["day_atr"] * t["sd"] >= 1.5
    return t


# ---------------------------------------------------------------- analysis

# ---------------------------------------------------------------- layer tree (scenarios)

def _gap_group(g: float) -> str:
    a = abs(g)
    return "gap 0-0.5%" if a < 0.5 else "gap 0.5-1%" if a < 1 else "gap 1-3%" if a < 3 else "gap >3%"


LAYERS = [
    ("Gap", lambda z: z["gap_pct"].map(_gap_group)),
    ("Gap side", lambda z: np.where(z["gap_pct"].abs() < 0.5, "flat open",
                                    np.where(np.sign(z["gap_pct"]) == z["sd"], "gap with the move", "gap against the move"))),
    ("First candle", lambda z: np.where(z["first_body"] & z["first_clv"], "strong first candle", "weak first candle")),
    ("Volume", lambda z: np.where(z["rvol_3"], "volume 3x+", np.where(z["rvol_15"], "volume 1.5-3x", "normal volume"))),
    ("Market", lambda z: np.where(z["sector_with"] & z["beat_nifty"], "with sector + beats Nifty",
                                  np.where(z["sector_with"], "with sector only",
                                           np.where(z["beat_nifty"], "beats Nifty only", "alone")))),
    ("Footprints", lambda z: np.where(z["fp"] >= 3, "3+ footprints", np.where(z["fp"] == 2, "2 footprints", "0-1 footprints"))),
    ("Structure", lambda z: np.where(z["vwap_now"] & z["pdh_break"], "beyond VWAP + yday high/low broken",
                                     np.where(z["vwap_now"], "beyond VWAP", "back inside VWAP"))),
]


def layer_tree(z: pd.DataFrame, split, days: int, min_n: int = 20) -> list[dict]:
    """Every path through the layers (depth 1..len(LAYERS), in order): how many signals, how often they end as the
    day's top 10 that way, the rest of the day after costs (all / train / test), win rate and months positive.
    A written scenario line for each path."""
    z = z.copy()
    names = []
    for name, f in LAYERS:
        z[name] = f(z)
        names.append(name)
    out = []
    for depth in range(1, len(names) + 1):
        keys = names[:depth]
        for path, g in z.groupby(keys):
            if len(g) < min_n:
                continue
            path = path if isinstance(path, tuple) else (path,)
            tr, te = g[g["day"] < split], g[g["day"] >= split]
            mo = g.groupby("month")["rest_pct"].mean()
            out.append({"depth": depth, "scenario": " → ".join(path), "n": int(len(g)),
                        "per_day": round(len(g) / max(days, 1), 2),
                        "topper_pct": round(g["topper_way"].mean() * 100, 1), "big_pct": round(g["big_way"].mean() * 100, 1),
                        "rest_pct": round(g["rest_pct"].mean(), 3),
                        "train": round(tr["rest_pct"].mean(), 3) if len(tr) >= 5 else None,
                        "test": round(te["rest_pct"].mean(), 3) if len(te) >= 5 else None,
                        "win_pct": round((g["rest_pct"] > 0).mean() * 100, 1),
                        "months_pos": f"{int((mo > 0).sum())}/{len(mo)}", "last_month": round(mo.iloc[-1], 3) if len(mo) else None,
                        "long": round(g[g["sd"] > 0]["rest_pct"].mean(), 3) if (g["sd"] > 0).sum() >= 5 else None,
                        "short": round(g[g["sd"] < 0]["rest_pct"].mean(), 3) if (g["sd"] < 0).sum() >= 5 else None})
    return out


def analyse(t: pd.DataFrame) -> dict:
    items = [k for k in CHECKLIST if k in t.columns]
    days = sorted(t["day"].unique())
    split = days[int(len(days) * 0.6)]
    t["month"] = pd.to_datetime(t["day"]).dt.strftime("%Y-%m")
    out = {"days": len(days), "from": str(days[0])[:10], "to": str(days[-1])[:10], "split": str(split)[:10], "tables": {}}
    for (tf, T), z in t.groupby(["tf", "T"]):
        key = f"{tf}m {T}"
        base_topper = z["topper_way"].mean()
        base_rest = z["rest_pct"].mean()
        # "common" uses the stocks whose direction so far equals their final direction (what the topper looked like)
        same = z[z["sd"] == z["final_dir"]]
        tops = same[same["topper"]]
        rest = same[~same["topper"]]
        rows = []
        for it in items:
            has = z[z[it]]
            tr, te = has[has["day"] < split], has[has["day"] >= split]
            months = has.groupby("month")["rest_pct"].mean()
            rows.append({
                "item": it, "text": CHECKLIST[it],
                "in_toppers_pct": round(tops[it].mean() * 100, 1), "in_others_pct": round(rest[it].mean() * 100, 1),
                "lift_common": round(tops[it].mean() / max(rest[it].mean(), 1e-9), 2),
                "share_pct": round(z[it].mean() * 100, 1),
                "p_topper_pct": round(has["topper_way"].mean() * 100, 2), "p_topper_lift": round(has["topper_way"].mean() / max(base_topper, 1e-9), 2),
                "p_big_pct": round(has["big_way"].mean() * 100, 1),
                "rest_pct": round(has["rest_pct"].mean(), 3), "rest_train": round(tr["rest_pct"].mean(), 3) if len(tr) else None,
                "rest_test": round(te["rest_pct"].mean(), 3) if len(te) else None,
                "months_positive": f"{int((months > 0).sum())}/{len(months)}",
                "last_month_rest": round(months.iloc[-1], 3) if len(months) else None,
                "n": int(len(has)),
            })
        tab = pd.DataFrame(rows).sort_values("p_topper_lift", ascending=False)
        # checklist score: items common (lift >= 1.5) and predictive (p_topper_lift >= 1.5) on the TRAIN days only
        trz = z[z["day"] < split]
        trs = trz[trz["sd"] == trz["final_dir"]]
        bt = trz["topper_way"].mean()
        chosen = [it for it in items
                  if trs[trs["topper"]][it].mean() >= 1.5 * max(trs[~trs["topper"]][it].mean(), 1e-9)
                  and trz[trz[it]]["topper_way"].mean() >= 1.5 * bt and trz[it].sum() >= 30]
        z = z.assign(score=z[chosen].sum(axis=1) if chosen else 0)
        sc = []
        for s_, g in z.groupby("score"):
            te = g[g["day"] >= split]
            sc.append({"score": int(s_), "n": int(len(g)), "p_topper_pct": round(g["topper_way"].mean() * 100, 1),
                       "test_p_topper_pct": round(te["topper_way"].mean() * 100, 1) if len(te) else None,
                       "rest_pct": round(g["rest_pct"].mean(), 3), "test_rest_pct": round(te["rest_pct"].mean(), 3) if len(te) else None})
        z = z.assign(fp=z[FOOTPRINTS].sum(axis=1))
        fps = []
        for k_ in (2, 3, 4, 5):
            g = z[z["fp"] >= k_]
            mo = g.groupby("month")["rest_pct"].mean()
            fps.append({"min_fp": k_, "per_day": round(len(g) / max(len(days), 1), 1), "rest_pct": round(g["rest_pct"].mean(), 3),
                        "train": round(g[g["day"] < split]["rest_pct"].mean(), 3), "test": round(g[g["day"] >= split]["rest_pct"].mean(), 3),
                        "long": round(g[g["sd"] > 0]["rest_pct"].mean(), 3), "short": round(g[g["sd"] < 0]["rest_pct"].mean(), 3),
                        "by_month": {a: round(b, 3) for a, b in mo.items()}})
        f2 = z.sort_values(["day", "fp", "w"], ascending=[True, False, False]).groupby("day").head(2)
        f2m = f2.groupby("month")["rest_pct"].mean()
        footprint = {"levels": fps, "top2": {"n": int(len(f2)), "rest_pct": round(f2["rest_pct"].mean(), 3),
                                             "train": round(f2[f2["day"] < split]["rest_pct"].mean(), 3),
                                             "test": round(f2[f2["day"] >= split]["rest_pct"].mean(), 3),
                                             "win_pct": round((f2["rest_pct"] > 0).mean() * 100, 1),
                                             "by_month": {a: round(b, 3) for a, b in f2m.items()}}}
        top2 = z.sort_values(["day", "score", "w"], ascending=[True, False, False]).groupby("day").head(2)
        t2te = top2[top2["day"] >= split]
        months = top2.groupby("month")["rest_pct"].mean()
        out["tables"][key] = {
            "base_topper_pct": round(base_topper * 100, 2), "base_rest_pct": round(base_rest, 3),
            "items": tab.to_dict("records"), "chosen": chosen, "score": sc, "footprint": footprint,
            "layers": layer_tree(z, split, len(days)),
            "top2": {"n": int(len(top2)), "rest_pct": round(top2["rest_pct"].mean(), 3),
                     "test_rest_pct": round(t2te["rest_pct"].mean(), 3) if len(t2te) else None,
                     "test_n": int(len(t2te)), "topper_pct": round(top2["topper_way"].mean() * 100, 1),
                     "test_topper_pct": round(t2te["topper_way"].mean() * 100, 1) if len(t2te) else None,
                     "by_month": {k: round(v, 3) for k, v in months.items()}},
        }
    return out


def build(stocks: dict, nifty: pd.DataFrame, tfs=TFS) -> pd.DataFrame:
    rows = []
    for tf in tfs:
        n = resample(nifty, tf) if tf != 5 or nifty.index.to_series().diff().min() < pd.Timedelta(minutes=5) else nifty
        n_open = n.groupby(n.index.normalize())["Open"].first().to_dict()
        nhm = n.index.strftime("%H:%M")
        n_at = {}
        for d0, g in n.groupby(n.index.normalize()):
            ghm = g.index.strftime("%H:%M")
            for T in TIMES:
                a = g[ghm < T]
                if len(a):
                    n_at[(d0, T)] = a["Close"].iloc[-1]
        del nhm
        for i, (sym, df) in enumerate(stocks.items()):
            if isinstance(df, str):
                df = pd.read_parquet(df).astype("float64")
            x = resample(df, tf) if df.index.to_series().diff().min() < pd.Timedelta(minutes=tf) else df
            x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:29")]
            if len(x) < 300:
                continue
            rows += stock_rows(sym, x, tf, n_open, n_at)
        log(f"{tf}-minute: {len(rows)} rows so far")
    return add_cross(pd.DataFrame(rows))


def save(res: dict):
    import paths
    out = paths.DATA / "bot"
    out.mkdir(parents=True, exist_ok=True)
    (out / "candle_study.json").write_text(json.dumps(res, default=str))
    try:
        import cloudstore
        if not cloudstore.enabled():
            try:
                import streamlit as st
                sb = dict(st.secrets.get("supabase") or {})
                cloudstore.configure(sb.get("url"), sb.get("key"))
            except Exception:
                pass
        cloudstore.upsert_rows("bot_results", [{"run_at": "candle_study " + res["run_at"],
                                                "result": json.loads(json.dumps(res, default=str))}], "run_at")
        time.sleep(3)
    except Exception as e:
        log(f"supabase: {e}")


def main(argv: list[str]):
    import universe as U
    if "--yahoo" in argv:
        import pickle
        bars, ix = pickle.load(open(argv[argv.index("--yahoo") + 1], "rb"))
        stocks = {k: v for k, v in bars.items() if k in U.FNO_SECTOR_OF}
        t = build(stocks, ix["NIFTY"], tfs=(5, 15))
        source = "Yahoo 5-minute (60 days)"
    else:
        stocks, nifty = load_dhan_1m()
        if nifty is None or not stocks:
            log("no data")
            return
        t = build(stocks, nifty)
        source = f"Dhan 1-minute, {DAYS} days, resampled to 3 / 5 / 15 minutes"
    res = analyse(t)
    res.update({"run_at": datetime.now(IST).isoformat(timespec="seconds"), "source": source, "checklist": CHECKLIST,
                "stocks": int(t["sym"].nunique())})
    if "--yahoo" in argv:
        out = argv[argv.index("--yahoo") + 1].rsplit("/", 1)[0] + "/candle_study_local.json"
        open(out, "w").write(json.dumps(res, default=str))
        t.drop(columns=["entry_ts"]).to_parquet(out.replace(".json", ".parquet"))
        log(f"saved {out}")
    else:
        save(res)
    log("done")


if __name__ == "__main__":
    main(sys.argv[1:])
