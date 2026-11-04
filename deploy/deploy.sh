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
# Public HTTPS name. sslip.io maps 13-233-251-144.sslip.io to 13.233.251.144, so
# no DNS setup is needed. Derived from an ec2-A-B-C-D hostname; override with
# DEPLOY_DOMAIN=your.domain, or DEPLOY_DOMAIN=none for tunnel-only access.
if [ -z "${DEPLOY_DOMAIN:-}" ]; then
  if [[ "$HOST" =~ ec2-([0-9]+)-([0-9]+)-([0-9]+)-([0-9]+)\. ]]; then
    DEPLOY_DOMAIN="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}-${BASH_REMATCH[4]}.sslip.io"
  elif [[ "$HOST" =~ @([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    DEPLOY_DOMAIN="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}-${BASH_REMATCH[4]}.sslip.io"
  else
    DEPLOY_DOMAIN="none"
  fi
fi
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

# Login. Default is OFF while you are testing: anyone with the URL can then view
# and edit the board. Turn it on with:  BOARD_LOGIN=on deploy/deploy.sh <key.pem>
BOARD_LOGIN="${BOARD_LOGIN:-off}"

if "${SSH[@]}" "test -f ~/$APP_DIR/.env"; then
  echo "==> keeping the existing .env on the server (delete it there to re-enter secrets)"
else
  read -r -s -p "FieldServe API key: " API_KEY; echo
  printf 'FIELDOPS_BASE_URL=%s\nFIELDOPS_API_KEY=%s\nBOARD_USER=board\nBOARD_PASSWORD=\nCONFLICT_POLICY=api\nTRUSTED_EMAIL_DOMAINS=omnimart.example\n' \
    "$API_URL" "$API_KEY" |
    "${SSH[@]}" "umask 077 && cat > ~/$APP_DIR/.env"
  unset API_KEY
fi

if [ "$BOARD_LOGIN" = "on" ]; then
  # Keep a password that already exists; otherwise ask for one (blank = generate).
  if ! "${SSH[@]}" "grep -qE '^BOARD_PASSWORD=.+' ~/$APP_DIR/.env"; then
    read -r -s -p "Board password (blank = generate one): " BOARD_PW; echo
    if [ -z "$BOARD_PW" ]; then
      # head closes the pipe early, which makes tr exit 141; "|| true" keeps pipefail from aborting.
      BOARD_PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24 || true)"
      echo "generated board password (shown once): $BOARD_PW"
    fi
    printf '%s\n' "$BOARD_PW" | "${SSH[@]}" "cd ~/$APP_DIR && read -r PW && sed -i '/^BOARD_PASSWORD=/d' .env && printf 'BOARD_PASSWORD=%s\n' \"\$PW\" >> .env"
    unset BOARD_PW
  else
    echo "==> login stays ON (password already set on the server)"
  fi
else
  "${SSH[@]}" "cd ~/$APP_DIR && sed -i '/^BOARD_PASSWORD=/d' .env && echo 'BOARD_PASSWORD=' >> .env"
  echo "==> TEST MODE: the login is OFF. Anyone with the URL can view and edit this board."
  echo "    Turn it back on any time with:  BOARD_LOGIN=on deploy/deploy.sh $KEY"
fi

# Keep DOMAIN / COMPOSE_PROFILES in the server's .env in step with this run.
if [ "$DEPLOY_DOMAIN" != "none" ]; then
  "${SSH[@]}" "cd ~/$APP_DIR && sed -i '/^DOMAIN=/d;/^COMPOSE_PROFILES=/d' .env && printf 'DOMAIN=%s\nCOMPOSE_PROFILES=tls\n' '$DEPLOY_DOMAIN' >> .env"
else
  "${SSH[@]}" "cd ~/$APP_DIR && sed -i '/^DOMAIN=/d;/^COMPOSE_PROFILES=/d' .env"
fi

echo "==> building and starting"
"${SSH[@]}" "cd ~/$APP_DIR && mkdir -p data && sudo chown -R 10001 data && sudo docker compose up -d --build"

echo "==> verifying (this talks to the REAL FieldServe API from the VPS)"
"${SSH[@]}" "cd ~/$APP_DIR && bash deploy/verify.sh"

if [ "$DEPLOY_DOMAIN" != "none" ]; then
cat <<MSG

Done. Open  https://$DEPLOY_DOMAIN   (test mode: no login unless you deployed with BOARD_LOGIN=on)

If the page does not load, the AWS Security Group must allow inbound TCP 80 and
443 from anywhere (EC2 > Instances > your instance > Security > Edit inbound rules).
Certificates are issued on the first request, which can take up to a minute.

Tunnel alternative (works without opening ports):
  ssh -i $KEY -L 8000:127.0.0.1:8000 $HOST   then   http://localhost:8000
MSG
exit 0
fi
cat <<MSG

Done. The console listens on the server's localhost only. Open it with a tunnel:

  ssh -i $KEY -L 8000:127.0.0.1:8000 $HOST
  then browse http://localhost:8000   (user: board, password: the one above)
MSG
