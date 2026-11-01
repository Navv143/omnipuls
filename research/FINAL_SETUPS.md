# Omnipuls - final trading setups (research concluded 1 Nov 2026)

Tested on NSE 5-minute data 2015 - Apr 2026 (Nifty 100 stocks, Nifty, Bank Nifty, India VIX), real 1-minute
Nifty/Bank Nifty futures 2015-2023, and daily data for all NSE stocks. Every result is after costs; filters were
chosen on 2015-2021 and checked on 2022-2026.

## Setup 1 (main, index intraday): Bank Nifty 5-STAR Momentum

Chart: Bank Nifty, 5-minute. One trade a day. Signals on candles from 09:30 to 15:00.

BUY when, at a candle's close, ALL of these are true (SELL is the mirror image):
1. Close above EMA 21 (EMA 9 gives identical results), VWAP, VWMA 20 and Supertrend (10, 3).
2. Market volume on this candle >= 1.5x its 20-day average for the same time of day.
3. Net volume (buying minus selling pressure of the stocks) points up on this candle.
4. RSI(14) >= 65 (SELL: <= 35).
5. Momentum candle: range >= 1.5x the average of the last 20 candles, body >= 50% of the range, green (SELL: red).
6. At least 60% of Nifty 50 stocks trade above their own VWAP (SELL: 40% or fewer).

Entry: at the signal candle's close. Stop: the Supertrend value. No fixed target: trail the stop with the
Supertrend; exit when price breaks it, or at 15:15.

Results (after 12 points cost per trade):
| | Trades/yr | Win % | Net pts/trade | t-stat | 2015-21 | 2022-26 | Years + | Max drawdown |
|---|---|---|---|---|---|---|---|---|
| Supertrend 10/3 (most profit) | 72 | 50% | +29 | 4.0 | +24 | +40 | 9/12 | -1,720 pts |
| Supertrend 5/2 (smoother, ~70 min holds) | 72 | 51% | +24 | 3.7 | +22 | +29 | 9/12 | -1,650 pts |

How to trade it: Bank Nifty futures, a FIXED number of lots (profit comes from the wide-stop trend days; sizing by
stop distance loses). Monthly options keep only ~+2.6% of premium per trade; if buying options, use ITM/ATM and the
same exits. Keep capital for at least 2x the worst drawdown. No 20-day trend filter (tested: it hurts).
Caveats: volume/breadth in the test came from cash-market stocks, not futures volume; some thresholds were picked
after seeing results. Paper-trade 4-8 weeks before real money.

## Setup 2 (stocks): Gap fade at the open

Each morning take the 2 F&O stocks with the biggest opening gap of 3%+. Buy gap-downs, short gap-ups, at the opening
price (pre-open order 09:00-09:08 in cash/MIS). Stop 0.75-1%. Exit 15:20.
Result: +0.66% per trade after 0.12% costs, 188 trades/yr, profitable 12 of 12 years (weaker since 2024).
Bonus: on days Nifty opens 0.5%+ lower, buying the biggest gap-downs made +1.36% per trade (~24/yr).
Only at the opening price: by 9:20 half the edge is gone, so it does not work with options bought later.

## Adaptive portfolio (added 1 Nov 2026): more trades, re-chosen every month

Library: 26 intraday strategies (Nifty / Bank Nifty: 5-STAR variants, sweeps, level breaks, ORB, fades;
F&O stocks: gap fade 9:20, gap-and-go, top-movers ORB follow/fade, prev-day high/low break follow/fade).
Rule: on the 1st of each month, rank the strategies by their last-12-month Sharpe (fixed size per trade, after costs)
and trade the top 5 (only those with a positive score) for the whole month. Nothing uses future data.

Findings (2016 - Apr 2026, out-of-sample by construction):
- Recent performance does predict next month: rank correlation +0.31 (6 m) / +0.34 (12 m), positive in 91-92% of months.
- Trading all 26 strategies all the time loses (-0.6% a month); choosing the recent leaders fixes that.
- 22 generic strategies (tuned momentum removed), top 5 by 12-month Sharpe, futures/cash:
  about 5 trades a day, +2.4% a month on notional, 66% of months and 10/11 years positive, Sharpe 1.8,
  worst drawdown -16% of notional. Weak recently: 2025 -1.2%, 2026 to April +1.8%.
- Most often chosen: stock gap fade 9:20, stock top-movers ORB follow, Bank Nifty / Nifty 5-STAR + volume + net volume.
- BUYING OPTIONS on these frequent signals loses (time decay + spread eat the small moves). An option-scored manager
  is only slightly positive and about zero since 2022. Option buying works only on the big-move momentum setup.
  Option SELLING could not be tested without real option prices (next step: Dhan expired-options data).

How to use: futures / cash (or stock futures) with fixed size per trade; notional 1-1.5x capital
(about 2.4-3.6% a month and -16% to -24% worst drawdown on the history). Paper-trade first.

## Indicator-settings study (added 1 Nov 2026)
4,338 settings per market: EMA crosses (+VWAP), RSI 2-21 reversion/momentum with many thresholds, multi-RSI agreement,
MACD (4 settings x 3 rules), Bollinger 10/20/30 x 1.5/2/2.5 breakout and reversion, Supertrend 7/10/14 x 1.5/2/3,
and the 21 EMA multi-timeframe break (15/30/60 min) + retest (3/5 min), each with 2-3 stops, 3 targets, 2 hold limits.
Real 1-min futures data for Nifty / Bank Nifty (2015-2023, built into 3/5/15/30/60 min) and BTC 1-min (2020-2026).
- Before costs the typical setting makes about +0.01% a trade; costs are 0.03% (index futures) / 0.08% (BTC).
- After costs profitable: Nifty 11%, Bank Nifty 15%, BTC 0% of settings. The 21 EMA 30m/3m retest: 0% on all three.
- Monthly re-tuning (pick last 6-12 months' best settings): Nifty ~0% a month, Bank Nifty ~+0.25% a month (Sharpe <1),
  BTC loses. Indicator tweaking alone does not create an edge; the edges found come from stock cross-sections
  (gap fade, top-movers ORB) and volume/breadth-filtered momentum held through big moves.

## Strategies from social-media videos (tested 1 Nov 2026) - all rejected
Real 1-min Nifty / Bank Nifty futures 2015-2023 (true 3/5/15-min bars), weekly ATM option P&L (VIX IV, 2% cost).
- EMA 9 / VWAP(OHLC4) crossover on 3-min (plain cross or first pullback; exit on close beyond EMA9; -25/-30% premium stop):
  14 variants x 2 indices: futures -0.00% to -0.03% a trade, win rate 17-29%, options -2% to -5% of premium a trade, 0-3 of 8 years positive.
- 9/15 EMA crossover (3/5/15-min, with/without VWAP filter): futures -0.02% to -0.08%, options -3% to -5% a trade, 0-1 of 8 years positive.
- Fibonacci retracement of the first-hour impulse (38.2/50/61.8, two stops, two targets, limit or confirmation entry):
  48 variants; best futures +0.02% (t 1.7, noise for 48 tries); every option version loses (-1% to -10%).
- Weekly pattern "Fri high < Thu high -> Monday visits Fri low (24/25)": real rate 55-58% vs 45% unconditional;
  Mon/Wed -> Thu 52% vs 46%. Traded (sell Monday open, target Fri low): ~0% a trade, negative 2022-26. Stocks: same.
- The "AI day-trader skill" reel contains no rules to test.
- The Trade Room "9 & 15 EMA scalping" (YouTube RMwUsnJB40c; rules from a written summary): EMA9 above EMA15, EMAs
  sloping >=30 degrees, strong candle closing above both EMAs, buy-stop at its high, stop at its low, 1:2, ITM option.
  144 variants (3/5-min, Nifty/Bank Nifty, slope/body/other-index filters). As described (moderate slope): ~0% futures,
  options -0.3% to -2% a trade. Nifty: no version works.
  Only finding: Bank Nifty 5-min with a VERY steep EMA9 (rising >= 0.35-0.5 ATR per candle), any strong close above both
  EMAs: futures +0.03% to +0.07% a trade (t 3.2-4.3, 9-11 of 12 years, 80-220 trades/yr on 2015-2026 index data) but
  weak 2022-2025 and options only +0.5% to +2.5% of premium (negative in 2022, 2023, 2025). Same message as 5-STAR:
  only steep momentum on Bank Nifty has an edge; not strong enough alone for option buying.


## Unusual-activity score (added 1 Nov 2026, F&O Stocks -> Unusual activity)
Live smart score for every F&O stock, candle by candle, vs the same time of day over the last 20 sessions:
time-based volume, turnover and range, candle volume/range, gap vs usual, futures OI change, order-book buy/sell
quantity (snapshots saved to activity_history/), RSI, VWAP, move from open in ATRs. Study behind the weights
(research/intraday/activity_study.py, Nifty 100 5-min 2015-2026): big movers with time-based volume or range 2-3x+
normal continue to 15:15 (+0.06% to +0.10% gross, +0.19% since 2022 for range 3x+); movers on low activity reverse;
single big candles, RSI and candle colour alone carry ~no information. A confirmation/screening tool, not a signal.

## Money flow (added 1 Nov 2026, F&O Stocks -> Money flow)
Each 5-min candle's turnover split into inflow/outflow by where it closed in its range; summed per stock and sector,
for the whole day or the last 60/30/15 min, plus futures OI value change, a sector rotation (from -> to) chart and a
sector x time heatmap. Study (research/intraday/flow_study.py, Nifty 100 5-min 2015-2026): sector flow persists a
little (top-3 inflow sectors beat bottom-3 by +0.04% to the close, +0.043% since 2022); stock-level flow adds ~nothing
beyond the price move and slightly reverses over 30-60 min. Descriptive tool for rotation, not a signal.

## Index option buying - discovery study (1 Nov 2026, research/index_options/)
Nifty / Bank Nifty futures, real 1-min volume + OI 2015-2023, ~129k 5-min bars each, 60+ readings per bar (cumulative
delta, OI buildup, RSI, MACD, VWAP, EMA, Bollinger squeeze, PDH/PDL/opening-range breaks and sweeps, time, VIX, gap),
outcome = ATM weekly option P&L (BS model, VIX IV, 2% cost).
- Random-bar call/put: about -4% of premium per trade (time decay + costs). Every single reading improves it in the
  momentum direction but none reaches zero.
- At cumulative-delta flips RSI jumps ~5 pts, MACD flips / EMA crosses / level breaks are ~3x more frequent and OI shows
  long buildup: the indicators all fire together because they measure the same thing (price momentum).
- Walk-forward LightGBM on all readings (60-min trades): Bank Nifty ~0 to +1% (t<0.5), Nifty -2%: direction is slightly
  predictable (futures +0.05-0.08% an hour) but too little for option premium.
- Day-level, trail to 15:15: trend established by 11:00-12:30 (>=0.6-0.8 ATR from open, VWAP side) WITH futures OI rising
  -> Bank Nifty option buys +4.1% avg (19/20 time x threshold cells positive), Nifty +1.9% (14/19). Without the OI
  condition the edge halves (BN) / vanishes (Nifty). 'First time it happens' entry is weaker and threshold-sensitive
  (BN +5-6% only at 1.0 ATR; Nifty +6-8% at 0.7). t-stats ~1-1.7: real mechanism, noisy, 10-20 trades/yr.
- Conclusion: option-buying edge lives only on trend days with new positions (OI) behind the move (same as 5-STAR).

## Small-cap Bollinger (35, 1.5) breakout, 3-4 month hold (1 Nov 2026, research/smallcap/)
Close above upper band (daily/weekly) then a later candle breaks and closes above that candle's high (with/without
volume 1.5-2x). 2012-2026, Rs 10-30 and Rs 10-200, turnover >= Rs 1 Cr, 0.5% cost, vs random eligible stocks same week.
Weekly, no volume filter, Rs 10-30: +5.5% (63d) vs +3.4% random; Rs 10-200: +5-7% vs +4-6% random. Median trade -5% to
-7%, win 40-44%, positive in 7-10 of 15 years. Volume confirmation makes it WORSE (edge ~0). Daily version ~= random.
Data has survivorship bias (current listings) which flatters both. Verdict: weak, +1-2% over random at best.

## Option-premium MODEL warning + real-price validator (1 Nov 2026)
Intraday option P&L on modelled premiums depends on how a day's time decay splits between session and overnight:
trading-time BS (all decay 09:15-15:30): 09:20 straddle selling wins 12/12 years; calendar-time BS (VIX is calendar
based): it loses 12/12 years (research/index_options/sell_study.py). The truth needs REAL prices:
research/index_options/dhan_index_options.py (run on the PC with Dhan) tests straddle/strangle/iron-fly selling and
the trend+OI / move-only / random option buys on Dhan's real expired-option 1-min data.
Robust under BOTH models: trend-day + OI-rising option buys beat random-time buys by ~+8-9 points of premium a trade
(trading-time: BN +6.7% vs -2.3% random; calendar-time: BN +11.8% vs +3.7%). Earlier option-buying figures in this file
used the trading-time model, i.e. are on the conservative side for buyers.

## Live: Scanners -> "Index trend-day + OI (options)" (trend_alert.py)
Nifty, Bank Nifty, Fin Nifty, Sensex, Midcap Select: move >= threshold x ATR from open, index future on the VWAP side,
futures OI above yesterday, 10:30-13:00 first signal; ATM option, stop -30%, trail 30% from peak after +30%, 15:15 exit.

## Dip-buying from quantifiedstrategies posts, Indian cash stocks (1 Nov 2026, research/dipbuy/mr_test.py)
A) RSI(3)<22 + EMA100 rising + close 1% below 10-day VWAP, buy next open, exit RSI(3)>55: F&O stocks 2012-2026, 1,248
   trades/yr, +0.19%/trade after 0.25% cost, win 64% - but random entries held the same days made +0.10% (edge +0.08%).
   Nifty 50 +0.03%/trade, Bank Nifty +0.19%. Portfolio (5 x 20%): CAGR 4.3%, max DD -40%.
B) Triple RSI(5) (<30, falling 3 days, <60 three days ago, above SMA200, exit RSI5 > 50): 491 trades/yr, +0.57%/trade,
   win 70%, random same-hold +0.48% (edge +0.09%). Nifty 50 -0.54%/trade (61% win; the post claims 90%/+1.4% on SPY),
   Bank Nifty -1.20%. Portfolio: CAGR 10.8%, max DD -33% vs Nifty buy & hold 9.8% / -38% (stock data has survivorship bias).
Verdict: high win rate, almost no edge over just holding; Indian indices trend more than US ones, so dip-buying the index fails.

Small caps (all NSE EQ, Rs 10-30 / Rs 10-200, turnover >= Rs 1 Cr, 0.5% cost, research/dipbuy/mr_smallcap.py):
RSI(3) dip -0.21% to -0.59%/trade (win 55-58%); Triple RSI(5) +0.28% (Rs 10-200) / -0.25% (Rs 10-30), win 60-64%.
Edge vs random small caps +0.2-0.4% (small caps on average lose after costs). Portfolio 5 x 20% (lowest RSI first):
CAGR -6% to -21%, drawdowns -64% to -97%: the deepest dips are often stocks that keep falling. Do not use on small caps.

## Rejected (do not trade)
Previous-day high/low break; top gainers/losers low-volume candle; 9 EMA + pivots; 9 EMA/VWAP crossover;
Nifty liquidity sweep (also with smart-money volume); 1-min first-swing breakout; Nifty/Bank Nifty ORB; gap-and-go;
ML stock picks; small-cap Rs 10-30 breakout screener; swing calls on breakouts; fading new highs/lows with internals; EMA9/VWAP 3-min (video), 9/15 EMA cross, Fibonacci retracement,
Thursday/Friday weekly high-low pattern.

## Next steps
1. Add a live "Bank Nifty 5-STAR" tab to Scanners (all 6 checks every 5 minutes, entry, stop, trail) + internals panel.
2. Re-check Setup 1 with real futures volume and OI from the 1-minute futures data.
3. Run research/intraday/gapfade_options_dhan.py to see whether options at 9:15-9:16 catch the gap fade.
4. Paper-trade both setups; turn on the automatic Dhan token (Dhan Connect).

## Follow-up, 1 Nov 2026 (this PC)
- Live tab added: Setups & Scanners -> "Bank Nifty 5-STAR" (six checks per 5-minute candle, entry, Supertrend stop
  and trail, internals panel). Replay of the last 250 sessions on Dhan data: 64 signals a year, 45% wins, +13 pts a
  trade after 12 pts cost (research: +29).
- Real futures volume and OI (`research/five_star_futures.py`): Dhan has intraday bars only for live contracts, so
  only 23 comparable sessions (24 Sep - 28 Oct 2026, November future, next-month until the 27 Oct expiry). All four
  versions lost in that window (research version 12 trades, -56 pts a trade after cost; futures-volume version -56;
  + OI rising -49 / -75). Every research signal also had futures volume 1.5x+, so the stock-turnover proxy agrees
  with the futures. Too few trades to judge; re-run as more sessions accumulate. The 2015-2023 1-minute futures data
  stayed in the other chat's cloud workspace and is not on this PC.
- Gap fade on real option prices (`research/intraday/gapfade_options_dhan.py`): Dhan's /charts/rollingoption returns
  DH-905 for every request (weekly and monthly, index and stock, 1- and 5-minute), including Dhan's own example
  shape. Not runnable until Dhan support enables it for this account.

## ETH, BTC and gold trend rules, 1 Nov 2026 (`research/eth_gold.py`)
Daily closes, decide at the close and hold from the next day, 0.10% cost per change (crypto), 0.05% (gold); the
period is split in two halves and a rule must beat buy-and-hold on risk in both.
- ETH (Binance, Aug 2017 on): long above the 50-day average, cash otherwise: Sharpe 1.05 vs 0.69 buy-and-hold, worst
  fall -64% vs -94%; second half Sharpe 0.82 vs 0.24, +30.5% a year vs -6.6%. The 20/100-day averages and 30-day
  momentum also beat buy-and-hold in both halves. Usable as a filter (when to hold ETH), not as a trading system.
- BTC: same rule, Sharpe 1.27 vs 0.81; second half 0.89 vs 0.50. Confirms the earlier BTC trend filter.
- Gold (COMEX GC=F, 2000 on): buy-and-hold +10.7% a year, Sharpe 0.66. No trend rule beats it (best: 200-day
  average, Sharpe 0.55). Gold is better simply held than traded on trend.

## Paper trading and option history (from 1 Nov 2026)
- The Trading Desk now logs the gap fade / panic gap-down / sector overreaction picks after 9:20 and every Bank Nifty
  5-STAR signal and its result. Admin -> Desk review -> "Paper trades" shows the running results against history.
- The cloud app records Nifty and Bank Nifty option chains (2 nearest expiries, 12 strikes each side, LTP, bid, ask,
  OI, volume, IV, delta, theta) every 5 minutes to the `logs` branch (`chain_log.py`). After 2-3 months this is
  enough to test option selling on real prices.

## Small fixed targets on momentum, 1 Nov 2026 (`research/momentum_target.py`)
The user's targets: Nifty 25-30 pts, Bank Nifty 45-50, F&O stocks 2-3%, gold 8-10 $, BTC 400-500 $, ETH 15-20 $.
5-minute bars (Indian markets Nov 2021 - Oct 2026, 52 stocks; crypto and gold 2 years from Binance). Three momentum
entries (30-min breakout, 2x range burst, 3 candles one way above/below the 20 average), stop 1x / 0.75x / 0.5x the
target, out after 30 / 60 / 120 minutes, compared with taking the same trade at any candle.
- Momentum entries hit the target only 1-5 points more often than a random entry (Bank Nifty: less often).
- 0 of 54 versions per market made money after costs; none positive in both halves. Before costs Nifty made about
  +1 pt a trade and ETH about +0.01%: the costs are larger than the edge.
- So a small fixed target on a plain momentum candle is not an edge in any of the six markets. Use the Trade odds
  page before a trade, and take small-target trades only on top of a tested setup (gap fade, panic gap-down, sector
  overreaction, Bank Nifty 5-STAR).

## Intraday study, last 1 year (`research/intraday_study.py`, 2 Nov 2026)
Descriptive, not one fixed rule: what happens after the event, in points each way (MFE / MAE), on 3/5/10/15-min
candles. Nifty and Bank Nifty from 1-minute Dhan data (Oct 2025 - Oct 2026); 206 F&O stocks on 5-minute data.
- Previous-day high / low break (first candle closing beyond it, ~70 a year per side per index):
  Nifty: 5-min break, median +28 pts your way vs -22 against in 30 min, +36-47 vs -27-42 in 60 min; about 55% close
  back inside within 30 min; close-out about 0. No volume / RSI / VWAP / time split held up with these small samples.
  Bank Nifty: breaks tend to FAIL: median 60-120 pts against in 60 min, 55-60% back inside within 30 min, and the
  average to the close went against the break in every year 2022-2026 (5 years of 5-min data: -77, -25, -19, -19,
  -46 pts). A lead for a fade setup; needs a proper rules test with stops.
- Same-time candle break (9:15, 9:30 ... 14:00 candle; 3/5/10/15-min): every candle time is close to 50/50 up vs
  down, points with you about equal to points against (Nifty ~30-35 each way in 60 min, Bank Nifty ~70-100), 60-75%
  fall back inside within 30 minutes, the other side breaks too on 40-75% of days. No candle time is directional.
- Top 5 gainers / losers each day (gaps over 3% out): 86-88% made their day low (gainers) / high (losers) in the
  first 15 minutes; 40-45% of the open-to-close move was done by 10:00, ~60% by 11:00. The common "triggers" fired on
  most movers (15-min range break on 88% of gainers, 3x volume burst on 85%), but on ALL stocks the same triggers
  became a top-5 mover only 4-8% of the time (2.5% at random) and the average move after the trigger to the close
  was about 0. The triggers show up on movers because movers move, not because they predict the move (hindsight).
  The real tell is early: the move starts at the open.

## Bank Nifty failed-break fade (`research/bn_fade.py`, 2 Nov 2026) - CANDIDATE SETUP 5
5 years of 5-minute data (Dec 2021 - Oct 2026), Bank Nifty index as the price, 5 pts cost a round trip.
Rule (version "B S2"): the day did not open beyond the previous day's high (or low); a 5-min candle between 9:20
and 14:30 closes beyond it; within the next 30 minutes a candle closes back inside the level -> trade AGAINST the
break at that close (short after a PDH break, long after a PDL break). Stop 0.4 x daily ATR(14) (about 250 pts).
Exit at 15:10's close, or at 2x the risk.
- 347 trades (58 a year), 49% wins, +26 pts a trade (exit at close) / +25 (2R); first half +31 / +23, second half
  +21 / +28; PDH shorts +25 and PDL longs +27. Total about +9,000 pts; worst losing run -3,300 / -2,600 pts.
- Robust: positive in all 36 tried mixes of stop (0.2-1.0 ATR), "back inside within" 15/30/45 min and exit (close or
  2R), both halves positive in all of them. Stops of 0.3 ATR and wider all give +21 to +29 pts. At 10 pts cost still
  +21. Entries before 11:00 +43 a trade; 11:00-14:30 +13 (first half -2).
- Weak years: 2023 (-5) and 2025 (-6 / +4); profit comes from 2022, 2024, 2026.
- Taking the trade right at the break (no "back inside" wait) is weaker; tight stops just past the break lose.
- Nifty, same rules: nothing (about 0). This is a Bank Nifty effect.
- Caveats: the idea came from looking at the last year, so 2026 is not a clean test (2022-2025 are). Index, not
  futures. Wide stop: size by the 250-pt risk. Paper-trade first.

## Popular YouTube methods and the user's own TradingView scripts (2 Nov 2026)
All coded as written, after costs (Nifty 2 pts, Bank Nifty 5, stocks 0.06%, crypto 0.10%, gold 0.5 $).
- Gautam Jha 1-min PDL/PDH reversal: -0.07 to -0.19R. Order-block retest: -0.15 to -0.45R, every year negative.
  Liquidity sweep reversal (index, stocks, gold; swing and yesterday's levels, 5 and 1-min): -0.17 to -0.49R.
  Power of Stocks 5 EMA as taught: -0.20R index, -0.44R stocks; traffic light 1/5/15-min: about 0.
  Gold London breakout: -0.03R (fade -0.45R). (`jha_orderblock.py`, `sweep_london.py`, `powerofstocks.py`)
- User's 22 scripts (`my_scripts.py`, `my_scripts2.py`): PDH/PDL Reversal v3, Momentum Scalper, XAUUSD Confluence,
  BB, Momentum Zone, EMA Ribbon BOS, Key Reaction Candle, 5:30-6:30 zone, 9:30 Sniper, Atomic Supertrend, AMD MSS,
  First Candle bias, RSI turn: all about 0 before costs and negative after.
- Only lead: "Order Flow + Structure + Order Blocks" strategy (SL 1.5%, TP 3%). Gold 15-min "base" signals:
  176 trades in 2 years, +0.31% a trade, 7 of 9 quarters positive, +0.17% without the best 5% (longs +0.70%,
  shorts +0.11%; gold rose strongly in this period). Stocks 5-min "FULL" (+0.10%) falls apart without the best 5%
  of trades or at the script's own 0.2% cost. Paper-trade gold before trusting it.
- Script bugs found: XAUUSD Confluence scores out of 7 but has 6 checks (Grade A never fires); AMD MSS's bullish
  "BOS" crosses the swing LOW (should be the swing high), bearish the swing high; Momentum Zone's yesterday
  high/low skips each day's first candle.
- ETH 1h RSI 40/60 cross with 4h EMA 50/200 filter, stop 1.5 ATR, 2R (last year): 206 trades, PF 1.02, +0.1% total
  at 0.1% fee per side; PF 1.14, +23% at 0.05% per side; max drawdown -28 to -34%; one losing quarter -22%.
