#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Embed the dialog-shim sources into freecad-gui.html as base64.

The two shims run inside the wasm CPython, so they have to reach it as a string in the
page. They were previously maintained AS base64 -- the JSPI one had no source file at all,
and the comment beside it pointed at the other shim's file. Editing a dialog meant
hand-decoding, editing, and re-encoding a blob, which is exactly why a stub that broke
every macro prompt sat there unnoticed.

  play-gui/wasm_dialog_shim_jspi.py  -> the `if(window.FC_JSPI)` branch   (the shipped one)
  play-gui/wasm_dialog_shim.py       -> the `if(!window.FC_JSPI)` branch  (Asyncify fallback)

Run after editing either file, then commit both the .py and the regenerated .html:

    python3 tools/gen-dialog-shims.py

Idempotent. Verifies the payload round-trips before writing, and refuses to write a change
that does not decode back to the source byte for byte.
"""
import base64
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "play-gui" / "freecad-gui.html"

# (source file, regex locating that branch's b64 literal)
SHIMS = [
    (ROOT / "play-gui" / "wasm_dialog_shim_jspi.py",
     re.compile(r"(if\(window\.FC_JSPI\)\{.*?_b64\.b64decode\(')([A-Za-z0-9+/=]+)(')", re.S)),
    (ROOT / "play-gui" / "wasm_dialog_shim.py",
     re.compile(r"(if\(!window\.FC_JSPI\)\{.*?_b64\.b64decode\(')([A-Za-z0-9+/=]+)(')", re.S)),
]


def main() -> int:
    html = HTML.read_text(encoding="utf-8", errors="surrogateescape")
    original = html
    changed = []

    for src_path, pattern in SHIMS:
        if not src_path.exists():
            print("ERROR: missing %s" % src_path, file=sys.stderr)
            return 1
        # The wasm side decodes as UTF-8, so encode from UTF-8 bytes, and normalise CRLF:
        # a stray \r inside the payload becomes a syntax error in the embedded python.
        raw = src_path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")

        if base64.b64decode(b64) != raw:
            print("ERROR: %s did not round-trip" % src_path.name, file=sys.stderr)
            return 1

        m = pattern.search(html)
        if not m:
            print("ERROR: could not locate the branch for %s in freecad-gui.html"
                  % src_path.name, file=sys.stderr)
            return 1

        if m.group(2) == b64:
            print("  unchanged  %s" % src_path.name)
            continue

        html = html[:m.start(2)] + b64 + html[m.end(2):]
        changed.append(src_path.name)
        print("  embedded   %s (%d bytes -> %d b64)" % (src_path.name, len(raw), len(b64)))

    if not changed:
        print("nothing to do")
        return 0

    # Re-extract from the FINAL text and compare against source, so a bad offset or a
    # clobbered neighbouring payload is caught here rather than at boot in a user's tab.
    for src_path, pattern in SHIMS:
        m = pattern.search(html)
        want = src_path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
        if not m or base64.b64decode(m.group(2)) != want:
            print("ERROR: verification failed for %s -- not writing" % src_path.name,
                  file=sys.stderr)
            return 1

    HTML.write_text(html, encoding="utf-8", errors="surrogateescape", newline="")
    print("updated %s (%s)" % (HTML.name, ", ".join(changed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
