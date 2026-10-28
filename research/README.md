# Omnipuls research

Strategy research behind the **Trade Setups** page. Everything here can be re-run.

## Reproduce

```
.venv\Scripts\python -m pip install lightgbm pyarrow
.venv\Scripts\python research\fetch.py           # downloads public data (~200 MB) into research\data
.venv\Scripts\python research\nse_data.py        # builds the F&O feature panel
.venv\Scripts\python research\picker.py          # walk-forward ML, ~10 minutes
.venv\Scripts\python research\evaluate_picker.py # picks vs rules vs random, trade simulations
.venv\Scripts\python research\indices.py         # NSE index edges
.venv\Scripts\python research\crypto_fx.py       # BTC, forex, INR, crude, natural gas
.venv\Scripts\python research\verify_dhan.py     # intraday checks on Dhan 5-minute data, plus gold (needs Dhan connected)
.venv\Scripts\python research\orb_v3.py --days 1800 --sweep  # independent test of the "Version 3" opening-range breakout (needs Dhan)
```

## Data

| Market | Source | Coverage |
|---|---|---|
| NSE F&O stocks, indices, India VIX | eod2_data (NSE bhavcopy), github.com/BennyThadikaran/eod2_data | Daily OHLCV, delivery, trades, 2012 to Oct 2026 |
| BTC/USD | Bitstamp 1-minute, github.com/ff137/bitstamp-btcusd-minute-data | 2015 to Oct 2026 |
| Forex, INR | US Federal Reserve daily rates, github.com/datasets/exchange-rates | Daily closes, 1971 to Oct 2026 |
| WTI, Brent, natural gas | US EIA spot, github.com/datasets/oil-prices and natural-gas | Daily closes |
| Gold | not reachable from the research machine: tested by `verify_dhan.py` on MCX gold | |

## Method

- Every rule decides with information available at the decision time (for NSE: the previous sessions and today's opening price).
- ML: LightGBM, walk-forward by year (train on all earlier years with a 10-day gap, predict the next year), 2015 to 2026 out of sample.
- Costs: 0.12% round trip on F&O stocks, 0.05% on index futures, 0.10% on BTC, 0.02% on FX majors.
- Daily bars can't show whether a stop or a target was hit first. Rules with a stop and an exit at the close don't depend on this; rules with targets were tested both ways and need intraday verification.
- Robustness: two separate periods, every year shown, nearby parameter values, higher costs, long and short sides separately.

## Findings

Validated (consistent across years, periods, parameters and costs):
1. **Gap fade on F&O stocks**: the two biggest opening gaps of 3%+ each day, faded at the open, 1% stop, exit at the close: avg +0.61% per trade after costs, profit factor 1.90, every year 2013-2025 profitable. Long side +0.64%, short side +0.58%. **Weak in 2026: +0.08% per trade so far (6 of 10 months flat or negative).**
2. **Panic gap-down reversal**: on days Nifty opens 0.5%+ lower, buy the two biggest 3%+ gap-downs, 1.5% stop: avg +1.27% per trade, profit factor 2.57, about 27 trades a year. Still +0.62% per trade in 2026: the safest one to start with.
3. **Sector overreaction**: gap-down 2.5%+ and 2.5% worse than the sector index: avg +0.54% per trade, 13 of 14 years profitable.
4. **BTC trend filter**: long only above the 100-day average: 2021-26 31%/yr, -38% worst drawdown (buy and hold 19%/yr, -77%).

Useful but not a strategy on its own:
- **ML big-mover model** (AUC 0.74 in every test year): its top pick moved 3%+ in its predicted direction on 46% of days (random 12.5%) and 3%+ either way on 75%. It did not beat "fade the biggest gap" for direction. Good for option buyers choosing what to watch.

Needs verification on real futures prices before trading:
- **Index overnight effect**: nearly all Nifty and Bank Nifty gains came between the close and the next open (2012-2021), intraday was negative. Weaker since 2022; index open prices can be stale.

Rejected (no consistent edge after costs): RSI(2) and IBS dip buying on Indian indices, day-of-week effects, gap trading on indices, VIX-spike buying, BTC session timing, forex and commodity trend following since 2013, NR7 "narrow range leads to expansion".

## Known limits

- The stock list is today's F&O list, so stocks that were removed are missing (survivorship). The short side, which this would hurt, works as well as the long side.
- Entry at the exact opening price assumes an order in the pre-open session (9:00-9:08) for cash shares, which fills at the opening auction price. NSE's official close is the 15:00-15:30 average price.
- Results are historical. Re-check with `verify_dhan.py` and paper-trade before using real money.
