# Omnipuls on the office server (Docker)

**Renting a cloud server with your own domain instead? Follow HOSTINGER.md** (HTTPS, live ticks, one setup script).

Three services run from one image:

| Service | What it does |
|---|---|
| `app` | The Omnipuls web app on port 8501, live prices tick by tick on the office network (port 8765). |
| `recorder` | Records market data for backtesting (`recorder.py`): 1-minute candles of indices, all F&O stocks, all stock and index futures (with OI) and Nifty / Bank Nifty options (with OI) after each close; option chains of Nifty, Bank Nifty, Fin Nifty, Midcap Select and Sensex (with IV and greeks) and full quotes of every instrument (order-book buy / sell quantity) every minute in market hours. |
| `updater` | Pulls every merge to `main` from GitHub every 5 minutes. The app uses new code at once; the recorder restarts itself. **Nobody needs to log in to the server after the first setup.** |

## One-time setup (about 15 minutes, by someone who can log in to the server)

The server needs Docker Engine with the compose plugin, and outbound internet to: github.com, pypi.org and
files.pythonhosted.org, Docker Hub (registry-1.docker.io), api.dhan.co and auth.dhan.co, the Supabase project,
query1.finance.yahoo.com and api.twelvedata.com. If the office uses an internet proxy, Docker needs it too
(ask IT: Docker daemon proxy and build proxy).

1. **A read-only GitHub token** for the updater: github.com → Settings → Developer settings → Fine-grained tokens →
   Generate: repository `Navv143/omnipuls` only, permission **Contents: Read-only**.

2. **Get the code** (replace `<TOKEN>`):
   ```sh
   git clone https://<TOKEN>@github.com/Navv143/omnipuls.git ~/omnipuls
   cd ~/omnipuls
   ```

3. **Secrets:** create `~/omnipuls/.streamlit/secrets.toml` with the same content as the Streamlit Cloud app's
   Secrets (users, `[dhan]`, `[supabase]`, `[twelvedata]`). It is never uploaded to GitHub.

4. **Start it:**
   ```sh
   cd ~/omnipuls/deploy
   docker compose up -d --build
   ```

5. **Open the ports** on the server's firewall if it has one (for example `sudo ufw allow 8501,8765/tcp`), then open
   **http://10.195.82.89:8501** from any computer or phone on the office network.

### One Dhan login in one place

Dhan may allow only one access token at a time. If the office server and the Streamlit Cloud app both make tokens
from the PIN and TOTP, they keep replacing each other's. Once the server runs, **remove `pin` and `totp_secret`
from the Streamlit Cloud app's Secrets** (or turn the cloud app off). The app and the recorder on the server share
one token automatically.

## After setup

- **Updates:** merge on GitHub; the server has them within 5 minutes. Only a change to `deploy/docker-compose.yml`
  or `Dockerfile` itself needs `cd ~/omnipuls/deploy && docker compose up -d --build` again (rare; the worklog will
  say so).
- **Is it working?** `docker compose ps` (all three `running`), `docker compose logs -f recorder`, and
  `~/omnipuls/market_data/status.json` (last snapshot times, rows, errors).
- **Restart everything:** `cd ~/omnipuls/deploy && docker compose restart`.

## The recorded data

In `~/omnipuls/market_data/` (set `DATA_DIR` in `deploy/.env` to put it on a bigger disk):

```
candles_1m/2026-11/2026-11-05.parquet     one file per trading day, all instruments
option_chain/2026-11/2026-11-05.parquet   every minute, 5 indices x 2 expiries x 51 strikes
quotes/2026-11/2026-11-05.parquet         every minute, every stock, future and index
```

Roughly 30-40 MB a trading day (about 8-10 GB a year): back the folder up now and then. Read it with pandas:

```python
import pandas as pd
c = pd.read_parquet("market_data/candles_1m/2026-11/2026-11-05.parquet")
bn_fut = c[(c.kind == "future") & (c.symbol == "BANKNIFTY")]      # 1-min OHLCV + OI
oc = pd.read_parquet("market_data/option_chain/2026-11/2026-11-05.parquet")
```

**What can and cannot be filled in later:** 1-minute candles of indices and stocks can be downloaded for past days
(`docker compose exec recorder python recorder.py --backfill 60`). Futures and options candles exist only while the
contract is live, and option chains (IV, greeks, bid / ask) and order-book quantities exist only at the moment they
are recorded: every day before the server runs is lost for those, so start it soon.
