"""One source of truth for every setup (all signals run on closed 3-minute candles from 7 Nov 2026 - candles.py;
the backtests below were on 5-minute candles, so the live record re-checks them on 3 minutes): when it looks, how it enters, its stop and exit, what the backtest said, and
its status. The Desk's playbook and blotter and the Research Lab's scoreboard read from here.

status: "core"     tested edge, trade it (paper until the live record confirms)
        "testing"  promising backtest, recording on paper
        "rejected" tested and failed (kept so we do not test it again)
`prefix` matches the setup names written to Supabase crypto_paper (rows are "<prefix> <SYMBOL>").
"""
from __future__ import annotations

SETUPS = [
    # ------------------------------------------------------------------ stocks
    {"prefix": "V3 early pick", "market": "Stocks", "status": "core", "window": "09:30-10:00",
     "look": "Top-10 mover at 9:30 (ATR, volume, range); no block deal; not a 0-1% gap its way",
     "entry": "First 3-min close beyond the 9:15-9:30 range (9:30 candle closes 9:33; 9:33-9:45 candles need 1.5x volume)",
     "stop": "0.5 ATR", "exit": "1 hour after entry: below -0.25% -> exit, else hold (trail 1 ATR, out 15:20)",
     "bt": "+0.58% a trade", "bt_win": "57%", "bt_n": "54 days",
     "note": "The only stock setup that keeps passing. Hour-1 check (276 breakouts): +0.23% vs +0.14% holding all. 77% of breakouts happen by 10:00: no break by 10:00 = no trade."},
    {"prefix": "V3 (top 2, filters)", "market": "Stocks", "status": "testing", "window": "09:30-12:00",
     "look": "V3's top 2 ranked stocks", "entry": "Breakout of the 9:15-9:30 range with volume and Nifty filters",
     "stop": "0.5 ATR", "exit": "Trail 1 ATR, out 15:20", "bt": "-0.05% a trade", "bt_win": "48%", "bt_n": "54 days",
     "note": "Kept to compare with the early pick."},
    {"prefix": "Footprint top 2 10:00", "market": "Stocks", "status": "testing", "window": "10:00",
     "look": "Most big-player footprints by 10:00: trap first, absorption, strong closes, gap against then turned, "
             "volume on its side, rejection wicks", "entry": "10:00 candle's open, in its direction so far",
     "stop": "1 ATR", "exit": "15:20", "bt": "+0.55% a trade", "bt_win": "65%", "bt_n": "39 days",
     "note": "Train +0.58% / test +0.51%, long and short alike. 6-month server run to confirm."},
    {"prefix": "Aligned 10:00", "market": "Stocks", "status": "testing", "window": "10:00",
     "look": "Stock, its sector and Nifty the same way; >= 0.5 ATR; >= 2x volume", "entry": "10:00 candle's open",
     "stop": "0.75 ATR", "exit": "Target 1.5 ATR or 15:20", "bt": "+0.16% a trade", "bt_win": "55%", "bt_n": "32 days",
     "note": "Halves +0.15 / +0.17."},
    {"prefix": "Grinder 10:30", "market": "Stocks", "status": "testing", "window": "10:30",
     "look": "Flat open; >= 0.4 ATR; beats Nifty 0.8%; VWAP held 80%; pullback <= 20%; sector with it",
     "entry": "10:30 candle's open", "stop": "Day's opposite extreme", "exit": "Target 1.5 ATR or 15:20",
     "bt": "+0.18% a trade", "bt_win": "56%", "bt_n": "45 days", "note": "Slow movers: pays only if held to the close."},
    {"prefix": "Sector top 2 UP", "market": "Stocks", "status": "testing", "window": "11:00 / 12:00 / 13:00",
     "look": "Sector up >= 0.3 ATR; its 2 strongest stocks above VWAP, within 0.3 ATR of the day's high",
     "entry": "Next candle's open", "stop": "0.75 ATR", "exit": "Target 1.5 ATR or 15:20",
     "bt": "+0.22% a trade", "bt_win": "56%", "bt_n": "32 days", "note": "Every quarter positive."},
    {"prefix": "Sector top 2 DOWN vs Nifty", "market": "Stocks", "status": "testing", "window": "11:00 / 12:00 / 13:00",
     "look": "Sector down >= 0.3 ATR while Nifty is up; its 2 weakest below VWAP near the low",
     "entry": "Next candle's open (short)", "stop": "0.75 ATR", "exit": "Target 1.5 ATR or 15:20",
     "bt": "+0.13% a trade", "bt_win": "62%", "bt_n": "14 days", "note": "Few days: building the sample."},
    {"prefix": "Ignition big mover", "market": "Stocks", "status": "testing", "window": "09:30-13:55",
     "look": "Stock already >= 1.5 ATR; first 1.5x-volume candle breaking the day's high (low)",
     "entry": "Next candle's open", "stop": "0.4 ATR", "exit": "Target 1.5 ATR or 15:20",
     "bt": "+0.13% a trade", "bt_win": "40%", "bt_n": "172 trades", "note": ""},
    # ------------------------------------------------------------------ index
    {"prefix": "Nifty ORB break", "market": "Index", "status": "testing", "window": "09:30-14:30",
     "look": "Nifty's first 5-min close beyond the 9:15-9:30 range", "entry": "Next candle's open",
     "stop": "Breakout candle's far end (0.1-0.5 ATR, ~40 pts)", "exit": "15:20",
     "bt": "+1.31R a trade", "bt_win": "41%", "bt_n": "22 days", "note": "4 trend days made it; 3-year hourly version ~0R."},
    {"prefix": "Nifty midday fade", "market": "Index", "status": "testing", "window": "11:00-14:00",
     "look": "Nifty closes > 0.1% above its last hour's high (first time)", "entry": "Short at the next open",
     "stop": "-", "exit": "After 60 minutes", "bt": "+0.09% a trade", "bt_win": "82%", "bt_n": "11 days",
     "note": "Midday breakouts fade 82%; few cases."},
    {"prefix": "Bank Nifty EBP", "market": "Index", "status": "testing", "window": "1-hour candles",
     "look": "Bank Nifty 1h EBP (50% limit, 20-hour level)", "entry": "Limit at 50%", "stop": "EBP rule",
     "exit": "Hold up to 14 hours (overnight)", "bt": "+0.40R a trade", "bt_win": "27%", "bt_n": "2 years 1h",
     "note": "Beats the control. Overnight risk."},
    {"prefix": "Nifty iron fly", "market": "Options", "status": "testing", "window": "Day after expiry, 09:30",
     "look": "Weekly: sell ATM call + put, buy wings ~2 SD away", "entry": "Real bid / ask from the recorder",
     "stop": "Defined risk (wing width - credit)", "exit": "Expiry day 15:15",
     "bt": "+0.20% of index a week", "bt_win": "62%", "bt_n": "11 years (model)", "note": "Option sellers' edge; real prices to confirm."},
    # ------------------------------------------------------------------ crypto / gold
    {"prefix": "BTC crash buy", "market": "Crypto", "status": "testing", "window": "24/7",
     "look": "5-min fall z <= -9", "entry": "Next candle's open", "stop": "-1.0%", "exit": "+1.5%",
     "bt": "+0.21R", "bt_win": "52%", "bt_n": "2023-26", "note": ""},
    {"prefix": "Gold crash buy", "market": "Crypto", "status": "testing", "window": "24/7",
     "look": "PAXG 5-min fall z <= -4", "entry": "Next candle's open", "stop": "-0.4%", "exit": "+0.4%",
     "bt": "+0.12R", "bt_win": "60%", "bt_n": "2023-26", "note": ""},
    {"prefix": "BTC burst momentum", "market": "Crypto", "status": "testing", "window": "24/7",
     "look": "5-min rise z >= 8", "entry": "After 1 candle", "stop": "Burst low", "exit": "12 candles",
     "bt": "+0.15R", "bt_win": "", "bt_n": "2023-26", "note": ""},
    {"prefix": "ETH burst momentum", "market": "Crypto", "status": "testing", "window": "24/7",
     "look": "5-min rise z >= 8", "entry": "After 1 candle", "stop": "Burst low", "exit": "12 candles",
     "bt": "+0.13R", "bt_win": "", "bt_n": "2023-26", "note": ""},
    {"prefix": "SOL burst momentum", "market": "Crypto", "status": "testing", "window": "24/7",
     "look": "5-min rise z >= 8", "entry": "After 1 candle", "stop": "Burst low", "exit": "12 candles",
     "bt": "+0.24R", "bt_win": "", "bt_n": "2023-26", "note": ""},
    {"prefix": "BTC NY pullback", "market": "Crypto", "status": "testing", "window": "New York session",
     "look": "Trend pullback in the NY session", "entry": "Rule in btc_sniper.py", "stop": "Rule", "exit": "Rule",
     "bt": "+0.09R", "bt_win": "36%", "bt_n": "31 trades", "note": "Weak."},
]

REJECTED = [
    # (idea, market, what was tested, result)
    ("Stock setups with a small stop (13 kinds)", "Stocks", "PDH break / sweep, ORB break / fade, first-hour break / fade, "
     "day-extreme break / sweep, VWAP cross, gap go / fill, ignition / fade; 45 days", "All negative after costs (0.12% = 0.3R)"),
    ("Opposite side of failed breakouts", "Stocks", "Sweeps and fades vs breakouts", "Mirror images: both lose after costs"),
    ("Gap and go, 1-3% gap with the move", "Stocks", "Layer tree, every check time", "-0.13% to -0.22%, both halves"),
    ("Retest / pullback entries", "Stocks", "Retest of the range edge, VWAP pullback, first pullback vs breakout close",
     "Worse than entering on the breakout close"),
    ("Momentum ignition (all stocks)", "Stocks", "First volume-burst day-high break, 4,936 events", "-0.08% to -0.09%"),
    ("Nifty midday breakout + leaders", "Stocks", "Nifty breaks its last hour, buy / short 3 leaders", "Up -0.01% to -0.31%, down ~0"),
    ("Sector midday breakout + top 2", "Stocks", "Sector breaks its last hour", "-0.03% to -0.41%"),
    ("Against Nifty AND own sector", "Stocks", "Lone divergent stocks", "Fade back: -0.18% to -0.39%"),
    ("ML direction model", "Stocks", "634k stock-candles, gradient boosting", "Timing predictable (AUC 0.74), direction not (0.565)"),
    ("Two-sided breakout bracket", "Stocks", "On predicted big-move moments", "-0.03% to -0.5% (whipsaws)"),
    ("Index first-hour break / sweep (3 years)", "Index", "Hourly 2023-26, small stops", "Nifty 0.00R, Bank Nifty -0.14R"),
    ("Index PDH / gap setups (3 years)", "Index", "Hourly 2023-26", "-0.35R to +0.2R, none significant"),
    ("Expected-move fade", "Index", "Nifty beyond the VIX-implied move by midday", "-0.03% (no snap-back)"),
    ("Expiry pin to round strikes", "Index", "Weekly expiries since 2019", "24.4 vs 25.4 points: no pin"),
    ("Noise band (Zarattini)", "Index", "Nifty 5-min / hourly", "Positive before costs, ~0 after"),
    ("Fibonacci levels", "Index / crypto", "Trend-based fib touches", "No edge after the look-ahead fix"),
    ("AMD / PO3 models", "Crypto / gold", "All timeframes", "No edge after costs"),
    ("EBP intraday", "Crypto / index", "Every timeframe, small stop", "No edge (only Bank Nifty 1h overnight kept)"),
    ("Crypto footprints at session opens", "Crypto", "BTC / ETH / SOL 2023-26", "Session-open move fades; footprints rare"),
    ("Fade crypto funding extremes", "Crypto", "Binance funding 2023-26", "Worked 2023-24, lost 2025-26 (rotated away)"),
]

STATUS_LABEL = {"core": "CORE", "testing": "TESTING", "rejected": "REJECTED"}


def family(setup_name: str) -> str | None:
    """The registry prefix a recorded setup name belongs to (longest match)."""
    best = None
    for s in SETUPS:
        if setup_name.startswith(s["prefix"]) and (best is None or len(s["prefix"]) > len(best)):
            best = s["prefix"]
    return best


def by_prefix() -> dict:
    return {s["prefix"]: s for s in SETUPS}
