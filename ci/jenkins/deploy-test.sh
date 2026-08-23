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
SSH="ssh -i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

echo "==> shipping $TAG to $TEST_HOST"
docker save "$TAG" | $SSH "$TEST_HOST" 'docker load'

echo "==> (re)starting $NAME on :$PORT"
# The event-counter volume (see infra/nginx.conf /t) survives the per-deploy container recreate,
# exactly like the production compose. The edge/ingress routes freecad.dev.virtastic.app -> :$PORT.
$SSH "$TEST_HOST" "
  set -e
  docker rm -f $NAME >/dev/null 2>&1 || true
  docker volume create fcweb-events-test >/dev/null 2>&1 || true
  docker run -d --name $NAME --restart unless-stopped -p ${PORT}:80 \
    -v fcweb-events-test:/var/log/fcweb $TAG >/dev/null
"

echo "==> health check on the container"
for i in $(seq 1 45); do
  code=$($SSH "$TEST_HOST" "curl -s -o /dev/null -w '%{http_code}' http://localhost:${PORT}/" || echo 000)
  hdr=$($SSH "$TEST_HOST" "curl -s -I http://localhost:${PORT}/ | grep -i cross-origin-opener" || true)
  if [ "$code" = "200" ] && [ -n "$hdr" ]; then
    echo "    $NAME healthy (HTTP $code, cross-origin-isolated) on :$PORT"
    exit 0
  fi
  sleep 2
done
echo "FATAL: $NAME did not become healthy on :$PORT"
$SSH "$TEST_HOST" "docker logs --tail 30 $NAME" || true
exit 1
