# What makes an F&O stock trend intraday (momentum study, 5 Nov 2026)

`momentum_study.py` · first run on Yahoo 5-minute candles: 235 F&O stocks, 45 sessions (31 Aug - 4 Nov 2026),
~7,900 stock-days per decision time (9:30, 9:45, 10:15). Tuning days to 8 Oct, unseen days from 9 Oct.
Trade = enter in the direction of the move at the next candle, hold to the 15:15 close, 0.12% costs.
The server re-runs it every night on the Setup Finder's year of Dhan 5-minute candles (results on the Bots page).

## 1. What comes before a trend day (open → 15:15 ≥ 1.5 ATR; 4.7% of stock-days)

By 10:15, a trend day was this many times more likely than average:
| Reading at 10:15 | Lift |
|---|---|
| Already moved ≥ 0.54 ATR from the open | 3.4× |
| Range so far ≥ 0.83 ATR | 3.3× |
| First 15 minutes' range ≥ 1.38× its usual | 2.7× |
| Moving ≥ 1.2% more than the market | 2.6× |
| Volume so far ≥ 1.4× the usual for this window | 2.4× |
| Money-flow share ≥ 64% in the move's direction | 2.3× |
| Within 0.36 ATR of (or beyond) the 20-day high / low | 1.9× |
| Open = low (long) / open = high (short) | 1.5× |
| Low-volatility stock (ATR 1.1-2.0% of price) | 1.4× |
| Market / sector moving the same way | 1.2× (against: 0.4-0.6×) |

## 2. But do they pay when entered at that time?

Mostly no: the obvious momentum readings (big volume, big relative strength, already far from the open) predict a
big day but the move is largely done by the time they show; entering at 10:15 earned about zero after costs.

What held in both the tuning and the unseen days (t counted over days, because all trades of one day move with the
market):
- **A stock moving against the market loses**: -0.21% to -0.38% a trade at every decision time, t -1.8 to -4.0 over
  days, negative in both periods. The clearest result: never trade a stock's move against the market's direction.
- With the market + not yet at the 20-day extreme (≥ 0.36 ATR of room): +0.20% to +0.25% a trade, up on 56-62% of
  days, t ≈ 2 over 39 days. Promising, not proven.
- Moving against the opening gap (gap filling) beat moving with it: +0.07% to +0.10% vs -0.06% to -0.09%.
- After a wide day yesterday (range ≥ 1.25 ATR) continuation fails (-0.09% to -0.11% in both periods).

## 3. Rules

3,600+ rules of 1-3 conditions per decision time; **none passed** on the unseen days once t is counted over days
(45 sessions are too few). The watch list keeps repeating one idea, to test on the full year:
**quiet yesterday (range ≤ 0.65 ATR) + moving ≥ 0.34 ATR from the open + market the same way + room to the 20-day
extreme** (+0.30% to +0.38% a trade on unseen days, 58-66% wins, t 1.8-2.3 over ~17 days).

This agrees with the earlier research (research/intraday/README.md): chasing stocks that already moved does not
pay; the edges come from the market's direction, compression → expansion, and the open (gap fade).

## Index funnel (5 Nov 2026, `index_funnel.py`)

Nifty 50, Bank Nifty, Fin Nifty, Sensex, Midcap Select on Yahoo 5-minute candles (52 days, 11 Aug - 4 Nov 2026);
index money and breadth from their stocks (weighted). Signal = first candle 9:30-14:00 where the steps pass, trade to
15:15, 0.02% costs.
| Steps | Signals | %/signal | Win % |
|---|---|---|---|
| 1 ATR active | 170 | +0.03 | 52 |
| + 2 range | 143 | +0.06 | 51 |
| + 3 index money with the move and growing | 139 | +0.12 | 55 |
| + 4 breadth ≥ 60% | 134 | +0.12 | 55 |
| + VIX not against | 127 | +0.10 | 53 (dropped: no help) |
By day (all indices) +0.11% (t 1.5); Nifty alone +0.25% a signal, 61% wins, t 2.6, both halves positive; Bank
Nifty about zero (fading it also loses). Most signals fire at 9:30-9:35. Promising, not proven: the server re-runs it
nightly on a year of Dhan data.

## Bank Nifty variants (5 Nov 2026, Yahoo 52 days, `index_funnel.banknifty_study`)
| Variant | Trades | %/trade | ≈ pts | Win % | 1st / 2nd half % |
|---|---|---|---|---|---|
| Funnel (steps 1-4) | 27 | -0.00 | -1 | 48 | +0.08 / -0.08 |
| Funnel from 10:00 | 20 | +0.03 | 16 | 50 | +0.09 / -0.03 |
| Nifty 50 money as the leader | 28 | +0.04 | 21 | 54 | +0.08 / -0.00 |
| Funnel + Nifty money | 25 | +0.05 | 26 | 52 | +0.13 / -0.03 |
| **Failed break of yesterday's high/low, faded** | 33 | **+0.12** | **67** | **61** | +0.11 / +0.13 |
HDFC+ICICI money as the leader, shorter holds (30-90 min) and fading money divergences did not help. The failed-break
fade matches the older research (Bank Nifty breaks usually fail). Re-tested nightly on the Dhan year and, with the
OI step, on the server's index snapshots (Supabase index_log) after a week of data.

## Momentum Funnel with a trade plan (5 Nov 2026, `research/funnel_backtest.py`)
Plan: entry next candle's open; stop beyond the last 30 minutes' swing low / high (0.3-0.6 daily ATR); half off at 1R
(stop to entry), rest at 2R or 15:15; 0.12% costs. Yahoo 5-minute, 235 F&O stocks, 46 days (31 Aug - 4 Nov).
| Cut | Trades | %/trade | Win % | By day t | 1st / 2nd half % |
|---|---|---|---|---|---|
| Every first signal per stock-day (~46 a day) | 2,102 | +0.04 | 51 | 0.6 | -0.09 / +0.17 |
| First 3 of the day | 138 | +0.21 | 57 | 1.4 | -0.10 / +0.51 |
| First 5 of the day | 230 | +0.18 | 56 | 1.5 | +0.00 / +0.36 |
| Signals at 9:30 | 701 | +0.08 | 51 | 0.7 | +0.07 / +0.09 |
| Top 3 by ATR × range | 138 | -0.01 | 51 | -0.1 | +0.06 / -0.08 |
No cut is positive in both halves with t ≥ 2: not proven. The live record (Supabase trade_signals) decides.

## Index momentum bot (5 Nov 2026, `research/index_momentum_test.py`, `index_funnel.momentum_now`)
Rule (every 5 minutes, 15-minute window): price moved ≥ 0.15 daily ATR AND the index stocks' net money increased AND
breadth vs yesterday ≥ 65% the same way and not falling AND ATR (last 15 min) ≥ 1.0x usual and rising. Trap = price
moved while money and breadth went the other way (rare; fading it lost → warning only).
Yahoo 5-minute, 45 days, entry next candle, funnel plan (stop beyond the 30-min swing, 1R / 2R, 15:15), 0.02% costs:
| Index | Rule | Trades | %/trade | R | Win % | halves |
|---|---|---|---|---|---|---|
| Nifty | with it, trend days only | 8 | +0.25 | +0.69 | 88 | +0.04 / +0.29 |
| Bank Nifty | fade it, not on trend days | 48 | +0.08 | +0.26 | 60 | +0.04 / +0.10 |
| Midcap Select | with it | 54 | +0.11 | +0.22 | 61 | +0.05 / +0.05 |
| Sensex | with it | 31 | +0.07 | +0.20 | 52 | +0.02 / +0.17 |
| Fin Nifty | lost either way → watch only | | | | | |
| **All together** | | **141** | **+0.10** | **+0.26** | **60** | **+0.06 / +0.14** (t 3.0 by day) |
Rules per index were chosen on this same data: confirm on the live record. 3 years hourly (Nifty): confirmed moves
+0.03% vs +0.01% unconfirmed, both halves +; Bank Nifty momentum no edge (consistent with fading it).
Trend day = 1+ ATR from yesterday's close with 75%+ breadth the same way.
