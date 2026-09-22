# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Python-dependency installs for the Addon Manager, in the browser build.

Upstream installs an add-on's ``<depend>`` packages by running ``python -m pip install
--target <vendor>`` as a subprocess (addonmanager_dependency_installer.py, _run_pip).
There is no subprocess and no python executable under emscripten, so
``create_pip_call`` raises "Could not locate Python executable on this system" before
pip is even attempted (addonmanager_utilities.py:602, measured on production
2026-09-21). Every add-on with a Python dependency failed at that dialog. The overlay's
``fcweb_am_install._patch_verify_pip`` turned that into a clean "cannot execute pip,
continue anyway?" dialog; this module makes the install succeed instead.

``run_installer`` replaces ``DependencyInstaller.run`` and, per package:

1. If it already imports, report "Requirement already satisfied" and move on.
   (PyYAML, numpy, matplotlib and more ship in the image; the History Workbench's
   PyYAML dependency was one of these.)
2. Otherwise fetch ``/proxy/pypi/simple/<name>/`` (PEP 503), pick the newest wheel
   that is pure Python (``py3-none-any`` or ``py2.py3-none-any``), download it through
   ``/proxy/pyfiles/`` and unzip it into the vendor directory, which lives inside the
   persisted home. Wheels are zips; this is what pip does for the common case.
3. A package that has only platform wheels or only an sdist needs compiled code and
   cannot be installed this way. That is reported as a failure with a sentence that
   says so, not as "pip not found".

Every fetch is an ``async_get`` callback. Nothing in the Addon Manager may block on the
network in this build (addonmanager_fcweb_async, measured 2026-09-03: a blocking call on
the main thread starves the Qt loop that delivers the reply), and the overlay keeps the
DependencyInstaller on the main thread. So ``run_installer`` returns at once and the
chain finishes later by emitting the same ``failure`` / ``finished`` signals the GUI
already listens to.
"""

import importlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
from urllib.request import urlopen, Request

PYPI_SIMPLE = "/proxy/pypi/simple/"
PYFILES_HOST = "files.pythonhosted.org"
PYFILES_PROXY = "/proxy/pyfiles/"
PURE_TAGS = ("py3-none-any", "py2.py3-none-any")

# Distribution name -> importable module, for the packages whose names differ. Anything
# not listed is tried as itself with '-' -> '_'.
IMPORT_NAMES = {
    "pyyaml": "yaml",
    "pillow": "PIL",
    "beautifulsoup4": "bs4",
    "python-dateutil": "dateutil",
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "pyserial": "serial",
    "attrs": "attr",
}


def _norm(name):
    """PEP 503 normalisation: lowercase, runs of -_. collapse to a single -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _split_requirement(req):
    """'PyYAML>=6,<7' -> ('PyYAML', '>=6,<7'). Extras and markers are dropped; the
    Addon Manager passes bare names in practice."""
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$", req)
    if not m:
        return req.strip(), ""
    return m.group(1), m.group(3).strip()


def _already_present(dist):
    mod = IMPORT_NAMES.get(_norm(dist), _norm(dist).replace("-", "_"))
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


_VER_RE = re.compile(r"^(?P<name>[^-]+)-(?P<ver>[^-]+)-(?P<tags>.+)\.whl$")


def _version_key(v):
    # Enough ordering for "newest": any final release beats any pre-release (pip's
    # default without --pre), then the numeric dotted release.
    m = re.match(r"(\d+(?:\.\d+)*)(.*)$", v)
    nums = [int(p) for p in m.group(1).split(".")] if m else [0]
    rest = m.group(2) if m else v
    pre = re.search(r"(a|b|rc|dev)\d*", rest) is not None
    return (0 if pre else 1, nums)


def _pick_wheel_from_page(dist, page):
    """Return ((filename, version, proxy-url), None) for the newest pure-Python wheel on
    an already-fetched PEP 503 page, or (None, reason)."""
    parser = _Links()
    parser.feed(page.decode("utf-8", "replace") if isinstance(page, (bytes, bytearray)) else str(page))
    best = None
    saw_wheel = False
    for href in parser.links:
        clean = href.split("#", 1)[0]
        fname = unquote(clean.rsplit("/", 1)[-1])
        m = _VER_RE.match(fname)
        if not m:
            continue
        saw_wheel = True
        if m.group("tags") not in PURE_TAGS:
            continue
        if best is None or _version_key(m.group("ver")) > _version_key(best[0]):
            best = (m.group("ver"), fname, clean)
    if best is None:
        if saw_wheel:
            return None, ("%s only publishes wheels with compiled code, which this build cannot "
                          "install. Open an issue on github.com/Virtastic/freecad-web and it "
                          "can be added to the image." % dist)
        return None, "%s has no wheels on PyPI; only source distributions." % dist
    ver, fname, href = best
    parts = urlsplit(href)
    if parts.netloc and parts.netloc.lower() != PYFILES_HOST:
        return None, "%s wheel is hosted on %s, which the proxy does not allow." % (dist, parts.netloc)
    url = PYFILES_PROXY + parts.path.lstrip("/") if parts.netloc else href
    return (fname, ver, url), None


def _fetch(url, timeout=60):
    """Desktop-only synchronous GET (self-check, manual use). Never called in the browser."""
    req = Request(url, headers={"User-Agent": "freecad-web addon manager"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _pick_wheel(dist):
    return _pick_wheel_from_page(dist, _fetch(PYPI_SIMPLE + _norm(dist) + "/"))


def _install_wheel(data, target):
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("wheel contains an unsafe path: %s" % name)
        z.extractall(target)
    if target not in sys.path:
        sys.path.append(target)
    importlib.invalidate_caches()


def _completed(args, code, out, err=""):
    return subprocess.CompletedProcess(args, code, out, err)


def run(args):
    """Answer a pip argument list where no network is needed (--version). Installs go
    through run_installer, which is callback-driven."""
    args = list(args)
    if not args or args[0] == "--version":
        return _completed(args, 0, "freecad-web wheel installer (no pip; pure-Python wheels from PyPI)")
    return _completed(args, 1, "", "synchronous pip is not available in the browser: %s" % " ".join(args))


def run_installer(self):
    """Replacement for DependencyInstaller.run() in the browser build. See the module
    docstring. Returns immediately; emits failure/finished later."""
    from addonmanager_fcweb_async import async_get
    import addonmanager_freecad_interface as fci
    import addonmanager_utilities as utils
    try:
        from PySideWrapper import QtCore
    except ImportError:
        from PySide6 import QtCore

    translate = fci.translate
    if self.location:
        target = os.path.join(self.location, "AdditionalPythonPackages")
    else:
        target = utils.get_pip_target_directory()
    required = [p for p in list(self.python_requires) if not p.lower().startswith("pyside")]
    optional = list(self.python_optional)

    def cancelled():
        try:
            return QtCore.QThread.currentThread().isInterruptionRequested()
        except Exception:
            return False

    def finish(ok):
        self.required_succeeded = ok
        if ok and not cancelled():
            try:
                self._install_addons()
                self.finished_successfully = self.required_succeeded
            except RuntimeError as e:
                fci.Console.PrintError(str(e) + "\n")
        self.finished.emit(self.finished_successfully)

    def fail_required(pymod, why):
        fci.Console.PrintError("%s\n" % why)
        self.failure.emit(
            translate("AddonsInstaller", "Installation of Python package {} failed").format(pymod),
            str(why))
        finish(False)

    def install_one(req, on_ok, on_err):
        dist, _spec = _split_requirement(req)
        if _already_present(dist):
            fci.Console.PrintMessage("Requirement already satisfied: %s\n" % dist)
            return on_ok()
        index_url = PYPI_SIMPLE + _norm(dist) + "/"

        def got_index(ok, page):
            if not ok:
                return on_err("could not query PyPI for %s (is the proxy key 'pypi' deployed?)" % dist)
            try:
                pick, why = _pick_wheel_from_page(dist, page)
            except Exception as e:
                return on_err("could not read the PyPI index for %s: %s" % (dist, e))
            if pick is None:
                return on_err(why)
            fname, ver, url = pick

            def got_wheel(ok2, data):
                if not ok2 or not data:
                    return on_err("downloading %s failed" % fname)
                try:
                    _install_wheel(data, target)
                except Exception as e:
                    return on_err("installing %s failed: %s" % (fname, e))
                fci.Console.PrintMessage("Successfully installed %s-%s (%d KB) into %s\n"
                                         % (dist, ver, len(data) // 1024, target))
                on_ok()

            async_get(url, got_wheel, timeout_ms=180000)

        async_get(index_url, got_index, timeout_ms=30000)

    def do_optional(i):
        if i >= len(optional) or cancelled():
            return finish(True)
        req = optional[i]

        def err(why):
            fci.Console.PrintError(translate("AddonsInstaller", "Installation of optional package failed")
                                   + ":\n" + str(why) + "\n")
            do_optional(i + 1)

        install_one(req, lambda: do_optional(i + 1), err)

    def do_required(i):
        if cancelled():
            return finish(False)
        if i >= len(required):
            return do_optional(0)
        req = required[i]
        install_one(req, lambda: do_required(i + 1), lambda why: fail_required(req, why))

    if not required and not optional:
        return finish(True)
    fci.Console.PrintMessage("freecad-web: installing Python dependencies from PyPI wheels "
                             "(required=%s optional=%s)\n" % (required, optional))
    do_required(0)


def fetch_and_install(dist, on_done, target=None):
    """Install one pure-Python distribution outside the Addon Manager's installer flow
    (fcweb_git uses it for dulwich). on_done(ok, why) runs once, on the main thread."""
    from addonmanager_fcweb_async import async_get
    if target is None:
        import addonmanager_utilities as utils
        target = utils.get_pip_target_directory()
    if _already_present(dist):
        return on_done(True, "already present")
    index_url = PYPI_SIMPLE + _norm(dist) + "/"

    def got_index(ok, page):
        if not ok:
            return on_done(False, "could not query PyPI for %s" % dist)
        try:
            pick, why = _pick_wheel_from_page(dist, page)
        except Exception as e:
            return on_done(False, "could not read the PyPI index for %s: %s" % (dist, e))
        if pick is None:
            return on_done(False, why)
        fname, ver, url = pick

        def got_wheel(ok2, data):
            if not ok2 or not data:
                return on_done(False, "downloading %s failed" % fname)
            try:
                _install_wheel(data, target)
            except Exception as e:
                return on_done(False, "installing %s failed: %s" % (fname, e))
            on_done(True, "installed %s-%s (%d KB)" % (dist, ver, len(data) // 1024))

        async_get(url, got_wheel, timeout_ms=180000)

    async_get(index_url, got_index, timeout_ms=30000)


def install_hooks():
    """Route the Addon Manager's dependency installer here. Idempotent."""
    if sys.platform != "emscripten":
        return False
    import addonmanager_dependency_installer as D
    import addonmanager_utilities as U

    # The overlay's earlier _patch_verify_pip made the check fail cleanly (no pip). Now
    # that packages can be installed, the check passes and run() is ours.
    D.DependencyInstaller._verify_pip = lambda self: True
    D.DependencyInstaller.run = run_installer
    # The Python-deps GUI consults get_python_exe to decide whether to offer installs.
    try:
        import addonmanager_freecad_interface as fci
        fci.get_python_exe = lambda: sys.executable or "python3"
    except Exception:
        pass
    # Anything installed on an earlier visit lives in the persisted home; make it
    # importable now rather than after the next install.
    try:
        vendor = U.get_pip_target_directory()
        if os.path.isdir(vendor) and vendor not in sys.path:
            sys.path.append(vendor)
    except Exception:
        pass
    return True


if __name__ == "__main__":
    # Self-check of the parts that need no network: requirement parsing, normalisation,
    # wheel selection from a canned PEP 503 page, safe extraction, and the pip stand-in.
    assert _norm("PyYAML") == "pyyaml" and _norm("scikit_learn") == "scikit-learn"
    assert _split_requirement("PyYAML>=6,<7") == ("PyYAML", ">=6,<7")
    assert _split_requirement("requests[socks]") == ("requests", "")
    page = ('<a href="https://files.pythonhosted.org/p/x-1.0-py3-none-any.whl#sha256=a">x</a>'
            '<a href="https://files.pythonhosted.org/p/x-2.0b1-py3-none-any.whl#sha256=b">x</a>'
            '<a href="https://files.pythonhosted.org/p/x-1.5-cp313-cp313-manylinux_2_17_x86_64.whl">x</a>'
            '<a href="https://files.pythonhosted.org/p/x-1.5.tar.gz">x</a>')
    pick, why = _pick_wheel_from_page("x", page.encode())
    assert why is None and pick[0] == "x-1.0-py3-none-any.whl" and pick[2] == "/proxy/pyfiles/p/x-1.0-py3-none-any.whl", pick
    pick, why = _pick_wheel_from_page("y", b'<a href="https://files.pythonhosted.org/p/y-1.0-cp313-cp313-win_amd64.whl">y</a>')
    assert pick is None and "compiled" in why, why
    pick, why = _pick_wheel_from_page("z", b'<a href="https://evil.example/z-1.0-py3-none-any.whl">z</a>')
    assert pick is None and "proxy does not allow" in why, why
    import tempfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("demo_pkg/__init__.py", "VALUE = 42\n")
        z.writestr("demo_pkg-1.0.dist-info/METADATA", "Name: demo_pkg\n")
    with tempfile.TemporaryDirectory() as d:
        _install_wheel(buf.getvalue(), d)
        assert os.path.exists(os.path.join(d, "demo_pkg", "__init__.py"))
        sys.path.remove(d)
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.py", "")
    try:
        with tempfile.TemporaryDirectory() as d:
            _install_wheel(bad.getvalue(), d)
        raise SystemExit("unsafe path was not rejected")
    except ValueError:
        pass
    assert run(["--version"]).returncode == 0
    assert run(["install", "--target", "/x", "y"]).returncode == 1
    assert _already_present("PyYAML") == (importlib.util.find_spec("yaml") is not None)
    print("fcweb_wheels self-check ok")
