#!/usr/bin/env bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed."
  if [[ "$OSTYPE" == darwin* ]] && command -v brew >/dev/null 2>&1; then
    brew install python
  else
    echo "Install it from https://www.python.org/downloads/ and run this again."
    exit 1
  fi
fi
if [ ! -x .venv/bin/python ]; then
  echo "Setting up Omnipuls for the first time..."
  python3 -m venv .venv || true
fi
if [ -x .venv/bin/python ]; then exec .venv/bin/python app.py; else exec python3 app.py; fi
