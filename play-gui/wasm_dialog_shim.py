# FreeCAD-WASM: make Python-triggered modal dialogs safe under Emscripten Asyncify.
#
# Why: on the wasm build (Qt-for-WebAssembly + -sASYNCIFY), a modal QDialog/
# QMessageBox exec() started from Python must asyncify-suspend across the CPython
# interpreter's C stack frame. CPython keeps its frame state in thread-state
# globals that asyncify's local save/restore does not capture, so the suspend
# corrupts the interpreter -> "RuntimeError: unreachable" / null-function traps
# that kill the whole instance. (C++-triggered dialogs have no Python frame on the
# stack and work fine; this only affects macros and Python-workbench dialogs.)
#
# A blocking exec() that returns the user's real choice is therefore impossible in
# this architecture. This shim degrades gracefully instead of crashing: the dialog
# is shown NON-blocking (show(), not exec()) and the call returns a safe default
# immediately (NoButton / Rejected / (value, False)) so the macro keeps running and
# fails toward "cancel / no change". The dialog stays on screen and interactive.
#
# Loaded once at boot from the wasm harness (freecad-gui.html), after PySide6 is
# imported. Import-guarded so a missing/renamed API never aborts boot.

import sys


def install():
    from PySide6 import QtWidgets as W, QtCore as C, QtGui as G

    NB = 0  # QMessageBox.NoButton == QDialog.Rejected == 0 -> safe "no choice"

    # ---- instance .exec / .exec_ : QDialog subclasses, QMessageBox(), QInputDialog()
    def _exec(self, *a, **k):
        try:
            self.setWindowModality(C.Qt.NonModal)
        except Exception:
            pass
        self.show()
        try:
            self.raise_()
        except Exception:
            pass
        return NB

    for cls in (W.QDialog, W.QMessageBox, W.QInputDialog):
        cls.exec = _exec
        cls.exec_ = _exec

    # ---- static QMessageBox.question / information / warning / critical
    def _make_msgbox_static(default_buttons):
        def _f(*a, **k):
            parent = a[0] if len(a) > 0 else k.get("parent")
            title = a[1] if len(a) > 1 else k.get("title", "")
            text = a[2] if len(a) > 2 else k.get("text", "")
            buttons = a[3] if len(a) > 3 else k.get("buttons", default_buttons)
            mb = W.QMessageBox(parent)
            try:
                mb.setWindowTitle(str(title))
                mb.setText(str(text))
                mb.setStandardButtons(buttons)
            except Exception:
                pass
            try:
                mb.setWindowModality(C.Qt.NonModal)
            except Exception:
                pass
            mb.show()
            return NB
        return staticmethod(_f)

    W.QMessageBox.question = _make_msgbox_static(W.QMessageBox.Yes | W.QMessageBox.No)
    W.QMessageBox.information = _make_msgbox_static(W.QMessageBox.Ok)
    W.QMessageBox.warning = _make_msgbox_static(W.QMessageBox.Ok)
    W.QMessageBox.critical = _make_msgbox_static(W.QMessageBox.Ok)

    # ---- static QInputDialog.getText / getItem / getInt / getDouble  -> (value, ok=False)
    W.QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    W.QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("", False))
    W.QInputDialog.getItem = staticmethod(
        lambda *a, **k: ((a[3][0] if len(a) > 3 and a[3] else ""), False))
    W.QInputDialog.getInt = staticmethod(
        lambda *a, **k: ((a[3] if len(a) > 3 else 0), False))
    W.QInputDialog.getDouble = staticmethod(
        lambda *a, **k: ((a[3] if len(a) > 3 else 0.0), False))

    # ---- static QFileDialog pickers -> empty selection (macros should prefer the
    #      native FreeCAD file bridge; a raw QFileDialog from Python would crash).
    W.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    W.QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
    W.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    W.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")

    # ---- static QColorDialog / QFontDialog -> invalid/default + ok=False
    W.QColorDialog.getColor = staticmethod(lambda *a, **k: G.QColor())
    W.QFontDialog.getFont = staticmethod(lambda *a, **k: (G.QFont(), False))


try:
    install()
    print("[fcweb] wasm dialog shim installed")
except Exception as _e:
    print("[fcweb] wasm dialog shim FAILED:", _e)
