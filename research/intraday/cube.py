"""Build a [symbol, day, slot] cube from the 5-minute CSVs. Slots 09:15..15:25 (75 bars)."""
import sys, numpy as np, pandas as pd, glob, os
SRC = sys.argv[1]; OUT = "/home/claude/bt/cube.npz"
files = sorted(glob.glob(os.path.join(SRC, "*_5minute.csv")))
frames = {}
for f in files:
    sym = os.path.basename(f).replace("_5minute.csv", "")
    df = pd.read_csv(f, parse_dates=["date"])
    df = df[(df.date.dt.time >= pd.Timestamp("09:15").time()) & (df.date.dt.time <= pd.Timestamp("15:25").time())]
    df = df.drop_duplicates("date").set_index("date")
    frames[sym] = df
    print(sym, len(df), df.index.min().date(), df.index.max().date(), flush=True)
days = sorted(set().union(*[set(d.index.normalize().unique()) for k, d in frames.items() if k == "NIFTY 50"]))
days = pd.DatetimeIndex(days)
slots = pd.timedelta_range("09:15:00", "15:25:00", freq="5min")
syms = sorted(frames)
S, D, T = len(syms), len(days), len(slots)
cube = np.full((5, S, D, T), np.nan, dtype=np.float32)
dpos = {d: i for i, d in enumerate(days)}
for si, s in enumerate(syms):
    df = frames[s]
    di = df.index.normalize().map(dpos)
    ok = ~pd.isna(di)
    ti = ((df.index - df.index.normalize()) - pd.Timedelta("09:15:00")) // pd.Timedelta("5min")
    di = np.asarray(di[ok], dtype=int); ti = np.asarray(ti[ok], dtype=int)
    for k, c in enumerate(["open", "high", "low", "close", "volume"]):
        cube[k, si, di, ti] = df[c].values[ok]
np.savez(OUT, cube=cube, syms=np.array(syms), days=days.values.astype("datetime64[D]"))
print("cube", cube.shape, "days", days.min(), days.max())
