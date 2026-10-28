"""Download research datasets from GitHub-hosted sources into ./data (throttled, resumable)."""
import sys, time, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import universe as U

OUT = Path(__file__).parent / "data"
(OUT / "nse").mkdir(parents=True, exist_ok=True)
EOD = "https://raw.githubusercontent.com/BennyThadikaran/eod2_data/main/daily/{}.csv"
INDICES = ["nifty 50", "nifty bank", "nifty financial services", "nifty it", "nifty auto", "nifty pharma", "nifty fmcg",
           "nifty metal", "nifty realty", "nifty energy", "nifty media", "nifty psu bank", "nifty private bank",
           "nifty infrastructure", "nifty midcap 100", "nifty smallcap 100", "nifty next 50", "nifty 500", "india vix",
           "nifty midcap select", "nifty oil & gas", "nifty consumer durables", "nifty healthcare index", "nifty commodities",
           "nifty pse", "nifty cpse", "nifty india consumption", "nifty services sector", "nifty mnc", "nifty 100",
           "nifty midcap 50", "nifty capital markets", "nifty india defence", "nifty chemicals"]


def get(url, dest, tries=6):
    if dest.exists() and dest.stat().st_size > 200:
        return "cached"
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                dest.write_bytes(r.read())
            return "ok"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "404"
            time.sleep(3 * (i + 1))  # 429: back off
        except Exception:
            time.sleep(3 * (i + 1))
    return "failed"


def main():
    names = sorted(U.FNO_SECTOR_OF) + INDICES
    stat = {}
    for n in names:
        fn = OUT / "nse" / (n.replace(" ", "_").replace("&", "and") + ".csv")
        r = get(EOD.format(urllib.parse.quote(n.lower())), fn)
        stat.setdefault(r, []).append(n)
        if r == "ok":
            time.sleep(0.6)
    for k, v in stat.items():
        print(k, len(v), v[:40] if k != "ok" and k != "cached" else "")
    other = {
        "fx_daily.csv": "https://raw.githubusercontent.com/datasets/exchange-rates/main/data/daily.csv",
        "wti_daily.csv": "https://raw.githubusercontent.com/datasets/oil-prices/main/data/wti-daily.csv",
        "brent_daily.csv": "https://raw.githubusercontent.com/datasets/oil-prices/main/data/brent-daily.csv",
        "natgas_daily.csv": "https://raw.githubusercontent.com/datasets/natural-gas/main/data/daily.csv",
        "btc_1min_hist.csv.gz": "https://raw.githubusercontent.com/ff137/bitstamp-btcusd-minute-data/main/data/historical/btcusd_bitstamp_1min_2012-2025.csv.gz",
        "btc_1min_latest.csv": "https://raw.githubusercontent.com/ff137/bitstamp-btcusd-minute-data/main/data/updates/btcusd_bitstamp_1min_latest.csv",
    }
    for fn, url in other.items():
        print(fn, get(url, OUT / fn))


if __name__ == "__main__":
    main()
