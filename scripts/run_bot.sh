#!/usr/bin/env bash
set -euo pipefail

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src"
python run_bot.py
