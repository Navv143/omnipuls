"""Score the Trading Desk's logged picks (desk_log.py): did the CE / PE focus stocks and the verdict pay off?

Reads every desk_log/*.csv on the `logs` branch (git fetch origin logs) plus the local desk_log.csv, downloads the
day's 5-minute bars from Dhan for each logged stock and Nifty (needs a valid token on this PC), and scores each pick
from the next candle after its log time: shares, 1% stop, exit 15:20, 0.12% costs. Groups by the futures buildup
recorded with the pick, which is the part that has no history to backtest.

Usage (Omnipuls folder): .venv\\Scripts\\python research\\desk_log_eval.py
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import dhan as D  # noqa: E402

COST, STOP = 0.0012, 0.01


def load_log() -> pd.DataFrame:
    frames = []
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "logs"], cwd=ROOT, check=True)
        names = subprocess.run(["git", "ls-tree", "--name-only", "origin/logs", "desk_log/"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.split()
        for n in names:
            txt = subprocess.run(["git", "show", f"origin/logs:{n}"], cwd=ROOT, capture_output=True, text=True,
                                 check=True).stdout
            frames.append(pd.read_csv(io.StringIO(txt)))
    except Exception as e:
        print("logs branch not read:", e)
    if (ROOT / "desk_log.csv").exists():
        frames.append(pd.read_csv(ROOT / "desk_log.csv"))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).drop_duplicates(["date", "check", "kind", "name", "side"])


def bars(seg, sid, ins, day) -> pd.DataFrame:
    df = D.intraday(seg, sid, ins, 5, 30)
    i = pd.DatetimeIndex(df.index)
    df.index = i.tz_convert("Asia/Kolkata").tz_localize(None) if i.tz is not None else i
    return df[df.index.normalize() == pd.Timestamp(day)].between_time("09:15", "15:25")


def outcome(df: pd.DataFrame, after: str, side: int) -> float:
    d = df[df.index.time > pd.Timestamp(after).time()]
    if d.empty:
        return np.nan
    e = d["Open"].iloc[0]
    sp = e * (1 - side * STOP)
    for _, b in d[d.index.time <= pd.Timestamp("15:20").time()].iterrows():
        if (side > 0 and b["Low"] <= sp) or (side < 0 and b["High"] >= sp):
            return -STOP - COST
    last = d[d.index.time <= pd.Timestamp("15:20").time()]["Close"].iloc[-1]
    return side * (last / e - 1) - COST


def main():
    L = load_log()
    if L.empty:
        print("No desk log yet.")
        return
    ids = D.equity_ids()
    res = []
    for _, r in L[L["kind"] == "focus"].iterrows():
        sid = ids.get(r["name"])
        if sid is None:
            continue
        try:
            df = bars("NSE_EQ", sid, "EQUITY", r["date"])
        except Exception as e:
            print("skip", r["name"], r["date"], e)
            continue
        res.append({**r.to_dict(), "net": outcome(df, r["logged_at"], 1 if r["side"] == "CE" else -1)})
    R = pd.DataFrame(res).dropna(subset=["net"])
    if R.empty:
        print("No scored picks yet.")
        return
    R["buildup"] = R["extra"].fillna("").replace("", "none")
    print(f"{len(R)} logged picks on {R['date'].nunique()} days; % per trade after costs:")
    print(R.groupby(["check", "side"])["net"].agg(["count", "mean"]).mul([1, 100]).round(3).to_string())
    print(R.groupby("buildup")["net"].agg(["count", "mean"]).mul([1, 100]).round(3).to_string())
    print(R.groupby(pd.cut(R["score"].abs(), [2, 3, 4, 5, 20]))["net"].agg(["count", "mean"]).mul([1, 100]).round(3).to_string())
    R.to_csv(HERE / "results" / "desk_log_scored.csv", index=False)


if __name__ == "__main__":
    main()
