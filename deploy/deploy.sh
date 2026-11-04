#!/usr/bin/env bash
# Ship the committed repo to a VPS and (re)start the stack there.
#
#   deploy/deploy.sh ~/keys/test.pem                 # uses DEPLOY_HOST below
#   DEPLOY_HOST=ubuntu@1.2.3.4 deploy/deploy.sh key.pem
#
# Run it from your own machine. It prompts for the FieldServe API key and a
# board password and writes them to .env ON THE SERVER over ssh stdin: they are
# never put on a command line, in shell history, or in the repo.
set -euo pipefail

KEY="${1:?usage: deploy/deploy.sh <private-key.pem>   e.g. deploy/deploy.sh ~/Downloads/test.pem}"
KEY="${KEY/#\~/$HOME}"  # tolerate a quoted ~ that the shell did not expand
HOST="${DEPLOY_HOST:-ubuntu@ec2-13-233-251-144.ap-south-1.compute.amazonaws.com}"
APP_DIR="${APP_DIR:-fieldserve-board}"
API_URL="${FIELDOPS_BASE_URL:-http://13.233.55.184:8377}"

[ -f "$KEY" ] || { echo "key file not found: $KEY" >&2; exit 1; }
chmod 400 "$KEY"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 "$HOST")

# Work from the repo root no matter where the script was started from.
cd "$(dirname "$0")/.."
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "note: uncommitted changes are NOT deployed (git archive ships HEAD only)" >&2
fi

echo "==> connecting to $HOST"
"${SSH[@]}" 'echo "connected as $(whoami) on $(uname -sr)"'

echo "==> installing Docker if needed"
"${SSH[@]}" 'command -v docker >/dev/null || { curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker "$USER"; }; sudo docker --version; sudo docker compose version'

echo "==> uploading $(git rev-parse --short HEAD)"
"${SSH[@]}" "mkdir -p ~/$APP_DIR"
git archive --format=tar HEAD | "${SSH[@]}" "tar -x -C ~/$APP_DIR"

if "${SSH[@]}" "test -f ~/$APP_DIR/.env"; then
  echo "==> keeping the existing .env on the server (delete it there to re-enter secrets)"
else
  read -r -s -p "FieldServe API key: " API_KEY; echo
  read -r -s -p "Board password (blank = generate one): " BOARD_PW; echo
  if [ -z "$BOARD_PW" ]; then
    # head closes the pipe early, which makes tr exit 141; "|| true" keeps pipefail from aborting.
    BOARD_PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24 || true)"
    echo "generated board password (shown once): $BOARD_PW"
  fi
  printf 'FIELDOPS_BASE_URL=%s\nFIELDOPS_API_KEY=%s\nBOARD_USER=board\nBOARD_PASSWORD=%s\nCONFLICT_POLICY=api\nTRUSTED_EMAIL_DOMAINS=omnimart.example\n' \
    "$API_URL" "$API_KEY" "$BOARD_PW" |
    "${SSH[@]}" "umask 077 && cat > ~/$APP_DIR/.env"
  unset API_KEY BOARD_PW
fi

echo "==> building and starting"
"${SSH[@]}" "cd ~/$APP_DIR && mkdir -p data && sudo chown -R 10001 data && sudo docker compose up -d --build"

echo "==> verifying (this talks to the REAL FieldServe API from the VPS)"
"${SSH[@]}" "cd ~/$APP_DIR && bash deploy/verify.sh"

cat <<MSG

Done. The console listens on the server's localhost only. Open it with a tunnel:

  ssh -i $KEY -L 8000:127.0.0.1:8000 $HOST
  then browse http://localhost:8000   (user: board, password: the one above)
MSG
