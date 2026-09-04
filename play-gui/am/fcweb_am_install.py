# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Make the Addon Manager's install and uninstall paths work in the browser build.

Two changes, both applied to classes rather than modules, because the GUI builds a fresh
installer per operation and a class patch reaches every one of them:

1. moveToThread becomes a no-op. The GUI still creates its QThread and calls start(); with
   the worker's affinity left on the main thread, `started -> run` resolves to a queued
   call delivered by the main event loop, and the thread spins an empty exec() and quits.
   This is required, not cosmetic: CPython here aborts outright the moment Python runs on
   a Qt worker thread (Fatal Python error: PyGILState_Release).

2. The ZIP download stops blocking. Upstream downloads inside
   _run_zip_downloader_in_event_loop, which spins processEvents() until the reply lands.
   On the main thread that is a frozen tab, because the event loop it is blocking is the
   very thing that delivers the reply. Instead the archive is fetched with the overlay's
   callback-based async_get BEFORE run() does its work, and run() is then re-entered with
   the bytes already in hand -- at which point upstream's own code runs unchanged, since
   _finalize_zip_installation only ever wanted a file on disk.

Nothing here changes what gets installed or where; the unpack, the GitHub subdirectory
handling and the status updates are all still upstream's.
"""

import os
import sys
import tempfile

import addonmanager_freecad_interface as fci

from addonmanager_fcweb_async import async_get


def _no_move_to_thread(self, _thread):
    """Keep the worker on the main thread. See the module docstring."""
    return None


def _patch_move_to_thread():
    """Stop every installer/uninstaller worker from migrating to a QThread."""
    import addonmanager_installer as inst
    import addonmanager_uninstaller as uninst
    import addonmanager_dependency_installer as depinst
    import addonmanager_workers_startup as startup

    classes = [
        inst.AddonInstaller,
        inst.MacroInstaller,
        uninst.AddonUninstaller,
        uninst.MacroUninstaller,
        depinst.DependencyInstaller,
        startup.CheckSingleUpdateWorker,
    ]
    for cls in classes:
        cls.moveToThread = _no_move_to_thread
    return "%d worker classes stay on the main thread" % len(classes)


def _patch_zip_install():
    """Pre-fetch the addon ZIP asynchronously, then let upstream's run() proceed."""
    import addonmanager_installer as inst

    orig_run = inst.AddonInstaller.run

    def run(self, *args, **kwargs):
        # Second entry: the bytes are here, so upstream's path is fully local and safe.
        if getattr(self, "_fcweb_zip", None) is not None:
            return orig_run(self, *args, **kwargs)

        try:
            zip_url = self.addon_to_install.get_zip_url()
        except Exception:
            zip_url = None
        if not zip_url or not str(zip_url).startswith(("http://", "https://")):
            # A local path needs no download; upstream handles it without blocking.
            return orig_run(self, *args, **kwargs)

        def arrived(ok, data):
            if not ok or not data:
                self.failure.emit(
                    self.addon_to_install,
                    fci.translate(
                        "AddonsInstaller", "Failed to download {}"
                    ).format(zip_url),
                )
                # finished must still fire or the progress dialog never goes away and
                # the GUI's close path spins waiting for a worker that already gave up.
                self.finished.emit()
                return
            self._fcweb_zip = data
            run(self, *args, **kwargs)

        fci.Console.PrintLog("Fetching %s without blocking the event loop\n" % zip_url)
        async_get(zip_url, arrived, timeout_ms=120000, attempts=2)
        return False   # not finished yet; arrived() re-enters run()

    def _install_by_zip(self):
        """Upstream's version, minus the download it can no longer do here."""
        data = getattr(self, "_fcweb_zip", None)
        if data is None:
            raise RuntimeError("ZIP bytes missing -- run() should have fetched them")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as f:
            name = f.name
            f.write(data)
        try:
            self._finalize_zip_installation(name)
        finally:
            self._fcweb_zip = None
            try:
                os.unlink(name)
            except OSError:
                pass
        return True

    inst.AddonInstaller.run = run
    inst.AddonInstaller._install_by_zip = _install_by_zip
    return "addon ZIPs download without blocking"


ALLOWED_PACKAGES_URL = (
    "https://raw.githubusercontent.com/FreeCAD/FreeCAD-addons/"
    "master/ALLOWED_PYTHON_PACKAGES.txt"
)


def _patch_allowed_packages():
    """Refresh the Python-package allowlist without blocking.

    AddonInstaller.__init__ calls _update_allowed_packages_list(), which does a
    utils.blocking_get -- a processEvents() spin. On the main thread that froze the tab
    before the installer had done anything at all: the constructor never returned.

    The list still gets refreshed, just asynchronously, and the local copy shipped with
    FreeCAD is loaded first so a decision is never made against an empty set. It only
    gates Python-package dependencies, which cannot be installed here anyway (no pip),
    but it is a security allowlist and is kept current rather than dropped.
    """
    import addonmanager_installer as inst

    cls = inst.AddonInstaller

    def update_async():
        def arrived(ok, data):
            if not ok or not data:
                fci.Console.PrintLog("Could not refresh ALLOWED_PYTHON_PACKAGES.txt\n")
                return
            names = set()
            for line in data.decode("utf8", "replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    names.add(line.lower())
            if names:
                cls.allowed_packages = names

        async_get(ALLOWED_PACKAGES_URL, arrived)

    cls._update_allowed_packages_list = staticmethod(update_async)

    # Populate now from the local copy, so __init__'s "elif not allowed_packages" branch
    # has something and cannot be tempted back onto the network path.
    try:
        cls._load_local_allowed_packages_list()
    except Exception as e:
        fci.Console.PrintLog("Local allowed-packages list unavailable: %r\n" % (e,))
    return "allowed-packages list refreshes asynchronously (%d local)" % len(
        cls.allowed_packages
    )


def install():
    """Apply the patches. Returns notes for the caller to log."""
    notes = []
    for fn in (_patch_move_to_thread, _patch_allowed_packages, _patch_zip_install):
        try:
            notes.append(fn())
        except Exception as e:
            notes.append("%s FAILED %r" % (fn.__name__, e))
    sys.stdout.flush()
    return notes
