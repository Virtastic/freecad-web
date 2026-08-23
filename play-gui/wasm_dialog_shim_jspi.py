# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# FreeCAD-Web JSPI build: route Python-triggered modal dialogs through a BLOCKING
# HTML modal (_fcwebdlg.confirm) that returns the user's REAL choice. Native Qt
# QMessageBox windows don't composite their body/buttons on this Qt-wasm build,
# so this bridge delivers actual user choice via the JSPI suspend instead.
import sys

def install():
    from PySide6 import QtWidgets as W
    import _fcwebdlg

    MB = W.QMessageBox

    # Map a QMessageBox.StandardButtons flag set to an ordered list of (flag, label).
    _ORDER = [
        (MB.Ok, "OK"), (MB.Yes, "Yes"), (MB.YesToAll, "Yes to All"),
        (MB.No, "No"), (MB.NoToAll, "No to All"), (MB.Abort, "Abort"),
        (MB.Retry, "Retry"), (MB.Ignore, "Ignore"), (MB.Save, "Save"),
        (MB.SaveAll, "Save All"), (MB.Discard, "Discard"),
        (MB.Apply, "Apply"), (MB.Reset, "Reset"), (MB.Close, "Close"),
        (MB.Cancel, "Cancel"),
    ]

    def _buttons_for(flags):
        pairs = [(f, lbl) for (f, lbl) in _ORDER if int(flags) & int(f)]
        if not pairs:
            pairs = [(MB.Ok, "OK")]
        return pairs

    def _ask(title, text, flags):
        pairs = _buttons_for(flags)
        labels = [lbl for (_f, lbl) in pairs]
        idx = _fcwebdlg.confirm(str(title or "FreeCAD"), str(text or ""), labels)
        if idx < 0 or idx >= len(pairs):
            idx = 0
        return pairs[idx][0]

    def _make_static(default_flags):
        def _f(*a, **k):
            parent = a[0] if len(a) > 0 else k.get("parent")
            title  = a[1] if len(a) > 1 else k.get("title", "")
            body   = a[2] if len(a) > 2 else k.get("text", "")
            flags  = a[3] if len(a) > 3 else k.get("buttons", default_flags)
            return _ask(title, body, flags)
        return staticmethod(_f)

    MB.question    = _make_static(MB.Yes | MB.No)
    MB.information = _make_static(MB.Ok)
    MB.warning     = _make_static(MB.Ok)
    MB.critical    = _make_static(MB.Ok)

    # instance .exec()/.exec_() on QMessageBox -> blocking HTML with its own buttons
    def _mb_exec(self, *a, **k):
        try:
            flags = self.standardButtons()
            return _ask(self.windowTitle(), self.text(), flags)
        except Exception:
            return MB.Ok
    MB.exec = _mb_exec
    MB.exec_ = _mb_exec

    # QInputDialog is deliberately NOT stubbed.
    #
    # It used to be, returning (value, False) -- i.e. "the user cancelled" -- for getText,
    # getItem, getInt and getDouble. That silently broke every macro and Python-workbench
    # command that asks for a name, a count or a length: they took the cancel branch and
    # quietly did nothing.
    #
    # The stated reason was that native Qt dialogs "don't composite their body/buttons" on
    # this Qt-wasm build. That is no longer true, and was measured on production before
    # removing this: a native QInputDialog constructed and shown reports
    # visible=True size=208x109 children=4 with real geometry. QMessageBox likewise --
    # scratchpad/reg-prod.js clicks a native one at real pixels and requires the real
    # return value (16384), and dlgsuite.js opens Preferences with 1631 widgets.
    #
    # The blocking exec() these statics perform suspends correctly because
    # _fcweb_run_python is in ASYNCIFY_EXPORTS, which is the same mechanism the QMessageBox
    # bridge above relies on.
    #
    # NOTE the stubs could not simply be deleted at runtime to test this: Shiboken types
    # raise AttributeError on `del`, so the natives are unrecoverable once overwritten.
    # That is why this is a source change rather than a probe.

try:
    install()
    print("[fcweb] JSPI blocking-dialog bridge installed")
except Exception as _e:
    print("[fcweb] JSPI dialog bridge FAILED:", _e)
