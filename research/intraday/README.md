# Intraday backtests on 5-minute data (Nifty 100, Feb 2015 - Apr 2026)

1. `python cube.py <folder with *_5minute.csv>` packs the CSVs into cube.npz (symbol x day x 5-minute slot).
2. `python run_v3.py`, `run_sweep.py`, `run_all.py`, `run_extra.py` print the results and write the CSVs.

Fills: entry at the open of the stated bar; a stop is checked against the level known before each bar; a bar that
opens through the stop fills at its open; stop is assumed before target inside one bar. Days with a 20%+ overnight
jump block that stock for 20 sessions (bad prints / corporate actions). Special sessions dropped.
Costs: 0.12% round trip for stocks (0.05% shown too), 0.05% for index trades.

## Stock options (Oct 2026)

`optmodel.py` prices an ATM option bought instead of the shares (Black-Scholes, IV = 1.15 x 20-day realized vol,
monthly expiry, roll under 5 days, 2% round-trip cost on premium). `run_opt.py`, `run_tgt.py`, `swing.py`, `ml.py`,
`ml_gap.py` test intraday rules, profit targets, multi-day setups and walk-forward models on option P&L.
`gapfade_options_dhan.py` repeats the gap fade on REAL 1-minute option prices from Dhan (run it on your computer).

Finding: the only strong edge for option buyers is the gap fade at the opening price (+9.5% per trade on premium,
positive every year). From 9:20 it is roughly zero since 2022. Everything else tested was marginal or explained by
the bull market / survivorship (random stocks held the same way did almost as well).

## Previous-day high/low break (Oct 2026)

Open within +-1% -> 1% move from the open -> first 5-minute close beyond the previous day's high/low, entry next bar.
73,821 signals 2015-2026 (`pdh.py`, `pdh_sim.py`, `pdh_an.py`, `pdh_combo.py`, `pdh_fade.py`).
Result: -0.11% per trade on shares after 0.12% costs, -2.4% per option trade; gross is about zero, and fading the
break loses the same. No volume (9:15-to-signal vs 10/20-day same window), candle-volume, ATR, VWAP, time or Nifty
filter, alone or in 1,068 combinations, gave an edge that held in both 2015-21 and 2022-26.

## Momentum continuation: buy/short stocks already moving (Oct 2026)

`research/momentum_dhan.py` on Dhan 5-minute data, 205 F&O stocks, Nov 2021 - Oct 2026. On average 23.5 F&O
stocks finish 3%+ up or down each day, but a stock already X% from yesterday's close at 9:30-11:00 has almost
nothing left for a trade entered then (0.12% costs, 1% stop or hold to the last bar before 15:20):
- 1-3% movers lose at every checkpoint (-0.04% to -0.10% per trade, t-stat -3 to -14).
- 3%+ by 10:00: +0.05% per trade (H1 +0.14%, H2 -0.04%); with volume 3x+ and Nifty the same way +0.07%
  (H2 -0.02%, t 1.8); gone with 0.05% slippage; about zero in 2025-26. Buying the top-1/2/3 movers: zero.
- The 30-stock first run (+0.33%) was a lucky, Adani-heavy sample. The live scanner built from it was removed.
- Lead to test properly, not traded: shorting stocks 1.5-3% down at 9:30 while Nifty is up (+0.12% to +0.21%,
  t 4-6, both halves positive but smaller in 2024-26). Found among 2,585 combinations, so it needs a fresh test.

## Momentum radar score and big-money bars (Oct 2026)

Same data. Radar score = within-day percentile of volume vs the same window on the last 10 sessions + move/ATR +
move size, for stocks 1%+ from yesterday's close. Only the #1 stock at 10:30 held up: +0.17% per trade (1% stop,
0.12% costs), t 3.1, both halves positive, +0.10% in 2025-26; top 3 +0.07%, top 10 -0.02%; 1 of 25 versions tried.
`research/bigbars_dhan.py`: big-money bars (5-minute candle with 3/4/5x its slot's 10-day volume, in the move's
direction) do not help. 3+ by 10:30: -0.01% per trade (+0.06% in 2021-24, -0.11% in 2025, -0.09% in 2026); buying
loses (-0.07%), shorting is +0.13% but only from 2022-24 (H2 -0.02%). OI cannot be tested (no expired-futures history).

## What big movers look like, and NR5/NR7/box/ATR-squeeze/OBV breakouts (Oct 2026)

`research/fetch_recent.py` (latest bars + 45 days of near+next futures OI), `research/movers_study.py`.
Last month (28 Sep - 29 Oct 2026, 22 sessions): of 4,004 stock-days that reached +-1% from yesterday's close, 405
were the day's top-10 gainers/losers. Movers start at the open: half had moved 1% by the first 5-minute bar, 2% by
9:35, 3% by 10:20. At the first 1% they differed from stocks that stalled in volume (median 1.3x usual vs 0.85x;
3x+ volume -> 38% became top-10 vs 10% base), gap the same way (25% vs 8%) and an early start (72% before 9:30).
They did NOT differ in NR5 (19% vs 18%), NR7, inside day, tight 10-day box, ATR squeeze or OBV leading; futures OI
was added less often for movers (60% vs 67%). Even with 3x+ volume the median move left after the first 1% was +0.19%.
5 years, 206 stocks, breakout of yesterday's high/low or the 10-day box by a 5-minute close (9:20-13:00), entry next
candle, 1% stop: all 84 versions lose after costs (-0.03% to -0.18% per trade); only 12-24% reach +2% before the stop
(an option buyer with a +2%/-1% plan needs 33%+). Adding volume 2x+ raises the +2% share to ~22% but still loses.

## Time-of-day volume spikes, 3-minute and 5-minute (Oct 2026)

`research/fetch_1min.py` (1-minute bars, last 40 days) and `research/volume_spikes.py`. Volume ratio = bar volume vs
the same time slot on the stock's previous 10 sessions; trade the candle's direction from the next bar's open.
Last month (3-minute, 17 sessions): after 5x+ and 10x+ spikes the average move is about 0 at 3-60 minutes, the same
as normal bars; held to the close -0.11% after costs; +1% before -0.5% in 26-28% of trades (2:1 needs 33%+).
Stock-days with a 5x+ spike were top-10 movers 11.6% of the time = the base rate; only 5% of movers had a spike
before their first 1%. 5 years (5-minute, 1,196 sessions, 464k spikes): same answer every year (-0.08% to -0.13%
held to the close; 10x+ spikes +0.015% after 60 minutes). Volume spikes mark activity, not direction.

## Sector money flow, TradeFinder-style (Oct 2026)

`research/sector_flow.py`, 5 years, 206 stocks. At 9:45/10:00/10:15/10:30 the sector with the strongest average
move in ATRs (optionally 70%+ breadth and/or 1.3x volume), then its stock with the highest R-factor proxy (volume vs
usual + move/ATR), entry next candle, "hit and run": 1% stop else exit after 30 minutes. All 64 versions lose
(-0.08% to -0.15% per trade after 0.12% costs, every half and 2025-26); the chosen stock does no better than a
random stock of the same sector or the market-wide top R stock. Last month at 10:00: 22 trades, 50% wins, -0.07%
average before costs. Holding to the close with the 1% stop is about 0.

## TradeFinder's verified trades vs our data (Oct 2026)

`research/tradefinder_trades.txt`: their Sensibull verified P&L (fanged-okra, Upstox), 2 Dec 2024 - 29 Oct 2026:
402 trading days, 369 positive (92%), about Rs 61 lakh shown, losses avg -Rs 2,465; 22 no-trade days, 44 days
not shared, no long-term statement. 398 of 402 days are stock options, 397 on a single stock; 183 different stocks;
63% calls. `research/tradefinder_match.py` (360 trades matched to Dhan 5-minute data): at 10:00 their stock is
already in the top 6% of F&O stocks by move that way (median +1.9%, 0.7 ATR), volume 1.5-1.8x its 20-day same-time
average, 77% had crossed yesterday's high (CE) / low (PE) by 10:30 (median 9:25; base 29%), sector moving the same
way 77% (base 50%). From 10:00 it moved a further +3.1% (median; base +0.7%) and finished in the day's top 10% of
movers 87% of the time. Our radar-style score at 10:30 ranks their stock median #10 (top 20: 71%, #1: 13%): the
radar finds the shortlist; the final pick from it is where their edge is (OI/option data we don't have, plus judgement).
Their 10 YouTube videos (playlist "TRADEFINDER aakash") describe: Nifty bias from index option/futures OI build-up in
the first 15-60 min; trade the extreme sector (strongest/weakest 9:15-10:00); in it the top 2-3 R-factor stocks
(R-factor = volume, OI, beta spread, turnover from 9:15 to now vs the same window on the last 20 days, futures and
options); avoid heavyweights; first 5-15 min low (high for PE) never broken; decisive first 30 min; breakout of
several levels at once (day high, swing high, yesterday's high); range bigger than yesterday's; move with Nifty;
entry mostly 9:45-10:30 on a pullback or strong candle; one trade a day; exit when sideways or a big opposite
candle. Tested on their picks: the morning low/high held for 94% of them but also for 91% of other movers, so it does
not narrow the list; the shortlist (broke yesterday's high/low, sector same way, volume 1.5x) holds their stock in
its top 5 on ~27% of days.

## Top-5 gainers/losers at 10:00, lowest-volume opposite candle break (Oct 2026)

`lvc.py`, `run_lvc.py`, `run_lvc2.py`. About 5-8 signals a day, 2015-2026. All 8 basic variants lose after costs
(-0.01% to -0.05% per share trade, -1.2% to -1.9% per option trade). Best subset: stocks already 2%+ from the open
by 10:00, fresh break, 0.5 ATR stop: +0.08% per share trade (8/12 years), but still -0.2% per option trade.

## Index build-up bars (Option Apex style) for scalping (31 Oct 2026)

`research/apex_backtest.py`. 3-minute bars of option (5 strikes each side) + futures OI build-up, rebuilt from Dhan
1-minute OI of contracts still live: Nifty 27 days, Bank Nifty 23, Fin Nifty 3 (Sep-Oct 2026). Before the last expiry
the rebuild uses next week's / next month's contract, a proxy for the live page. Index points, signed in the bar's way.

- Weak bars (under half a typical bar) say nothing. Strong bars point the right way, modestly: Nifty bars 1-2x typical
  +3.2 pts next 15 min (54% hit); Bank Nifty bars 2x+ +14.6 pts (58%), 4x+ +29 pts (68%, 31 bars).
- Fading a strong bar loses on every index (Bank Nifty -15 pts a trade, t -2.4): never trade against one.
- No mechanical scalp holds up after costs with a 1:3 stop and 30-min exit: the best (Nifty 3-bar streak with the day's
  cumulative build-up, +3.1 pts, t 1.45, both halves positive) loses on Bank Nifty; Bank Nifty's 3x burst (+16 pts)
  loses in the first half. Too few days to trust either.
- Use: direction filter (trade only with strong bars and the day's build-up), not a stand-alone signal. Re-run weekly:
  results/apex_history.csv.gz keeps every rebuilt day, so the sample grows past Dhan's one-month window.
