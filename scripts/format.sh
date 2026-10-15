#!/usr/bin/env bash
# Format the portal sources (mechanical, no behaviour change): frontend TS/TSX with Prettier, backend Python with Black.
# Runs the tools in throwaway containers (the host has no npm/pip). Usage: scripts/format.sh [frontend|backend|all]
set -euo pipefail
cd "$(dirname "$0")/.."
what=${1:-all}
if [ "$what" = frontend ] || [ "$what" = all ]; then
  docker run --rm -v "$PWD/frontend:/w" -w /w node:22-alpine \
    sh -c 'npx -y prettier@3.3.3 --log-level warn --write "src/**/*.{ts,tsx}"'
fi
if [ "$what" = backend ] || [ "$what" = all ]; then
  docker run --rm -v "$PWD:/w" -w /w python:3.12-slim \
    sh -c 'pip install -q --root-user-action=ignore black==24.10.0 >/dev/null 2>&1 && black -q -l 140 --skip-string-normalization backend/app.py profile_admin.py bridge.py ops/cron_helper.py'
fi
