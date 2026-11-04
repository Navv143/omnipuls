#!/bin/sh
# The web app. Code updates are picked up live (app.py runs fresh on every page load and reloads changed modules);
# only a change of requirements.txt or .streamlit/config.toml needs a restart, which this script does by exiting
# (Docker starts it again, and the entrypoint installs the new packages).
cd /app/code
sig() { cat requirements.txt .streamlit/config.toml 2>/dev/null | sha1sum | cut -d' ' -f1; }
START=$(sig)
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
PID=$!
while kill -0 "$PID" 2>/dev/null; do
  sleep 60
  if [ "$(sig)" != "$START" ]; then
    echo "requirements or Streamlit config changed: restarting the app"
    kill "$PID"; wait "$PID"; exit 0
  fi
done
wait "$PID"
