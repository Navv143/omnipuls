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

## Top-5 gainers/losers at 10:00, lowest-volume opposite candle break (Oct 2026)

`lvc.py`, `run_lvc.py`, `run_lvc2.py`. About 5-8 signals a day, 2015-2026. All 8 basic variants lose after costs
(-0.01% to -0.05% per share trade, -1.2% to -1.9% per option trade). Best subset: stocks already 2%+ from the open
by 10:00, fresh break, 0.5 ATR stop: +0.08% per share trade (8/12 years), but still -0.2% per option trade.
