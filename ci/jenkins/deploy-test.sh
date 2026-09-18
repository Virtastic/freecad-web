#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Ship the built freecad image to the test app server and (re)start it there.
# Run ON the build server (holds freecad:test, can ssh the test host). The image is large (~785 MB,
# the engine + 341 MB preload are baked in), so `docker save | ssh docker load` takes a bit over the
# LAN, but it needs no registry and matches the game-port pattern.
set -euo pipefail
_cfg="$(dirname "$0")/config.env"
# shellcheck disable=SC1090
[ -f "$_cfg" ] && . "$_cfg"
TEST_HOST="${TEST_HOST:?set TEST_HOST in ci/jenkins/config.env}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
TAG="${TAG:-freecad:test}"
NAME="${NAME:-freecad-test}"
PORT="${PORT:-8084}"
SESSION_TAG="${SESSION_TAG:-fcweb-session:test}"
SESSION_NAME="${SESSION_NAME:-fcweb-session-test}"
SESSION_VOL="${SESSION_VOL:-fcweb-session-test}"   # named: sessions survive every redeploy
NET="${NET:-fcweb}"
SMOKE_URL="${SMOKE_URL:-https://freecad.dev.virtastic.app}"
SSH="ssh -i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

echo "==> shipping $TAG and $SESSION_TAG to $TEST_HOST"
docker save "$TAG" "$SESSION_TAG" | $SSH "$TEST_HOST" 'docker load'

echo "==> (re)starting $NAME on :$PORT"
# The event-counter volume (see infra/nginx.conf /t) survives the per-deploy container recreate,
# exactly like the production compose. The edge/ingress routes freecad.dev.virtastic.app -> :$PORT.
# Both containers share a user-defined network so that docker's embedded DNS answers the
# name nginx proxies to. On the default bridge there is no embedded DNS and /share/ would
# 502 forever. The alias is what nginx hardcodes; the container name stays project-scoped so
# nothing else on this host can collide with it.
$SSH "$TEST_HOST" "
  set -e
  docker network create $NET >/dev/null 2>&1 || true
  docker volume create fcweb-events-test >/dev/null 2>&1 || true
  docker volume create $SESSION_VOL >/dev/null 2>&1 || true
  docker rm -f $SESSION_NAME >/dev/null 2>&1 || true
  docker run -d --name $SESSION_NAME --restart unless-stopped \
    --network $NET --network-alias session \
    -v $SESSION_VOL:/data \
    -e FCWEB_PUBLIC_URL=$SMOKE_URL \
    -e FCWEB_SHARE_MAX_GB=5 -e FCWEB_SHARE_MAX_MB=25 \
    $SESSION_TAG >/dev/null
  docker rm -f $NAME >/dev/null 2>&1 || true
  docker run -d --name $NAME --restart unless-stopped --network $NET -p ${PORT}:80 \
    -v fcweb-events-test:/var/log/fcweb $TAG >/dev/null
"

echo "==> health check on the container"
for i in $(seq 1 45); do
  code=$($SSH "$TEST_HOST" "curl -s -o /dev/null -w '%{http_code}' http://localhost:${PORT}/" || echo 000)
  hdr=$($SSH "$TEST_HOST" "curl -s -I http://localhost:${PORT}/ | grep -i cross-origin-opener" || true)
  if [ "$code" = "200" ] && [ -n "$hdr" ]; then
    echo "    $NAME healthy (HTTP $code, cross-origin-isolated) on :$PORT"
    # ...and the session service behind it, or sharing and MCP are dead on arrival
    if $SSH "$TEST_HOST" "curl -fsS http://localhost:${PORT}/share/health" | grep -q '"ok"'; then
      echo "    session service answering through nginx"
      exit 0
    fi
    echo "FATAL: $NAME is up but /share/health does not answer (session container or network)"
    $SSH "$TEST_HOST" "docker logs --tail 30 $SESSION_NAME" || true
    exit 1
  fi
  sleep 2
done
echo "FATAL: $NAME did not become healthy on :$PORT"
$SSH "$TEST_HOST" "docker logs --tail 30 $NAME" || true
exit 1
