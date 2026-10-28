# Omnipuls

A live market dashboard and screener for Indian stocks and indices, crypto, forex, INR currency pairs and commodities. Runs on your own computer in the browser.

## Brand

The logo is concept 1, **Aligned Momentum**: an 'O' built from vertical data bars, broken at the top right where a line chart breaks out. It uses an electric aqua to blue gradient on deep navy slate. The wordmark is set in Sora, with **omni** in semibold and **puls** in a light weight. Blue was chosen so the brand never competes with the green and red used for buy/sell and price moves.

All three concepts are in the `brand` folder as SVG files, with a comparison sheet (`omnipuls_logo_concepts.png`). The app's logo, icon and Windows icon are in `assets`. To regenerate them, run `python brand/make_logos.py` (needs `cairosvg` and `fonttools`).

## Start it

**Windows:** double-click **run_windows.bat** once. It installs Python if needed, installs the app's packages (progress shows in a black window), puts a **Omnipuls** shortcut on your desktop, then opens the app in its own window and closes the black window.

After that, start the app from the **Omnipuls** desktop shortcut. It opens straight into the app window with no black window. To stop it, press **Quit Omnipuls** at the bottom of the app's sidebar.

**Mac:** double-click **Omnipuls.command**. **Any system:** run `python app.py`.

The app opens in a window of its own (Edge or Chrome app mode) once it is ready. If no window appears, open http://localhost:8501 in your browser. If it can't start, a message shows the reason, and full details are in `navv.log` in the app folder.

## Running on Streamlit Cloud

Omnipuls works on Streamlit Community Cloud, with these differences from running on your own computer:

- **Accounts and the Dhan token go in Secrets** (your app → ⋮ → Settings → Secrets), never in GitHub. See `.streamlit/secrets.toml.example`. On a public server the app won't offer "Create your admin account", so a stranger can't claim it; add your admin in Secrets first.
- **Files reset whenever the app restarts, redeploys or wakes from sleep.** Accounts added, passwords changed or tokens pasted in the app last until then. Under Account, the app shows the lines to paste into Secrets to keep an account. Watchlists and alerts also reset.
- **Dhan tokens expire every 24 hours.** Update `access_token` in Secrets each day, or paste the day's token in Dhan Connect. If a pasted token expires, the app falls back to the one in Secrets.
- **Live prices update every 1–2 seconds.** The server still receives every tick from Dhan, but Streamlit Cloud doesn't allow the direct tick stream to the browser, so the page fetches the latest ticks each second. On your own computer it is still tick by tick.
- **Quit Omnipuls** is hidden on the cloud, and on your own computer only the admin sees it.
- Yahoo Finance and NSE sometimes limit requests from cloud servers. Indian prices come from Dhan when connected, and the F&O list falls back to Dhan's contract list.
- `.gitignore` keeps private files (Dhan token, accounts, watchlists, caches, `.venv`) out of GitHub.

## Sign in

The first time Omnipuls opens, it asks you to create the **admin account** (name, user ID and password). After that, everyone signs in with a user ID and password.

- **Admin:** sees every page, including Portfolio and Dhan Connect, and manages users under **Account**: add users, reset passwords, change roles, delete users.
- **User:** sees all market pages but not Portfolio or Dhan Connect, so your account and token stay private.
- **Everyone:** can change their own password under **Account**, and has their own watchlist and alerts.

Accounts can also be defined in Streamlit secrets (`[users.<id>]` with name, role and password or salt + hash). Passwords are stored only as salted hashes (PBKDF2-SHA256) in `users.json`; after 5 wrong attempts an ID is locked for 5 minutes. A forgotten admin password can be reset on the computer itself: in the app folder, run `.venv\Scripts\python reset_password.py`.

You stay signed in while the window is open; closing or reloading the page asks you to sign in again.

## Appearance

Each user picks a layout under **Account → Appearance**, and it follows them to every device:

- **Clean Corporate** (default): navy sidebar with a thin divider; frameless tables with a navy header row and light grey alternate rows.
- **Modern Minimalist**: charcoal sidebar with an electric-blue edge; framed, rounded tables with an uppercase white header and soft blue-grey stripes.
- **Vibrant Accent**: slate sidebar with an emerald bar beside the active page; grey-framed tables with a light grey header and mint stripes.

## Search and filters

Every table has a search box, click-to-sort column headers, filters for sector, market, trend, buildup or rating where the table has them, **All / ▲ Gainers / ▼ Losers** chips, a row count and **CSV** download. Prices in tables tick live. Click a stock name to open its chart. Pages with their own lists add their own filters too: sector search and advancing/declining/trend filters on Sector Performance, ITM/strike/minimum-OI filters on the Option Chain, scans and filters on F&O Stocks and OI Analysis, and search on the watchlist.

## On your phone

Omnipuls runs on your computer, and your phone opens it over the same Wi-Fi. As admin, open **Account → Open on your phone** to see the address (for example `http://192.168.1.5:8501`), open it in the phone's browser, sign in, and use "Add to home screen" for an app icon. Layouts adapt to the screen: on phones, metric cards sit two per row, wide lists scroll sideways, and charts are shorter. Live ticks work on the phone too. The first time, Windows may ask whether Python can use the network; allow it on private networks. Keep it to your home or office Wi-Fi, and don't expose it to the internet.

## Pages

Use the menu in the left sidebar.

### Markets

**Dashboard**: a running ticker tape and live tiles for Nifty 50, Bank Nifty, Sensex, Nifty Midcap 100, Fin Nifty, BTC/USD, ETH/USD, XAU/USD, Solana and US Oil (WTI). Below them, sector performance (today, 1 week, 1 month, 3 months, 1 year), then the top 10 gainers and top 10 losers among F&O stocks.

**NSE Indices & Sectors**: broad-market indices (Nifty 50, Bank, Sensex, Fin Nifty, Midcap Select, Midcap 100, Next 50, Smallcap 100, Nifty 500, India VIX and more) and about 24 sectoral and thematic indices, each with LTP, change, open/high/low, returns, distance from 52-week high, RSI and trend.

**Sector Performance**: overall advances, declines and the A/D ratio, then every sector with its average move (today, 1 week, 1 month, 3 months, 1 year), the matching NSE sector index, an advance/decline bar, best and worst stock, and turnover. Click a sector to list its stocks; click a stock name to open its chart.

**F&O Stocks**: every NSE F&O stock with LTP, change, open, high, low, previous close, gap, volume and volume vs average, turnover, lot size, lot value, ATR, RSI, trend, Supertrend, technical rating, returns, 52-week range and signals. Includes advance/decline counts, sector breadth, 18 scans (gainers, losers, volume spike, gaps, big movers, high volatility, RSI, trend, Supertrend and MACD signals) and filters by sector, price, RSI and trend. The F&O list and lot sizes are downloaded from NSE's contract file each day.

**Crypto, Forex, Currency (INR), Commodities**: live tiles plus a full table for each market. The currency page also has a rupee converter.

### Tools

**Screener**: scan any mix of markets plus your watchlist, or add symbols on the fly. 20 ready-made scans (gainers, losers, volume spike, RSI oversold/overbought, near 52-week high/low, EMA trend stack, pullback in uptrend, golden/death cross, MACD crossovers, Supertrend flips, gaps, high volatility) and filters for change %, RSI, volume, trend, rating and name. Click any row to open its chart. Download results as CSV from the table menu.

**Chart & Details**: candlestick chart from 1-minute to monthly, with EMA 20/50/200, Bollinger Bands, VWAP, Supertrend and classic pivots, plus volume, RSI and MACD panels. Below the chart: technical summary, key levels, returns from 1 day to 1 year, fundamentals for stocks (market cap, P/E, P/B, ROE, margins, debt/equity and more) and latest news.

**Watchlist & Alerts**: your saved symbols with live price, RSI, trend and signals, and price alerts that pop up while the app is open. Both are saved in `watchlist.json` next to the app.

## Dhan (live Indian market data and your account)

Open **Dhan Connect** in the sidebar menu and paste your **Client ID** and **access token**. To get them, log in to web.dhan.co and open My Profile → Access DhanHQ APIs. The token is valid for 24 hours: renew it from the same page while it is valid, or paste a new one.

With Dhan's **Data APIs** subscription active:

- **Tick-by-tick prices.** The app keeps one connection open to Dhan's live market feed for every Indian instrument it shows: indices, F&O stocks and futures, MCX and currency futures. Live widgets update in place on every trade, with a green or red flash, without reloading the page: the dashboard tiles and ticker, the top 10 gainers and losers (re-ranked live), the **Live prices** board on the F&O page (sortable, searchable), the index tiles, and the price and 5-level market depth on each chart. The rest of the page (indicators, tables, scans) refreshes on the sidebar timer, every 60 seconds by default. The feed also supplies the exchange's previous close and previous-day OI, so change % and OI change are exact at any hour. Turn it off in Dhan Connect if you prefer.

- Indices, F&O stocks, charts and quotes come from Dhan live quotes instead of Yahoo, refreshed as often as every 5 seconds.
- Extra quote fields: average price (VWAP), upper/lower circuit, total buy/sell quantity, and 5-level market depth on each chart.
- Charts use Dhan candles: 1, 5, 15, 25 and 60 minutes, daily, weekly and monthly.
- **F&O Stocks** can add the nearest stock future's price, basis, open interest, OI change and buildup (long buildup, short covering, short buildup, long unwinding), with scans for each.
- **OI Analysis**: long buildup, short buildup, short covering and long unwinding counts and top-10 lists, OI gainers and losers, buildup by sector, index futures (Nifty, Bank Nifty, Fin Nifty, Midcap Select, Next 50), and a full table of every stock future with OI, OI change and OI value.
- **Option Chain** for Nifty, Bank Nifty, Fin Nifty, Midcap Select, Sensex and every F&O stock: OI, change in OI, volume, IV, LTP, greeks, PCR, max pain, support/resistance from OI, ATM straddle and expected move, plus OI and IV charts.
- **MCX Commodities** (gold, silver, crude, natural gas, base metals) and **Currency Futures** (USD/INR and others), always on the nearest contract.

Without the Data APIs, prices come from Yahoo, but **Portfolio** still works: funds and margin, holdings with live P&L, positions with MTM, and today's orders and trades. The app only reads your account; it never places, changes or cancels orders.

The token is saved only in `dhan_config.json` in the app folder. You can use the environment variables `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` instead. On the first run each day, the app downloads daily history from Dhan for its indicators; prices are live right away and indicator columns fill in over a few refreshes.

## Symbols

Type plain names in any symbol box and the app converts them:

| You type | Becomes |
|---|---|
| reliance, tcs, irctc | RELIANCE.NS, TCS.NS, IRCTC.NS |
| nifty, banknifty, sensex, vix | ^NSEI, ^NSEBANK, ^BSESN, ^INDIAVIX |
| btc, eth, solusdt | BTC-USD, ETH-USD, SOL-USD |
| eurusd, usdinr | EURUSD=X, USDINR=X |
| gold / xauusd, silver, crude, brent, natgas, copper | GC=F, SI=F, CL=F, BZ=F, NG=F, HG=F |

For a BSE-only stock add `.BO`. To change the built-in lists, edit `universe.py`.

## Data notes

- Prices come from Yahoo Finance through the free `yfinance` library. Crypto, forex and futures update close to real time; NSE quotes can lag by a few minutes.
- Gold and silver are COMEX futures (GC=F, SI=F), which track XAUUSD spot closely but trade at a small premium.
- Refresh defaults to every 60 seconds. If you see "rate-limited" errors, raise it to 2 or 5 minutes.
- The technical rating counts five daily checks: price above EMA 20, EMA 50 and EMA 200, MACD above its signal line, and Supertrend up. It is a summary of trend, not a trade signal.
- For information only, not investment advice.

## Files

- `app.py`: the app
- `auth.py`: user accounts and password hashing
- `reset_password.py`: reset any password from the computer running the app
- `bootstrap.py`: installs missing packages, creates the desktop shortcut and opens the app window
- `indicators.py`: RSI, EMA, MACD, ATR, Bollinger, VWAP, Supertrend, pivots and screener metrics
- `universe.py`: symbol lists, index names, F&O sectors and dashboard tiles (edit to customise)
- `fno.py`: downloads the F&O list and lot sizes from NSE
- `feed.py`: Dhan live market feed (binary WebSocket) and the local relay that pushes ticks to the page
- `livecomp/`: the live widgets (tiles, ticker, movers, board, quote and depth)
- `dhan.py`: DhanHQ v2 client (quotes, history, option chain, portfolio, instrument lists)
- `.streamlit/config.toml`: theme (navy slate and aqua blue, Sora font)
- `assets/`: logo, app icon and Windows icon
- `brand/`: all three logo concepts and the script that draws them
