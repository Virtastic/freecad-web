#!/bin/sh
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
# freecad-web one-command install. Docker is the only thing you need -- no Python, no
# Node, no build tools. Run it from a clone, or download it on its own and it will fetch
# what it needs.
#
#   ./setup.sh              pull the prebuilt image (fast), falling back to a local build
#   ./setup.sh --build      always build locally from the release artifacts (~445 MB)
#   ./setup.sh --port 9000  serve on a different port
#   ./setup.sh --ref dev    take the source tree from a branch, not the release tag
#
# POSIX sh on purpose: this is the first thing a stranger runs, and it must not depend on
# bash being present or on any particular bash version (macOS still ships 3.2).

set -eu

REPO="${FCWEB_REPO:-Virtastic/freecad-web}"
RELEASE="${FCWEB_RELEASE:-v1.0.0}"
IMAGE="${FCWEB_IMAGE:-ghcr.io/virtastic/freecad-web:1.0.0}"
PORT="${FCWEB_PORT:-8080}"
MODE=auto
# Which source tree to fetch, which is not always the release being installed. They
# differ when running a newer installer against an older engine release -- and they had
# to differ to test the standalone path before the first release that contains it.
REF=""

ASSETS="FreeCAD.js FreeCAD.wasm FreeCAD.data gmsh.js gmsh.wasm ccx.js ccx.wasm"
DOCKER_URL="https://docs.docker.com/get-started/get-docker/"

say()  { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf '\nFATAL: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '5,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --build)      MODE=build ;;
        --pull)       MODE=pull ;;
        --port)       PORT="${2:?--port needs a number}"; shift ;;
        --tag)        RELEASE="${2:?--tag needs a release tag}"; shift ;;
        --ref)        REF="${2:?--ref needs a branch or tag}"; shift ;;
        -h|--help)    usage ;;
        *)            die "unknown option: $1  (try --help)" ;;
    esac
    shift
done

# --------------------------------------------------------------------------------------
# 1. Docker preflight.
#
# Everything here runs before a single byte is downloaded. `docker info` rather than
# `docker --version` is the important choice: the CLI answers --version on its own, so it
# succeeds with the daemon stopped, with Docker Desktop not started, and for a Linux user
# who is not in the docker group. Only `docker info` is a real round trip to the daemon.
# --------------------------------------------------------------------------------------
preflight() {
    step "Checking Docker"

    command -v docker >/dev/null 2>&1 || die "Docker is not installed (no 'docker' on PATH).
       freecad-web runs entirely inside a container -- Docker is all you need.
       Install: $DOCKER_URL
       (Windows/macOS: Docker Desktop.  Linux: Docker Engine + the compose plugin.)"

    info=$(docker info --format '{{.ServerVersion}}|{{.OSType}}|{{.DockerRootDir}}' 2>/dev/null) || die \
"Docker is installed but the daemon is not reachable.
       Windows/macOS: start Docker Desktop, wait for 'Engine running', then re-run.
       Linux: sudo systemctl start docker
              -- if that says 'permission denied', add yourself to the docker group:
                 sudo usermod -aG docker \"\$USER\"    (then log out and back in)"

    ver=${info%%|*}
    rest=${info#*|}
    ostype=${rest%%|*}
    droot=${rest#*|}

    # Major number only. 20.10 is the sole 20.x release, so ">= 20" is exact -- and it
    # avoids sort -V, which BSD/macOS sort lacked until recently.
    case "$ver" in
        [0-9]*)
            major=${ver%%.*}
            [ "$major" -ge 20 ] 2>/dev/null || die \
"Docker engine 20.10 or newer is required (found $ver).
       Upgrade: https://docs.docker.com/engine/install/"
            ;;
        *)  warn "unrecognised Docker version string '$ver' -- continuing anyway." ;;
    esac

    if ! docker compose version --short >/dev/null 2>&1; then
        if command -v docker-compose >/dev/null 2>&1; then
            die "You have the legacy 'docker-compose' (v1). This needs Compose V2, invoked
       as 'docker compose' -- a space, not a hyphen. Compose v1 is end-of-life.
       Install: https://docs.docker.com/compose/install/linux/"
        fi
        die "The Docker Compose V2 plugin is missing ('docker compose' not recognised).
       Install: https://docs.docker.com/compose/install/"
    fi

    # The image is Linux-based. Checking unconditionally costs nothing on Linux, where
    # OSType is trivially 'linux', and saves a baffling failure on Windows.
    [ "$ostype" = "linux" ] || die \
"Docker is in Windows container mode; this image is Linux-based.
       Right-click the Docker whale in the system tray -> 'Switch to Linux containers...',
       wait for the engine to restart, then re-run this script."

    # Disk is a WARNING, never fatal. On Docker Desktop (macOS) and WSL2, DockerRootDir is
    # a path inside the VM that does not exist on the host, so any host-side df is a proxy
    # measurement. A false FATAL would block a perfectly capable machine; a false pass just
    # costs a build that fails with this number already printed above it.
    dir="$droot"
    [ -d "$dir" ] || dir="$HOME"
    free=$(df -Pk "$dir" 2>/dev/null | awk 'NR==2 {print int($4/1048576)}') || free=""
    case "$free" in
        ''|*[!0-9]*) : ;;
        *) [ "$free" -ge 10 ] || warn "only ${free} GiB free on the volume holding Docker's storage.
         The image is ~1.1 GB and a local build needs roughly 5 GiB of working space.
         If you hit 'no space left on device', try: docker system prune -a" ;;
    esac

    say "  Docker $ver, compose $(docker compose version --short), $ostype containers${free:+, ${free} GiB free}"

    case "$(uname -m 2>/dev/null || echo unknown)" in
        arm64|aarch64)
            if [ "$MODE" != build ]; then warn \
"this is an arm64 machine and the prebuilt image is amd64; it will run under emulation.
         For a native image, re-run with --build."; fi ;;
    esac
}

# --------------------------------------------------------------------------------------
# 2. Source tree. Running from a clone uses it in place; running standalone fetches the
#    tag tarball, which is only ~3.4 MB (the big artifacts are not in git).
# --------------------------------------------------------------------------------------
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

resolve_tree() {
    if [ -f "$here/infra/Dockerfile" ] && [ -f "$here/docker-compose.yml" ]; then
        TREE="$here"
        step "Using the checkout at $TREE"
        return
    fi
    [ -n "$REF" ] || REF="$RELEASE"
    TREE="$PWD/freecad-web-${REF}"
    step "Fetching the freecad-web $REF source (~3.4 MB) into $TREE"
    if [ -f "$TREE/infra/Dockerfile" ]; then
        say "  already present, reusing it"
        return
    fi
    mkdir -p "$TREE"
    url="https://github.com/$REPO/archive/$REF.tar.gz"
    if ! curl -fL --retry 3 "$url" 2>/dev/null | tar xz --strip-components=1 -C "$TREE"; then
        # Same private-repo fallback as the assets below: gh can reach a tarball that
        # anonymous curl cannot. Not a path an end user takes.
        if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
            say "  (public download failed; retrying via authenticated gh)"
            gh api "/repos/$REPO/tarball/$REF" 2>/dev/null \
                | tar xz --strip-components=1 -C "$TREE" \
                || die "could not download the $REF source via gh either"
        else
            die "could not download $url
       Check the release tag exists and that you have network access.
       If the repository is not public yet, install the GitHub CLI and run 'gh auth login'."
        fi
    fi
    [ -f "$TREE/infra/Dockerfile" ] || die "the downloaded archive is missing infra/Dockerfile"
}

# --------------------------------------------------------------------------------------
# 3. The engine artifacts, for a local build. 445 MB across seven files, fetched from the
#    release. -C - resumes a partial download rather than restarting it.
# --------------------------------------------------------------------------------------
fetch_assets() {
    step "Downloading the engine artifacts (~445 MB) -- this is the slow part"
    mkdir -p "$TREE/play-gui"
    for name in $ASSETS; do
        out="$TREE/play-gui/$name"
        url="https://github.com/$REPO/releases/download/$RELEASE/$name"

        # "It exists and is non-empty" is not the same as "it is the whole file". A
        # download interrupted at 90% leaves something that looks fine here and produces
        # an image that is broken in a way nothing downstream checks. Ask the server how
        # big the file should be and compare; -C - then resumes rather than restarting.
        want=""
        if [ -s "$out" ]; then
            want=$(curl -fsSIL --max-time 30 "$url" 2>/dev/null \
                   | awk 'tolower($1) == "content-length:" { print $2 }' | tr -d "\\r" | tail -1)
            have=$(wc -c < "$out" | tr -d " ")
            case "$want" in
                ''|*[!0-9]*) say "  have    $name (could not confirm size)"; continue ;;
                *) if [ "$have" = "$want" ]; then say "  have    $name"; continue; fi
                   say "  resume  $name ($have of $want bytes)" ;;
            esac
        else
            say "  fetch   $name"
        fi
        if ! curl -fL --retry 3 -C - -# -o "$out" "$url"; then
            # Private-repo fallback, and how a maintainer tests this before the repo is
            # public. Not a path an end user ever takes.
            if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
                say "  (public download failed; retrying via authenticated gh)"
                gh release download "$RELEASE" -R "$REPO" -p "$name" -D "$TREE/play-gui" --clobber \
                    || die "could not download $name"
            else
                rm -f "$out"
                die "could not download $name from $url
       If the release is not public yet, install the GitHub CLI and run 'gh auth login'."
            fi
        fi
    done
}

# --------------------------------------------------------------------------------------
# 4. Start it. --wait blocks on the image's own HEALTHCHECK and returns non-zero if the
#    container goes unhealthy, so there is no polling loop to write here. The timeout is
#    chosen against that healthcheck's timing (start-period 10s, interval 60s, retries 3
#    => unhealthy at ~190s); anything shorter reports a less useful "timed out".
# --------------------------------------------------------------------------------------
start() {
    cd "$TREE"
    FCWEB_PORT="$PORT" FCWEB_IMAGE="$IMAGE" \
        docker compose up -d --wait --wait-timeout 240 "$@" || {
            say ""
            say "The container did not come up healthy. Last 40 log lines:"
            FCWEB_PORT="$PORT" FCWEB_IMAGE="$IMAGE" docker compose logs --tail 40 || true
            die "startup failed."
        }
}

# --------------------------------------------------------------------------------------
# 5. Prove it works rather than asserting it. COOP/COEP are not cosmetic: without
#    cross-origin isolation SharedArrayBuffer is unavailable and the engine never boots,
#    which looks exactly like a broken install.
# --------------------------------------------------------------------------------------
verify() {
    step "Verifying"
    base="http://localhost:$PORT"
    if command -v bash >/dev/null 2>&1 && [ -x "$TREE/ci/jenkins/smoke-test.sh" ]; then
        bash "$TREE/ci/jenkins/smoke-test.sh" "$base" || die "the server is up but is not serving correctly (see above)."
        return
    fi
    hdr=$(curl -fsS -D - -o /dev/null "$base/" 2>/dev/null) || die "no HTTP 200 from $base/"
    printf '%s' "$hdr" | grep -qi 'cross-origin-opener-policy: *same-origin' \
        || die "the COOP header is missing -- the engine cannot start without cross-origin isolation."
    printf '%s' "$hdr" | grep -qi 'cross-origin-embedder-policy: *require-corp' \
        || die "the COEP header is missing -- the engine cannot start without cross-origin isolation."
    for f in FreeCAD.js FreeCAD.wasm FreeCAD.data legal.html; do
        curl -fsS -o /dev/null -I "$base/$f" || die "$f is not being served"
    done
    say "  200 OK, COOP + COEP present, engine assets served"
}

# --------------------------------------------------------------------------------------

preflight
resolve_tree

built=no
if [ "$MODE" = build ]; then
    fetch_assets
    step "Building the image locally (a few minutes -- it compresses 340 MB of engine data)"
    start --build
    built=yes
else
    step "Pulling $IMAGE"
    if docker pull "$IMAGE"; then
        start --no-build
    elif [ "$MODE" = pull ]; then
        die "could not pull $IMAGE and --pull was requested."
    else
        warn "could not pull $IMAGE -- falling back to building it locally.
         (If the package is not public yet, this is expected.)"
        fetch_assets
        step "Building the image locally (a few minutes)"
        start --build
        built=yes
    fi
fi

verify

cat <<EOF

  freecad-web is running:   http://localhost:$PORT/

  Open it in Chrome or Edge 137+ (it needs JSPI, SharedArrayBuffer and WebGL2).
  Use localhost, not this machine's LAN IP -- the engine only starts on a secure context.

  Stop it:     cd $TREE && docker compose down
  Start again: cd $TREE && docker compose up -d
EOF
if [ "$built" = yes ]; then say "  Built locally from release $RELEASE."; fi
exit 0
