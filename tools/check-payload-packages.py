# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Assert the preload payload actually contains the Python packages the app needs.

    python tools/check-payload-packages.py gate-serve/FreeCAD.js
    curl -fsS https://host/FreeCAD.js | python tools/check-payload-packages.py -

WHY THIS EXISTS

On 2026-08-26 the live site was found to be serving a build whose preload payload held the
Python standard library and nothing else. numpy, matplotlib, PIL and ifcopenshell were all
absent. FEM could not start, the Addon Manager could not start, and Draft -- a default
workbench -- could not import. It had been live since the 2026-08-25 deploy.

Nothing noticed, because every check that existed asked a question this failure does not
answer:

  * the image built                     -- it did
  * the canary answered HTTP 200        -- it did
  * COOP/COEP headers were right        -- they were
  * the engine URLs were stamped        -- they were
  * FreeCAD.wasm was present            -- it was
  * the app booted and drew a box       -- it did, in 13.0 s

An engine with no Python packages boots perfectly. It simply cannot do anything a user came
for. This looks inside the payload instead of at the wrapper around it.

WHAT IT CAN AND CANNOT SEE

FreeCAD.js does not carry a file list -- the files live in the .data blob. What it does
carry is one `FS_createPath(parent, name)` call per DIRECTORY, so a package's subdirectory
count is readable and a package that was never staged has none at all. Measured on a good
build against the broken live one:

    numpy         529  vs  0
    matplotlib    400  vs  0
    ifcopenshell  572  vs  0
    PIL            97  vs  0
    pivy           46  vs  1

That is not a marginal signal, which is what makes a static check worth having here.

The limit, stated so nobody trusts this further than it goes: a FLAT package -- PySide6 has
no subdirectories -- is invisible to this, and so is a directory tree that was staged empty.
Those need the application to actually import them, which is what `boot-gate.py
--scenario imports` does. This check is the cheap half that can run against any URL in a
second; it is not a replacement for the boot gate.
"""
import io
import re
import sys

# name, minimum subdirectories. The floors sit far below the real counts -- numpy ships 529
# and this asks for 50 -- because the failure being caught is total absence. Pruning junk
# out of a package must not fail a build.
REQUIRED = (
    ('numpy', 50),
    ('matplotlib', 50),
    ('ifcopenshell', 20),
    ('PIL', 20),
    ('pivy', 5),
)

# The mount that third-party packages land on, and a floor for how many top-level packages
# it should hold. The broken build had 3; a good one has dozens.
PKG_MOUNT = '/pyside-pkg'
# 10, not 15. A good build holds 15 -- setting the floor at what a passing build happens to
# have today means the next pruned package fails the release. The broken one held 3.
PKG_MOUNT_MIN = 10

CREATE = re.compile(r'FS_createPath"?\]?\(\s*"([^"]*)"\s*,\s*"([^"]*)"')


def subdirs(text, pkg):
    """Directories created anywhere beneath a package of this name, on any mount."""
    return len(re.findall(r'/(?:pyside-pkg|pylib)/' + re.escape(pkg) + r'[/"]', text))


def main():
    if len(sys.argv) < 2:
        print('usage: check-payload-packages.py <FreeCAD.js|->', file=sys.stderr)
        return 2
    path = sys.argv[1]
    text = (sys.stdin.read() if path == '-'
            else io.open(path, encoding='utf-8', errors='replace').read())

    if 'FS_createPath' not in text:
        print('::error::%s carries no preload manifest, so there is nothing to check. '
              'That is itself wrong for a FreeCAD.js.' % path, file=sys.stderr)
        return 2

    bad = []
    for name, floor in REQUIRED:
        n = subdirs(text, name)
        print('  %-8s %-14s %5d directories (need >= %d)'
              % ('ok' if n >= floor else 'MISSING', name, n, floor))
        if n < floor:
            bad.append('%s (%d)' % (name, n))

    top = sorted({m.group(2) for m in CREATE.finditer(text) if m.group(1) == PKG_MOUNT})
    print('  %-8s %-14s %5d top-level packages (need >= %d)'
          % ('ok' if len(top) >= PKG_MOUNT_MIN else 'MISSING', PKG_MOUNT, len(top),
             PKG_MOUNT_MIN))
    if len(top) < PKG_MOUNT_MIN:
        bad.append('%s holds only %d packages: %s' % (PKG_MOUNT, len(top), ', '.join(top)))

    if bad:
        print('::error::the payload is missing Python packages: %s. A build like this boots '
              'normally and then fails everything a user came for -- FEM, the Addon Manager '
              'and Draft all import these.' % '; '.join(bad), file=sys.stderr)
        return 1

    print('payload carries every required Python package (%s holds %d)'
          % (PKG_MOUNT, len(top)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
