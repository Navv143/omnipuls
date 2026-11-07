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

## With or against Nifty, stock and sector (5 Nov 2026, `research/divergence_study.py`)
5 Nov: Nifty +2.4% but 53 stocks fell (PIIND -19%, CUMMINSIND -14%); Capital Goods & Infra (29 stocks, 34% up),
Chemicals and Telecom went against Nifty. Over 46 days 26% of sector-days move against Nifty and ~9 stocks a day finish
>= 1 ATR against it (33 with it). At 10:00 / 10:30 / 11:00, stocks already >= 0.5 ATR their way, by group (32 days,
rest of the day from the next open, 0.12% costs):
- with/with (stock, its sector and Nifty all the same way): ~50 a day, +0.15% to +0.17%; on >= 2x volume (~12 a day)
  +0.15% to +0.18% with both halves positive at every check; with a 0.75 ATR stop and 1.5 ATR target at 10:00 +0.16%
  (halves +0.15 / +0.17, 55% win). Down days (short) only ~3 a day and unstable.
- against Nifty with the sector also against (a sector going its own way): ~12 a day, halves flip sign (-0.39 / +0.34):
  continuation depends on the period, not predictable from these readings.
- against Nifty AND its own sector (alone): fades back - -0.18% to -0.39%, both halves negative; fading it is about 0
  after costs (+0.15% at 11:00, halves +0.28 / +0.01).
- Against-Nifty stocks that finish big vs those that fade: already further (1.0 vs 0.6 ATR), gapped their way (0.31 vs
  0.13 ATR), much more volume (2.1x vs 1.3x) - news-type moves - but trading them is still unstable (halves flip).
Added "Aligned 10:00" (with/with, >= 0.5 ATR, >= 2x volume) and "Nifty midday fade" as paper setups (momentum_paper.py).

## Sector leg + its top 2 stocks, instead of Nifty (5 Nov 2026, `research/sector_leaders_study.py`)
Sector index = average move (ATR from yesterday's close) of the sector's stocks (>= 5 stocks), every 5 minutes.
32 days, both directions, stop first, 0.12% costs.
- A. Sector breakout of its last hour (11:00-14:00), top 2 stocks: loses on both sides (-0.03% to -0.41%) - midday
  sector breakouts fade, like Nifty's.
- B. Sector already >= 0.3 ATR at 11:00 / 12:00 / 13:00, its top 2 stocks that way:
  - UP, top 2 above VWAP and within 0.3 ATR of the day's high, stop 0.75 / target 1.5 ATR, first per stock-day:
    +0.22% a trade, halves +0.07 / +0.33, every quarter positive (+0.09 / +0.17 / +0.34 / +0.29), 67% of days positive,
    ~9 a day. The rest of the sector (rank 3+) only +0.10% (halves -0.06 / +0.21): the top 2 add. Best at 12:00
    (+0.39%, halves +0.35 / +0.42) - not used on its own (picked after seeing the data). Sector >= 0.5 ATR: +0.24%.
  - DOWN with Nifty: unstable (halves +0.27 / -0.64). DOWN against a rising Nifty: +0.13% first per stock-day, +0.34%
    when also below VWAP and near the low - but only 14 days and two of four quarters negative.
  - UP against a falling Nifty: only 8 days, about 0.
Added "Sector top 2 UP" and "Sector top 2 DOWN vs Nifty" as paper setups (momentum_paper.sector_picks).

## Setup scan: breakouts AND their opposites, small stops, 2 stocks a day, 1 index trade (5 Nov 2026)
`research/setup_scan.py` (45 days, 5-min, all F&O stocks + Nifty / Bank Nifty): pdh_break vs pdh_sweep, orb_break vs
orb_fade, first-hour break vs fade, day-extreme break vs sweep-and-reclaim, VWAP cross, gap go vs gap fill, ignition vs
its fade. Structure stop at the signal candle, only small stops (0.1-0.5 ATR), exits 1R / 2R / 3R / close.
- Stocks: median stop 0.4% of price, so 0.12% costs = 0.3R a trade; every setup and its opposite loses after costs
  (best pdh_break -0.06R, gap_fill -0.01R). Before costs breakouts are slightly positive (+0.1 to +0.25R held to the
  close) and the sweeps / fades slightly negative: "the other side" of a failed breakout is not better.
- Top 2 a day: only ORB break ranked by the day's move (= the V3 logic) is positive in both halves (+0.38R, halves
  +0.68 / +0.09). Warning: an arbitrary top-2 of gap fills showed +0.71R while all gap fills are ~0R - with ~90 trades
  +-0.7R is within luck.
- Index: Nifty ORB break, first of the day, stop at the breakout candle (~0.16%, ~40 points), held to the close: +1.31R
  (22 days, halves +1.08 / +1.44) but made by 4 trend days (+14R, +9R, +6.5R, +5.4R); Bank Nifty same rule ~0R.
`research/index_hourly_scan.py` (3 years of hourly candles, ~720 days): with small structure stops nothing is reliably
positive - first-hour break 0.00R (Nifty) / -0.14R (Bank Nifty); best Nifty first-hour breakdown short +0.09R (t 1.0,
every year positive); pdh / gap / sweep versions -0.35R to +0.2R, none significant. A tight index stop is mostly hit by
normal noise. "Nifty ORB break" added as a paper record to see whether the 5-min version holds on new days.

## The option sellers' edge: what options promise vs what happens (5 Nov 2026, `research/option_edge_study.py`)
Daily Nifty and India VIX 2015-2026 (Yahoo), hourly Nifty 3 years.
- Volatility premium is real and persistent: VIX was above the next month's realized volatility on 79% of days (avg 16.5
  vs 14.1). Short ATM straddle proxy (Black-Scholes at VIX): 1-day wins 69% (avg +0.14% of the index); 1-week wins 64%
  (avg +0.24% a week), positive in every year 2015-2026, last 12 months +0.26% - but worst weeks -12% (Mar 2020),
  -3% to -6% in other bad weeks: never unhedged.
- Weekly iron fly (bought wings at 2 weekly SDs, defined risk): wins 62% of weeks, avg +0.20% of the index a week, max
  loss ~2.8%; positive every year (2024 +0.01%, 2026 so far +0.07% - thin years); the buyer of the same (retail side)
  loses -0.20% a week. Wings at 1.5 SD: +0.16%, max loss 1.7%. Caveats: Black-Scholes at VIX (real wings cost more -
  skew), no brokerage / STT / slippage on 4 legs, weekly IV differs from the 30-day VIX: to be checked on real option
  prices from the recorder before any money.
- Expected-move fade (Nifty already beyond the VIX-implied day move by 11:15-14:15, 28% of days): no snap-back (-0.03%).
- Expiry pin to 100-point strikes: none worth trading (close 24.4 vs 25.4 pts from a strike, 33% vs 29% within 15 pts).

## Candle study: the mandatory checklist + big-player footprints (5 Nov 2026, `candle_study.py`)
27 checklist items (before the open / first candle / by the decision time / footprints), read in each stock's direction
so far at 09:30-11:00. Server: 6 months of Dhan 1-minute candles -> 3 / 5 / 15 minutes, every night (bots.run_research).
First local run (Yahoo 5-min, 39 days, 24 usable after the 21-day history):
- The visible items (already >= 1 ATR, top 10 movers now, 3x volume, gap its way, top 2 of its sector) identify the day's
  toppers well - checklist top 2 at 10:30 are toppers 81% of the time on the test days - but by then the move is mostly
  done: rest of the day only +0.06%.
- The footprint items (trap the other way first, absorption, strong closes, opened against then turned, volume on the
  candles going its way, rejection wicks) are what predicts the REST of the day. 5-min at 10:00, >= 4 footprints:
  +0.51% (train +0.47 / test +0.54, every month positive, ~5 a day); top 2 a day by footprints +0.55% (train +0.58 / test
  +0.51, 65% win, 67% of days positive), long +0.48% and short +0.54% (not a market-direction effect).
  Added as paper "Footprint top 2 10:00" (momentum_paper.footprint_picks uses candle_study.stock_rows itself).
- To confirm on the 6-month server run (and 3-min); the in-app table shows it per timeframe and month.
Also added: ironfly.py - paper weekly Nifty iron fly on the recorder's real option prices (bid / ask), marked every cycle.

## Top 10 gainers / losers by opening gap group (5 Nov 2026, `research/gap_groups_study.py`)
46 days, all F&O stocks; groups by the size of the opening gap (either direction).
- Where the toppers come from: gap 0-0.5% 42-46%, 0.5-1% 24%, 1-3% 24-28%, > 3% 6-8%. All stocks: 60% / 25% / 14% / 1%.
- Odds: a > 3% gap becomes a topper 25-31% of the time, a 1-3% gap 8-9%, a flat open only 3% - but flat opens give the
  most toppers in number, and their move comes AFTER the open (open-to-close +3.8% of the +3.9% day).
- Timing (median share of the open-to-close move still ahead): flat opens 83% at 9:30, 69% (gainers) / 57% (losers) at
  10:00, half done by ~10:05-10:20; 0.5-1% gaps half done ~9:55; 1-3% ~9:35-9:40; > 3% ~9:20-9:30.
- So: big gaps must be caught at the open (V3); flat opens can be caught at 9:45-10:30 (footprint / grinder window).
Also: F&O → "Flow radar" view (net flow top 10 increasing / decreasing with a plain story, index treemap of where money
enters and leaves, sudden-change feed, all-F&O sector treemap).

## Crypto: footprints at session opens, and fading the funding crowd (5 Nov 2026)
`research/crypto_footprint.py` (BTC / ETH / SOL 5-min, 2023-10/2026, Asia / London / New York opens, decision at
open + 45 min, hold 6 h, stop 1 ATR): following the session-open move loses (-0.08% after 0.05%); >= 4 footprints
+0.46% but only 98 cases in 4 years, 2023 and the last 6 months negative - the stock footprint edge does not carry over.
`research/crypto_funding.py` (Binance 8-h funding, extreme = top / bottom 5% (2%) of the last 90 days, take the other
side, hold 24 / 72 h, stop 1.5 ATR, 0.10% costs): fading crowded longs loses; following loses; buying when the crowd is
heavily short worked in 2023 (+1.2% to +2.9%) and 2024 (+0.2% to +0.9%) but lost in 2025 and 2026 (-0.4% to -0.8%):
an edge that rotated away - recent months decide, not the 3-year average. No new crypto setup deployed; crash buy and
burst momentum stay on paper.

## Layer tree: every scenario tested separately (5 Nov 2026, candle_study.layer_tree)
Layers in order: gap group → gap side (flat / with the move / against the move) → first candle (strong / weak) →
volume (normal / 1.5-3x / 3x+) → market (with sector + beats Nifty / sector only / Nifty only / alone) → footprints
(0-1 / 2 / 3+) → structure (beyond VWAP + yesterday's high/low broken / beyond VWAP / back inside). Every path with
>= 20 signals is scored: signals a day, top-10 %, rest of the day after costs (all / train / test), win %, months +,
long / short. Shown in the app (Auto Trader → Candle study → Scenario tree). First local run (39 days, 5-min):
- Gap AGAINST the move is positive at every check, both halves, every month: 0.5-1% gap +0.22% to +0.27%, 1-3% gap at
  10:00 +0.38% (train +0.20 / test +0.47).
- Gap WITH the move 1-3% (gap and go) loses at every check, both halves (-0.13% to -0.22%): the retail trap.
- Deep paths reach +0.4% to +0.6% but on 30-100 signals out of ~245 paths: to be confirmed on the 6-month server run.

## How and when to enter (6 Nov 2026, `research/entry_timing.py`)
The 10 biggest movers at 9:30 each day (450 candidates, 45 days), five entries, same exit (stop 0.5 ATR, 15:20, 0.12%):
breakout close beyond the 9:15-9:30 range +0.135% (61% fill, halves +0.18 / +0.10) - the best; market at 9:30 +0.07%;
VWAP pullback +0.03%; first pullback stop entry +0.01% and retest of the range edge +0.005% (halves flip). By gap: > 3%
gap that breaks its range +1.64% (33% fill); 1-3% gap negative with every entry. Clock: 60% of breakouts by 9:45, 77% by
10:00; 25% of candidates had already made the day's extreme before 9:30. Rule: enter on the breakout CLOSE, no retest
wait, no break by 10:00 = no trade, skip 1-3% gap-with-the-move.
Also: app redesign - Desk (market strip, core trades, all setups blotter, playbook by time window, V3 watchlist),
Money Flow, Research Lab (scoreboard backtest vs live, playbook rules, entry & timing, candle study, paper record,
rejected ideas), all setups in setup_registry.py; old pages under More.

## All signals on closed 3-minute candles (6 Nov 2026, candles.py)
Why stocks showed "buying" at 9:15: Dhan returns the candle still forming; at 9:16 the 9:15 candle holds the pre-open
price plus a minute of trade, and money flow / smart score read a gap-up's first minute as buying (the bots could also
fire on a 1-minute-old candle at any time). Now: candles.closed() drops the forming candle everywhere (app loader,
bots), so nothing signals before the first candle closes (9:18). Timeframe: 3 minutes built from Dhan 1-minute
candles anchored to 9:15 (OMNI_TF=5 to go back); history from the shared 1-minute cache (cache_m1). The bots run 10 s
after each candle closes. V3 on 3-minute candles (Yahoo 1-min, 80 stocks, 7 days) works: 6 Nov CGPOWER short on the
9:30-9:33 candle. The backtests were on 5-minute candles: the live record and tonight's 3-minute candle study re-check.

## After the breakout: hour by hour (6 Nov 2026, `research/breakout_hourly.py`)
276 breakouts of the 9:30 top-10 movers (45 days). Median move its way at each hour's end +0.09% / -0.01% / +0.01% /
+0.04% / +0.07%, with ~+0.4-0.6% best and ~-0.3-0.5% worst inside each hour. The first hour decides: below -0.5% after
hour 1 -> rest of day -0.30% (no recovery); 0 to +0.5% -> +0.31%; above +1% -> +0.48% (winners keep running). Rule
"exit at 1 hour if below -0.25%, else hold to 15:20": +0.233% a trade (halves +0.29 / +0.18) vs hold-all +0.139%.
Desk V3 watchlist now shows entry, each hour's move with its high / low, now %, and the hour-1 call.

## Old signal engines retired (6 Nov 2026)
Live paper 5-6 Nov: index funnel 5 trades -0.36R (20% win, stops ~0.7% = 130-400 index points), index momentum bot
-0.21R, momentum funnel 72 trades -0.26R (31% win), master bot -0.06R / -0.24R. None ever passed a backtest; their
stop rule (beyond the last 30 minutes' swing, 0.3-0.6 daily ATR) is far too wide for an index. 6 Nov: Nifty / Sensex
long 10:30 and Bank Nifty short 9:30 all stopped at -1R within an hour, while the tested Nifty ORB break (stop 48
points, 0.2%) was +1.35R. Now: the Auto Trader trades only setup_registry "account" setups (V3 early pick + Nifty ORB
break); the old cards sit in a collapsed "Untested signals - not traded" box on Market View.

## Super Bot back-test (7 Nov 2026, research/superbot_backtest.py)
40 trading days (Sep-Nov 2026), Yahoo 5-minute candles, ~200 F&O stocks, checkpoints every 15 min 09:30-14:30, the
live rules (8 trades a day, best scores first, next-candle entry, stop / target / profit lock / 15:20, cost 0.12%).
No past futures OI or order book: stage 4 ran on unusual candles and the smart score only.

TRADES: 320 on 40 days (8.0 a day) | win 53% | avg +0.148% a trade after costs | avg R +0.07 | h1 +0.022% h2 +0.273% | total +47.2%
  by exit: stop 61 (-1.83%), target 14 (+2.95%), time 204 (+0.37%), trailed 41 (+1.00%)
  by side: DOWN 124 (+0.076%, win 54%), UP 196 (+0.193%, win 53%)
  by entry time: 09h 276 (+0.13%), 10h 44 (+0.25%)
  by score: (0, 8] 55 (+0.18%), (8, 10] 90 (+0.02%), (10, 12] 174 (+0.21%), (12, 99] 1 (-1.18%)
REJECT / REPEAT: 9130 ({'REJECT': 8565, 'REPEAT': 565})
WHAT EACH STAGE ADDS (move to the close in the stage-1 direction, from the checkpoint, before costs):
  stage 2 Expansion      passed n= 56548 +0.142%  |  rejected n= 41618 +0.120%  |  difference +0.023%

Checks: t = 1.64 (not significant), 21 of 40 days positive, weeks from -0.43% to +0.77%. Against every trending stock
at the same checkpoint: Super Bot picks +0.27% to the close, all trending +0.21% (before costs): the stages add ~0.06%,
most of the result is the period's momentum. Stage 4 (without OI) hurt; 276 of 320 trades came at 09:30-09:45 (the
8-trade limit fills early). Verdict: keep on paper; not a proven setup. Re-run weekly on the server's 6 months
(Saturdays, bot_results "superbot_bt ...") and on the live record once it has a few weeks.

## Today's review (6 Nov 2026): where we missed
- Top 20 movers: two kinds. Early (ASTRAL, TIINDIA, CGPOWER, DATAPATTNS, MOTHERSON, HFCL: done by 10:00, several
  gave part back) and late (FORTIS, YESBANK, HAVELLS, CROMPTON, SIEMENS, MCX, ICICIBANK, HDFCLIFE: most of the move
  after 13:00, highs 14:00-15:25; YESBANK, HAVELLS, SIEMENS were negative at 10:00). Median share of the day's move
  done: 29% by 9:30, 48% by 10:00, 72% by 11:00. No setup of ours enters after 14:30 and most only in the morning.
- Super Bot replayed on today: 19 of the top 20 passed all five filters, but the 8-trade limit was full at 9:45
  with ordinary picks (+2.28% in total on 8 trades); the stages are not selective (almost every trending stock
  reaches the decision stage) and the score does not rank the real movers first.
- Shorts against a strong market: on a Nifty +2% day the sector top-2 DOWN shorts, 5 of 6 Ignition shorts and the
  Super Bot's CGPOWER short (-4.36%) were stopped. In the 40-day replay: Super Bot shorts with Nifty > +0.5% at entry
  -0.46% a trade (16, 37% wins), longs with Nifty -0.5..0% -0.35% (43); with the market +0.3% to +0.6%.
- Candidate rules to test on the server's 6 months (not adopted on 40 days): trade with the market only; spread the
  8 trades (e.g. at most 4 by 10:00); an afternoon (13:00-14:30) breakout setup for the late movers; skip entries
  after a move of 2.5+ ATR already made.

## Super Bot: 2-3 picks a day (7 Nov 2026, research/superbot_strict.py)
Every decision-stage candidate of 40 days (9,462, about 237 a day) with its features and the result of trading it.
Seven rules chosen in advance from the earlier findings, tested together, alone and each left out, at most 3 trades a
day and 1 per sector (best score first):

| Version | Trades/day | Win | Avg a trade | t | 1st / 2nd half |
|---|---|---|---|---|---|
| all candidates | 237 | 49% | -0.03% | -3.2 | |
| live rules (8 a day) | 8 | 53% | +0.14% | 1.5 | +0.07 / +0.21 |
| 3 a day, 1 per sector | 3 | 50% | -0.02% | -0.2 | -0.24 / +0.19 |
| **3 a day + with the market** | **3** | **61%** | **+0.29%** | **2.2** | **+0.18 / +0.40** |
| all 7 rules | 1.4 | 56% | +0.27% | 1.2 | +0.13 / +0.40 |

With the market (longs while Nifty is up on the day, shorts while down) is the rule that matters: alone it gives
the best result, and taking it out of the full set drops it to +0.03%. Not overextended and money last 30 min never
removed a trade; stronger than Nifty and unusual candle alone did nothing; sector leader helped the first half only;
volume 2x and unusual candle on top of the market rule gave the same result. Adopted in the live Super Bot (paper):
with the market, 3 a day, 1 per sector. Still to confirm on the server's 6 months (Saturday back-test).

## Super Bot exits (7 Nov 2026, research/superbot_exits.py)
Same entries, 6 stops x 6 targets x 6 trails, on the 120 picks and on all 2,313 market-aligned candidates (40 days):
- Stop: the live swing stop (last 6 candles, 0.3-1.0 daily ATR) is best on both (+0.22% / +0.045% averaged over the
  other choices); tight stops (0.5%, 1-1.5x the 5-min ATR) are near zero or negative: noise stops them out.
- Target: farther is better on both (1R worst; no target / 3R best).
- Trail: lock 50% after 1R is best on the picks; on all candidates no trail averages more (+0.10%) but wins less
  (49% vs 53%); differences 0.02-0.03% a trade.
- Live rule +0.268% (picks) / +0.055% (all); with a 3R target instead of the next swing level +0.278% / +0.076%:
  better on both samples, so adopted (superbot.RULES target_r = 3); stop and profit lock unchanged.

## Why Super Bot trades lose (7 Nov 2026)
- Losers vs winners at entry: almost identical (volume, money, sector rank, move so far, score, risk) - the loss is
  not visible at entry with the data we have.
- What decides it is the market after entry: Nifty against the trade by > 0.3% after entry -> 79% of picks lose
  (-0.91% avg), 76% of all candidates; Nifty with the trade by > 0.3% -> 20-24% lose (+0.89%).
- 46% of losing picks were +0.5% or more first, then reversed (the profit lock starts at +1R, ~1.5%).
- Reacting does not help: exiting when Nifty turns 0.2 / 0.3 / 0.5% against lowers the result on both samples
  (+0.278 -> +0.11 / +0.23 / +0.21% picks; +0.076 -> +0.02 / +0.05 / +0.06% all) because dips often recover; locking
  profit from +0.5R raises wins (69%) but cuts the winners (+0.10% picks, +0.01% all). The current exits stay.
- Losses are the cost of the setup: control them by size (the same rupee risk per trade, 1R = the stop distance)
  and the 3-a-day / 1-per-sector limits, not by more exit rules.

## Super Bot entry window (7 Nov 2026)
Every market-aligned candidate by entry window (40 days): 9:30-10 +0.19% (56% wins), 10-10:30 +0.04%, 10:30-11
-0.01%, 11-12 +0.13% (59%), 12-13 +0.03%, 13-14:30 -0.01%. With 3 a day: from 9:30 (fills in the first half hour)
+0.27% but September -0.6%; 11:00-12:00 only +0.20%, 62% wins, t 2.17, Sep +4.4 / Oct +14.8 / Nov +4.4%, halves
+0.20 / +0.19; opening only +0.16% with September -9.5% (33% wins). Adopted (paper): entries 11:00-12:00.

## Super Bot in time windows (40 days, with the market, 1 per sector / stock, research/superbot_windows.py)

| Plan | Trades/day | Win | Avg | t | Halves | Sep / Oct / Nov | Worst day |
|---|---|---|---|---|---|---|---|
| Live: 11:00-12:00, max 3 | 3.0 | 62% | +0.20% | 2.17 | +0.20 / +0.19 | +4.4 / +14.8 / +4.4 | -2.7% |
| 9:30 1 + 10:00 2 + 12:00 2 | 4.5 | 66% | +0.20% | 2.34 | +0.25 / +0.15 | +11.6 / +13.9 / +10.3 | -5.6% |
| 9:30 2 + 10:00 2 + 12:00 2 | 5.2 | 63% | +0.18% | 2.20 | +0.22 / +0.14 | +9.1 / +16.9 / +11.5 | -7.0% |
| 10:00 2 + 12:00 2 (no 9:30) | 3.6 | 66% | +0.24% | 2.53 | +0.36 / +0.12 | +19.9 / +10.9 / +3.9 | -5.3% |
| 10:00 2 + 11:00-12:00 2 | 3.9 | 68% | +0.27% | 2.94 | +0.35 / +0.18 | +19.0 / +13.8 / +8.4 | -6.1% |

- By window: 9:30-10:00 is weak (+0.06%, -0.07% as the first of 1; Sep -5.7% alone); 10:00-10:30 (+0.25%), 11:00-12:00
  (+0.28%) and 12:00-12:30 (+0.23-0.27%) carry the result.
- Day rules (P&L at the window's start = closed + open trades at that moment's price) made every split worse:
  "trade later only if flat / losing" 1+1+2: +5.0% total vs +20.6% always; "only if winning": +4.0%. Later windows are
  about as good after a winning morning as after a losing one, so stopping or chasing removes good trades.
- 10:00-10:30 was weak for ALL candidates (+0.04%) but good for the top-2 by score: the ranking matters there.
- 40 days, five plans compared: the best-looking row is partly luck. More trades a day = bigger worst day.

### Shifted 15 minutes later: 9:45 / 10:45 / 12:45 (same rules, no stock repeated in a day: checked, 0 overlaps)

| Plan | Trades/day | Win | Avg | t | Total | Sep / Oct / Nov | Worst day |
|---|---|---|---|---|---|---|---|
| 30-min windows 2+2+2 | 5.7 | 56% | +0.13% | 1.66 | +28.8% | +3.4 / +12.1 / +13.2 | -9.0% |
| 30-min windows 1+2+2 | 4.8 | 53% | +0.04% | 0.57 | +8.1% | -1.0 / +4.6 / +4.5 | -6.1% |
| 15-min windows 2+2+2 | 4.6 | 55% | +0.03% | 0.32 | +4.8% | -6.1 / +1.9 / +9.0 | -9.0% |
| 10:45 + 12:45 only | 3.8 | 52% | -0.06% | -0.80 | -8.8% | -7.8 / -0.4 / -0.6 | -4.4% |

By window: 9:45-10:15 +0.35% a trade; 10:45-11:15 -0.04% (worst); 12:45-13:15 +0.07%. "Trade later only if flat /
losing" again worse (+20.0%). A 15-minute shift turns 10:00-10:30 / 12:00-12:30 (+0.25%) into 10:45 / 12:45 (~0%):
the window edge is fragile, so the exact time slots are mostly noise on 40 days. Wait for the 6-month server test.

### Fixed runs: the bot run once at a set time, top N of everything passing (research/superbot_fixed_runs.py)

9:45 top 3 + 11:00 top 3 + 13:30 top 2: 6.7 trades a day, win 55%, +0.06% a trade, t 0.86, Sep -6.5%, worst day -8.8%.
By run: 9:45 +0.24%, 11:00 +0.06%, 13:30 -0.12%. Alone: 9:45 x3 +0.24% (Sep 0.0), 10:30 x3 +0.16%, 12:00 x3 +0.12%,
11:00 x3 -0.15% (Sep -13.8%), 13:30 x3 -0.03%.
A fixed run takes stocks that have been on the list for a while (late); the live bot takes a stock when it FIRST passes
all six stages. Same 11:00-12:00 hour: first arrivals +0.20% a trade, a fixed 11:00 run -0.15%. Freshness matters more
than the clock time; keep the live 'first arrival' design.

## Weak points of the 3-window plan (10:00-10:30 x2, 11:00-12:00 x2, 12:00-12:30 x2) - research/superbot_weakpoints.py, superbot_fixes.py

Base (40 days): 223 trades, 5.6 a day, win 66%, +0.254% a trade, t 3.49, halves +0.34 / +0.17, worst day -6.1%.
- Main loss driver: Nifty turning against the trade after entry. Nifty with the trade by > 0.3%: 66 trades +0.82% each
  (the whole profit); against by > 0.3%: 29 trades -0.27%. Not visible at entry (exiting on a market turn was tested
  earlier and made it worse).
- Chasing: stocks that already moved > 1.0 day-ATR earn +0.006% (top third), > 2.64% on the day +0.04%, > 2.17%
  stronger than Nifty +0.10%. On all candidates the 1.0-2.0 ATR band is negative but > 2 ATR is positive again: not clean.
- Bad days cluster (all trades go with the market, so they are one bet): 22 Oct -6.1%, 3 Nov -3.3%.
- 1st trade of the day (10:00 window) +0.12%, 6th trade +0.08%; 2nd-5th +0.24 to +0.42%.

Fixes (skipped stocks replaced by the next best, as live):
| Version | Trades/day | Avg | t | Halves | Worst day |
|---|---|---|---|---|---|
| Base | 5.6 | +0.254% | 3.49 | +0.34 / +0.17 | -6.1% |
| Skip moved > 1.0 day-ATR | 5.2 | +0.265% | 4.16 | +0.28 / +0.25 | -4.3% |
| Skip > 2.5% stronger than Nifty | 5.4 | +0.290% | 4.82 | +0.38 / +0.20 | -3.8% |
| Day loss cap 1.5% | 5.1 | +0.264% | 3.42 | +0.34 / +0.17 | -5.3% |
| Max 5 a day | 5.0 | +0.277% | 3.47 | +0.35 / +0.20 | -5.8% |
| Moved <= 1.0 ATR + loss cap 1.5% | 4.7 | +0.285% | 4.23 | +0.28 / +0.30 | -3.4% |
The fixes add little to the average (+0.01 to +0.04%) but cut the worst day; on the live 11-12 rule the ATR cut does
nothing. The bigger step is the 3 windows themselves. Confirm on the 6-month server data before going live.

## Target: 70%+ wins with profit factor > 1.5 (research/superbot_winrate.py, 420 exit combinations)

As now: 3 windows win 66% PF 1.83; + 'moved <= 1.0 ATR' win 65% PF 2.03; live 11-12 x3 win 62% PF 1.64.
- 12 exit combinations pass win >= 70% and PF > 1.5 in BOTH halves; all use 'stop to cost after +0.5R' (no target):
  3 windows + moved <= 1.0 ATR: win 74.2%, PF 2.55, +0.32% a trade (h1 78% / 2.49, h2 71% / 2.59).
- But 86 of its 155 wins are scratches (+0.0 to +0.1% after costs). With 0.05% slippage on stop fills the win rate falls
  to 42% (PF 2.47): a 70% win rate here is only on paper.
- Real profit locks (move the stop to +0.4..0.8% after a +0.8..1.5% move), 0.05% slippage: win 61-64%, PF 1.9-2.25 in
  both halves, +0.23..0.36% a trade. E.g. after +1.2% lock +0.6%: win 63%, PF 2.19 (h1 2.22 / h2 2.15), +0.33%.
Conclusion: PF > 1.5 is met comfortably (about 2.0-2.3, steady); a REAL 70% win rate is not reached by exits or by the
filters tested so far (the profit comes from ~18% of trades that make > 1%).

## ORB / yesterday's levels, and sector vs Nifty direction (superbot_orb_sector.py, sector_independence.py)

Sector independence (daily, 3 years, sector indices): least tied to Nifty = IT (corr 0.51), Pharma (0.52, up on 28% of
Nifty down days), FMCG (0.59); then PSU Bank, PSE, Metal, Realty (~0.7). BankNifty / Fin Service / Infra move with Nifty
(0.87-0.89, opposite on only 16-19% of days). Intraday 60 days (F&O stocks): Pharma (5-min corr 0.38), Telecom, Chemicals,
IT, Capital Goods (~0.5) most independent; Chemicals and Capital Goods closed opposite to Nifty on 42% of days.

Direction rule (40 days, all candidates): against Nifty but with the sector = 683 trades, -0.12% each (PF 0.76); in
independent sectors -0.11%, Nifty-linked -0.13%. 3-window plan: with Nifty +0.254% (PF 1.83); with sector instead
+0.073% (PF 1.17); Nifty OR sector +0.116%; independent sectors following their sector +0.161%; the added trades alone
-0.20% (PF 0.66). So the skipped 'against Nifty' moves lose on average, even in Pharma / IT: keep the Nifty rule.

Breakouts (market-aligned candidates): 94% are already beyond the 15-min opening range; the 6% that are not lose
(-0.14%, PF 0.73). Beyond the 30-min range or yesterday's high / low makes no real difference. In the 3-window plan:
+ beyond 15-min range +0.268% (PF 1.88, worst day -5.2%), + beyond 30-min range +0.281% (PF 1.92), + beyond yesterday's
high / low +0.227% (worse). Small gains; the 15-min range rule is a cheap safety filter.

## Out-of-the-box ideas (research/novel_ideas.py; gross = no costs, then net; train vs test)

Holds in both periods but too small for costs: gold +0.023% in the hour after the 10:30 London fix (t 3.2; net -0.007%
at 0.03% cost); Nifty's 9:15-10:15 hour drifts down -0.036% (t -2.7, 2023-2026); heavyweights' last-15-min lead over
the index predicts the next 15 min (+0.013%, t 3.1); big 30-min index moves continue (+0.02-0.03% in 30 min) - fading
them in 'choppy' variance-ratio regimes loses. No edge: hour-of-day for BTC, crypto funding hours, London -> NY
reversal (gold, BTC, EUR, GBP), BTC weekend -> Monday (train +1.3%, test +0.04%: decayed), narrow-breadth fade, quiet
first hour breaks.
Morning laggards (research/morning_laggards.py, 58 days): short the weakest 3 / 5 / 10 stocks vs Nifty at 10:15, cover
15:15: net +0.29 / +0.20 / +0.07% a trade; only on days Nifty is down at 10:15: +0.51 / +0.40 / +0.20% (PF 2.8, no
losing month, both halves +). Longs on the leaders lose. 6-month server check runs Saturday night.

## Cross-sectional scan (research/cross_section_scan.py, 58 days, 160 rules fixed in advance, train / test halves)

No rule reached t >= 2 on the train half alone (29 days is short). But the 16 rules positive after costs in BOTH halves
are ALL one family: SHORT the weakest 5 stocks (by move vs Nifty, vs sector, below VWAP, or weak on high volume) at
10:15 / 11:15 / 12:15, cover 15:15: +0.2-0.34% gross, +0.1-0.26% net a trade. Hedged with Nifty it stays positive but
small (+0.04-0.09% net): weak stocks keep underperforming into the close, and part of the gain is the market falling.
Longs on the strongest stocks: ~0 in every variant. Opening gap: no edge.
Portfolio (38 days, equal size per trade): Super Bot 3 windows 71% winning days, PF 3.4; weak-stock shorts family 58%,
PF 2.6; together 74% winning days, PF 3.65, worst day -6.6% - but correlation 0.65 (both lean short on weak days), so
they are not independent; Nov: both down. Needs the 6-month check (morning_laggards.py runs Saturday night).
