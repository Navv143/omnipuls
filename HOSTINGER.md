# Omnipuls on a Hostinger VPS with your own domain

Result: **https://app.yourdomain.com** with live prices tick by tick, the market data recorder running every market
day, and updates arriving by themselves from GitHub. About 30 minutes, once.

## 1. Buy the server

1. Go to **hostinger.com/in/vps-hosting** and pick **KVM 2** (2 vCPU, 8 GB RAM, 100 GB NVMe).
2. Choose the period. 12 or 24 months gives the low price; it renews at a higher monthly rate (check the renewal
   price at checkout). GST (18%) is added.
3. Pay. Hostinger then opens the **VPS setup**:
   - **Location:** choose **India** if it is offered (closest to Dhan and NSE). If not, the nearest Asian location.
   - **Operating system:** plain **Ubuntu 24.04** (the "Ubuntu 24.04 with Docker" template is also fine).
   - **Root password:** a long, strong one. Save it in a password manager. Never paste it into a chat.
4. In **hPanel → VPS → Overview**, note the server's **IP address** (for example `82.112.x.x`).

## 2. Point your domain at the server

Use a sub-address such as `app.yourdomain.com`, so your main website (if any) stays separate.

- **Domain bought at Hostinger:** hPanel → **Domains** → your domain → **DNS / Nameservers** → **Add record**.
- **Domain at another company (GoDaddy, Namecheap, BigRock...):** their **DNS management** page.

Add this record:

| Type | Name | Points to | TTL |
|---|---|---|---|
| A | `app` | your server's IP address | 300 (or the lowest offered) |

Wait 5-30 minutes. To check: open **dnschecker.org**, type `app.yourdomain.com`: it should show your server's IP.

## 3. A read-only GitHub key for updates

GitHub → your photo → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate**:
- Repository access: **Only select repositories → Navv143/omnipuls**
- Permissions: **Contents: Read-only** (nothing else)
- Expiration: 1 year (put a reminder to renew it; updates stop when it expires)

Copy the token (starts with `github_pat_`).

## 4. Install Omnipuls (one command after the download)

Open the server's terminal: hPanel → VPS → **Browser terminal** (or from your computer: `ssh root@<server IP>`).
Then paste, replacing `<TOKEN>`:

```sh
apt-get update && apt-get install -y git
git clone https://<TOKEN>@github.com/Navv143/omnipuls.git /opt/omnipuls
cd /opt/omnipuls && bash deploy/setup.sh
```

The script asks two things:
1. **Your web address:** `app.yourdomain.com`.
2. **Your Secrets:** an editor opens. Paste the same content as the Streamlit Cloud app's Secrets
   (Streamlit Cloud → your app → ⋮ → Settings → Secrets). It must contain:
   - your admin account: `[users.navneet]` with `name`, `role = "admin"`, `password`
     (a public server never offers "create account" on the page),
   - `[dhan]` with `client_id`, `pin`, `totp_secret` (tokens are then made automatically every day),
   - `[supabase]` `url` and `key`, and `[twelvedata]` `api_key`.

   Save with **Ctrl+O, Enter**, close with **Ctrl+X**.

It then installs everything and starts. Open **https://app.yourdomain.com** after a minute and sign in.

## 5. Right after it works

- **One Dhan login in one place:** remove `pin` and `totp_secret` from the **Streamlit Cloud** app's Secrets (or
  stop the cloud app). Otherwise both keep making tokens and replace each other's.
- If Dhan ever asks you to register a **static IP** for API access, give it the server's IP address: a VPS keeps the
  same IP.

## Every day after that: nothing

- **Updates:** every merge to `main` on GitHub reaches the server within 5 minutes.
- **Data:** recorded into `/opt/omnipuls/market_data/` every market day (about 30-40 MB a day).

## If something looks wrong

In the server terminal:

```sh
cd /opt/omnipuls/deploy
docker compose -f docker-compose.yml -f docker-compose.cloud.yml ps          # all four "running"?
docker compose -f docker-compose.yml -f docker-compose.cloud.yml logs --tail 50 app
docker compose -f docker-compose.yml -f docker-compose.cloud.yml logs --tail 50 recorder
cat /opt/omnipuls/market_data/status.json                                    # last recording, errors
```

To restart everything: `cd /opt/omnipuls && bash deploy/setup.sh` (safe to run again).

## Yearly reminders

Hostinger renewal, domain renewal, GitHub token renewal (step 3).
