#!/usr/bin/env bash
# Installs requirements into ./.venv if needed, then starts the app with the standard run command.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f .venv/.requirements-installed ] || [ requirements.txt -nt .venv/.requirements-installed ]; then
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  touch .venv/.requirements-installed
fi

exec uvicorn app.main:app --reload "$@"
