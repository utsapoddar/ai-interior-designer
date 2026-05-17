#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi
if ! command -v npm >/dev/null 2>&1 && [ -x /opt/homebrew/bin/npm ]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi
pytest -q
cd frontend
npm run build
printf 'VERIFY OK\n'
