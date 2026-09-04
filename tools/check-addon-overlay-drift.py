#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Fail when the Addon Manager overlay's forks have gone stale.

play-gui/am/ forks two upstream worker modules and patches the methods of a third. None of
that is visible to the type checker or the test suite: if FreeCAD changes the original,
the overlay carries on shadowing it with the old logic and the Addon Manager silently
behaves like the previous release. There is no error to notice.

So the upstream files the overlay was derived from are pinned by hash in
play-gui/am/UPSTREAM.txt, and this compares them against the vendored tree.

    python3 tools/check-addon-overlay-drift.py [deps/src/freecad]

Exits non-zero if a pinned file has changed or is missing. When it fires, re-derive the
fork against the new upstream and update the hash in the same commit -- do not just bump
the hash, which converts a real warning into a silent regression.
"""
import hashlib
import os
import sys

PINS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "play-gui", "am", "UPSTREAM.txt")


def read_pins(path):
    pins = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                print("malformed line in %s: %r" % (path, line), file=sys.stderr)
                return None
            pins.append((parts[0], parts[1].strip()))
    return pins


def main(argv):
    tree = argv[1] if len(argv) > 1 else "deps/src/freecad"
    pins = read_pins(PINS)
    if pins is None:
        return 2
    if not os.path.isdir(tree):
        # Not an error: the vendored source is gitignored and absent on most machines.
        print("skip: %s is not present, nothing to compare against" % tree)
        return 0

    bad = []
    for want, rel in pins:
        path = os.path.join(tree, rel)
        if not os.path.isfile(path):
            bad.append((rel, "missing from the tree", want, "-"))
            continue
        with open(path, "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()
        if got != want:
            bad.append((rel, "changed upstream", want, got))

    if not bad:
        print("addon overlay: %d pinned upstream file(s) unchanged" % len(pins))
        return 0

    print("addon overlay is derived from files that have moved:", file=sys.stderr)
    for rel, why, want, got in bad:
        print("  %s -- %s" % (rel, why), file=sys.stderr)
        print("      pinned: %s" % want, file=sys.stderr)
        print("      tree:   %s" % got, file=sys.stderr)
    print("", file=sys.stderr)
    print("Re-derive the fork in play-gui/am/ against the new upstream, then update", file=sys.stderr)
    print("play-gui/am/UPSTREAM.txt in the same commit.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
