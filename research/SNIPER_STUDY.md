# BTC and gold (XAU): "sniper" intraday setups, 1-2 trades a day, small stop (5 Nov 2026)

Data: BTC Binance spot 5-minute candles, Jan 2023 - Oct 2026 (~1,400 days). Gold: PAXG (gold-backed token, tracks
spot XAU) 5-minute candles, weekdays, same period. Real spot gold (Dukascopy XAUUSD minutes) was downloading too
slowly to finish in the session; re-run on it when complete. Session times in London / New York local time
(daylight saving handled). Entry at the next candle's open, stop and target in the same candle = stop, costs per round
trip BTC 0.05%, gold 0.02% (both optimistic). Tune 2023-2024, confirm 2025-2026. Code: `research/sniper_study.py`.

## Result: no setup passes

Every popular setup loses after costs, in the tuning years and the test years, and most also have no edge before
costs (gross +0.0 to +0.08R).

| Setup (as traders describe it) | BTC avg R | Gold avg R | Median stop |
|---|---|---|---|
| NY opening range breakout (9:30 ET, 15/30 min) | -0.03 to -0.28 | -0.07 to -0.09 | BTC 0.3-0.8%, gold 0.3-0.4% |
| London opening range breakout (8:00) | -0.10 to -0.17 | -0.17 to -0.29 | BTC 0.4-0.5%, gold 0.2-0.3% |
| COMEX open range (8:20 ET) | - | -0.10 to -0.15 | gold 0.26-0.34% |
| Asian range liquidity sweep, faded at London / NY | -0.26 to -0.55 | -0.23 to -0.46 | BTC 0.16-0.31%, gold 0.12-0.20% |
| Previous day high / low sweep, faded | -0.26 to -0.46 | -0.28 to -0.44 | ~0.2-0.35% |
| VWAP 2.5-3σ snap-back | -0.12 to -0.21 | -0.20 to -0.45 | 0.14-0.33% |
| Trend pullback to VWAP (1-hour trend) | London -0.3, **NY +0.03 to +0.09** | -0.14 to -0.39 | 0.2-0.5% |
| ORB only with the 1-hour / daily trend | -0.13 to **+0.08** | -0.02 to -0.22 | 0.3-0.8% |
| First half hour predicts the last half hour | -0.05% to -0.07% a trade | - | time exit |

Best leads (not proven, both t < 1.6):
- BTC: NY-session trend pullback to VWAP (1-hour trend, 13:30-18:00 London, stop below the last 6 candles, stop
  0.3-0.8%, target 3R): +0.09R a trade, 36% wins, 508 trades, positive 2023 / 2024 / 2025, slightly negative 2026;
  falls to ~0 if the stop band changes to 0.4-1.0%: fragile.
- BTC: NY ORB 30 min taken only with the 1-hour trend, target 3R: +0.08R, but +0.15 in tuning vs +0.02 in the test.
- Gold: NY ORB 9:30 ET 30 min only in the daily trend: +0.04 to +0.06R in 2025-26 but -0.10 in 2023-24.

## Why: small stops are the problem
- A stop of 0.12-0.2% on gold ($3-8) or 0.15-0.3% on BTC sits inside normal 5-minute noise; it is taken out before
  the move, so sweep / reversal entries with tight stops lose 0.2-0.5R a trade.
- Costs in R = cost % / stop %: 0.05% on a 0.2% BTC stop is 0.25R per trade before any edge.
- The only things near break-even had stops of 0.4-0.8% (BTC) and traded with the trend in the busiest session (New
  York). That is the opposite of "tiny stop sniper".

## What would be needed before trading it
1. Re-test gold on real spot data (Dukascopy) when downloaded; PAXG has its own noise.
2. Forward-test the two BTC leads in paper for 4-6 weeks (one signal a day at most) before any money.
3. Lower costs (maker / limit entries) matter more than the setup for small stops.

## ICT Power of 3 (PO3) on the 10:00 New York 4-hour candle (5 Nov 2026, `sniper_study.po3`)

Rules from the "Full PO3 checklist": bias = previous 4H candle (6-10 ET) and today's candle from midnight ET agree;
HTF PDA tap = before 10:00 price traded in yesterday's discount (long) / premium (short) half; accumulation = 9:30-10:00
range; manipulation = a sweep beyond it against the bias between 10:00 and 11:30; confirmation = 5-min close beyond the
last 3 candles' high / low (CISD / break of structure) by 12:00; stop beyond the manipulation extreme; target 2R / 3R /
range projection; exit 14:00 (end of the 4H candle). 18 variants (with / without PDA, bias 4H / day / both, 3 targets).

| | Trades | Win % | Avg R after costs | Before costs | Years |
|---|---|---|---|---|---|
| BTC, full checklist, 2R | 333 | 42 | -0.06 | **+0.10** | 2023 -0.29, 2024 +0.01, 2025 +0.08, 2026 -0.08 |
| BTC, full checklist, 3R | 333 | 41 | -0.02 | - | 2023 -0.25, 2024 +0.02, 2025 +0.14, 2026 -0.06 |
| BTC, all 18 variants | 333-704 | 39-44 | -0.02 to -0.09 | | |
| Gold, full checklist, 2R | 221 | 40 | -0.17 | -0.07 | negative every year |
| Gold, all 18 variants | 221-398 | 38-41 | -0.11 to -0.24 | | |

- BTC: the full checklist has a small edge before costs (+0.10R, t 1.5), which taker costs (0.05% round trip on a
  0.43% stop = 0.12R) wipe out; with maker (limit) fills it would be about +0.05R: not worth trading on its own.
- Gold: no edge even before costs; the 10:00 ET 4H candle is not where gold's stop hunts reverse.
- PO3 is taught on Nasdaq futures (NQ); only 60 days of 5-min NQ data are free, too few to test. The 1-minute
  inverse-FVG entry was not tested (5-min confirmation used); a 1-minute entry shrinks the risk but raises costs in R.

## Strategy lab: GitHub, YouTube and paper setups (5 Nov 2026, `research/strategy_lab.py`)

Same honest rules. 11 strategies, BTC and gold (PAXG), 5-min and 15-min:

| Strategy (source) | BTC avg R | Gold avg R |
|---|---|---|
| ICT Silver Bullet 3-4 / 10-11 / 2-3 NY (YouTube) | -0.08 to -0.25 | -0.10 to -0.39 |
| BinHV45 (freqtrade GitHub) | +0.13 to +0.42 but only 22 trades in 4 years | 1 trade |
| ClucMay72018 (freqtrade) | < 10 trades | 1 trade |
| EMA200 + MACD (YouTube) | -0.86 to -1.03 | -0.32 to -0.58 |
| Supertrend + Stoch RSI + EMA200 (viral video) | -0.28 to -0.39 | -0.06 to -0.16 |
| RSI(2) Connors | -0.07 to -0.24 | -0.06 to +0.01 |
| EMA 9/21 + VWAP | -0.11 to -0.13 | -0.22 to -0.24 |
| Bollinger squeeze breakout | -0.18 to -0.19 | -0.21 to -0.27 |
| Donchian 20 breakout | -0.13 to -0.27 | -0.05 to -0.17 |
| First 30 min after the open predicts the day (papers) | +0.01 | -0.11 to -0.18 |
| Gold 10 AM long bias (vendor) | - | +0.01 |

### The one that holds: crash-candle buy (the idea inside BinHV45)
A 5-min close-to-close drop of Z x the 20-day standard deviation of 5-min returns → buy the next open, fixed
target / stop, exit after 4 hours. Long only (fading spikes loses).
- BTC Z=9, target 1.5%, stop 1.0%: 104 trades (0.5 a week), 54% wins, +0.21R (t 1.9), tuning +0.19 / test +0.23,
  positive all 4 years; at double costs +0.16R. Neighbourhood (Z 8-10, target 1.5%, stop 1-1.5%) all positive with
  both halves positive.
- Gold Z=4, target 0.4%, stop 0.4%: 592 trades (3 a week), 60% wins, +0.12R (t 3.2), positive all 4 years and 12 of
  16 quarters; +0.07R at double costs. PAXG crash candles are real gold moves (5-min correlation with COMEX GC 0.95,
  gold fell 0.3-0.6% in the same candles). Last 60 days were negative on both PAXG (-0.12R) and GC (small sample).
- Paper-traded live from 5 Nov 2026 (`crash_buy.py`, agents.py every minute; reproduces the backtest trades).

## Burst study: what happens after every wild 5-minute candle (5 Nov 2026, `research/burst_study.py`)

Every candle with |return| ≥ 4x the 20-day normal 5-min move (BTC, ETH, SOL, gold: ~9-15 a week each, 4 years),
and the next 1-7 candles (entry at the next open, costs in):
- On average bursts do NOT run on after costs. Direction decides: in crypto UP-bursts continue (6 candles: ETH +0.10%,
  SOL +0.08%, BTC +0.05% before costs) and DOWN-bursts snap back (the crash buy). Gold reverses both ways.
- Size decides: giant up-bursts (8x+) continue in all three coins in both halves: 6 candles after costs BTC +0.10 /
  +0.26%, ETH +0.30 / +0.43%, SOL +0.19 / +0.46%. The first candle after usually pauses; the run comes in candles 2-6.
  Very high volume (8x usual) and the New York morning help a little; breakouts of the day's range, the 20-hour trend
  and the close location do not.
- Trade: up-burst ≥ 8x, enter one candle later, stop at the burst candle's low (1.4-2.6% away), exit after 12 candles:
  BTC +0.21% a trade (+0.22 / +0.21), ETH +0.36% (+0.19 / +0.52), SOL +0.61% (+0.64 / +0.58); ~0.7 a week per coin.
  Stops at the burst midpoint (tighter) get shaken out.
- 60 days of oil, gold futures, EURUSD, GBPUSD, USDJPY, USDINR and Nasdaq futures: forex and USDINR bursts do not run
  (run-on 30-40%); oil mixed; Nasdaq up-bursts 6x+ ran on 77% (13 events: watch); too little data for more.
- Paper-traded live as "BTC / ETH / SOL burst momentum" (crash_buy.py, reproduces the backtest trades exactly).
