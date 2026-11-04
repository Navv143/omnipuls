#!/bin/sh
# Runs before every service starts: installs Python packages again only when requirements.txt differs from what
# this container has (the image records the list it was built with), then starts the service's command.
set -e
cd /app/code
git config --global --add safe.directory /app/code 2>/dev/null || true
H=$(sha1sum requirements.txt | cut -d' ' -f1)
if [ "$(cat /tmp/.req_hash 2>/dev/null)" != "$H" ]; then
  echo "requirements.txt changed: installing packages"
  pip install --no-cache-dir -q -r requirements.txt
  echo "$H" > /tmp/.req_hash
fi
exec "$@"
