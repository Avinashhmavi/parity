#!/usr/bin/env bash
# Run ON the server, in the app directory. Proves the deployment works against
# the real FieldServe API and prints what it saw. Safe to re-run: a sync is
# idempotent, and the first one only reads from the API (no sheet edits yet).
set -uo pipefail
cd "$(dirname "$0")/.."
DC="sudo docker compose"
# docker compose prints "Container ... Created" lines to stderr; hide those, keep real errors.
quiet() { grep -v -E '^ ?Container |^ ?Network '; }
FAILED=0
step() { printf '\n== %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*"; FAILED=1; }

step "container health"
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8000/api/live >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS http://127.0.0.1:8000/api/live && echo || fail "web app did not come up; see: $DC logs board"

step "login is enforced"
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/board)
if grep -q '^BOARD_PASSWORD=.\+' .env 2>/dev/null; then
  [ "$CODE" = 401 ] && echo "ok: /api/board without credentials -> 401" || fail "expected 401 without credentials, got $CODE"
else
  echo "warning: BOARD_PASSWORD is empty, the board has no login (got $CODE)"
fi

step "can the server reach the real FieldServe API? (response shapes, truncated)"
$DC run --rm --no-deps -T board python3 sync.py --probe 2>&1 | quiet | head -c 1500 || fail "probe failed"

step "one full sync"
if $DC run --rm --no-deps -T board python3 sync.py 2>&1 | quiet | tail -n 3; then :; else fail "sync failed"; fi

step "who each ticket is waiting on"
$DC run --rm --no-deps -T board python3 sheet.py summary 2>&1 | quiet | head -n 40

step "result"
[ "$FAILED" = 0 ] && echo "all checks passed" || { echo "some checks FAILED (see above)"; exit 1; }
