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

## Top-5 gainers/losers at 10:00, lowest-volume opposite candle break (Oct 2026)

`lvc.py`, `run_lvc.py`, `run_lvc2.py`. About 5-8 signals a day, 2015-2026. All 8 basic variants lose after costs
(-0.01% to -0.05% per share trade, -1.2% to -1.9% per option trade). Best subset: stocks already 2%+ from the open
by 10:00, fresh break, 0.5 ATR stop: +0.08% per share trade (8/12 years), but still -0.2% per option trade.
