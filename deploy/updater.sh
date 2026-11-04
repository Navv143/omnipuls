#!/bin/sh
# Pulls new commits of the deployed branch from GitHub every UPDATE_EVERY seconds (default 300). The app picks them up
# on its own; the recorder restarts itself when the code changes.
CODE="${CODE_DIR:-/app/code}"; STATE="${STATE_DIR:-/app/state}"
cd "$CODE"
git config --global --add safe.directory "$CODE" 2>/dev/null || true
BRANCH="${DEPLOY_BRANCH:-main}"
while true; do
  OLD=$(git rev-parse HEAD 2>/dev/null)
  if git fetch -q origin "$BRANCH" && git merge -q --ff-only "origin/$BRANCH"; then
    NEW=$(git rev-parse HEAD)
    [ "$OLD" != "$NEW" ] && echo "$(date '+%F %T') updated $OLD -> $NEW"
  else
    echo "$(date '+%F %T') update failed (no internet to github.com, or local changes in the folder)"
  fi
  date '+%F %T' > "$STATE/last_update_check"
  sleep "${UPDATE_EVERY:-300}"
done
