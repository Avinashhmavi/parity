#!/usr/bin/env bash
# Run from YOUR machine (no ssh needed). Checks the public site end to end:
# certificate, login, data, last sync, and the people summary. Read-only.
#
#   deploy/check-live.sh                       # https://13-233-251-144.sslip.io
#   SITE=https://board.example.com deploy/check-live.sh
set -uo pipefail
SITE="${SITE:-https://13-233-251-144.sslip.io}"
USER_NAME="${BOARD_USER:-board}"
read -r -s -p "Board password for $SITE (just press Enter if the login is off): " PW; echo
ok=0; bad=0
pass() { printf '  PASS  %s\n' "$*"; ok=$((ok+1)); }
fail() { printf '  FAIL  %s\n' "$*"; bad=$((bad+1)); }
# The password goes to curl on stdin, never on a command line.
auth() { if [ -n "$PW" ]; then printf 'user = "%s:%s"\n' "$USER_NAME" "$PW"; else printf '\n'; fi; }
get() { auth | curl -sS -m 25 -K - "$SITE$1"; }
code() { auth | curl -sS -m 25 -K - -o /dev/null -w '%{http_code}' "$SITE$1"; }

echo "== $SITE"
[ "$(curl -sS -m 20 -o /dev/null -w '%{http_code}' "$SITE/api/live")" = 200 ] && pass "HTTPS answers with a valid certificate" || fail "site not reachable (is TCP 443 open in the AWS security group?)"
if [ -n "$PW" ]; then
  [ "$(curl -sS -m 20 -o /dev/null -w '%{http_code}' "$SITE/api/board")" = 401 ] && pass "data is locked without a password" || fail "data is NOT locked without a password"
  [ "$(code /api/board)" = 200 ] && pass "the password works" || { fail "the password was rejected"; echo "$ok passed, $bad failed"; exit 1; }
else
  [ "$(code /api/board)" = 200 ] && pass "the board data loads (login is off: test mode)" || { fail "the board data does not load"; echo "$ok passed, $bad failed"; exit 1; }
fi
[ "$(curl -sS -m 20 -o /dev/null -w '%{http_code}' "$SITE/")" = 200 ] && pass "the web page loads" || fail "the web page does not load"

H="$(get /api/health)"; S="$(get /api/summary)"
python3 - "$H" "$S" <<'PY'
import json, sys
h, s = json.loads(sys.argv[1]), json.loads(sys.argv[2])
last = h.get("lastSync") or {}
t = s["totals"]
def line(ok, text): print(("  PASS  " if ok else "  FAIL  ") + text)
line(bool(last.get("ok")), f"last sync succeeded ({last.get('finished_at', 'never')}, {last.get('requests', '?')} requests)")
line(t["tickets"] > 0, f"{t['tickets']} jobs on the board, {t['noise']} ignored as spam/alerts")
line(last.get("errors", 1) == 0, f"no push errors (errors={last.get('errors')}, rejected={last.get('rejected')})")
line(sum(p["pending"] for p in s["workload"]) == t["pending"], "people totals add up to the pending jobs")
print(f"        waiting now: {t['pending']}   with problems: {t['flagged']}   done: {t['done']}")
for p in s["workload"][:6]:
    print(f"        {p['pending']:>5}  {p['person']} ({p['role']})")
sys.exit(0 if last.get("ok") and t["tickets"] > 0 else 1)
PY
[ $? -eq 0 ] && ok=$((ok+3)) || bad=$((bad+1))
echo; echo "$ok checks passed, $bad failed"
[ "$bad" -eq 0 ]
