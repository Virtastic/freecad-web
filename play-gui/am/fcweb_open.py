# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""`open`, `xdg-open`, `explorer`, `gio open`: "show this in the OS" for the browser build.

The catalogue scan (scratchpad/addon-binaries.py, 2026-09-21) found these to be the
most common thing add-ons shell out to after git: a dozen of them open a URL, a folder
or a file with the desktop's default handler (FreeCAD-Ribbon, BillOfMaterials-WB, addFC,
CfdOF, FreeCAD-Beginner-Assistant among them). There is no desktop here, but there is
a browser: a URL opens in a new tab, a file becomes a download, a folder is refused
with a sentence (a browser has no folder view).

The request travels the way the sharing module talks to the page: a JSON line appended
to a file under /tmp (MEMFS) that the page polls on its 2 s tick and clears. No stdout
marker, nothing blocking, no JS bridge from Python.
"""

import json
import os
import subprocess
import sys
import time

REQ_PATH = "/tmp/fcweb-open.jsonl"
NAMES = {"open", "xdg-open", "explorer", "explorer.exe", "gio", "start", "cmd"}


def _request(kind, target):
    with open(REQ_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "target": target, "t": time.time()}) + "\n")


def open_target(target, cwd=None):
    """Return (returncode, stderr). URLs open in a tab; files download; folders refuse."""
    t = str(target).strip()
    if not t:
        return 2, "open: nothing to open\n"
    if "://" in t or t.startswith("mailto:") or t.startswith("www."):
        _request("url", t if "://" in t or t.startswith("mailto:") else "https://" + t)
        return 0, ""
    path = t if os.path.isabs(t) else os.path.join(cwd or os.getcwd(), t)
    if os.path.isdir(path):
        return 1, ("open: %s is a folder; the browser build has no folder window. The files "
                   "are in the app's own storage, reachable through File > Open.\n" % t)
    if os.path.isfile(path):
        _request("file", path)
        return 0, ""
    return 1, "open: %s: no such file\n" % t


def handle(argv, cwd=None):
    """argv is [open-like-command, ...args]. Returns (code, stdout, stderr) or None if
    this is not an open-style command."""
    name = os.path.basename(str(argv[0])).lower() if argv else ""
    if name not in NAMES:
        return None
    args = [str(a) for a in argv[1:]]
    if name == "gio":
        if args[:1] != ["open"]:
            return 1, "", "gio: only `gio open` is supported in the browser\n"
        args = args[1:]
    if name in ("cmd", "start"):
        # `cmd /c start "" <target>` and `start <target>` are the Windows spellings.
        args = [a for a in args if a not in ("/c", "/C", "start", '""', "")]
    if name == "explorer" or name == "explorer.exe":
        args = [a.lstrip("/") if a.lower().startswith("/select,") else a for a in args]
        args = [a.split(",", 1)[1] if a.lower().startswith("select,") else a for a in args]
    args = [a for a in args if not a.startswith("-")]
    if not args:
        return 2, "", "%s: nothing to open\n" % name
    code, err = open_target(args[-1], cwd)
    return code, "", err


if __name__ == "__main__":
    import tempfile
    REQ_PATH = os.path.join(tempfile.gettempdir(), "fcweb-open-test.jsonl")
    if os.path.exists(REQ_PATH):
        os.remove(REQ_PATH)
    d = tempfile.mkdtemp()
    f = os.path.join(d, "a.txt"); open(f, "w").write("x")
    assert handle(["xdg-open", "https://example.com"]) == (0, "", "")
    assert handle(["open", "www.example.com"])[0] == 0
    assert handle(["explorer", "/select,%s" % f])[0] == 0
    assert handle(["gio", "open", f])[0] == 0
    assert handle(["cmd", "/c", "start", '""', "https://example.com/x"])[0] == 0
    assert handle(["open", d])[0] == 1 and "folder" in handle(["open", d])[2]
    assert handle(["open", os.path.join(d, "nope")])[0] == 1
    assert handle(["gio", "info", f])[0] == 1
    assert handle(["git", "status"]) is None
    rows = [json.loads(l) for l in open(REQ_PATH, encoding="utf-8")]
    kinds = [r["kind"] for r in rows]
    assert kinds == ["url", "url", "file", "file", "url"], kinds
    assert rows[1]["target"] == "https://www.example.com"
    os.remove(REQ_PATH)
    print("fcweb_open self-check ok")
