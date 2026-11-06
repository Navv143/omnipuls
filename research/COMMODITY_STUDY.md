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
