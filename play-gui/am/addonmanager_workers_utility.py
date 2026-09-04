# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2022 FreeCAD Project Association
# SPDX-FileNotice: Part of the AddonManager.
#
# FreeCAD-Web overlay. Forked from upstream addonmanager_workers_utility.py and shadowed
# onto sys.path ahead of Mod/AddonManager (see the loader in play-gui/freecad-gui.html).
#
# WHY: upstream's ConnectionChecker is a QThread, and CPython in this build aborts the
# moment Python runs on a Qt worker thread:
#
#     Fatal Python error: PyGILState_Release: thread state ... must be current when releasing
#
# Its slots are worse than that. success/failure are emitted FROM the worker thread into
# main-thread slots, and _network_connection_failed then opens a modal via
# MessageDialog.show_modal -> dialog.exec(). That is a nested event loop entered from a
# cross-thread queued slot, and it is the exact crash reported on 2026-09-03.
#
# The irony is that this class already used the right primitive: submit_unmonitored_get
# plus the completed signal. It was broken only by the sync-over-async wrapper around it --
# `while not self.done: processEvents(); time.sleep(0.1)` -- which is why it needed a thread
# at all. Delete the loop and the callback IS the result; no thread, no cross-thread slots.
#
# Everything else is upstream verbatim.

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore

import NetworkManager

import addonmanager_freecad_interface as fci
from addonmanager_fcweb_async import AsyncWorker

translate = fci.translate


class ConnectionChecker(AsyncWorker):
    """Checks connectivity to the addon server. Emits success() or failure(str).

    Same contract as upstream -- start(), isFinished(), requestInterruption(), wait() and
    the two signals -- but it never leaves the main thread. AsyncWorker supplies the
    QThread-shaped API that addonmanager_connection_checker.py calls (isFinished at :63,
    wait at :79).
    """

    success = QtCore.Signal()
    failure = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConnectionChecker")
        self.request_id = None
        self.data = None

    def run(self):
        fci.Console.PrintLog("Checking network connection...\n")
        url = fci.Preferences().get("status_test_url")
        # attempts=1 deliberately: this is a reachability probe. Retrying three times
        # behind a message box the user cannot dismiss is worse than failing fast.
        self._get(url, self._received, timeout_ms=30000, attempts=1, disable_cache=True)

    def _received(self, ok, data):
        self.data = data if ok else None
        if not self.data:
            self.failure.emit(
                translate(
                    "AddonsInstaller",
                    "Unable to read data from addons.freecad.org. The server may be down, "
                    "or you may not be connected to the internet.",
                )
            )
        else:
            fci.Console.PrintLog(
                "FreeCAD Addon server response: %s\n" % self.data.decode("utf-8", "replace")
            )
            self.success.emit()
        self._finish()

    # Kept so anything still calling the upstream API does not explode. The base class
    # manages the completed connection now, so there is nothing left to disconnect.
    def disconnect_network_manager(self):
        pass

    def connection_data_received(self, id: int, status: int, data):
        """Upstream slot, retained for compatibility. Nothing connects it any more."""
        if self.request_id is not None and self.request_id == id:
            if status == 200:
                self.data = data.data()
            else:
                fci.Console.PrintWarning(
                    "No data received: status returned was %s\n" % status
                )
                self.data = None
