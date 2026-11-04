#!/usr/bin/env bash
# One-time setup of Omnipuls on a fresh Ubuntu VPS (Hostinger KVM 2), from the cloned repository:
#     bash deploy/setup.sh
# Installs Docker if needed, opens only SSH/HTTP/HTTPS, adds 2 GB swap, asks for your domain and Secrets, and starts
# the app (HTTPS on your domain, live ticks), the data recorder and the auto-updater. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(id -u)" = 0 ] || { echo "Run as root (Hostinger: log in as root, or use: sudo bash deploy/setup.sh)"; exit 1; }
echo "== Omnipuls setup =="

if ! command -v docker >/dev/null 2>&1; then
  echo "-- installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || { echo "Docker's compose plugin is missing: apt-get install docker-compose-plugin"; exit 1; }

if command -v ufw >/dev/null 2>&1; then
  echo "-- firewall: only SSH, HTTP and HTTPS open"
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

if ! swapon --show | grep -q .; then
  echo "-- adding 2 GB swap (safety margin for memory)"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
timedatectl set-timezone Asia/Kolkata 2>/dev/null || true

DOMAIN=$(grep -s '^DOMAIN=' deploy/.env | cut -d= -f2 || true)
if [ -z "${DOMAIN:-}" ]; then
  read -rp "Your web address for the app (for example app.omnipuls.in): " DOMAIN
  echo "DOMAIN=$DOMAIN" > deploy/.env
fi
MYIP=$(curl -fsS -4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
# ask public DNS (the server's own /etc/hosts maps its hostname to 127.0.1.1, which is not what the internet sees)
DNSIP=$(curl -fsS -m 10 "https://dns.google/resolve?name=$DOMAIN&type=A" 2>/dev/null | grep -o '"data":"[0-9.]*"' | head -1 | cut -d'"' -f4)
[ -n "$DNSIP" ] || DNSIP=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '$1 !~ /^127\./ {print $1; exit}')
if [ "${SKIP_DNS_CHECK:-0}" != 1 ] && [ "$DNSIP" != "$MYIP" ]; then
  echo "!! $DOMAIN points to '${DNSIP:-nothing}', but this server is $MYIP."
  echo "   Add a DNS 'A' record: $DOMAIN -> $MYIP (see HOSTINGER.md), wait a few minutes, then run this script again."
  echo "   (HTTPS can only start once the domain points here.)"
  exit 1
fi

if [ ! -s .streamlit/secrets.toml ]; then
  cp .streamlit/secrets.toml.example .streamlit/secrets.toml
  echo "-- opening the Secrets file: paste the same content as your Streamlit Cloud Secrets, then Ctrl+O, Enter, Ctrl+X"
  read -rp "   Press Enter to open the editor..." _
  ${EDITOR:-nano} .streamlit/secrets.toml
fi
chmod 600 .streamlit/secrets.toml

echo "-- building and starting (first time 3-5 minutes)"
cd deploy
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --build
echo
echo "== Done. Open https://$DOMAIN in a minute (the HTTPS certificate is fetched on the first visit). =="
echo "   Check:  cd $(pwd) && docker compose -f docker-compose.yml -f docker-compose.cloud.yml ps"
