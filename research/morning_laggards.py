"""Morning laggards (research/novel_ideas.py idea J): at 10:15 rank every F&O stock by its 9:15-10:15 move minus
Nifty's; short the weakest N at the next 5-minute open, cover at 15:15 (also: long the strongest N, and both).
Variants fixed in advance: N = 3 / 5 / 10; plain, and only on days Nifty is down at 10:15. Cost 0.12% a round trip.
Gross and net, by month, both halves; on the server's 6 months (or the local 60 days).

Usage: python research/morning_laggards.py --server
       python research/morning_laggards.py <fno60_new.pkl> <yahoo_idx5m.pkl>
"""
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U   # noqa: E402

COST = 0.12


def naive(df):
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    d = d[d.index.second == 0]
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])


def day_rows(stocks: dict, nifty: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for day in sorted(set(nifty.index.normalize())):
        nz = nifty[nifty.index.normalize() == day]
        m_n = nz[nz.index < day + pd.Timedelta(hours=10, minutes=15)]
        if len(m_n) < 6 or nz.index.max() < day + pd.Timedelta(hours=15, minutes=10):
            continue
        n_mv = (m_n["Close"].iloc[-1] / nz["Open"].iloc[0] - 1) * 100
        for s, b in stocks.items():
            z = b[b.index.normalize() == day]
            if len(z) < 40:
                continue
            m = z[z.index < day + pd.Timedelta(hours=10, minutes=15)]
            a = z[(z.index >= day + pd.Timedelta(hours=10, minutes=15)) & (z.index < day + pd.Timedelta(hours=15, minutes=15))]
            if m.empty or a.empty:
                continue
            rows.append({"day": day, "stock": s, "rs": (m["Close"].iloc[-1] / z["Open"].iloc[0] - 1) * 100 - n_mv,
                         "nifty_10": n_mv, "ret": (a["Close"].iloc[-1] / a["Open"].iloc[0] - 1) * 100})
    return pd.DataFrame(rows)


def evaluate(r: pd.DataFrame) -> str:
    out = []
    days = sorted(r["day"].unique())
    mid = days[len(days) // 2]
    for n in (3, 5, 10):
        for cond in ("all days", "Nifty down at 10:15"):
            per = []
            for day, g in r.groupby("day"):
                if len(g) < 50 or (cond != "all days" and g["nifty_10"].iloc[0] >= 0):
                    continue
                g = g.sort_values("rs")
                per.append({"day": day, "short": -g["ret"].head(n).mean(), "long": g["ret"].tail(n).mean()})
            p = pd.DataFrame(per)
            if p.empty:
                continue
            p["both"] = (p["short"] + p["long"]) / 2
            for leg in ("short", "long", "both"):
                x = p[leg]
                net = x - COST
                pf = net[net > 0].sum() / -net[net < 0].sum() if (net < 0).any() else np.inf
                mon = p.groupby(p["day"].dt.strftime("%Y-%m"))[leg].apply(lambda s: (s - COST).sum()).round(1)
                out.append(f"{leg:5s} weakest/strongest {n:2d} | {cond:20s} | {len(x):3d} days | gross {x.mean():+.3f}% "
                           f"(t {x.mean() / x.std() * np.sqrt(len(x)):+.2f}) | net {net.mean():+.3f}% PF {pf:.2f} win "
                           f"{(net > 0).mean() * 100:.0f}% | halves {x[p['day'] < mid].mean() - COST:+.3f} / "
                           f"{x[p['day'] >= mid].mean() - COST:+.3f} | losing months {(mon < 0).sum()}/{len(mon)} | "
                           + ", ".join(f"{k} {v:+.1f}" for k, v in mon.items()))
    return "\n".join(out)


def main(argv):
    if "--server" in argv:
        import bot as B
        import candles as C
        cache = B.BOT_DIR / "cache_m1"
        stocks = {}
        for s in sorted(U.FNO_SECTOR_OF):
            f = cache / f"{s.replace('&', '_and_')}.parquet"
            if f.exists():
                stocks[s] = naive(C.resample(C.naive(pd.read_parquet(f)).astype("float64"), 5))
        nf = next((f for f in (cache / "NIFTY.parquet", cache / "NIFTY 50.parquet") if f.exists()), None)
        nifty = naive(C.resample(C.naive(pd.read_parquet(nf)).astype("float64"), 5))
    else:
        st, _ = pickle.load(open(argv[1], "rb"))
        stocks = {s: naive(df) for s, df in st.items() if s in U.FNO_SECTOR_OF and df is not None and len(df)}
        nifty = naive(pd.read_pickle(argv[2])["NIFTY"])
    r = day_rows(stocks, nifty)
    head = (f"MORNING LAGGARDS / LEADERS | {r['day'].nunique()} days ({r['day'].min().date()} to {r['day'].max().date()}) | "
            f"{r['stock'].nunique()} stocks | rank 9:15-10:15 vs Nifty, enter 10:15, out 15:15, cost {COST}%")
    text = head + "\n" + evaluate(r)
    print(text)
    if "--server" in argv:
        try:
            import cloudstore
            run_at = datetime.now().isoformat(timespec="seconds")
            cloudstore.upsert_rows("bot_results", [{"run_at": "morning_laggards " + run_at, "result": json.loads(json.dumps(
                {"run_at": run_at, "report": text}, default=str))}], "run_at")
        except Exception as e:
            print(f"save: {e}")


if __name__ == "__main__":
    main(sys.argv)
