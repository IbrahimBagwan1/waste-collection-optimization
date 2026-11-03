#!/usr/bin/env bash
# WASTEX launcher (macOS / Linux):  ./start.sh            (Docker Kafka if available)
#                                   ./start.sh --embedded (no Docker)
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "Python 3.10 or newer is required (https://www.python.org/downloads/)."; exit 1
fi
[ -x .venv/bin/python ] || "$PY" -m venv .venv
if [ ! -f .venv/.installed ]; then
  echo "Installing dependencies (first run only, can take several minutes) ..."
  .venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
  touch .venv/.installed
fi
if [ "$1" = "--embedded" ]; then exec .venv/bin/python run.py --embedded; else exec .venv/bin/python run.py --docker; fi
