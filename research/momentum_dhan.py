"""Momentum continuation test on real 5-minute bars from Dhan (run on your own computer).

Question: every day 5-10 F&O stocks finish 3%+ up or down. When a stock has already moved X% by time T, how often
does it go on to finish 3%+ the same way, and how much is left for a trade entered at that moment?

What it does
  1. Base rate: how many F&O stocks finish +-3% each day (checks the "5-10 a day" idea).
  2. Continuation map: at 9:30, 9:45, 10:00, 10:30 and 11:00, for stocks already 1%, 1.5%, 2%, 3%+ from yesterday's
     close: share that finish 3%+ that way, the move left after entry, and P&L after 0.12% costs for two exits
     (hold to 15:20; 1% stop then 15:20).
  3. Splits by relative volume (volume so far vs the same time on the last 10 days), gap, Nifty direction and
     strength vs the stock's sector.
  4. Every combination of the above, each checked on the first and second half of the dates separately. Only
     combinations that make money after costs in BOTH halves are worth a scanner.

Entry is the open of the bar that starts at the checkpoint (e.g. 9:45 bar open), never a price already seen.

Usage (in the Omnipuls folder, with Dhan connected):
  .venv\\Scripts\\python research\\momentum_dhan.py --days 1800
First run downloads ~20 requests per stock (about 30-45 minutes for all F&O stocks); downloads are cached for
the day in research\\cache. Results print to the screen and are saved in research\\results\\momentum_*.csv.
  --limit 30      test on the first 30 stocks only (quick check)
  --selftest      run on synthetic random data, no Dhan needed (checks the script; results mean nothing)
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="All-NaN slice encountered")  # holidays / days a stock didn't trade

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import universe as U  # noqa: E402

OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
COST = 0.0012  # round trip on shares, as in the rest of the research
NSLOT = 75  # 09:15 .. 15:25
CHECKS = ["09:30", "09:45", "10:00", "10:30", "11:00"]
EXIT = "15:20"
STOP = 0.01
MOVE_BINS = [0.01, 0.015, 0.02, 0.03, 1.0]
MOVE_LABELS = ["1-1.5%", "1.5-2%", "2-3%", "3%+"]
MIN_N = 150  # smallest combination worth reading
PREFIX = ""  # "selftest_" for synthetic runs, so they never overwrite real results


def slot(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return (h * 60 + m - (9 * 60 + 15)) // 5


# ---------------------------------------------------------------- data

def to_grid(df: pd.DataFrame, days: pd.DatetimeIndex) -> dict | None:
    """5-minute bars -> {O,H,L,C,V: [day, slot]} aligned to `days` (NaN where missing)."""
    if df is None or df.empty:
        return None
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    tod = (idx.hour * 60 + idx.minute - (9 * 60 + 15)) // 5
    day = idx.normalize()
    pos = pd.Series(np.arange(len(days)), index=days)
    di = pos.reindex(day).values
    ok = (tod >= 0) & (tod < NSLOT) & ~np.isnan(di)
    di, ti = di[ok].astype(int), np.asarray(tod[ok], dtype=int)
    g = {}
    for k, c in zip("OHLCV", ["Open", "High", "Low", "Close", "Volume"]):
        a = np.full((len(days), NSLOT), np.nan)
        a[di, ti] = df[c].values[ok]
        g[k] = a
    for k in "OHLC":
        g[k][g[k] <= 0] = np.nan
    return g


def download(days_back: int, limit: int | None):
    """{symbol: 5-minute DataFrame} for F&O stocks, plus Nifty 50."""
    import dhan as D
    from verify_dhan import bars
    ids = D.equity_ids()
    nifty = bars("IDX_I", 13, "INDEX", 5, days_back)
    syms = [s for s in sorted(U.FNO_SECTOR_OF) if s in ids][:limit]
    raw = {}
    t0 = time.time()
    for i, s in enumerate(syms, 1):
        try:
            raw[s] = bars("NSE_EQ", ids[s], "EQUITY", 5, days_back)
        except Exception as e:
            print(f"  {s}: {e}")
        if i % 10 == 0:
            print(f"  downloaded {i}/{len(syms)} stocks ({time.time() - t0:.0f}s)", flush=True)
    return nifty, raw


def synthetic(n_stocks=40, n_days=500, seed=7):
    """Random-walk 5-minute bars with fat-tailed trend days. For checking the script only."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2022-01-03", periods=n_days)
    stamps = [d + pd.Timedelta(minutes=555 + 5 * t) for d in days for t in range(NSLOT)]
    idx = pd.DatetimeIndex(stamps)

    def walk(vol):
        drift = np.repeat(rng.standard_t(3, n_days) * vol * 0.04, NSLOT)
        r = rng.normal(0, vol, len(idx)) + drift
        r[::NSLOT] += rng.normal(0, vol * 4, n_days)  # overnight gaps
        c = 100 * np.exp(np.cumsum(r))
        o = np.r_[c[0], c[:-1]]
        hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 3, len(c))))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 3, len(c))))
        v = rng.lognormal(10, 0.5, len(c)) * (1 + 3 * np.abs(r) / vol)
        return pd.DataFrame({"Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v}, index=idx)

    names = sorted(U.FNO_SECTOR_OF)[:n_stocks]
    return walk(0.0007), {s: walk(0.0018) for s in names}


# ---------------------------------------------------------------- events

def ffill_rows(a: np.ndarray) -> np.ndarray:
    return pd.DataFrame(a).ffill(axis=1).values


def day_basics(g: dict) -> dict:
    C = ffill_rows(g["C"])
    has = np.isfinite(g["C"]).sum(1) >= 60
    last = C[:, -1]
    prev = np.r_[np.nan, last[:-1]]
    prev[~np.r_[False, has[:-1]]] = np.nan  # yesterday must be a full session too
    op = g["O"][:, 0]
    with np.errstate(all="ignore"):
        hi, lo = np.nanmax(g["H"], 1), np.nanmin(g["L"], 1)
        tr = np.nanmax(np.stack([hi - lo, np.abs(hi - prev), np.abs(lo - prev)]), 0) / prev
    atr = pd.Series(tr).rolling(14, min_periods=10).mean().shift(1).values
    gap = op / prev - 1
    ok = has & np.isfinite(prev) & np.isfinite(op) & np.isfinite(atr) & (np.abs(gap) < 0.2)
    return {"C": C, "last": last, "prev": prev, "open": op, "atr": atr, "gap": gap, "ok": ok}


def stock_events(sym: str, g: dict, days: pd.DatetimeIndex) -> tuple[pd.DataFrame, np.ndarray]:
    b = day_basics(g)
    O, H, L, V, C = g["O"], g["H"], g["L"], g["V"], b["C"]
    ex = slot(EXIT)
    exit_px = np.where(np.isfinite(O[:, ex]), O[:, ex], C[:, ex - 1])
    close_chg = b["last"] / b["prev"] - 1
    rows = []
    for ck in CHECKS:
        s = slot(ck)
        px = C[:, s - 1]
        chg = px / b["prev"] - 1
        cumv = np.nansum(V[:, :s], 1)
        avgv = pd.Series(np.where(b["ok"], cumv, np.nan)).rolling(10, min_periods=7).mean().shift(1).values
        entry = np.where(np.isfinite(O[:, s]), O[:, s], px)
        side = np.sign(chg)
        keep = b["ok"] & (np.abs(chg) >= MOVE_BINS[0]) & np.isfinite(entry) & np.isfinite(avgv)
        if not keep.any():
            continue
        k = np.where(keep)[0]
        sd, en = side[k], entry[k]
        hold = sd * (exit_px[k] / en - 1)
        # 1% stop, checked bar by bar from the entry bar; a bar opening through the stop fills at its open
        stop_px = en * (1 - sd * STOP)
        Lw, Hw, Ow = L[k, s:ex], H[k, s:ex], O[k, s:ex]
        hit = np.where(sd[:, None] > 0, Lw <= stop_px[:, None], Hw >= stop_px[:, None])
        hit &= np.isfinite(Lw)
        first = np.where(hit.any(1), hit.argmax(1), -1)
        o_hit = Ow[np.arange(len(k)), np.maximum(first, 0)]
        fill = np.where(sd > 0, np.fmin(o_hit, stop_px), np.fmax(o_hit, stop_px))
        stopped = sd * (np.where(first >= 0, fill, exit_px[k]) / en - 1)
        with np.errstate(all="ignore"):
            mfe = np.where(sd > 0, np.nanmax(H[k, s:ex], 1) / en - 1, 1 - np.nanmin(L[k, s:ex], 1) / en)
        rows.append(pd.DataFrame({
            "date": days[k], "sym": sym, "check": ck, "side": sd.astype(int), "chg": chg[k],
            "from_open": px[k] / b["open"][k] - 1, "gap": b["gap"][k], "atr": b["atr"][k],
            "rvol": cumv[k] / avgv[k], "entry": en, "hold": hold, "stop1": stopped, "was_stopped": first >= 0,
            "mfe": mfe, "finish3": sd * close_chg[k] >= 0.03, "left_to_close": sd * (b["last"][k] / en - 1)}))
    big = np.where(b["ok"], np.abs(close_chg) >= 0.03, np.nan)
    return (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()), big


def build(nifty_df: pd.DataFrame, raw: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = nifty_df.index.tz_localize(None) if nifty_df.index.tz is not None else nifty_df.index
    days = pd.DatetimeIndex(sorted(set(idx.normalize())))
    ng = to_grid(nifty_df, days)
    nb = day_basics(ng)
    full = np.isfinite(ng["C"]).sum(1) >= 60
    days_ok = days[full]
    nchg = {ck: pd.Series(nb["C"][:, slot(ck) - 1] / nb["prev"] - 1, index=days) for ck in CHECKS}
    ev, big = [], {}
    for s, df in raw.items():
        g = to_grid(df, days)
        if g is None:
            continue
        e, b = stock_events(s, g, days)
        big[s] = b
        if not e.empty:
            ev.append(e)
    E = pd.concat(ev, ignore_index=True)
    E = E[E["date"].isin(days_ok)].copy()
    E["nifty"] = [nchg[c].get(d, np.nan) for c, d in zip(E["check"], E["date"])]
    E["sector"] = E["sym"].map(U.FNO_SECTOR_OF).fillna("Other")
    sec_mean = E.groupby(["date", "check", "sector"])["chg"].transform("mean")
    sec_n = E.groupby(["date", "check", "sector"])["chg"].transform("size")
    E["vs_sector"] = np.where(sec_n > 1, E["side"] * (E["chg"] - sec_mean) * sec_n / (sec_n - 1), np.nan)
    E["move"] = pd.cut(E["chg"].abs(), MOVE_BINS, labels=MOVE_LABELS, right=False)
    E["rvol_b"] = pd.cut(E["rvol"], [0, 1.5, 3, np.inf], labels=["RVOL <1.5x", "RVOL 1.5-3x", "RVOL 3x+"])
    sg = E["side"] * E["gap"]
    E["gap_b"] = np.select([sg >= 0.01, sg <= -0.01], ["gapped same way 1%+", "gapped other way 1%+"], "small gap")
    E["nifty_b"] = np.where(np.sign(E["nifty"]) == E["side"], "Nifty same way", "Nifty other way")
    E["sector_b"] = np.select([E["vs_sector"] >= 0.01, E["vs_sector"].isna()],
                              ["beats sector 1%+", "sector n/a"], "with sector")
    E["dir"] = np.where(E["side"] > 0, "up (buy)", "down (short)")
    mid = E["date"].quantile(0.5)
    E["half"] = np.where(E["date"] < mid, "H1", "H2")
    B = pd.DataFrame(big, index=days).loc[days_ok]
    return E, B


# ---------------------------------------------------------------- reporting

def summary(x: pd.DataFrame, ndays: int) -> dict:
    n1, n2 = (x["half"] == "H1").sum(), (x["half"] == "H2").sum()
    net = x["stop1"] - COST
    return {"n": len(x), "per day": round(len(x) / max(ndays, 1), 2),
            "finish 3%+ %": round(100 * x["finish3"].mean(), 1),
            "left to close %": round(100 * x["left_to_close"].mean(), 2),
            "best move left %": round(100 * x["mfe"].mean(), 2),
            "hold net %": round(100 * (x["hold"] - COST).mean(), 3),
            "1% stop net %": round(100 * net.mean(), 3),
            "win %": round(100 * (net > 0).mean(), 1),
            "H1 net %": round(100 * (x.loc[x["half"] == "H1", "stop1"] - COST).mean(), 3) if n1 else np.nan,
            "H2 net %": round(100 * (x.loc[x["half"] == "H2", "stop1"] - COST).mean(), 3) if n2 else np.nan,
            "t-stat": round(net.mean() / net.std() * np.sqrt(len(net)), 2) if len(net) > 2 and net.std() > 0 else np.nan}


def table(E, by, ndays):
    rows = []
    for key, x in E.groupby(by, observed=True):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(by, key)), **summary(x, ndays)})
    return pd.DataFrame(rows)


def report(E: pd.DataFrame, B: pd.DataFrame):
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    ndays = E["date"].nunique()
    print(f"\n{E['sym'].nunique()} stocks, {ndays} sessions, {E['date'].min():%d %b %Y} to {E['date'].max():%d %b %Y}")
    print(f"Costs {COST * 100:.2f}% round trip. 'Net' columns use the 1% stop then exit {EXIT} unless named 'hold'.")

    per_day = B.sum(axis=1)
    print("\n1. How many F&O stocks finish 3%+ up or down each day")
    print(f"   average {per_day.mean():.1f} a day (median {per_day.median():.0f}); "
          f"{(per_day >= 5).mean() * 100:.0f}% of days have 5 or more; base rate {np.nanmean(B.values) * 100:.1f}% "
          "of stock-days")

    print("\n2. Continuation map: stocks already X% from yesterday's close at the checkpoint, traded that way")
    m = table(E, ["check", "move"], ndays)
    print(m.to_string(index=False))
    m.to_csv(OUT / f"{PREFIX}momentum_map.csv", index=False)

    print("\n3. Splits at 10:00 for stocks already 2%+ (one filter at a time)")
    x10 = E[(E["check"] == "10:00") & (E["chg"].abs() >= 0.02)]
    for col in ["dir", "rvol_b", "gap_b", "nifty_b", "sector_b"]:
        print(table(x10, [col], ndays).to_string(index=False))
        print()

    print("4. Every combination (checkpoint x move x direction x RVOL x gap x Nifty x sector, 'any' allowed)")
    dims = ["move", "dir", "rvol_b", "gap_b", "nifty_b", "sector_b"]
    rows, tested = [], 0
    for ck, xc in E.groupby("check"):
        for r in range(0, 4):  # up to 3 filters on top of the checkpoint
            for combo in itertools.combinations(dims, r):
                groups = xc.groupby(list(combo), observed=True) if combo else [((), xc)]
                for key, x in groups:
                    tested += 1
                    if len(x) < MIN_N or min((x["half"] == "H1").sum(), (x["half"] == "H2").sum()) < MIN_N // 3:
                        continue
                    key = key if isinstance(key, tuple) else (key,)
                    rows.append({"check": ck, "filters": " & ".join(f"{v}" for v in key) or "(none)",
                                 **summary(x, ndays)})
    G = pd.DataFrame(rows)
    # a filter that keeps every trade gives the same rows as the shorter combination; keep the shorter one
    G = G.assign(nf=G["filters"].str.count("&")).sort_values("nf")
    G = G.drop_duplicates(["check", "n", "1% stop net %", "hold net %"]).drop(columns="nf")
    G.to_csv(OUT / f"{PREFIX}momentum_combos.csv", index=False)
    good = G[(G["H1 net %"] > 0) & (G["H2 net %"] > 0)].copy()
    good["worst half %"] = good[["H1 net %", "H2 net %"]].min(axis=1)
    good = good.sort_values("worst half %", ascending=False)
    print(f"   {tested} combinations tested, {len(G)} distinct with enough trades, {len(good)} positive in both halves "
          f"after costs.")
    if good.empty:
        print("   None held up: chasing stocks that are already moving did not pay in this data.")
    else:
        print("   Best by the weaker half (with this many tries, a few look good by luck: want t-stat 3+ and "
              "several signals a week):")
        cols = ["check", "filters", "n", "per day", "finish 3%+ %", "1% stop net %", "hold net %", "win %",
                "H1 net %", "H2 net %", "t-stat"]
        print(good[cols].head(20).to_string(index=False))
    E.to_csv(OUT / f"{PREFIX}momentum_events.csv.gz", index=False, compression="gzip")
    print(f"\nCSV files in {OUT}: {PREFIX}momentum_map.csv, {PREFIX}momentum_combos.csv, "
          f"{PREFIX}momentum_events.csv.gz")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1800, help="days of 5-minute history (Dhan keeps about 5 years)")
    ap.add_argument("--limit", type=int, default=None, help="test only the first N F&O stocks (quicker)")
    ap.add_argument("--selftest", action="store_true", help="synthetic data, no Dhan; checks the script only")
    a = ap.parse_args()
    t0 = time.time()
    if a.selftest:
        print("SELF-TEST on random synthetic data: the numbers below mean nothing.")
        PREFIX = "selftest_"
        nifty, raw = synthetic()
    else:
        import dhan as D
        if not D.configured():
            sys.exit("Connect Dhan first (Dhan Connect page in Omnipuls, or DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN).")
        nifty, raw = download(a.days, a.limit)
    if nifty is None or nifty.empty or not raw:
        sys.exit("No data downloaded.")
    E, B = build(nifty, raw)
    report(E, B)
    print(f"\nDone in {time.time() - t0:.0f}s.")
