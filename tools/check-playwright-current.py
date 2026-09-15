#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Fail when a newer Playwright image exists, because a workaround is waiting on one.

    python3 tools/check-playwright-current.py

tools/boot-gate.py tolerates ONE renderer death per scenario. That tolerance is not about
this build: the box's kernel log records the same segfault over and over, every one of them
at the same instruction offset inside chrome-headless-shell --

    chrome-headless[810541]: segfault at 377e0899d000 ip 000060312b605554 error 4
      in chrome-headless-shell[4264554,603128e67000+9a6d000]
    ip - VMA base = 0x279E554, identical across every crash

-- and disassembling that address gives a conservative pointer scan walking up a thread
stack in 8-byte steps and reading one page past the end of the mapping. Our wasm is
JIT-compiled into anonymous memory and cannot land on a stable ELF offset, so it is the
browser, and Playwright v1.62.0-noble was the newest image published when this was written.

The danger is not the tolerance. It is that the tolerance OUTLIVES its cause: Chromium gets
fixed, nobody notices, and the gate quietly keeps absorbing renderer deaths forever --
including any this build eventually causes itself. So this fails the moment a newer image
exists, which is the moment to bump the pin, re-run the gate, and DELETE the retry.

Network failures are not build failures: if the registry cannot be reached this reports and
exits 0. It is a reminder, not a dependency.
"""
import json
import re
import sys
import urllib.error
import urllib.request

TAGS_URL = 'https://mcr.microsoft.com/v2/playwright/python/tags/list'
PINNED_IN = '.github/workflows/link-freecad.yml'
TAG_RE = re.compile(r'^v(\d+)\.(\d+)\.(\d+)-noble$')


def version(tag):
    m = TAG_RE.match(tag)
    return tuple(int(g) for g in m.groups()) if m else None


def pinned_tag():
    """The tag the gate actually runs, read from the workflow rather than duplicated."""
    with open(PINNED_IN, encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    found = set(re.findall(r'mcr\.microsoft\.com/playwright/python:(v[\d.]+-noble)', text))
    if not found:
        print('!! no playwright image pin found in %s -- has the gate moved?' % PINNED_IN,
              file=sys.stderr)
        sys.exit(1)
    if len(found) > 1:
        print('!! %s pins more than one playwright image: %s' % (PINNED_IN, sorted(found)),
              file=sys.stderr)
        sys.exit(1)
    return found.pop()


def main():
    pin = pinned_tag()
    print('pinned: %s (from %s)' % (pin, PINNED_IN))
    if version(pin) is None:
        print('!! cannot parse %r' % pin, file=sys.stderr)
        return 1

    try:
        with urllib.request.urlopen(TAGS_URL, timeout=30) as resp:
            tags = json.load(resp).get('tags', [])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # A reminder must not become a dependency: an unreachable registry says nothing
        # about this build.
        print('   registry unreachable (%s) -- skipping, this is not a build failure'
              % type(exc).__name__)
        return 0

    releases = sorted((v for v in (version(t) for t in tags) if v))
    if not releases:
        print('   no -noble release tags returned -- skipping')
        return 0
    newest = releases[-1]
    print('newest published: v%d.%d.%d-noble (%d release tags)'
          % (newest + (len(releases),)))

    if newest <= version(pin):
        print('   up to date; the renderer-death tolerance in tools/boot-gate.py still has '
              'no browser to move to')
        return 0

    print('::error::a newer Playwright image exists: v%d.%d.%d-noble (pinned %s). '
          'tools/boot-gate.py tolerates one renderer death per scenario ONLY because there '
          'was no newer browser -- the crash is a Chromium segfault at a fixed instruction '
          'offset, not this build. Bump the pin (and the playwright== pip pin beside it), '
          're-run the gate, and if the deaths are gone DELETE the retry in run_scenario. If '
          'they are not gone, update this message with what you measured.'
          % (newest + (pin,)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
