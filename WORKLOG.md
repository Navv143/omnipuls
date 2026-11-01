# Omnipuls work log

What was built, fixed and tested, day by day, with the commit for each change. Research details are in
`research/intraday/README.md` and `research/README.md`; this log is the short version.

## 29-30 Oct 2026: radar, TradeFinder process, index build-up, smart money, new layout

**Built and shipped**
- Dark theme for the whole app; logo switched to the Aligned Momentum mark.
- Losing scanners removed (low-volume candle, previous-day break) with their research rows.
- Momentum radar (Setups & Scanners → Momentum radar): every stock 1%+ from yesterday's close vs the same time window
  on its last 20 sessions (volume, range, move vs ATR, futures OI change near + next month, big-money bars).
  Shortlist = TradeFinder pattern (broke yesterday's high/low, sector the same way, volume 1.5x+); daily log of the
  10:30 picks and a track record. `9382eac`, `e48f953`
- Option writing check on the shortlist: put/call OI change on 3 strikes each side, nearest expiry. `a8f4004`
- Index Build-up page (Option Apex style): Nifty / Bank Nifty / Fin Nifty 3-minute candles with green/red bars of
  option + futures OI build-up, and bull/bear dominance at 9:45, 10:15, 10:30 and the whole day. `2e6ebc2`
- Sector smart money: sectors ranked by the rupee value of fresh futures positions; shown in the radar. `2e6ebc2`
- Smart Money Sectors page: best picks (top R-factor stocks moving with a favoured sector), sector table, every
  sector's stocks with live price and R-factor (volume, OI, range and move vs the last 20 sessions). `804c1f6`
- Trader-first layout `d033e45`: Dashboard = Nifty build-up, smart money and breadth cards, sector heatmap (sector →
  stocks, coloured by smart money or price), today's 5 picks, F&O movers. Menu regrouped (Trade / Markets / Dhan /
  Tools), Trade Setups merged into Setups & Scanners, Crypto/Forex/Currency/Commodities merged into Global Markets.
- App made public on Streamlit Cloud so it opens on any phone or computer; F&O data on the cloud fixed (clear
  message when Dhan is disconnected, token auto-renew in its last 3 hours).

**Researched (all after costs)**
- Momentum continuation, big-money bars, NR5/NR7/box/OBV breakouts, 3-minute volume spikes, sector money flow:
  no edge. Radar #1 at 10:30: +0.17% per trade, the only part that held.
- TradeFinder's 402 verified days: their pick is already a top-6% mover at 10:00 and runs a further 3.1%; our
  shortlist holds it in its top 5 on ~27% of days. Their edge is the final pick (option/OI data + judgement).

## 30-31 Oct 2026: automatic token, users, build-up backtest, broad re-search

**Built and shipped**
- Automatic Dhan token: with `client_id`, `pin` and `totp_secret` in Streamlit Secrets the app makes a fresh 24-hour
  token itself (Dhan generateAccessToken + TOTP) whenever one is missing, nearly expired or rejected. PIN and TOTP
  secret are never written to files. `383d5db`
- Users list shows "Secrets" once an in-app account is saved in Secrets (was always "App (until restart)"). `dbbce2f`
- "Confirmed since" on the radar records only during market hours (was stamping night-time views). `d278613`
- Breakout (V3) ranking flags likely block deals (opening volume 20x+ usual, e.g. SAGILITY 30 Oct). `d6e08cc`
- 28 F&O stocks that had no sector mapped (CUB, SAGILITY, NAVINFLUOR, ATHERENERG, COCHINSHIP, ...). `2c18a3e`

**Researched (all after costs)** `d278613`, `793e4bc`
| Study | Result |
|---|---|
| Index build-up bars, 3-min (Nifty 27 days, Bank Nifty 23) | Strong bars point the right way (Bank Nifty 2x+ bars +14.6 pts in 15 min, 58%); fading them loses; no mechanical scalp holds on both indices. Use as a direction filter. Re-run weekly to grow the sample. |
| 23 index intraday rules, Nifty + Bank Nifty, 5 years | Index move ~0 for every rule; every rule loses for an option buyer after time decay. |
| Positional momentum, reversal, 52-week high, low vol, pullback, sector momentum (14 years daily) | 12-1 momentum looked +13.5%/yr but is mostly survivorship; on the 100 most traded stocks +4-8%/yr with -41% drawdowns. |
| Short stocks 1.5-3% down at 9:30 while Nifty is up | +0.18% per trade, positive every year 2021-26, but only +0.07% a day as a book; only the 9:30 entry works. Lead, not traded. |
| YouTube "smallest stop loss" (lowest-volume opposite candle) | 2,300 trades: -0.15% per trade, every year negative. Rejected. |
| Quiet open (gap under 1%) then a 1% move | 161,383 events: next move a coin flip; 725 filter combinations, none hold. |
| 30 Oct V3 ranking and radar shortlist | Both worked that day (shortlist +0.8% to +4.9% after 10:30); one day is not an edge. |

**Still the strongest:** the opening-price setups (gap fade, panic gap-down buy, sector overreaction) in the
Opening setups tab.

## Open items
- Put `pin` and `totp_secret` in the cloud app's Secrets (only there, not on this PC: Dhan may allow one token).
- Re-run `research/apex_backtest.py` weekly with a valid token on this PC to grow the build-up history.
- Candidates for next: Morning plan card (opening setups + 9:30 relative-weakness short), daily option-chain logging
  to test hedged option selling, cash-futures arbitrage scanner.
