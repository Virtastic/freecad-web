# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Boot hook for the FreeCAD-Web Addon Manager overlay.

Imported once at startup, after /fcweb-am is on sys.path. Holds the patches that cannot be
delivered by shadowing a module -- because a class object is shared, so replacing a method
on it is visible to every module that already imported that class, which shadowing is not.

Nothing here imports the Addon Manager's own modules eagerly. They are not on sys.path
until the workbench is activated, and importing them at boot would both slow startup and
drag Qt network machinery in before the GUI exists. install() only registers a hook.
"""

import sys

_installed = False


def _patch_blocking_dialogs():
    """Make the Addon Manager's modal helpers non-blocking.

    MEASURED 2026-09-03: a QMessageBox opened from a Qt timer callback crashes the tab. Two
    runs of the same probe against the same container differed only in whether that modal
    was opened -- without it, 208 console lines and a clean exit; with it, "Page crashed".

    The mechanism: the shipped dialog shim (wasm_dialog_shim_jspi.py) routes
    QMessageBox.exec() through _fcwebdlg.confirm, which SUSPENDS the wasm stack via JSPI.
    Only exports named in ASYNCIFY_EXPORTS (fcweb_run_python, fcweb_dispatch_event) may
    suspend; a Qt timer or network callback is neither, so the suspend is fatal.

    Every completion in this overlay lands in a slot that may want to tell the user
    something -- the connection check failing, an install finishing. Those all funnel
    through MessageDialog.show_modal, which is a nested exec(). Replaced with show().

    Widgets/ is a package-relative import so it cannot be shadowed; the class is patched
    instead, which reaches every importer regardless of when they imported it.
    """
    from addonmanager_fcweb_async import notify

    try:
        from Widgets.addonmanager_utility_dialogs import MessageDialog
    except Exception as e:  # not importable until the workbench is active
        return "MessageDialog unavailable (%r)" % (e,)

    def _show_modal(self, *_a, **_k):
        title = getattr(self, "windowTitle", lambda: "FreeCAD")()
        text = ""
        for attr in ("text", "message", "detailedText"):
            try:
                v = getattr(self, attr)
                text = v() if callable(v) else v
                if text:
                    break
            except Exception:
                continue
        notify(title or "Addon Manager", text or "")
        return None

    MessageDialog.show_modal = _show_modal
    return "MessageDialog.show_modal -> non-blocking"


# Startup-phase tracing. The sequence advances on a signal, so when a phase aborts the
# engine there is no traceback -- only the last phase entered tells you where it died.
TRACE = False


def _trace_startup():
    """Print each startup phase as it is entered, with the catalogue size so far."""
    import AddonManager
    cls = AddonManager.CommandAddonManager
    orig = cls.do_next_startup_phase

    def traced(self):
        AddonManager._fcweb_cmd = self
        try:
            nxt = self.startup_sequence[0].__name__ if self.startup_sequence else "<done>"
        except Exception:
            nxt = "?"
        try:
            rows = self.item_model.rowCount()
        except Exception:
            rows = -1
        print("[fcweb] am phase=%s rows=%d" % (nxt, rows))
        sys.stdout.flush()
        return orig(self)

    cls.do_next_startup_phase = traced
    return "startup phase tracing on"

OVERLAY_DIR = "/fcweb-am"

# Load order matters: each shadow imports the ones above it by bare name.
SHADOWS = (
    "addonmanager_fcweb_async",
    "addonmanager_workers_utility",
    "addonmanager_workers_startup",
)

# Names already bound into other modules by `from <shadow> import <name>`. sys.path cannot
# reach these -- the binding happened at import time and points at the class object.
REBIND = {
    "AddonManager": (
        "CreateAddonListWorker",
        "CheckWorkbenchesForUpdatesWorker",
        "GetBasicAddonStatsWorker",
        "GetAddonScoreWorker",
        "CheckForMissingDependenciesWorker",
    ),
    "addonmanager_package_details_controller": ("CheckSingleUpdateWorker",),
    "addonmanager_connection_checker": ("ConnectionChecker",),
}


def _install_shadows():
    """Replace the shipped worker modules, whatever sys.path says.

    MEASURED 2026-09-03: putting /fcweb-am at sys.path[0] was NOT enough. FreeCAD puts the
    Mod/AddonManager directory ahead of it when the workbench loads, so every import
    resolved to the shipped QThread workers and this entire overlay sat unused while the
    engine kept aborting in PyGILState_Release. The trace that proved it:

        am startup_mod=/freecad/Mod/AddonManager/./addonmanager_workers_startup.py
        am worker_base=QThread

    So load by explicit file path instead, and cover both import orderings:
      * sys.modules[name] = ours  -> any import that has NOT happened yet gets ours;
      * REBIND                    -> any `from X import Y` that ALREADY happened is repointed.
    """
    import importlib.util
    import os

    loaded = {}
    for name in SHADOWS:
        path = os.path.join(OVERLAY_DIR, name + ".py")
        if not os.path.isfile(path):
            raise RuntimeError("overlay module missing: %s" % path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        # Registered BEFORE exec so the next shadow's bare-name import resolves to this one.
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        loaded[name] = mod

    rebound = 0
    missing = []
    for target, names in REBIND.items():
        mod = sys.modules.get(target)
        if mod is None:
            continue          # not imported yet; the sys.modules entry above covers it
        for n in names:
            for sh in loaded.values():
                if hasattr(sh, n):
                    setattr(mod, n, getattr(sh, n))
                    rebound += 1
                    break
            else:
                missing.append("%s.%s" % (target, n))

    note = "shadows loaded (%d), rebound %d name(s)" % (len(loaded), rebound)
    if missing:
        note += "; NOT FOUND: " + ", ".join(missing)
    return note


def _patch_connection_checker():
    """Rebuild the connection checker the registered command already owns.

    The Std_AddonMgr command object is constructed when FreeCAD registers the command, long
    before this overlay loads, and its ConnectionCheckerGUI holds a ConnectionChecker built
    from the SHIPPED module -- a QThread. Rebinding the class reaches every later instance
    but cannot reach one that already exists, so starting it ran Python on a worker thread
    and CPython aborted in PyGILState_Release about 0.7 s later.

    MEASURED 2026-09-04, the three runs that pinned it:
      * Gui.runCommand('Std_AddonMgr')          -> abort 0.7 s later
      * Gui.runCommand('Std_ViewFitAll')        -> no abort (not command dispatch itself)
      * Activated()'s steps called directly on a FRESHLY built command, which picks up the
        shadow                                  -> no abort
    """
    import addonmanager_connection_checker as ccm

    orig_start = ccm.ConnectionCheckerGUI.start

    def start(self):
        # ccm.ConnectionChecker is the rebound (AsyncWorker) class by the time this runs.
        self.connection_checker = ccm.ConnectionChecker()
        self.signals_connected = False
        orig_start(self)

    ccm.ConnectionCheckerGUI.start = start
    return "ConnectionCheckerGUI rebuilds its checker from the shadow"


def _patch_modal_launch():
    """Stop the Addon Manager window from opening modally.

    launch() ends with self.dialog.exec(). On this build QDialog::exec() suspends through
    JSPI, and only stacks entered via fcweb_run_python may suspend. launch() is reached
    from the connection checker's success signal -- a network callback -- so that exec()
    suspends on a stack that is not allowed to, and the engine dies.

    exec() is not load-bearing here: launch() ignores its return value and every control in
    the dialog is already wired through signals (rejected/accepted are connected a few
    lines above it). So the dialog is shown non-modally instead.

    Done by patching loadUi rather than launch(), because the dialog object is created
    inside launch() and this is the only seam that sees it without forking 60 lines.
    """
    import os
    import addonmanager_freecad_interface as fci

    orig_load_ui = fci.loadUi

    def load_ui(path, *args, **kwargs):
        widget = orig_load_ui(path, *args, **kwargs)
        try:
            if os.path.basename(str(path)) == "AddonManager.ui":
                widget.exec = widget.show
        except Exception:
            pass
        return widget

    fci.loadUi = load_ui
    return "AddonManager.ui opens non-modally (exec would suspend illegally)"


def _stash_command():
    """Record the live command object as AddonManager._fcweb_cmd.

    The registered Std_AddonMgr instance is otherwise unreachable from Python -- FreeCAD
    keeps it in the C++ command registry -- and both the boot gate and any support probe
    need a handle on the running Addon Manager to inspect its model or its workers.
    """
    import AddonManager

    cls = AddonManager.CommandAddonManager
    orig_launch = cls.launch

    def launch(self):
        AddonManager._fcweb_cmd = self
        return orig_launch(self)

    cls.launch = launch
    return "command object exposed as AddonManager._fcweb_cmd"


def _install_now():
    """Applied the first time an Addon Manager module is importable."""
    notes = []
    try:
        notes.append(_install_shadows())
    except Exception as e:
        notes.append("SHADOW INSTALL FAILED %r -- shipped QThread workers still in place"
                     % (e,))
    try:
        notes.append(_patch_connection_checker())
    except Exception as e:
        notes.append("connection-checker patch FAILED %r" % (e,))
    try:
        import fcweb_am_install
        notes.extend(fcweb_am_install.install())
    except Exception as e:
        notes.append("install patches FAILED %r" % (e,))
    try:
        notes.append(_stash_command())
    except Exception as e:
        notes.append("command stash FAILED %r" % (e,))
    try:
        notes.append(_patch_modal_launch())
    except Exception as e:
        notes.append("modal-launch patch FAILED %r" % (e,))
    try:
        notes.append(_patch_blocking_dialogs())
    except Exception as e:
        notes.append("dialog patch FAILED %r" % (e,))
    if TRACE:
        try:
            notes.append(_trace_startup())
        except Exception as e:
            notes.append("trace patch FAILED %r" % (e,))
    return [n for n in notes if n]


def install():
    """Register a lazy hook; the Addon Manager is not importable at boot."""
    global _installed
    if _installed:
        return
    _installed = True
    print("[fcweb] addon-manager overlay active on /fcweb-am")
    sys.stdout.flush()

    try:
        from PySideWrapper import QtCore
    except ImportError:
        from PySide6 import QtCore

    # Poll until the workbench has been activated and its modules are importable, then
    # apply the class patches once. Cheap: a 2 s timer that stops after it succeeds.
    state = {"timer": None, "tries": 0}

    def _try():
        state["tries"] += 1
        try:
            import Widgets.addonmanager_utility_dialogs  # noqa: F401
        except Exception:
            if state["tries"] > 900:          # ~30 min, then give up quietly
                state["timer"].stop()
            return
        state["timer"].stop()
        for note in _install_now():
            print("[fcweb] addon-manager: %s" % note)
        sys.stdout.flush()

    t = QtCore.QTimer()
    t.timeout.connect(_try)
    t.start(2000)
    state["timer"] = t
    # Held on the module so the QTimer is not garbage-collected with this frame.
    globals()["_hook_timer"] = t


def probe_modal_from_callback():
    """R1 probe. ANSWERED 2026-09-03: a blocking modal from a Qt callback crashes the tab.

    Kept because it is the cheapest way to re-test the question if the JSPI export list or
    the dialog shim ever changes. Do not run it casually -- it is expected to kill the page.
    """
    try:
        from PySideWrapper import QtCore, QtWidgets
    except ImportError:
        from PySide6 import QtCore, QtWidgets

    def _from_timer():
        try:
            QtWidgets.QMessageBox.information(
                None, "FCWEB probe", "Modal opened from a Qt timer callback.")
            print("FCWEB_AM_PROBE timer_modal=ok")
        except BaseException as e:
            print("FCWEB_AM_PROBE timer_modal=FAILED %r" % (e,))
        sys.stdout.flush()

    def _nonblocking():
        from addonmanager_fcweb_async import notify
        try:
            notify("FCWEB probe", "Non-blocking notify from a Qt timer callback.")
            print("FCWEB_AM_PROBE timer_notify=ok")
        except BaseException as e:
            print("FCWEB_AM_PROBE timer_notify=FAILED %r" % (e,))
        sys.stdout.flush()

    QtCore.QTimer.singleShot(1500, _nonblocking)
    QtCore.QTimer.singleShot(6000, _from_timer)
