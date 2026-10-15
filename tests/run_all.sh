#!/usr/bin/env bash
# Full acceptance suite against the live portal (real Hermes/LLM calls; billable on the webtest profile).
# Refuses to run while any portal response is active, because some tests restart bridges.
set -uo pipefail
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
active=$(docker exec hermes-web-backend python -c "import sqlite3,time;c=sqlite3.connect('/data/portal.db');print(c.execute(\"select count(*) from turns where state in ('running','waiting') and created>?\",(time.time()-900,)).fetchone()[0])")
if [ "$active" != "0" ]; then echo "Active responses: $active. Not running (tests restart bridges)."; exit 2; fi
suite=(throttle totp policy multiuser perms settings cmd audit usage skills plugins artifacts dialogs limits prefs modelswitch subs oauth sandbox impersonate busy paging chatstatus cursor chatmodel vps rewind pin sleep search share reap attach session)
[ $# -gt 0 ] && suite=("$@")
rc=0; for t in "${suite[@]}"; do tests/run.sh "tests/acceptance/${t}_acceptance.py" >/dev/null || rc=1; printf '%-10s %s\n' "$t" "$(tail -1 "tests/${t}_acceptance.txt")"; done
exit $rc
