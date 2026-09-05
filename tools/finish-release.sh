#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Wait for a link run, check its gate, and publish it as the latest release.
#
#     bash tools/finish-release.sh <run-id> [tag]
#     bash tools/finish-release.sh 32946598073 build-20260826-fem
#
# Everything from "the runner came back" to "there is a release ready to deploy", without
# anyone watching a queue. It does NOT deploy: production is a separate, deliberate act
# (git push origin main:ovhcloud), and this script prints that command rather than running
# it.
#
# WHY THIS EXISTS
#
# The last stretch of this release is mechanical and slow -- a ~90 minute link, a gate, a
# download, a release -- and it has repeatedly been interrupted by something unrelated: a
# runner agent dying, a laptop sleeping, a session ending. Each interruption cost a whole
# cycle because the next person had to work out where it had got to. One command, one exit
# code, and the state is in the log.
set -uo pipefail
cd "$(dirname "$0")/.."

RUN="${1:?run id -- the link run to wait for}"
TAG="${2:-build-$(date -u +%Y%m%d)-fem}"

say() { printf '%s  %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

say "waiting for link run $RUN"
last=""
while :; do
    read -r status conclusion < <(gh run view "$RUN" --json status,conclusion \
        --jq '"\(.status) \(.conclusion // "-")"' 2>/dev/null || echo "unknown -")
    step="$(gh api "repos/{owner}/{repo}/actions/runs/$RUN/jobs" \
        --jq '.jobs[].steps[]|select(.status=="in_progress")|.name' 2>/dev/null | head -1)"
    line="$status/$conclusion ${step:+-- $step}"
    [ "$line" != "$last" ] && { say "  $line"; last="$line"; }
    case "$status" in
        completed) break ;;
        unknown)   say "  cannot read the run -- is the id right?"; exit 2 ;;
    esac
    sleep 60
done

if [ "$conclusion" != "success" ]; then
    say "the link did NOT pass ($conclusion). What failed:"
    gh api "repos/{owner}/{repo}/actions/runs/$RUN/jobs" \
        --jq '.jobs[].steps[]|select(.conclusion=="failure")|"    \(.number) \(.name)"' 2>/dev/null
    say "the gate output, if it got that far:"
    gh run view "$RUN" --log-failed 2>/dev/null         | grep -E '==>|::error' | grep -v '36;1m'         | sed 's/^.*[0-9]Z //' | sed 's/^/    /' | head -30
    say "nothing published. Fix the failure and re-run the link."
    exit 1
fi

say "link passed. The gate said:"
gh run view "$RUN" --log 2>/dev/null | grep -E '==> ' | grep -v '36;1m'     | sed 's/^.*==> /    /' | head -30

say "publishing $TAG"
bash tools/publish-release.sh "$RUN" "$TAG" || { say "publish failed"; exit 1; }

say "released $TAG. Production is a separate step, on purpose:"
say "    ci/jenkins/smoke-test.sh http://192.168.1.137:8084   # after the Jenkins deploy"
say "    git push origin main:ovhcloud                        # then production"
say "and once it is live, check it from outside:"
say "    bash ci/jenkins/smoke-test.sh https://freecad.virtastic.app"
say "    python3 tools/boot-gate.py --base-url https://freecad.virtastic.app --scenario all"
