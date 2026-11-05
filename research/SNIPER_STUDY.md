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
