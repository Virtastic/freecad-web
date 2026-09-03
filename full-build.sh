#!/bin/sh
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
# Clone freecad-web and build the deployable container from that clone, end to end.
# Takes roughly 10-15 minutes, almost all of it downloading ~445 MB of engine artifacts
# and compressing them into the image. You need git and Docker; nothing else.
#
#   ./full-build.sh                    clone into ./freecad-web and build
#   ./full-build.sh --port 9000        ... on a different port
#   ./full-build.sh --dir /opt/fcweb   ... into a different directory
#
# WHAT THIS IS NOT: it does not compile the WebAssembly engine from source. That is a
# separate ~7-9 hour job needing ~100 GB of disk and 16+ GB of RAM, spread across five CI
# lanes (Qt, OCCT, VTK, CPython, PySide, FreeCAD itself), and it is documented in
# BUILD-WEH.md rather than scripted -- three pieces of it are not yet automated at all.
# This script builds the container that ships the already-compiled engine.

set -eu

REPO="${FCWEB_REPO:-Virtastic/freecad-web}"
RELEASE="${FCWEB_RELEASE:-v1.0.0}"
DIR=""

die() { printf '\nFATAL: %s\n' "$*" >&2; exit 1; }

rest=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dir)  DIR="${2:?--dir needs a path}"; shift ;;
        --tag)  RELEASE="${2:?--tag needs a release tag}"; shift ;;
        -h|--help) sed -n '5,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        # Everything else is for setup.sh (--port, --pull, ...); pass it straight through.
        *) rest="$rest $1" ;;
    esac
    shift
done

[ -n "$DIR" ] || DIR="$PWD/freecad-web"

command -v git >/dev/null 2>&1 || die "git is not installed.
       Install it from https://git-scm.com/downloads, or use setup.sh instead --
       it needs only Docker and downloads a source tarball rather than cloning."

if [ -d "$DIR/.git" ]; then
    printf '\n==> Reusing the existing clone at %s\n' "$DIR"
    git -C "$DIR" fetch --depth 1 origin "refs/tags/$RELEASE:refs/tags/$RELEASE" 2>/dev/null || true
    git -C "$DIR" checkout -q "$RELEASE" || die "could not check out $RELEASE in $DIR"
else
    printf '\n==> Cloning %s at %s into %s\n' "$REPO" "$RELEASE" "$DIR"
    git clone --depth 1 --branch "$RELEASE" "https://github.com/$REPO.git" "$DIR" \
        || die "clone failed. Check the tag $RELEASE exists and that you have network access."
fi

[ -x "$DIR/setup.sh" ] || chmod +x "$DIR/setup.sh" 2>/dev/null || true

# --build, not the default pull: the point of this script is to build from the clone.
# shellcheck disable=SC2086
exec sh "$DIR/setup.sh" --build --tag "$RELEASE" $rest
