#!/usr/bin/env bash
# Run ON the server. Verifies the WRITE path against the real API: temporarily
# changes ONE ticket (document, status, engineer, both-sides-at-once, conflict),
# asserts the API took each change, then restores the ticket.
#
#   bash deploy/live-check.sh            # picks a ticket for you
#   bash deploy/live-check.sh 195765     # use a specific ticket id
set -euo pipefail
cd "$(dirname "$0")/.."
ARGS=(--yes)
[ -n "${1:-}" ] && ARGS+=(--ticket "$1")
sudo docker compose run --rm --no-deps -T board python3 -m fieldserve_board.devtools.live_check "${ARGS[@]}" 2>&1 | grep -v -E '^ ?Container |^ ?Network '
