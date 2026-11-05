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
