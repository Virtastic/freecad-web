# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""The first Python that runs in the browser build, via CPython's own hook.

`site` imports `sitecustomize` from sys.path during interpreter start-up, before FreeCAD's
Mod loop runs any add-on's Init.py/InitGui.py. The page writes this file into the
interpreter's site-packages directory in emscripten's preRun (freecad-gui.html), which is
the only way to get code in ahead of an installed add-on without relinking: the Addon
Manager overlay (fcweb_am_boot) is applied seconds after the GUI is up, and an add-on's
InitGui.py has run by then.

Kept to what MUST precede the Mod loop. Everything else stays in fcweb_am_boot.
"""
import sys

# urllib3 v2 (__init__.py line 208 in 2.8.0) sees sys.platform == "emscripten" and imports
# its Pyodide backend, which needs Pyodide's `js` and `pyodide.ffi`; this build is not
# Pyodide, so `import requests` raised ModuleNotFoundError inside the Lens add-on's
# InitGui.py (measured 2026-09-22). The backend is never used here -- fcweb_requests puts
# requests.Session.send on QtNetwork -- so a no-op module under its name lets urllib3
# import exactly as on a desktop.
if sys.platform == "emscripten" and "urllib3.contrib.emscripten" not in sys.modules:
    import types
    _stub = types.ModuleType("urllib3.contrib.emscripten")
    _stub.inject_into_urllib3 = lambda: None
    _stub.extract_from_urllib3 = lambda: None
    sys.modules["urllib3.contrib.emscripten"] = _stub
    del _stub

# `requests` over the page's synchronous transport, hooked the moment it is imported
# (the Lens add-on calls requests.get from its InitGui.py). fcweb_requests.py sits next
# to this file in site-packages.
if sys.platform == "emscripten":
    try:
        import fcweb_requests
        fcweb_requests.install_import_hook()
    except Exception as _e:
        print("[fcweb] sitecustomize: requests hook not installed: %r" % (_e,))
