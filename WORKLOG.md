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
