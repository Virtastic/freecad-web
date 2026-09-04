# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Callback-based HTTP for the FreeCAD-Web build. Nothing here may block.

The Addon Manager's own workers are QThreads, and CPython in this build aborts outright
the moment Python runs on a Qt worker thread:

    Fatal Python error: PyGILState_Release: thread state ... must be current when releasing

The obvious alternative -- run the same work inline on the main thread -- deadlocks
instead. Those workers block waiting on network replies, and it is the Qt event loop that
delivers replies, so blocking the loop starves the very thing being waited for. That was
measured on 2026-09-03: the application froze and never opened. NetworkManager's own
docstring says it in as many words: "Do not use on the main GUI thread, it will prevent
any event processing while it blocks."

JSPI cannot rescue a blocking call either. Only exports named in ASYNCIFY_EXPORTS
(fcweb_run_python, fcweb_dispatch_event) may suspend, and a Qt network callback is
neither -- suspending there raises SuspendError and takes the page down.

So: callbacks, always. submit_unmonitored_get returns immediately and reports through the
`completed` signal. That is the one pattern proven to work here -- tools/boot-gate.py's
ADDONS_PY fetches the real 175-addon catalogue with it.
"""

import sys
import addonmanager_freecad_interface as fci
import NetworkManager

try:
    from PySideWrapper import QtCore
except ImportError:  # older layouts
    from PySide6 import QtCore


def defer(ms, fn, _parent=None):
    """Run fn() after ms milliseconds. The one place the overlay defers work.

    Plain QTimer.singleShot. An owned-QTimer variant was tried first, on the theory that
    singleShot was what aborted the engine; it was not. The abort was the shipped
    QThread-based ConnectionChecker owned by the pre-registered Std_AddonMgr command,
    which died ~0.7 s after activation -- right when the next deferred call happened to
    run, which is what made the timer look guilty. See fcweb_am_boot._patch_connection_checker.
    """
    QtCore.QTimer.singleShot(int(ms), fn)


class Fetch(QtCore.QObject):
    """One unmonitored GET, with retries and a watchdog. Emits done() exactly once."""

    done = QtCore.Signal(bool, object)  # ok, bytes (b"" on failure)

    def __init__(self, url, timeout_ms=30000, attempts=3, retry_delay_ms=3000,
                 disable_cache=False, parent=None):
        super().__init__(parent)
        self.url = url
        self.timeout_ms = timeout_ms
        self.attempts_left = attempts
        self.retry_delay_ms = retry_delay_ms
        self.disable_cache = disable_cache
        self._index = None
        self._finished = False
        NetworkManager.InitializeNetworkManager()
        self._nm = NetworkManager.AM_NETWORK_MANAGER

    def start(self):
        self._nm.completed.connect(self._completed)
        self._submit()
        return self

    def _submit(self):
        self.attempts_left -= 1
        idx = self._nm.submit_unmonitored_get(
            self.url, timeout_ms=self.timeout_ms, disable_cache=self.disable_cache
        )
        self._index = idx
        # Watchdog. QNetworkRequest's own transfer timeout should fire first, but a request
        # the browser drops without answering -- a COEP refusal, a proxy key we forgot to
        # allow-list -- would otherwise park the startup sequence forever behind a progress
        # bar with no way out. Keyed on idx so a stale timer cannot abort a later attempt.
        defer(self.timeout_ms + 2000, lambda: self._timed_out(idx), self)

    def _completed(self, index, code, data):
        if self._finished or index != self._index:
            return
        if code == 200:
            self._emit(True, bytes(data.data()) if data is not None else b"")
        else:
            fci.Console.PrintWarning("Addon Manager: HTTP %s from %s\n" % (code, self.url))
            self._retry_or_fail()

    def _timed_out(self, idx):
        if self._finished or self._index != idx:
            return
        self._nm.abort(idx)
        fci.Console.PrintWarning("Addon Manager: timed out fetching %s\n" % self.url)
        self._retry_or_fail()

    def _retry_or_fail(self):
        if self.attempts_left > 0:
            self._index = None
            defer(
                self.retry_delay_ms,
                lambda: None if self._finished else self._submit(),
                self,
            )
        else:
            self._emit(False, b"")

    def cancel(self):
        if not self._finished and self._index is not None:
            self._nm.abort(self._index)
        self._emit(False, b"")

    def _emit(self, ok, data):
        if self._finished:
            return
        self._finished = True
        try:
            self._nm.completed.disconnect(self._completed)
        except (RuntimeError, TypeError):
            pass
        try:
            self.done.emit(ok, data)
        except RuntimeError:
            # The receiver's C++ side was deleted (the dialog closed under us). Not an error.
            pass


# A Fetch that is garbage-collected before completing drops its `completed` connection and
# the callback simply never runs -- a silent stall, not an error. This set is the only
# thing preventing that; it is not dead code.
_in_flight = set()


def async_get(url, callback, parent=None, **kwargs):
    """Fire and forget. callback(ok: bool, data: bytes) runs once, on the main thread.

    Chain sequential GETs by calling async_get again from inside the callback.
    """
    f = Fetch(url, parent=parent, **kwargs)
    _in_flight.add(f)

    def _relay(ok, data, f=f):
        _in_flight.discard(f)
        callback(ok, data)

    f.done.connect(_relay)
    return f.start()


class AsyncWorker(QtCore.QObject):
    """Stands in for a QThread worker in AddonManager.py's startup sequence.

    do_next_startup_phase (AddonManager.py:365) only needs a one-shot `finished`, so the
    seven-phase chain keeps working untouched. cleanup_workers (:259) and reject() (:296)
    call the QThread API on whatever sits in self.workers, so the five methods they use are
    stubbed here -- far cheaper than shadowing AddonManager.py, which is 800 lines we
    otherwise never need to fork.

    isFinished() MUST become True as soon as requestInterruption() is called: reject()
    spins `wait(25); processEvents()` until every worker reports finished, and on this
    build that spin is a frozen tab, not a wait.
    """

    finished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._interrupted = False
        self._fetch = None

    # ---- the QThread-shaped API AddonManager.py and the *_gui modules call ----
    def start(self):
        self._running = True
        self._interrupted = False
        # Deferred one turn so run() cannot re-enter the caller that is still wiring us up,
        # and so the progress bar gets a chance to repaint between startup phases.
        defer(0, self._run_guarded, self)

    def isFinished(self):
        return not self._running

    def isRunning(self):
        return self._running

    def isInterruptionRequested(self):
        return self._interrupted

    def requestInterruption(self):
        self._interrupted = True
        if self._fetch is not None:
            self._fetch.cancel()
        self._finish()

    def wait(self, _ms=0):
        return not self._running   # nothing ever blocked, so there is nothing to wait for

    def quit(self):
        self.requestInterruption()

    terminate = quit

    # ---- for subclasses ----
    def run(self):
        raise NotImplementedError

    def _run_guarded(self):
        """run() dies inside PySide's slot wrapper, so an exception here is silent AND
        parks the startup sequence forever behind a progress bar waiting for a finished
        signal that will never come. Report it and finish, so the sequence moves on.
        (An unset current_thread cost two debug cycles this way.)
        """
        self._safe(self.run)

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except BaseException:
            import traceback
            fci.Console.PrintError(
                "Addon Manager worker %s failed:\n%s\n"
                % (self.objectName() or type(self).__name__, traceback.format_exc())
            )
            self._finish()

    def _get(self, url, callback, **kwargs):
        """A fetch whose callback is dropped if we were interrupted meanwhile."""
        def _guarded(ok, data):
            self._fetch = None
            if not self._interrupted:
                self._safe(callback, ok, data)
        self._fetch = async_get(url, _guarded, parent=self, **kwargs)

    def _finish(self):
        if self._running:
            self._running = False
            try:
                self.finished.emit()
            except RuntimeError:
                pass

def notify(title, text, icon=None):
    """Show a message WITHOUT blocking. The only safe way to talk to the user from a
    completion callback.

    MEASURED 2026-09-03, and the reason this function exists: a QMessageBox opened from a
    QTimer callback crashes the tab. Two runs of the same probe container differed only in
    whether the modal was opened -- the run without it produced 208 console lines and
    exited cleanly, the run with it died with "Page crashed". The shipped dialog shim makes
    QMessageBox.exec() blocking via _fcwebdlg.confirm, which suspends the wasm stack, and
    only ASYNCIFY_EXPORTS may suspend. A Qt callback is not one of them.

    show() returns immediately and never suspends, so it is safe anywhere.
    """
    try:
        from PySideWrapper import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets
    try:
        box = QtWidgets.QMessageBox()
        box.setWindowTitle(str(title))
        box.setText(str(text))
        if icon is not None:
            box.setIcon(icon)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        box.setModal(False)
        box.show()
        box.raise_()
        # Held until closed: a QMessageBox with no parent is garbage-collected the moment
        # this frame returns, and the window vanishes before it is read.
        _open_dialogs.append(box)
        box.finished.connect(lambda _r, b=box: _open_dialogs.remove(b)
                             if b in _open_dialogs else None)
        return box
    except Exception as e:
        # Never let the notification itself become the failure.
        fci.Console.PrintWarning("Addon Manager: %s -- %s (%r)\n" % (title, text, e))
        return None


_open_dialogs = []
