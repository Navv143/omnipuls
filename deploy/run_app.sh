#!/bin/sh
# The web app. Code updates are picked up live (app.py runs fresh on every page load and reloads changed modules);
# only a change of requirements.txt or .streamlit/config.toml needs a restart, which this script does by exiting
# (Docker starts it again, and the entrypoint installs the new packages).
cd /app/code
sig() { cat requirements.txt .streamlit/config.toml 2>/dev/null | sha1sum | cut -d' ' -f1; }
START=$(sig)
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
PID=$!
healthy() { python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=20); sys.exit(0)" 2>/dev/null; }
FAILS=0
sleep 120   # give the app time to start
while kill -0 "$PID" 2>/dev/null; do
  sleep 60
  if [ "$(sig)" != "$START" ]; then
    echo "requirements or Streamlit config changed: restarting the app"
    kill "$PID"; wait "$PID"; exit 0
  fi
  # watchdog: the app stopped answering (hung) -> restart it instead of staying down
  if healthy; then FAILS=0; else FAILS=$((FAILS + 1)); echo "$(date '+%F %T') health check failed ($FAILS)"; fi
  if [ "$FAILS" -ge 3 ]; then
    echo "$(date '+%F %T') app not answering for 3 minutes: restarting it"
    kill "$PID"; sleep 10; kill -9 "$PID" 2>/dev/null; exit 0
  fi
done
wait "$PID"
