# Commodity study (6 Nov 2026): best intraday and swing setup

Data: Yahoo front-month futures for gold, silver, crude, natural gas and copper (COMEX / NYMEX; MCX follows them
× USDINR). Daily 2005-2026 for swing, hourly Jun 2024 - Nov 2026 for intraday (IST, MCX day 09:30-23:30).
Honest test: entry at the next candle's open, stop checked first, costs 0.03-0.04% intraday and 0.06% swing a round
trip, both halves of the period, quarters / years. Scripts: research/commodity/ (get_data.py first).

## Verdict: no commodity setup is strong enough for real money yet

### Swing (daily)
| Setup | Result | Verdict |
|---|---|---|
| Gold / silver trend (20-55 day breakout, long above 200-day MA) | avg +0.6-1.0% a trade, both halves positive, every parameter | earns the same per day as just holding gold while above its 200-day MA: no timing edge |
| Holding only above the 200-day MA vs buy & hold | gold 7.9% vs 10.8% a year, worst fall -40% vs -44% | filter costs return, barely cuts drawdown |
| **Copper: RSI(2) < 10 above the 200-day MA, exit close above 5-day MA** | 129 trades, 70% wins, +0.51% a trade (drift ~0.1%), both halves + | **best swing rule**, but 2010-15 and 2022-24 lost: paper test |
| Crude / natural gas trend | negative in 2016-26, natgas -13% a trade last 2 years | avoid |
| NR7 breakout, EMA20 pullback, 12-month momentum | ~0 after costs | no |

### Intraday (hourly)
| Setup | Result | Verdict |
|---|---|---|
| Asia range, morning 2h ORB, London range breakouts (and their fades) | -0.1 to +0.03R, all 5 markets | no edge |
| Prior-day high/low break, failed break | -0.2 to +0.08R | no |
| Gold Order Flow (the app's 15-min strategy) on hourly gold | 145 trades, -0.29% a trade; negative on silver / copper | **not robust**: its +0.31% came from one market in a gold bull run |
| Gold: day moved > 0.5 ATR by 18:30 IST, follow it to 23:30 | 91 trades +0.10R, but only at 18:30 exactly (17:30 / 19:30 lose) | fragile, no |
| Natural gas: follow the day's move into the US session | 96% of parameter sets positive, but 2nd half ~0R | faded, no |
| Natural gas: fade a 09:30 gap > 0.3 daily ATR, exit 23:30 | 150 trades +0.12%, but most profit in one quarter (2026Q4) | lead only |

Takeaways: commodities trend over months (gold, silver) but intraday breakouts don't pay after costs; the intraday
moves follow US data / news, not the morning structure. The one rule worth paper-trading is copper's 2-day dip buy;
for gold, holding beats every timing rule tested.

## Crude oil and natural gas: intraday option trades (7 Nov 2026, research/commodity/options_intraday.py)
There is no MCX option price history yet, so this tests the futures moves that option trades depend on.

| Finding | Crude | Natural gas |
|---|---|---|
| Share of the day's movement in US hours (18:30-23:30 IST) | 64% (2024-25) / 45% (2025-26) | 65% / 39% |
| Weekly US report (crude Wed, gas Thu, 20:00 IST summer / 21:00 winter): 2-hour move vs other days | 1.25x | 1.45x (1.69x in 2025-26) |
| 2-hour move > 2.5% after the report | - | 19% of reports vs 7% of other days |
| Report-hour move continues to the close? | no (+0.02%) | no; moves >= 1% partly reverse: +0.39% fading to the close, 61 reports, both halves |

Reading for options: the gas report is the one big scheduled move, but it is known in advance, so its premium rises
before it and drops after (IV crush): buying straddles before it only pays if the move beats that. No follow-through
after the report, so buying options in the direction of the first move has no support; the partial reversal after big
gas moves is a lead (selling the move's side after the report), not an edge. The rest of the day is quieter in Asian
hours, which favours option sellers only if premiums keep the full day's decay there; that needs real option prices.

Next: the recorder now saves MCX crude oil and natural gas option chains every minute (09:00-23:30, nearest expiry,
15 strikes each side, LTP / bid / ask / OI / IV / greeks) to <data>/mcx_option_chain/. After 3-4 weeks (12-16 reports)
the report straddle, the post-report fade with options and the quiet-hours premium sale can be tested on real premiums.
