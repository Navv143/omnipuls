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

### V3 by breakout candle and the volume / Nifty filters (5 Nov 2026, same data)
- The 9:30 candle is the best: 109 top-10 breakouts, +0.31% (halves +0.17 / +0.45); 9:35 -0.06%, 9:40 +0.26%,
  9:45 +0.12%, after 9:45 -0.15% (both halves negative).
- The filters help only for breakouts after the first candle: 9:35-9:45 with volume ≥1.5x +0.17% vs -0.07% without;
  at 9:30 almost every breakout passes (81 of 109) and the few that fail did no worse; after 9:45 they do not help.
- V3's own pool (rank 1-2) breaking out at 9:30: 17 trades, +0.61%, but halves -0.25 / +1.37 (too few).
- Early pick changed to: the day's first top-10 breakout on the 9:30 candle, or 9:35-9:45 with volume ≥1.5x; no
  block deal; not gapped 0-1% the trade's way: 47 trades, 57% wins, +0.58%, halves +0.60 / +0.56 (same as before:
  most days the first qualifying breakout is the 9:30 candle).
- Live 5 Nov (Dhan): Motilal ranked 1, broke out at 9:30 with volume 5.2x → traded by V3 and the early pick;
  PI Industries (rank 4) a block deal (85x) → skipped (it lost 1.7%).

## How the day's top gainers / losers look at 9:30 (5 Nov 2026, `research/toppers_study.py`)
235 F&O stocks, 45 days (Yahoo 5-min, 11 Aug - 5 Nov): 10,520 stock-days; topper = the day's top 10 gainers or
losers (8.6% of stocks). Readings from the 9:15-9:30 candles only.
- Toppers are mostly the big movers already at 9:30: of the top 5 movers at 9:30 (move from yesterday's close), 68%
  finish as toppers; top 10 → 55%, top 20 → 38% (and they make 38% of all toppers).
- 9:30 readings that raise the topper rate (lowest → highest fifth): opening range vs ATR 3.8% → 19.2%, opening
  volume vs usual 5.0% → 18.0%, move so far vs ATR 4.7% → 20.1%, first 15 min vs Nifty 4.2% → 20.3%, gap vs ATR
  6.6% → 15.6%, ATR % 4.4% → 14.0%; beyond yesterday's high / low 12.2% vs 6.5% inside; all three candles the same
  colour 11.6% vs 7.7%; first 15 min continuing the gap 10.4% vs 6.5%. Same in both halves. These are V3's ranking
  inputs (ATR, opening range, RVOL, gap), which is why V3's top names are often the day's toppers.
- But the move AFTER 9:30 is a coin flip without a trigger: continuing the direction so far from 9:30 to 15:25 goes
  on 48-51% of the time and loses after costs (all stocks -0.05%, top-20 movers -0.08%). Best static subset: top-20
  movers with opening range >1 ATR or volume >6x: +0.16% after costs, halves +0.09 / +0.20 (thin). Very volatile
  stocks (ATR >4.5%) among the top movers: -0.86%, both halves.
- The tradable part needs the breakout trigger (V3: a close beyond the 9:15-9:30 range, best on the 9:30 candle):
  the V3 early pick +0.58% a trade vs +0.16% for the best static 9:30 selection. Skipping ATR >4.5% does not help
  the early pick (its 3 such picks won).

## "Grinders": flat open, big move by the close (5 Nov 2026, `research/grinders_study.py`)
235 F&O stocks, 45 days: 7,352 flat-open stock-days (|gap| ≤ 0.3 ATR); 587 (8.0%) finish ≥ 1.25 ATR from yesterday's
close. Readings at 9:30 / 10:00 / 10:30 / 11:00 / 12:00, in the direction of the move so far.
- What is different about them (medians, grinders vs other flat opens, 10:30): already 0.76 vs 0.26 ATR from
  yesterday's close; beating Nifty since the open by 1.30% vs 0.51%; above (below) VWAP on 80% vs 67% of candles;
  pullback from the day's extreme 15% vs 38% of the move; volume 1.12x vs 0.73x the usual for the time; their sector
  moving the same way (0.38 vs 0.13 ATR). Before the open nothing separates them: yesterday's range, NR7, ATR %,
  room to the 20-day high / low are about the same.
- When they show: the top 10 flat-open movers become grinders 29% at 9:30, 41% at 10:00, 45% at 10:30, 55% at 12:00
  (base 8%); a grinder almost never reverses its direction after 10:00 (99%).
- Tradable from 10:00 / 10:30, not from 9:30: the "grinder profile" (move ≥ 0.4 ATR, beats Nifty ≥ 0.8%, held VWAP
  ≥ 80% of candles, pullback ≤ 20%) with its sector moving the same way, held to the close, after 0.12% costs:
  10:00 +0.20% (halves +0.10 / +0.28, 8 a day, 59% go on); 10:30 +0.20% (halves +0.23 / +0.18, 14 a day, 62% go on);
  11:00 +0.19% (halves +0.38 / +0.09); 12:00 +0.15% (+0.40 / +0.02). The same profile at 9:30 loses -0.76% (three
  candles are too few: early strength fades). No stop was used (hold to the close): to be tested with a stop.

### Speed of the move: target / stop / 1-2 hour tests (5 Nov 2026, `research/grinder_exits.py`, `research/ignition_study.py`)
- Grinders are slow, not momentum. Grinder profile + sector at 10:30 (719 trades): median best move within 30 / 60 / 120
  minutes 0.11 / 0.14 / 0.21 ATR (0.36 by the close); only 6% reach +0.5 ATR within an hour, 14% within two hours, 35% by
  the close; the day's best price comes after 2 hours in 61% of trades. Exits after 60 minutes lose (-0.05% to -0.09%),
  after 120 minutes about 0 (+0.01 / +0.12 halves at 11:00); held to the close with the stop at the day's opposite extreme
  and a 1.5 ATR target: +0.18% (halves +0.14 / +0.20, 56% win). A tight stop (0.3 ATR) is worse (+0.13%).
- Momentum ignition (first 5-min candle of the day breaking the day's high / low on >= 1.5x usual volume, 09:30-13:55,
  4,936 events): no fast move on average - 9% reach +0.5 ATR within an hour, average 60-minute result +0.01 ATR, every
  target / stop / 1-2 hour combination loses after costs (-0.08% to -0.09%). Higher volume (5x+) or earlier time only
  slightly faster (14% / 12% within an hour), still negative.
- What separates the 9% fast movers from the 58% duds (no +0.2 ATR in an hour): bigger signal candle (0.28 vs 0.22 ATR),
  more volume (3.1x vs 2.7x), already further from the open (0.57 vs 0.46 ATR), Nifty not strongly the same way. The
  clearest: stocks already >= 1.5 ATR on the day - 24% reach +0.5 ATR in an hour, 33% in two; with a 0.4 ATR stop and a
  1.5 ATR target held to the close +0.13% (172 trades, halves +0.12 / +0.14, 40% win); limited to 2 hours +0.05%.
- So: in F&O stocks the fast momentum is at the open (big 9:30 movers, V3 early pick); after that the moves that last
  are slow grinds that pay only if held to the close. Both added as paper setups with the result after 1 h / 2 h
  recorded (momentum_paper.py, crypto_paper pct_60 / pct_120).

## Move finder: every stock, every 5 minutes, machine learning (5 Nov 2026, `research/move_finder*.py`)
634,008 stock-candles (09:30-14:20, 46 days, both directions). Label: from the next open, +0.75 ATR within 60 minutes
before -0.3 ATR (0.7% of moments). Gradient-boosted model trained on 25 days, judged on the 21 later days it never saw.
- WHEN a big move comes is predictable: test AUC 0.74; the top 1% of moments see a fast 0.75 ATR move 12.5% of the
  time vs 1.4% normally (9x). What they share: the last 30 minutes already wide (0.69 vs 0.20 ATR), volume about 3x the
  usual for the time, the day's range already about 1.5 ATR, early in the day (around 10:35), weak market breadth.
- WHICH WAY is not: the model's side is right 7.0% vs wrong 5.5% in its top 1%; a model trained only on the moves to
  tell up from down reaches AUC 0.565 (the best single reading, the last 15-minute move, 0.56). After the stop and
  0.12% costs every version is about 0 or negative (top 1%: -0.06%; top 3 a day: +0.24% but halves -0.01 / +0.48).
- A two-sided breakout bracket around the last 30 minutes' range on those moments loses (-0.03% to -0.5%): whipsaws.
- Conclusion: from price and volume alone, intraday direction after the open is close to a coin flip in F&O stocks;
  volatility is predictable. Next: test the volatility edge with options (buy ATM straddle on a predicted big move)
  once the recorder has 2-3 weeks of option chains, and add OI / futures-OI readings to the panel (24 Nov study).

## Nifty leg + leaders, up and down (5 Nov 2026, `research/nifty_leaders_study.py`)
Idea from 5 Nov (8 quiet leaders moved together when Nifty made a second leg at 11:40-12:45). Trigger: Nifty 5-min close
beyond its last 60 (or 30) minutes' high / low, 11:00-14:00, first per side and day; buy (short) the top 3 stocks
already >= 0.5 ATR the same way, beyond VWAP, quiet (last 30 min <= 0.35 ATR) and near the day's extreme, strongest
sector first. 32 days, ~25-30 triggers per side.
- Up side: every version loses (-0.01% to -0.31% a trade). Down side: about 0 (-0.17% to +0.06%, halves mixed).
- Why: Nifty itself does not follow through after a midday breakout. After an up breakout of the last hour (47 days, 60
  days of data) Nifty is higher 60 minutes later only 40% of the time (avg -0.06%); after a strong one (> 0.1% beyond the
  range, 11 days) only 18% (-0.15%). Down breakouts: 41% (avg -0.03%). Midday breakouts mostly fade; 5 Nov was the
  exception, not the rule. (A fade of strong midday up breakouts is a possible idea, only 11 cases so far.)
