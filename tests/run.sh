#!/usr/bin/env bash
# Run one or more acceptance scripts inside the backend container against nginx.
# Credentials are read from root-only secrets/*.json and passed on stdin; never printed.
# Chats a script leaves in the `tester` account are deleted afterwards (tests/cleanup_dialogs.py; tester only).
# Usage: tests/run.sh perms_acceptance.py [settings_acceptance.py ...]
set -euo pipefail
cd "$(dirname "$0")/.."
# Origin header the acceptance scripts send (must match the portal's allowed origin).
# Taken from the environment, else PORTAL_ORIGIN / PORTAL_HOST in the project .env.
if [ -z "${PORTAL_ORIGIN:-}" ] && [ -f .env ]; then
  PORTAL_ORIGIN=$(sed -n 's/^PORTAL_ORIGIN=//p' .env | tail -1 | tr -d "\"'\r")
  if [ -z "$PORTAL_ORIGIN" ]; then
    _host=$(sed -n 's/^PORTAL_HOST=//p' .env | tail -1 | tr -d "\"'\r")
    [ -n "$_host" ] && PORTAL_ORIGIN="https://$_host"
  fi
fi
export PORTAL_ORIGIN="${PORTAL_ORIGIN:-https://localhost}"
CREDS=$(python3 -c "import json,glob,os;print(json.dumps({os.path.basename(f)[:-5]:json.load(open(f))['password'] for f in glob.glob('secrets/*.json')}))")
docker exec -i hermes-web-backend sh -c "cat > /tmp/cleanup_dialogs.py" < tests/cleanup_dialogs.py
rc=0
for script in "$@"; do
  name=$(basename "$script" .py)
  # snapshot of tester's chats; the SNAP marker tells a real (possibly empty) list from a failed call
  before=$(echo "$CREDS" | docker exec -i -e PORTAL_ORIGIN="$PORTAL_ORIGIN" hermes-web-backend python -W ignore /tmp/cleanup_dialogs.py snap 2>/dev/null || true)
  docker exec -i hermes-web-backend sh -c "cat > /tmp/$name.py" < "$script"
  echo "=== $name"
  if ! echo "$CREDS" | docker exec -i -e PORTAL_ORIGIN="$PORTAL_ORIGIN" hermes-web-backend python -W ignore "/tmp/$name.py" | tee "tests/$name.txt"; then rc=1; fi
  docker exec hermes-web-backend rm -f "/tmp/$name.py"
  grep -q '^FAIL' "tests/$name.txt" && rc=1
  if [[ "$before" == SNAP* ]]; then
    # shellcheck disable=SC2086
    echo "$CREDS" | docker exec -i -e PORTAL_ORIGIN="$PORTAL_ORIGIN" hermes-web-backend python -W ignore /tmp/cleanup_dialogs.py clean ${before#SNAP} || true
  fi
done
docker exec hermes-web-backend rm -f /tmp/cleanup_dialogs.py
exit $rc
