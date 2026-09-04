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

    orig_install_by_zip = inst.AddonInstaller._install_by_zip

    def _install_by_zip(self):
        """Upstream's version, minus the download it can no longer do here."""
        data = getattr(self, "_fcweb_zip", None)
        if data is None:
            # A local path: upstream's version does no network work on that branch, so
            # let it run rather than failing. run() only pre-fetches remote URLs.
            return orig_install_by_zip(self)
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


def _patch_verify_pip():
    """Fail the pip check cleanly instead of raising out of the dependency installer.

    _verify_pip shells out to pip through subprocess. There is no subprocess in this
    build, and the exception it raises is not the CalledProcessError upstream catches, so
    it propagated out of DependencyInstaller.run() and the installation died with no
    explanation. Emitting no_pip is the path upstream already has for "pip is missing",
    and it ends in a dialog offering to continue without the Python packages.

    This is a hard ceiling, not a bug: Python-package dependencies can never be installed
    here. An addon that only wants them for optional features still installs and works.
    """
    import addonmanager_dependency_installer as dep

    def verify_pip(self):
        call = "pip (unavailable in the browser build)"
        try:
            import addonmanager_utilities as utils
            call = " ".join(utils.create_pip_call([]))
        except Exception:
            pass
        fci.Console.PrintWarning(
            "Python packages cannot be installed in the browser build; "
            "continuing without them\n"
        )
        self.no_pip.emit(call)
        return False

    dep.DependencyInstaller._verify_pip = verify_pip
    return "pip check fails cleanly (no subprocess in this build)"


def _patch_macro_fetch():
    """Let wiki macros install without blocking, by replaying them against a cache.

    Macro.install() and fill_details_from_wiki() reach the network through
    Macro.blocking_get, a class attribute captured at import time -- so it is patched
    rather than shadowed, which reaches every module that already imported the class.

    The replacement never blocks: a cache hit returns the bytes, a miss starts an
    async_get and returns None. Upstream already treats None as "could not fetch" and
    warns instead of raising, so a miss is safe -- it just yields an incomplete macro.

    That is what the replay is for. A wiki macro needs two round trips (the wiki page,
    then the rawcodeurl found inside it), so the operation is simply run again each time
    the outstanding fetches settle, and each pass gets one step further. Two rounds is the
    normal case; the cap stops a macro whose URLs never resolve from retrying forever.
    """
    from addonmanager_macro import Macro
    import addonmanager_installer as inst

    cache = {}
    pending = {}

    def cached_get(url, *_args, **_kwargs):
        if url in cache:
            return cache[url]
        if url not in pending:
            pending[url] = True

            def arrived(ok, data, u=url):
                pending.pop(u, None)
                cache[u] = data if (ok and data) else None

            async_get(url, arrived, timeout_ms=60000)
        return None

    Macro.blocking_get = cached_get

    orig_run = inst.MacroInstaller.run
    MAX_ROUNDS = 6

    def run(self, *args, **kwargs):
        rounds = getattr(self, "_fcweb_rounds", 0)
        macro = self.addon_to_install.macro

        # Warm the cache by asking for what this macro needs, then let the fetches land.
        # The pass below produces no side effects the GUI can see: it only populates the
        # macro object, which upstream's run() does anyway.
        if not getattr(macro, "code", None) and rounds < MAX_ROUNDS:
            try:
                macro.fill_details_from_wiki(macro.url)
            except Exception as e:
                fci.Console.PrintLog("Macro detail fetch round %d: %r\n" % (rounds, e))
            if not getattr(macro, "code", None):
                self._fcweb_rounds = rounds + 1
                _when_settled(pending, lambda: run(self, *args, **kwargs))
                return False

        return orig_run(self, *args, **kwargs)

    inst.MacroInstaller.run = run
    return "wiki macros fetch without blocking (replayed, max %d rounds)" % MAX_ROUNDS


def _patch_macro_toolbar_prompt():
    """Do not ask, from a callback, whether to add a toolbar button for a macro.

    _ask_to_install_toolbar_button runs from _base_installation_success -- a signal
    handler -- and its own comment calls it a "Synchronous set of modals". Those exec()
    calls suspend through JSPI on a stack that may not suspend, so the macro finished
    installing and then took the engine down with it: the files were on disk and the tab
    was dead.

    The macro is fully installed and runnable from the Macro menu without a toolbar
    button, so the prompt is dropped and the user is told where to add one by hand.
    """
    import addonmanager_installer_gui as gui
    from addonmanager_fcweb_async import notify

    def ask(self):
        try:
            name = self.addon_to_install.macro.name
        except Exception:
            name = "The macro"
        notify(
            "Macro installed",
            "%s is installed and available from the Macro menu. To put it on a "
            "toolbar, use Tools then Customize." % name,
        )

    gui.MacroInstallerGUI._ask_to_install_toolbar_button = ask
    return "macro toolbar prompt replaced with a non-blocking note"


def _rescan_preference_packs():
    """Pick up preference packs an addon just installed, without a restart.

    Returns the names that appeared, or [] if none did.

    Guarded with hasattr: the binding only exists in a build carrying the
    ApplicationPy PreferencePackManager patch. On an older engine this does nothing and
    a page reload still picks the theme up, which is the pre-existing behaviour.
    """
    try:
        import FreeCADGui as Gui
    except Exception:
        return []
    if not hasattr(Gui, "rescanPreferencePacks"):
        return []
    try:
        before = set(Gui.listPreferencePacks())
        Gui.rescanPreferencePacks()
        new = sorted(set(Gui.listPreferencePacks()) - before)
    except Exception as e:
        fci.Console.PrintLog("Preference pack rescan failed: %r\n" % (e,))
        return []
    if new:
        fci.Console.PrintMessage(
            "New preference pack(s) available: %s\n" % ", ".join(new)
        )
    return new


def _patch_preference_pack_rescan():
    """Rescan preference packs as soon as an addon's files are on disk.

    Without this the theme installs correctly and then appears nowhere: FreeCAD only
    scans for preference packs at startup, and in the browser a restart is a page reload
    that costs the user their session. That is the whole reason the binding was added,
    and nothing was calling it.

    Hooked on _finalize_zip_installation rather than on a success signal because that is
    the exact moment the files exist, and it covers both the downloaded and local-path
    branches.
    """
    import addonmanager_installer as inst
    from addonmanager_fcweb_async import notify

    orig_finalize = inst.AddonInstaller._finalize_zip_installation

    def finalize(self, filename):
        result = orig_finalize(self, filename)
        new = _rescan_preference_packs()
        if new:
            try:
                name = self.addon_to_install.display_name
            except Exception:
                name = "The addon"
            notify(
                "Theme installed",
                "%s added %d preference pack(s): %s.\n\nChoose one under "
                "Edit then Preferences, General, Theme -- no reload needed."
                % (name, len(new), ", ".join(new)),
            )
        return result

    inst.AddonInstaller._finalize_zip_installation = finalize
    return "preference packs rescanned after install"


def _when_settled(pending, then, tries=0):
    """Call then() once no fetches are outstanding. Polls; never blocks."""
    from addonmanager_fcweb_async import defer

    if not pending or tries > 120:
        then()
        return
    defer(500, lambda: _when_settled(pending, then, tries + 1))


def install():
    """Apply the patches. Returns notes for the caller to log."""
    notes = []
    for fn in (_patch_move_to_thread, _patch_allowed_packages, _patch_verify_pip,
               _patch_zip_install, _patch_macro_fetch,
               _patch_macro_toolbar_prompt, _patch_preference_pack_rescan):
        try:
            notes.append(fn())
        except Exception as e:
            notes.append("%s FAILED %r" % (fn.__name__, e))
    sys.stdout.flush()
    return notes
