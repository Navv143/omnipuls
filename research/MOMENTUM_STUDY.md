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

## Do OI, net volume or order-book buy/sell help the momentum bot? (5 Nov 2026)
- OI: yes, by the earlier study on real Nifty / Bank Nifty futures 1-minute data 2015-2023 (FINAL_SETUPS.md,
  "Index option buying"): trend days WITH futures OI rising carried the edge; without OI it halved (Bank Nifty) /
  vanished (Nifty). No intraday OI history exists for the 45-day test, so the momentum bot now attaches the futures
  build-up (15 min and the day) to every signal and the server records it (trade_signals.note) to compare
  confirmed vs unconfirmed on the live record.
- Net volume / cumulative delta: little extra (moves with RSI, MACD, breaks: all measure momentum; stock-level net
  money adds ~nothing beyond the price move). The bot's money condition already covers it.
- Order-book buy / sell quantity: no evidence yet; recorded every minute by the recorder, to be tested later.

## Momentum bot window: 5 / 10 / 15 minutes (5 Nov 2026)
Same rules, all indices with their per-index modes, 45 days:
| Window | Trades | %/trade | Win % | halves | t (days) |
|---|---|---|---|---|---|
| 5 min (move ≥ 0.08-0.10 ATR) | 144-182 | +0.05-0.06 | 57-58 | +0.04 / -0.01 to +0.02 | 0.4-1.0 |
| 10 min (move ≥ 0.12 ATR) | 160 | +0.06 | 57 | +0.05 / +0.09 | 2.4 |
| 15 min (move ≥ 0.15 ATR) | 141 | +0.10 | 60 | +0.06 / +0.14 | 3.0 |
The 10-minute signal comes a median 5 minutes before the 15-minute one, ~0.11% earlier in price on average, but with more
false starts. Both are live: EARLY (10 min) and CONFIRMED (15 min), recorded as separate sources.

## Closing picks: buy at 15:15, sell next day (5 Nov 2026, `research/closing_study.py`)

Stocks (Yahoo 5-minute, 58 days, 235 F&O stocks, 0.12% costs), readings at 15:15: day's move, last-30-minute move,
close location in the day's range, last-30-minute money share and net vs the day, volume vs usual, sector money.
- No long or short rule held up: e.g. 60%+ buying in the last 30 minutes with net ≥ 2% of the day's turnover and a close
  near the high → next open -0.12%, next close -0.23%. Reversal versions (fade late strength) were ~0 too.
- So the stock picks on the Closing Picks page are labelled untested and recorded to be tested live.

Indices (Yahoo daily, 10 years):
- Nifty, close in the top 20% of the day's range → next open +0.138% (up 70%, 10 of 11 years) vs +0.107% any day.
- Nifty, strong day (1+ ATR) closing at the high → +0.182% (76% up, 11 of 11 years).
- Bank Nifty, top-20% close → +0.201% (11 of 11 years) vs +0.091% any day.
- Bottom-20% closes → ~0 (no short edge).
Small but steady edge. The live page adds the last 30 minutes' index money, breadth change, futures OI build-up and
option writing (calls vs puts added near the money) as confirmations; whether they add anything is tested on the
recorded picks (`closing_picks`, next open and next close after costs).

## 5 Nov 2026: Momentum Funnel day rebuilt (the morning was never recorded)
Trade recording went live at ~13:25, so the funnel's morning picks (10:30-12:55: 94 suggestions, 28 stocks) were not
in trade_signals. Rebuilt from funnel_log (first suggestion per stock and side) with the bots' plan
(funnel.trade_plan) and managed exits (funnel.manage) on Yahoo 5-min candles: `research/funnel_rebuild_5nov.csv`.
- All day: 32 trades closed, 59% wins, +0.13R a trade before costs (+4.1R), about -0.05% a trade after 0.12% costs.
- Morning (before 13:00): 25 trades, 64% wins, +0.17R; afternoon: 7 trades, 43%, -0.02R.
- Buys (with the 2.5% up day): +0.30R; sells (against it): -0.37R, 5 of 8 stopped.
- The recorded afternoon-only view (-0.20R) understated the funnel; one day, still about break-even after costs.

## What separates Momentum Funnel winners from losers (5 Nov 2026, `research/funnel_winners.py`)
1,890 funnel signals (Yahoo 5-min, 45 days to 4 Nov) with the bots' plan and managed exits; every entry reading split
into thirds (`research/funnel_winners_trades.csv`). All signals: 59% wins, +0.05R, -0.04% a trade after costs.
Readings that matter in BOTH halves:
- Market moving with the trade (average F&O move from the open, in the trade's direction): top third (≥0.55%) +0.20R,
  68% wins, +0.18% after costs (halves +0.17 / +0.22); weak market support (<0.24%) +0.04R.
- The stock gapped in the trade's direction (>0.13 ATR): -0.05R, 53% wins (halves -0.14 / +0.01); no gap with it +0.10R.
- Chasing: the last 15 minutes' ATR already > 1.82x usual: -0.03R; calmer +0.08R (halves both better).
Weak / no difference: day ATR, range, the stock's net money and its growth, sector money, how far it had run from the
open, distance from VWAP, time of day (before / after 12:00), yesterday's range. Wider stops slightly better.
Combined (market with ≥0.55%, no gap with the trade, not chasing): 304 trades (6.8 a day), 72% wins, +0.30R, +0.33% a
trade after costs, halves +0.19 / +0.38R. Chosen after looking at the whole sample: to be confirmed on the live record.

## Breakout V3: what makes its picks work (5 Nov 2026, `research/v3_study.py`, `research/v3_study.csv`)
Every session (54 days, Yahoo 5-min): the top 10 of V3's 9:30 ranking (ATR %, 9:15-9:30 range, opening RVOL, gap)
and each one's first 15-min opening-range breakout until 12:00, with V3's own trade (entry next open, stop 0.5 ATR,
trail 1 ATR, exit 15:20, 0.12% costs).
- The ranking does not pick the winner: rank 1 +0.08% (filtered), rank 2 -0.21%, ranks 6-10 +0.13%. What V3 trades
  now (rank 1-2 with the volume and Nifty filters): 56 trades, 48% wins, -0.05% a trade (halves +0.05 / -0.18).
- The volume and Nifty filters do not help: breakouts failing them did +0.09%.
- Timing decides: breakouts by 9:45 +0.20% (halves +0.10 / +0.30); 9:50-10:30 -0.27%; after 10:30 -0.35%.
- Block deals (opening RVOL ≥20x): 8 trades, 12% wins, -0.99% (5 Nov PIIND, RVOL 47, -1.7%).
- Gapped 0-1% the trade's way: 31% wins, -0.24% (same finding as the funnel: the move is partly used up).
- With Nifty's day direction looked strong (+0.19% vs -0.23%) but uses the close: hindsight, not usable.
- Combined (top-10 breakout by 9:45, no block deal, not gapped 0-1% the trade's way, the day's first such breakout):
  49 trades (~1 a day), 57% wins, +0.59% a trade after costs, halves +0.61 / +0.56. Chosen on the same data: to be
  confirmed live. Lodha (3 Nov) ranked 4 and broke out at 10:00, BHEL (4 Nov) ranked 7, Motilal (5 Nov) ranked 2;
  4 Nov's first qualifying breakout was INOXWIND (+3.0%); on 3 Nov the rank-1 pick HFCL lost -3.2%.
