# The two PDF strategies, tested on every market and timeframe (6 Nov 2026)

Scripts: `get_data.py` (data), `london_breakout.py`, `redbar.py`. Entry at the next candle's open after the signal close,
stop checked first in every candle, costs a round trip (index 0.03%, stocks 0.12%, commodities 0.03%, FX 0.01%,
crypto 0.08%), results in R after costs and in % of the underlying, both halves of each period.

Data: Yahoo 2m (NIFTY / BANKNIFTY, 31 days), 5m / 15m (60 days), 1h (2-3 years) for Nifty, BankNifty, 60 F&O stocks
(1h) / 180 F&O stocks (5m, 15m), gold, silver, crude, natural gas, copper (COMEX / NYMEX, which MCX follows), EURUSD,
GBPUSD, USDJPY, USDINR; plus 3.5 years (2023-2026) of 5-minute PAXG (gold) and BTC.

## 1. Gold "London Clean Breakout" (claimed 74% wins, profit factor 6.24, 2019-2026)

As written: Asian box 01:00-07:00 server time (Europe/Athens), first 15m close outside it in 07:30-10:30, stop at the
box middle, target 1.5R, out at 15:00. Variants: mid-volume filter, 1R / 3R targets, stop at the far side of the box.

| Market | TF | Trades | Target hit | Stopped | Timed out | Net R a trade | Total R | PF |
|---|---|---|---|---|---|---|---|---|
| Gold (PAXG, 3.5 years) | 5m | 554 | 21% | 38% | 42% | -0.09 | -49.5 | 0.82 |
| Gold (PAXG, 3.5 years) | 15m | 497 | 20% | 36% | 44% | -0.08 | -38.4 | 0.84 |
| Gold (PAXG, 3.5 years) | 1h | 435 | 14% | 29% | 57% | -0.11 | -46.3 | 0.75 |
| Gold futures (2 years) | 1h | 320 | 16% | 25% | 59% | +0.02 | +4.8 | 1.04 |
| Silver (2 years) | 1h | 336 | 18% | 26% | 56% | +0.04 | +14.2 | 1.12 |
| Crude (2 years) | 1h | 367 | 27% | 47% | 26% | -0.08 | -28.7 | 0.86 |
| Natural gas (2 years) | 1h | 363 | 20% | 50% | 30% | -0.21 | -74.3 | 0.64 |
| BTC (3.5 years) | 15m | 480 | 18% | 31% | 51% | -0.10 | -49.3 | 0.77 |

On average across every market and timeframe the target was hit 23% of the time, never close to 74%. Gold over 3.5 years
lost in 2023 and 2024 and made money only in 2025. The only rows with both halves positive are 60-day FX samples
(EURUSD 15m +0.17R on 45 trades) - too small to trust. The PDF's numbers cannot be reproduced; the report reads as
generated, not measured. Verdict: no edge; do not trade it.

## 2. Dr. Devendra's 7 setups (Red Bar PDF)

The exact rules used are at the top of `redbar.py` (S1 opening mean retest, S2 red bar POB, S3 30-EMA pullback, S3f
30-EMA fade, S4 11:30-12:00 channel break, S5 12:00-12:45 range with 50% stop and flip; S6 CPR and S7 3:15 box as
filters). Target 3R (the PDF's 1:3) and 1.5R.

- 491 combinations (setup x market x timeframe x filter x target). Only ONE has t >= 2 with both halves positive and 30+
  trades: Nifty 1h red bar POB (139 trades, 53% win, +0.26R, +0.07% a trade). About 1 in 100 is what luck alone gives;
  the same rule loses on F&O stocks and is flat on BankNifty, so it is not confirmed.
- Average % a trade after costs is negative for every setup with every filter (-0.01% to -0.08%).
- F&O stocks (180 stocks, 5m / 15m; 60 stocks 1h, 3 years): every setup loses, on every timeframe (thousands of trades).
- MCX commodities (IST session): every setup loses except the 1h 30-EMA pullback (+0.18R on 72 trades, h2 near 0).
- CPR and the 3:15 box as filters: no consistent help (the average stays negative).

Verdict: as mechanical rules none of the 7 setups has an edge after costs on Indian indices, stocks or commodities. Our
Super Bot (with the market, 1 per sector, settled window) stays far better (+0.20% a trade, t 2.2, no losing month).
