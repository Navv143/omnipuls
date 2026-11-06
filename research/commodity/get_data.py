"""Download the data the commodity study uses (Yahoo front-month futures): daily since 2000, hourly 2 years,
15-min / 5-min 60 days -> cmd.pkl in this folder. Run from research/commodity/."""
import pickle, time
import yfinance as yf
SYMS = {"GOLD": "GC=F", "SILVER": "SI=F", "CRUDE": "CL=F", "NATGAS": "NG=F", "COPPER": "HG=F"}
out = {}
for k, s in SYMS.items():
    out[k] = {}
    for iv, per in (("1d", "max"), ("1h", "730d"), ("15m", "60d"), ("5m", "60d")):
        x = yf.download(s, period=per, interval=iv, progress=False, multi_level_index=False, auto_adjust=False)
        if x.index.tz is not None:
            x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None)
        out[k][iv] = x[["Open", "High", "Low", "Close", "Volume"]].dropna()
        time.sleep(1)
pickle.dump(out, open("cmd.pkl", "wb"))
