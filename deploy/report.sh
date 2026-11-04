#!/usr/bin/env bash
# Run ON the server (or via: ssh ... 'cd fieldserve-board && bash deploy/report.sh').
# Syncs once, then prints a compact data-quality report: counts and samples, not
# the dataset. Paste the output back to tune the noise and extraction rules.
set -euo pipefail
cd "$(dirname "$0")/.."
DC="sudo docker compose"
$DC run --rm --no-deps -T board python3 sync.py >/dev/null 2>&1 || { echo "sync failed; run deploy/verify.sh" >&2; exit 1; }
$DC run --rm --no-deps -T board python3 sheet.py report 2>&1 | grep -v -E '^ ?Container |^ ?Network '
