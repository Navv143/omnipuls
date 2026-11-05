# Omnipuls work log

What was built, fixed and tested, day by day, with the commit for each change. Research details are in
`research/intraday/README.md` and `research/README.md`; this log is the short version.

## 28-29 Oct 2026: TradingView charts and going online (chat "Charts migration to TradingView")

- Price chart moved from Plotly to TradingView Lightweight Charts (`tvchart/index.html`, `tv_chart()` in app.py):
  candles with volume, live OHLC legend, EMA 20/50/200, Bollinger, VWAP, Supertrend, pivots, RSI and MACD panes,
  IST times, zoom kept across refreshes. Bar charts (sectors, OI, option chain) stay Plotly. The old `navv/` copy
  got the same chart. `628064c`
- Git and GitHub CLI installed; code uploaded to the private repo Navv143/omnipuls with passwords, tokens, watchlists
  and caches left out; dev container added. `fc0474c`
- Deployed on Streamlit Community Cloud at omnipuls-navv.streamlit.app (branch main, app.py, Python 3.12). Admin
  login `navsolanki` copied to Secrets as salt + hash (no plain password). An older broken "omnipuls ·
  streamlit_app.py" app in the Streamlit workspace points to a deleted repo and can be removed.

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

## 31 Oct - 1 Nov 2026: unusual activity, money flow, index flow, trend-day alert, big research round (chat "Navv")

**Built and shipped**
- F&O Stocks -> **Unusual activity**: smart score for every F&O stock, candle by candle, vs the same time of day over
  the last 20 sessions (time-based volume / turnover / range, candle volume and range, gap vs usual, futures OI change,
  order-book buy/sell quantity, RSI, VWAP, move from open in ATRs). Tabs: ranking, unusual candles feed, stock candle
  by candle, how the score works. (`activity.py`)
- F&O Stocks -> **Money flow**: inflow / outflow / net flow per stock and sector (turnover split by where each candle
  closes), whole day or last 60/30/15 min, sector rotation (from -> to) Sankey, sector x time heatmap, futures OI value
  change; **Scope** selector for Nifty 50, Bank Nifty, Fin Nifty, Sensex, Midcap Select with weights, index points
  contributed, weighted flow and flow vs the index through the day. (`indices.py`, weights 29 Oct 2026 + NSE live)
- Setups & scanners -> **Index trend-day + OI (options)** tab: move >= threshold x ATR from open, index future on the
  VWAP side, futures OI above yesterday, 10:30-13:00; ATM option with -30% stop and trailing exit. (`trend_alert.py`)
- Loader (scan_service v3): order-book snapshots every minute (saved to activity_history/), index bars incl. India VIX,
  nearest index futures with OI (NSE + BSE Sensex). Fixed: today's refresh no longer wipes a stock's saved history
  (stocks could drop out of scanners mid-session).
- Live feed picks up an automatically renewed token without a restart.

**Researched** (details in research/FINAL_SETUPS.md)
- Index option discovery (260k bars, 60+ readings, walk-forward ML): only trend days with futures OI rising pay an
  option buyer (BN +4.1%, Nifty +1.9% a trade; beats random-time buys by ~+8-9 pts under both premium models).
- Option premium model warning: intraday selling flips from 12/12 years up to 12/12 down depending on the theta model.
  Real-price test: `research/index_options/dhan_index_options.py --years 1` (then 5) on this PC.
- Rejected: EMA9/VWAP 3-min, 9/15 EMA, Trade Room 9/15 scalping, Fibonacci retracement, Thu/Fri weekly pattern,
  small-cap Bollinger breakout, RSI(3) / Triple RSI dip-buying (cash and small caps).
- Unusual activity / money flow studies: confirmation tools (big movers on 2-3x usual activity continue; sector flow
  persists slightly), not stand-alone signals.

## 5 Nov 2026: landing page, Open = High/Low column, Setup Finder (research bot)

- Landing page (PR #11): logo (SVG), headline and short summary, feature chips, rotating slides of the real
  features, feature tiles; sign-in is a compact card whose button opens the form (first on phones).
- Open = High / Open = Low (PR #12): `ind.ohl_flag`, in radar, R-factor, breakout and unusual-activity rows and
  automatically in any table with the day's open / high / low; shown only when a stock qualifies.
- Setup Finder `bot.py`: a year of 5-min Nifty 100 + Nifty bars from Dhan (cached, topped up nightly); events at
  10:00 / 10:30 / 11:00 / 12:00 with money-flow buying share, net flow vs usual turnover, volume vs usual by that
  time, range so far vs usual day, move in ATR, gap, open = high / low, sector and market flow; ~6,900 rules after
  0.12% costs; tuned on the first 60% of days, judged only on the last 40% + neighbour robustness; Nifty MACD crosses
  with / without Nifty 100 flow. Results: <data>/bot/latest.json and Supabase bot_results. Tested: planted edge found
  and confirmed on unseen days; no-edge data -> 0 passed (losses = costs).
- recorder.py runs the bot in its own process every evening after 16:30 (or when the app asks), never in market
  hours. App: "Setup Finder" page (Today menu) with results and "Run tonight"; a passed rule's live matches join the
  Market View as Tested signals and count in the trade idea.

## 5 Nov 2026: build-up carries yesterday, Nifty flow × MACD, money rotation, short texts

- Index build-up: computes yesterday's session from the same 1-minute downloads (no extra calls) and reads the
  positions open at yesterday's close (option OI at the strikes from the chain's previous OI, futures OI). Page
  shows "Carried from yesterday" (yesterday's net build-up and bullish share, futures and option OI then vs now,
  PCR) and a running total "Since yesterday" (default) or "Today only".
- Market View: "Nifty 50: money flow candle by candle" (Nifty candles with MACD-cross markers, coloured when the
  30 minutes of flow before the cross agree; money into / out of the Nifty 50 stocks per candle, darker = bigger,
  with the running total; MACD panel) with a plain-words reading; "Where the money moves" (sectors money leaves,
  red, to sectors it goes to, green). MACD alone was rejected in testing; the flow-backed version is labelled
  untested until tested.
- Method / research texts (note, note_md) collected into one collapsed "How it works" box at the bottom of each
  page; one-line how-to under the status bar of each main page.

## 5 Nov 2026: design system, fonts, menu (look and feel, phase 1)

- Audit: 47 hard-coded colours, 34 font sizes, 11 corner radii, 5 separate style blocks; card figures asked for
  JetBrains Mono, which was never loaded.
- Design tokens (`:root` in the global CSS: colours, type scale, radii, number font); Trading Desk and Market View
  styles now use only tokens; evidence badges use the app's own green / blue.
- Fonts (.streamlit/config.toml): Inter for text and numbers (tabular digits app-wide), Sora for headings (brand),
  JetBrains Mono loaded for card figures; heading scale and weights, 0.6rem radius, colour-blind-safe chart colours.
- Menu regrouped by task: Today (Market View, Trading Desk, Signals & Scanners, Option Chain), Markets, Tools,
  Account (admin pages). URLs unchanged.
- Market View cards: one point per line, the key point in bold; shorter wording.
- Mobbin (design research) needs a paid Mobbin plan; not used.

## 5 Nov 2026: Market View (one page: every signal and reading, with what it means)

- New first page and start page, "Market View": (1) Trade idea right now: tested signals if any fired, otherwise
  the mood, the bias and an honest "wait" with what to watch; (2) All signals, one list: tested setups, Version 3
  breakouts, CE/PE focus, smart-money picks, each labelled Tested / Small edge / Context (a card list on phones);
  (3) cards for Nifty, Bank Nifty, Fin Nifty, Sensex (vs yesterday's high/low, opening range, futures VWAP, move in
  ATR), India VIX, Nifty build-up, F&O breadth, fresh futures money, sector money flow, unusual activity and the
  Nifty / Bank Nifty option chains (support / resistance by OI, PCR, max pain), each with "-> what it means".
- Interpretations in `market_view.py`, grounded in research/FINAL_SETUPS.md (Bank Nifty breaks tend to fail, Nifty
  breaks ~half slip back, trend day + OI is the tested option buy, sector flow persists a little, unusual movers
  continue). Untested readings say so.
- The page also writes the desk log (Supabase), so recording continues when people use it instead of the desk.
- Running the server (Hostinger, srv2128506.hstgr.cloud) since 4 Nov evening; setup.sh DNS check fixed (PR #7).

## 4 Nov 2026: Hostinger VPS + own domain (HTTPS, live ticks)

- Sizing measured: app 155 MB idle, recorder 114 MB, full market + all scanners about +300 MB, ~15 s CPU for the
  first calculation of the day; peak ~1.5-2 GB with the OS. Choice: Hostinger KVM 2 (2 vCPU, 8 GB, 100 GB NVMe).
- `deploy/docker-compose.cloud.yml` + `deploy/Caddyfile`: Caddy in front (free HTTPS for DOMAIN), the app not
  reachable directly; live ticks go through wss://DOMAIN/ticks. `OMNIPULS_TICKS=1` streams ticks on a public server
  (PUBLIC stays on, so no "create admin" screen).
- Tick relay now needs a per-feed secret key that only pages the app drew carry: strangers are cut off (tested).
- `deploy/setup.sh`: one command on a fresh Ubuntu VPS (Docker, firewall 22/80/443, swap, domain check, Secrets,
  start). `HOSTINGER.md`: buying and setup guide. Tested here: page over HTTPS through Caddy, port 8501 closed,
  ticks through wss with key, stranger rejected.

## 4 Nov 2026: market data recorder, Docker for the office server, Today's plan card

**Built**
- "Today's plan" card at the top of the Trading Desk: only the tested setups, each signal / waiting / none with entry,
  stop and target, and a plain "no trade" when none fired; the rest is labelled "Market context" (untested).
- `recorder.py`: 1-minute candles after each close (indices, all F&O stocks, stock + index futures near/next with OI,
  Nifty / Bank Nifty options 2 expiries x 15 strikes each side with OI), option chains of 5 indices every minute
  (IV, greeks, bid/ask, OI) and full quotes of every instrument every minute (buy/sell quantity), as Parquet in
  market_data/. Backfills missed candle days; skips holidays; shares the Dhan token with the app via
  dhan_config.json (the app now adopts a newer saved token instead of fighting it). Tested against a simulated
  Dhan API (candles with OI, options, chains with one index failing, quotes, daily join, holiday, token renewal).
- `paths.py` + OMNIPULS_STATE: all files the app writes can live in one folder outside the code (default unchanged).
- Docker: `Dockerfile`, `deploy/docker-compose.yml` (app on 8501 + tick relay 8765, recorder, updater pulling `main`
  every 5 minutes), `DEPLOY.md`. Built and run here: app healthy and renders, accounts saved to the state volume,
  recorder waits for Dhan; updater tested on a local repo.

**Open**
- One-time setup on the office server (10.195.82.89) by someone who can log in: DEPLOY.md. Not reachable from the
  cloud session (private address).
- After it runs: remove pin / totp_secret from the Streamlit Cloud Secrets (one Dhan token at a time).

## 2 Nov 2026: Trading Desk signals saved to Supabase

- `desk_log.save` also writes every row to the Supabase `desk_log` table (the six desk checkpoints, CE/PE focus,
  index plans, opening setups, Bank Nifty 5-STAR and fade, Gold Order Flow paper trades). One row per
  (date, checkpoint, kind, name, side): a checkpoint logged again after a restart replaces the first copy.
  `desk_log.load` (Desk review page) reads it back, so the history survives restarts. Table created in the
  `omnipuls` project; public key sees 0 rows. Tested end to end against a stand-in API.
- Rows are written when the Trading Desk is open at or after each checkpoint (as before): if nobody opens the app
  that day, nothing is logged.

## 2 Nov 2026: Supabase storage and Crypto.com prices

**Built**
- `cloudstore.py` + `supabase/schema.sql`: accounts (users.json), preferences (user_state.json) and watchlists are
  also saved to a Supabase table and restored when a cloud restart wipes the files. Off until `[supabase] url` and
  `key` (secret key) are in Secrets; RLS on with no policies, so only the secret key can read the table. Tested
  against a stand-in API: account + preference restored after wiping the files, sign-in works.
- `cryptocom.py`: Crypto.com Exchange public prices (no key, no daily limit) for crypto when Yahoo fails, before
  Twelve Data; daily tiles and Chart page candles. USD pair, else USDT, from the exchange's instrument list.
- Twelve Data and Crypto.com now map Yahoo's numbered coin names (TON11419-USD -> TON); they never matched before.

**Open**
- Supabase project `omnipuls` created (Mumbai, free plan, https://vtiumooustkzsqhqpkbr.supabase.co) with the
  app_files table; checked that the public key sees 0 rows and cannot write. To do: put `[supabase] url` and the
  secret key (Project Settings -> API Keys, sb_secret_...) in Streamlit Secrets, and merge this branch.

## 2 Nov 2026: scanner calculations off the page path, 3x faster

**Why pages were still slow after the refresh fixes:** after each loader pass (every 1-2 min in market hours) the
first page view recalculated the radar, R-factor and unusual-activity scores for ~200 stocks while it waited:
~23 s per new candle and ~43 s on the first load of the day (measured on 200 stocks x 40 sessions; slower on the
cloud's shared CPU). Trading Desk, Scanners and Smart Money all hit this.

**Fixed** (all outputs checked identical to the old code on the same data)
- Futures OI "usual change" (`scanners._oi_window`): one pass instead of a loop re-scanning every bar for every day;
  R-factor 14.3 s -> 1.8 s, radar 3.2 s -> 0.4 s.
- Same-time-of-day averages (`activity.baseline`, `fut_baseline`): one groupby instead of pivot_table per table;
  "HH:MM" labels by lookup instead of strftime (also in `scanners`). First load: prepare 4.7 s -> 2.0 s, unusual
  activity 18.5 s -> 10.5 s.
- Pages no longer wait for a recalculation: the last result for the same loader and session shows at once and the
  new one is built in the background, one at a time (`_fresh_or_last` in app.py). Only the first result of the day
  is built while the page waits. Numbers lag by at most one loader pass.

## 2 Nov 2026: slow app and repeated refreshing fixed

**Fixed**
- Yahoo "skip 15 min after a failure" never worked: its state was a plain dict in app.py, reset on every rerun, so
  every refresh waited on Yahoo again when it was limiting the server. Now kept across reruns (Global page refresh
  with Yahoo down: 6.6 s -> 0.7 s).
- Dhan unreachable: the token check was retried on every page load (up to ~1 min with retries). Now it waits 2 min
  after a network failure; new credentials are checked at once (refresh with Dhan down: 4.1 s -> 0.6 s).
- Auto-refresh: whole-page reruns could be as often as every 5 s (default 10-60 s). Now 30 s minimum, default 2 min
  (5 min on the cloud); off on Account, Dhan Connect, Research and Desk review (it interrupted typing); paused outside
  NSE hours on Indian-only pages. Scanners / Smart Money / activity sections: every minute in market hours, 5 min
  otherwise. Live prices still stream tick by tick.
- Module reload after a code update cleared every cache and the live feed whenever a file's time changed (OneDrive
  can touch files without changing them); now only when the content changes.
- "Refresh now" retries Yahoo and Dhan straight away.
- Twelve Data fallback (twelve.py): a background worker now loads the symbols pages ask for at 7 calls a minute
  (before: at most 7 per page load, so 20 coins took several refreshes); refresh spacing stretches so the 800 daily
  credits last until the reset at 05:30 IST (before: ~51 symbols every 10 min ran out in under 3 hours); "out of
  credits for the day" pauses calls until the reset; symbols not on the plan are skipped for 6 hours. The Chart page
  now falls back to Twelve Data for crypto, forex, gold and WTI when Yahoo fails. Sidebar shows loaded symbols and
  credits used while Yahoo is down.

## 1 Nov 2026: Navv work shipped, Trading Desk, speed, Twelve Data, top menu

**Built and shipped**
- The "Navv" chat's work (unusual activity, money flow, index flow, trend-day alert, research) arrived here
  uncommitted via OneDrive; committed and pushed after replacing scipy in trend_alert.py (not installed, would have
  stopped the app). `6a19fc6`
- Fixes after that deploy: the cloud kept old copies of changed modules (AttributeError `set_indices`), now reloaded
  once per file version and rerun if Streamlit swaps a module mid-update (`83b81af`, `84b8171`); Infinity in the
  Unusual activity table broke the widget, now blank (`8fbf857`); empty futures buildup crashed sector money (`3e78a42`).
- Trading Desk (first page): market verdict -100..+100 from build-up, breadth, money flow, futures money, Nifty move
  and VIX; index strip with sparklines; Nifty / Bank Nifty option plan (CE / PE / Wait, trend-day alert when it
  fires); CE and PE focus lists (3+ readings agreeing, with reasons); desk note; signals from every scanner, sector
  heatmap + money flow, picks, most unusual. `d2d8d9a`, `3e78a42` (`desk.py`)
- Claude's read: free copy-ready prompt for claude.ai; one-click "Ask Claude" if `[anthropic] api_key` is in Secrets
  (claude-opus-5-5, at most one call per 5 minutes). `64b2796`
- Speed: scanner results kept across page loads (were rebuilt every load); Yahoo skipped 15 min after a failure;
  Twelve Data fallback for crypto, forex, gold, WTI when Yahoo fails (`[twelvedata] api_key`, free plan: 7 calls a
  minute, 10-minute reuse). `90a83aa` (`twelve.py`)
- Menu as a bar on top, sidebar closed by default; charts open in a new tab signed in by a 12-hour link code (reset on
  restart); Screener starts on all F&O stocks. `0cc08e9`

## Open items
- Check the top menu and new-tab charts signed in, also on a phone (pop-ups must be allowed for the site).
- Add `[twelvedata] api_key` in Secrets (and optionally `[anthropic] api_key` for one-click Claude).
- Optional: automatic Dhan token on this PC for local testing (test first whether Dhan allows two tokens at once).
- Put `pin` and `totp_secret` in the cloud app's Secrets (only there, not on this PC: Dhan may allow one token).
- Re-run `research/apex_backtest.py` weekly with a valid token on this PC to grow the build-up history.
- Run research/index_options/dhan_index_options.py (real expired-option prices) and send the summary back.
- Candidates for next: Morning plan card (opening setups + 9:30 relative-weakness short), daily option-chain logging
  to test hedged option selling, cash-futures arbitrage scanner.

## 5 Nov 2026: five live bots and the Setup Finder on all F&O stocks

- Setup Finder (bot.py v2) now tests **all F&O stocks and the five indices**, not the Nifty 100. No fixed 10:30
  time: a setup fires at the first candle its conditions are true (9:30-14:30). Tuned on the first 60% of days,
  judged on the last 40%; checked on planted-edge data (12 rules passed, unseen ≈ tuning) and true-null data (0 passed).
- New `bots.py`, started and kept alive by the recorder: every 5 minutes in market hours it runs
  1. Index bot (move in ATR, constituents' money flow, MACD, futures OI build-up, passed index rule signal),
  2. Sector bot (money by sector, rotation from/to), 3. Sector movers (top gainers/losers and whether money backs them),
  4. F&O unusual (volume, range, net money, open = high/low, tested-rule signals), 5. Master bot: an idea **passes**
  only when a tested rule fired and 3+ of 4 balance checks agree (market money, Nifty not against, sector money,
  VIX calm); 3+ checks without the rule = watch. Ideas are logged to Supabase `bot_ideas` and scored at 15:35.
  The nightly research (after 16:30) now runs from bots.py.
- App: the Setup Finder page became **Bots** (master ideas, a tab per bot, research for stocks and each index);
  Market View lists the master bot's ideas and counts passed ones as tested signals.
- Tested with mocked market data: planted sector rally → tested-rule signals passed 4/4, watch ideas, each idea
  logged once, scored at the close; app pages render without errors.

## 5 Nov 2026: Market View redesign (visual, not text)

- New `mv_ui.py`: index pulse tiles (price, change chip, today's sparkline vs yesterday's close, range bar with
  yesterday's high/low, 2-3 word tags), a mood gauge with the readings' votes, the trade idea panel, signals as
  colour-coded chips (green long, red short; status pill), market-internals meters (build-up, breadth, money flow,
  fresh futures money, VIX scale, unusual activity), a sector money heatmap (size = turnover, colour = net money)
  and option-writer bars (spot between support and resistance, max pain marked).
- The long explanations moved into tooltips and a folded "What each reading means"; the full signal table is folded.
- Mobbin (design references) needs a paid plan, so the layout follows Sensibull / StockEdge / TradingView patterns.

## 5 Nov 2026: Radar bot with odds, Bots dashboard

- The bots no longer wait only for tested setups. A **Radar** reads every F&O stock every 5 minutes against its own
  usual: move from the open in ATR, range vs ATR, volume vs usual by this time, the latest 5-minute candle's volume
  and size vs the same slot on 20 days, the 15-minute jump in ATR, money-flow buying share, futures OI change vs its
  usual daily change (from the recorder's quotes), order-book buy share, open = high / low.
- **Odds engine** (`bot.odds_table` / `odds_lookup`): for each kind of moment (side, time of day, volume vs usual, move
  in ATR, money flow agreeing) what happened next on the last 150 days: share that kept going to 15:15 after costs,
  average result, share that ran another 1 ATR, number of cases. Rebuilt every night with the new day.
- Master bot adds **good odds** ideas (55%+ kept going, 40+ cases, 3+ points over the usual, 3+ balance checks).
- Every radar event is logged to Supabase `radar_events` and scored at 15:35; the **odds check** compares the odds
  with what happened (the self-improvement loop).
- Bots page is now a dashboard: KPIs, master ideas, radar event cards with odds bars, live feed, odds check, system
  health, and every F&O stock's full readings. Market View shows the top sudden changes.

## 5 Nov 2026: Sectors page redesign

- Top KPIs (advancing, declining, A/D ratio, average move, net money, most active stock) and the sector money heatmap.
- Every sector as a card: header with the sector's average change, R-factor, smart score and activity (volume vs usual
  by now); its stocks listed below (price, change, change %, R-factor, smart score, activity %); a footer line with the
  number of stocks, how many up / down, and the sector's money inflow, outflow and net with a buy/sell bar.
- Sort sectors by change, net money, R-factor, smart score or activity; search a sector or stock.
- Sector detail: pick a sector for a full live table (price, change, R-factor bar, smart score, activity, build-up, OI
  change, money in / out / net, gap, volume × average, RSI, trend, O=H/L, lot, chart link).

## 5 Nov 2026: AI Desk, six agents over every market

- `desk_agents.py` (pure logic) + `agents.py` (24/7 runner, started by the recorder next to bots.py; every 15 min):
  ATLAS (global regime: S&P / Nasdaq trend, VIX, dollar index, US 10y, India VIX → bias per class), VEGA (daily +
  hourly trend, 20-day breakout / breakdown with volume, pullback to the 20-day average, support / resistance from
  swing points, ATR and volume vs average, RSI), ORION (headlines scored, high-impact catalysts), LUNA (RSI extremes,
  5-day z-score, class breadth, crypto Fear & Greed; crowded = against), TITAN (1% risk sizing, stop 0.75-2 ATR beyond
  support / resistance, all stops ≤ 4%, R/R ≥ 1.5, volatility, correlation ≤ 0.75, max 6 trades / 2 per class),
  NOVA (TRADE / WAIT / REJECT).
- Universe: 10 indices (India, US, Europe, Asia), 14 stocks (India + US), 6 crypto, gold / silver / copper / platinum,
  crude / Brent / natural gas / wheat, 6 forex pairs. Yahoo data, Crypto.com fallback for crypto.
- Every TRADE call is paper-tracked (target / stop / 3-day time-out) in calls.json and Supabase `desk_calls`.
- New page **AI Desk** (Today menu): agent cards, NOVA counts, trade / wait / reject cards with entry, stop, target,
  each agent's vote and TITAN's risk review, a table per market class with 60-day sparklines, ORION's headlines and
  the paper record. On Streamlit Cloud (no server state) the page computes the desk itself every 15 minutes.

## 5 Nov 2026: Momentum study (what makes a stock trend intraday)

- `momentum_study.py`: per F&O stock-day, readings at 9:30 / 9:45 / 10:15 (gap, yesterday's range and close, ATR
  squeeze, room to the 20-day extreme, move / range so far, volume vs usual, opening-range expansion, money flow,
  relative strength, market / sector direction, O=H/L) → trend-day lift and the trade result to 15:15 after costs,
  1-3 condition rules judged on unseen days with t counted over days. Runs every night on the server after the Setup
  Finder (year of Dhan data); results on the Bots page. First run on 45 days of Yahoo data: research/MOMENTUM_STUDY.md.

## 5 Nov 2026: Momentum Funnel (simple step-by-step watchlist)

- `funnel.py` + page **Momentum Funnel** (Today menu). Step 1: average 5-minute true range from 9:15 to now vs the
  same window on the last 20 days (default ≥ 1.2×) and the last 15 minutes vs the same 15 minutes (≥ 1.0×); side =
  up / down from the open. Step 2: the sector's net money in that direction (option: also rising). Step 3: the stock's
  net money in that direction and beyond its value 15 minutes ago. Passing stocks = watchlist (long / short), with an
  "Add to Watchlist & Alerts" button; funnel counts, sector money heatmap and a step-by-step table of every stock.
- Checked on real Yahoo 5-minute data (5 Nov, 9:55): 235 stocks → 26 → 22 → 14 on the watchlist.

## 5 Nov 2026: Funnel step 2 (range), suggestions, stored snapshots

- New step 2: high-low from 9:15 to now vs the usual high-low of that window (default ≥ 1.2×); sector money and stock
  money are now steps 3 and 4.
- **Suggested: best to trade now** = watchlist stocks moving with the market, ranked by a 0-100 score (ATR, range,
  last 15 min, money share, sector share, market direction, room to the 20-day high/low, quiet yesterday), each with
  the reasons. Stocks against the market are never suggested (they lost at every time in the momentum study).
- The server stores the funnel every 5 minutes: all F&O stocks in <data>/funnel/<day>/<HHMM>.parquet and the step-1
  stocks in Supabase `funnel_log`, so the steps and the score can be tested on what was known at each moment.
- Real data check (5 Nov): 235 → 26 (ATR) → 22 (range) → 18 (sector) → 12 (stock money) → 7 suggested.

## 5 Nov 2026: Funnel step 5 (market) and picks across the app

- Step 5 from the momentum study: moving with the market (average F&O move from the open) and not the day after a
  wide day (yesterday's range ≥ 1.25 ATR). Watchlist = all 5 steps, ranked by score; steps 1-4 only = "on watch"
  (folded, with the reason).
- The server's funnel picks feed the master bot (source "Momentum funnel", same 4 balance checks) and show on
  Market View ("Momentum Funnel picks"). Snapshots now store step 5 too.
- Real data check (5 Nov): 235 → 26 → 22 → 18 → 12 → 5.

## 5 Nov 2026: Index funnel

- `index_funnel.py`: Nifty 50, Bank Nifty, Fin Nifty, Sensex, Midcap Select with the funnel's steps: ATR active, range
  expanding, index money (its stocks' weighted money flow with the move and growing), breadth ≥ 60% of the weight with
  the move (India VIX shown, not a step). Live cards on Momentum Funnel → Indices with today's first signal; backtest
  nightly on the server (Dhan year) → <data>/bot/index_funnel.json.
- First test (Yahoo, 52 days): index money is the step that adds the edge; Nifty +0.25% a signal (t 2.6), Bank Nifty ~0.

## 5 Nov 2026: Nifty / Bank Nifty money, OI and levels

- `index_levels.py`: classic pivots + CPR from yesterday; fixed-range volume profile from the index future's volume
  (POC, value area high / low for yesterday and the last 5 sessions); futures OI change today and last 15 minutes with
  the build-up; option-chain support (most puts) / resistance (most calls), today's biggest put / call writing, PCR,
  max pain; OI step (no OI reading against the move, at least one with it); one ladder of all levels with the nearest
  support / resistance and a stop / target (reward/risk shown, flagged under 1.5R).
- Momentum Funnel → Indices → Nifty 50 / Bank Nifty tabs: setup with step 5 (OI), index money chart (price + money per
  candle + running total), OI since the last check (CE / PE / futures, kept in server memory through the day), levels
  ladder, option OI by strike, futures OI through the day coloured by build-up. The recorder already stores the chain
  every minute and futures OI, so the OI step can be backtested once a few weeks are recorded.

## 5 Nov 2026: Bank Nifty focus, index snapshots for the OI re-test

- Server stores every index's funnel steps, index money, futures OI / build-up and option OI (from the recorder's chain)
  every 5 minutes in Supabase `index_log`, so the OI step can be re-tested from outside the server.
- Bank Nifty variants tested (research/MOMENTUM_STUDY.md): the failed break of yesterday's high / low, faded, is the
  best (+0.12% ≈ 67 pts, 61% wins, both halves); it shows live on the Bank Nifty tab. The nightly server backtest now
  includes the Bank Nifty variants and writes the result to Supabase bot_results too.

## 5 Nov 2026: Index signals on Market View, full-app check, new landing page

- Market View: "Index setups" section (funnel steps for Nifty, Bank Nifty, Fin Nifty, Sensex, Midcap Select + the
  Bank Nifty failed-break fade line); index funnel signals join the Signals list (Nifty / Midcap as "Small edge").
  The Bank Nifty failed-break fade was already a tested setup in the app (plan rows); the new test confirms it.
- Fix: style blocks joined with content in one markdown call did not render (index cards, funnel picks); every style
  block is now its own call across the app.
- Fix: index money skipped stocks whose candles have no volume column (was an error).
- Full check: all 25 pages run without errors (AppTest); Supabase shows the server storing desk_log, bot_ideas,
  radar_events, desk_calls, funnel_log and index_log today (real futures OI / option OI in index_log).
- New landing / sign-in page: aurora background with grid, top bar with live NSE status and IST time, gradient headline,
  stats strip, frosted sign-in card, feature tape, live product preview (sample data, labelled), feature cards, how it
  works, honesty strip, footer; phone layout stacks with sign-in right after the headline.

## 5 Nov 2026: Landing page without setup details

- The sign-in page no longer describes any setup or method (no steps, indicators, rules, test method or data source):
  generic feature names (Market View, Smart watchlist, Index intelligence, Bots, AI Desk, Sectors), a generic
  preview (stocks covered → shortlisted → watchlist; signals without their rules) and a generic "how it works".
  Setup details stay inside the app, behind sign-in.

## 5 Nov 2026: Trade plans and signal record; AI Desk Indian-first

- Trade plan for every funnel stock, index funnel signal and the Bank Nifty fade (`funnel.trade_plan`): entry at the
  signal, stop beyond the last 30 minutes' swing (0.3-0.6 daily ATR; the fade: beyond the day's extreme), target 1 = 1R
  (half off, stop to entry), target 2 = 2R, exit 15:15. Shown on the watchlist / index cards, Market View and the Bank
  Nifty tab.
- Server records each signal once (source + symbol a day), tracks it live and scores it at 15:35 (`funnel.simulate`):
  <data>/bots/trades/<day>.json and Supabase `trade_signals`; "Signal record" on Momentum Funnel (stocks / indices).
- First backtest of the funnel with the plan (research/funnel_backtest.py): about break-even, not proven.
- AI Desk: Indian indices and 16 Indian stocks first, then crypto, forex, commodities and the rupee (no US / foreign
  stocks or indices); ATLAS reads Nifty, Bank Nifty, India VIX and USD/INR; the dollar index is context only.

## 5 Nov 2026: Live-reload fix, plans for every bot idea

- Fix: the server kept old helper modules in memory after pulling new code (Streamlit re-runs app.py but not its
  imports), so the trade levels and the Indian AI Desk did not show. Changed pure helper modules are now reloaded on
  the next page load (and once when a running server picks up this fix); stateful ones (Dhan, scan service, feed,
  accounts, storage) are never reloaded.
- Bots: every master-bot idea and radar event has the plan (entry / "buy near" or "sell near", stop, target 1, target 2,
  exit 15:15); ideas show as cards with their checks; every master idea is recorded and scored with the other signals
  (source "Master bot (tested / odds / watch)"); Signal record on the Bots page too.

## 5 Nov 2026: Gap & go and trend-day banner (the 2.5% day with no index signal)

- Cause: the move was mostly the opening gap and the index setups measure from the open. Tested gap / trend rules on
  10 years daily and 3 years hourly (research/MOMENTUM_STUDY.md): no rule has a real edge; the break of the first
  hour's high / low in the gap direction is the only consistent one (small).
- `index_funnel.day_trend` (vs yesterday's close: change, gap, ATR, breadth vs yesterday, trend day) and
  `index_funnel.gap_go` (first-hour break + breadth ≥ 70%, with the plan). Trend-day banners on Market View and
  Momentum Funnel → Indices; Gap & go in the Signals list and recorded by the server (trade_signals, source "Gap & go").

## 5 Nov 2026: Index momentum bot (money + breadth + ATR confirmation, trap warning)

- `index_funnel.momentum_table / momentum_now`: every 5 minutes per index, price + net money increasing + breadth vs
  yesterday high and not falling + ATR rising = confirmed burst; price against money and breadth = trap warning.
  Per-index rule (MOM_MODE): Nifty with it on trend days only, Bank Nifty fades bursts except on trend days, Midcap and
  Sensex with it, Fin Nifty watch only. Each signal with the plan; recorded by the server (source "Index momentum bot",
  several a day, 1 h apart) and scored at the close. Cards on the Bots page and Market View; signals in the list.
- First test (45 days): 141 trades, +0.10% (+0.26R), 60% wins, both halves positive; replay of 5 Nov: Nifty LONG 09:50
  @ 24,413 → target 1; Bank Nifty fades skipped (trend day).

## 5 Nov 2026: OI on every momentum signal
- `index_funnel._oi_at`: the index future's build-up over the signal's 15 minutes and for the day; "OI confirms" when
  new positions are on the burst's side. Shown on the momentum cards, saved in trade_signals.note (new column) so the
  live record can be split by OI confirmation.

## 5 Nov 2026: Momentum bot EARLY stage (10-minute window)
- Signals now come in two stages: EARLY (10-minute window, move ≥ 0.12 ATR; ~5 minutes earlier) and CONFIRMED
  (15-minute window), each with the plan and OI, recorded separately ("Index momentum bot (early)").

## 5 Nov 2026: Times everywhere, TradingView links, chart levels

- Chart legend shows the hovered candle's date and time; "Live data as of HH:MM IST" on Market View and "as of" on its
  sections; every signal chip shows its time (⏱).
- TradingView: `mv_ui.tv_url / tv_link` map our symbols (NSE stocks, indices, crypto, forex, commodities) to
  TradingView; "TradingView ↗" opens a new tab from the chart page, every card (watchlist, index, momentum, ideas, radar,
  AI Desk, trend banners, sector stock rows) and a link column in the funnel, sector, radar, AI Desk and signal tables.
- Chart: yesterday's high / low and today's recorded signal levels (entry and stop solid, targets dashed) as lines;
  day and 52-week ranges no longer cut off.

## 5 Nov 2026: Phone home-screen icon
- iPhones showed a plain "O" (Streamlit has no apple-touch-icon). New static/ folder served by Streamlit
  (enableStaticServing): apple-touch-icon 180 px, icon-192 / icon-512 and manifest.json, rendered from the brand SVG as
  a full square; the page head gets the icon / manifest / app-name tags; Caddy also serves /apple-touch-icon*.png at
  the site root (after a Caddy restart).

## 5 Nov 2026: Live price and exit management on every signal
- `funnel.manage`: re-checked every 5-minute candle after a signal: stop → exit; target 1 → book half, stop to entry,
  then trail 1R behind the best close; target 2 → exit the rest; before target 1, momentum slowing (0.5R+ in profit,
  two candles against and a close through the 5-min EMA 9) → exit; 15:15 → exit what is left. Returns LTP, move in
  points / % / R, best / worst R, the stop now and the advice (HOLD / TIGHTEN / CAUTION / CLOSED).
- Live block (LTP · move · R · best / worst · stop now · advice) on index cards, trend / Gap & go banners, momentum
  cards, the Bank Nifty fade line, funnel watchlist cards (recorded signal), funnel picks on Market View and the Bots
  page ideas / momentum cards; Signal record gains LTP, R now, best R, advice, managed exit and managed R; AI Desk paper
  calls gain the current price and R now.
- Server records the managed exit next to the plain target / stop result (trade_signals m_exit / m_r / m_pct, ltp,
  r_now, best_r, worst_r, advice) so the two exits can be compared.

## 5 Nov 2026: Closing Picks (buy near the close for the next day)
- New page "Closing Picks" (Today menu). From 14:45 the server's bots compute a live read every 5 minutes; at 15:15 the
  picks are fixed and recorded (`<data>/closing/<day>.json` and Supabase `closing_picks`).
- Indices (Nifty, Bank Nifty tested; Fin Nifty, Midcap, Sensex watch-only): close location in the day's range, day in
  ATR, constituents' money and breadth change in the last 30 minutes, futures OI build-up in the last 30 minutes, calls
  vs puts written near the money in the last 30 minutes (recorder option chain) with the strikes that got the most.
- Stocks (untested): last 30 / 15 minutes' money, close location, volume vs usual, sector money in the last 30
  minutes, futures OI change in the last 30 minutes (recorder quotes); top 10 buys, sells under an expander.
- Scored on the next trading day: the gap at the open (after 9:20) and the close (15:35), after costs; the record table
  and KPIs (index BUY vs NO TRADE days, stock BUY / SELL) show the results.

## 5 Nov 2026: Entry time on every signal, faster pages
- Market View signals all carry a Time (first column of the table, ⏱ on every chip): Breakout V3 its signal time with
  entry and stop; CE / PE focus stocks, smart-money picks and funnel picks the first time they showed today (and the
  price then), kept in `<data>/signals_seen/<day>.json` for every viewer and for later tests. Funnel pick cards show
  "entry signal at HH:MM" (the recorded signal's time).
- Speed: the index bots (index funnel, Bank Nifty fade, trend day / Gap & go, momentum bot for 5 indices, ~5 s) and
  the Momentum Funnel build (~10 s) ran on every refresh of every viewer; now they are rebuilt only when new candles
  arrive, in the background, and the last result shows at once (`_index_bots`, `_funnel_now`).
- Page timings logged to Supabase `app_perf` (page, seconds, Market View per section) to find what is still slow.

## 5 Nov 2026: Auto Trader (paper account, six agents)
- `autotrader.py`: Scanner → Filter (tested setups only, 9:20-15:00, stop 0.15-2.5%, one open position per symbol) →
  Analyst (plan order, reward:risk ≥ 1.5) → Risk manager (1% risk a trade, max 5 open, no new trades at -3% for the
  day, position ≤ 3x equity) → Executor (paper position at the signal entry, managed exits from the signal record) →
  Reporter (equity, P&L, wins / losses, equity curve). Starting capital ₹1,00,000 (paper).
- Server (`bots.py auto_step`): every 5 minutes on the day's signal records; decisions fixed once made;
  `<data>/autotrader/<day>.json`, `account.json` (daily history, closed at 15:35) and Supabase `auto_trades`.
- New page "Auto Trader" (Today menu): the six agents as a pipeline with today's counts, account KPIs, position cards
  (qty, entry, stop, targets, R, P&L, exit), equity curve, every decision with its reason, daily record and the rules.
- Replay on 5 Nov's real signals: 8 trades, +₹3,770 (index trades won, funnel stocks lost). No real orders.

## 5 Nov 2026: BTC sniper paper trade
- `btc_sniper.py`: the best lead of research/SNIPER_STUDY.md (BTC NY-session trend pullback to VWAP: 1-hour trend,
  13:30-18:00 London, trigger candle, stop beyond the last 6 candles 0.3-0.8%, target 3R, exit 21:00 London, one trade
  a day). Replayed on Jun-Aug 2025 it gives the backtest's 31 trades exactly.
- `agents.py` (24/7) checks it every minute 13:25-21:15 London on Crypto.com candles: state to
  `<data>/crypto_paper/btc_state.json`, trades to `record.json` and Supabase `crypto_paper`.
- Auto Trader page: "BTC sniper · paper" section (today's state or trade with entry time in IST, stop, target, R now,
  the record and its stats vs the tested +0.09R / 36%).

## 5 Nov 2026: Strategy lab and crash-buy paper trades (BTC, gold)
- `research/strategy_lab.py`: 11 popular setups (freqtrade BinHV45 / ClucMay, ICT Silver Bullet, EMA200+MACD,
  Supertrend+StochRSI, RSI2, EMA9/21+VWAP, squeeze, Donchian, open momentum, gold time bias) on BTC and gold: all lose
  or are flat after costs except the crash-candle buy (findings in research/SNIPER_STUDY.md).
- `crash_buy.py` + `agents.crash_tick` (every minute, 24/7; gold weekdays): BTC Z=9 / +1.5% / -1.0% and gold (PAXG)
  Z=4 / +0.4% / -0.4%, 4 h max, 2 a day max; 20-day history paged from Crypto.com; trades to record.json and
  Supabase crypto_paper. Auto Trader page: "Crash buy · paper" panel (today's trigger level, signal, open trade) and a
  per-setup record vs the tested numbers.

## 5 Nov 2026: Burst study and burst-momentum paper trades
- `research/burst_study.py`: every wild 5-min candle on BTC, ETH, SOL, gold (4 years) and oil, gold futures, forex,
  USDINR, Nasdaq (60 days): giant crypto up-bursts run on, crashes snap back, gold fades, forex does not run.
- `crash_buy.py` gains burst momentum setups (BTC / ETH / SOL: up-burst ≥ 8x, enter one candle later, stop at the burst
  low, 12-candle hold), run every minute by agents.crash_tick with the crash buys; all trades stored in record.json
  and Supabase crypto_paper. Auto Trader panel renamed "Wild-move setups · paper".

## 5 Nov 2026: Bank Nifty EBP 1h (overnight) paper trade
- `bn_ebp.py`: Engulfing Bar Play on 1h Bank Nifty candles (built from the 5-min bars, 9:15 grid), 50% limit for 3
  hours, stop at the wick (gap fills at the open), target the 20-hour swing, hold up to 14 trading hours; reproduces
  the research trades.
- `bots.bn_ebp_step` every 5 minutes in market hours: <data>/bots/bn_ebp.json (since, trades with state) and Supabase
  crypto_paper. Auto Trader page: "Bank Nifty EBP 1h · paper" (limit waiting / open trade with R and points) and the
  trades in the per-setup record.
