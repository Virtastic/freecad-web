// Link-time wrap of QDialog::exec() for the wasm/Asyncify build.
//
// WHY: emscripten Asyncify cannot suspend across a CPython interpreter frame — the
// frame state lives in CPython thread-state globals that Asyncify's local save/restore
// does not capture. So a modal QDialog::exec() entered while Python bytecode is on the
// C stack (a macro, `Gui.runCommand(...)` from Python, a Python-workbench command, a
// Python ViewProvider method, etc.) traps `RuntimeError: unreachable` and kills the whole
// wasm instance. C++/menu/toolbar-triggered dialogs have NO Python frame on the stack and
// suspend fine — those must keep working (real modal).
//
// WHAT: this wrap detects "a CPython frame is currently executing on this thread" and, in
// that case ONLY, degrades the modal exec() to a NON-blocking show() that returns
// Rejected(0) immediately — the exact graceful degradation the PySide shim
// (play-gui/wasm_dialog_shim.py) already applies to Python-*created* dialogs, extended
// here to C++-*created* dialogs (Help>About, Preferences, QMessageBox, QInputDialog,
// QFileDialog, ...). Outside Python it calls the real exec() unchanged.
//
// Coverage: QMessageBox / QInputDialog / QFileDialog / QColorDialog / QFontDialog have no
// own exec() symbol in Qt6 — they use the inherited QDialog::exec — and the static helpers
// (QMessageBox::warning/question/..., QInputDialog::getText, ...) all construct a dialog and
// call its exec(). So wrapping this single symbol degrades all of them, and e.g.
// QInputDialog::getText returns ("", false) for free when its internal exec() returns 0.
//
// Detection is precise (not a GIL heuristic): PyThreadState_GetFrame() is non-NULL iff
// Python bytecode is on the stack. We guard with PyGILState_Check() so we never touch
// CPython state without the GIL. The GIL can be held with no Python running (e.g. a C++
// command holding PyGILStateLocker to log a macro line) — in that case the frame is NULL,
// so menu-triggered C++ dialogs correctly stay real-modal.
//
// Compile (no headers needed — ABI-compatible minimal decls):
//   em++ -fexceptions -pthread -O2 -c dialog_exec_wrap.cpp -o dialog_exec_wrap.o
// Link (mirrors postevent_wrap.o):
//   -Wl,--wrap=_ZN7QDialog4execEv  dialog_exec_wrap.o

// --- Minimal, ABI-compatible CPython declarations (pointer args/returns are all one wasm
//     i32, so void* matches the real PyThreadState*/PyFrameObject*/PyObject* ABI). Avoids
//     pulling pyconfig.h / full Python.h into this tiny translation unit. Signatures verified
//     against deps/src/cpython/Include: Py_IsInitialized (pylifecycle.h), PyGILState_Check
//     (cpython/pystate.h), PyThreadState_Get / PyThreadState_GetFrame (pystate.h). ---
extern "C" {
    int   Py_IsInitialized(void);
    int   PyGILState_Check(void);
    void* PyThreadState_Get(void);
    void* PyThreadState_GetFrame(void* tstate);  // PyFrameObject* (NEW reference) or NULL
    void  Py_DecRef(void* obj);
}

// --- Qt entry points, referenced by their mangled names via extern "C" so the compiler
//     emits/expects them verbatim (no re-mangling). Verified defined in libQt6Widgets.a. ---
extern "C" {
    int  __real__ZN7QDialog4execEv(void* self);          // real QDialog::exec()
    void _ZN7QDialog8setModalEb(void* self, bool modal);  // QDialog::setModal(bool)
    void _ZN7QWidget4showEv(void* self);                  // QWidget::show()
    void _ZN7QWidget5raiseEv(void* self);                 // QWidget::raise()
}

extern "C" bool fcweb_is_running_python(void)
{
    if (!Py_IsInitialized()) return false;
    if (!PyGILState_Check())  return false;   // GIL not held here -> no Python executing on this thread
    void* ts = PyThreadState_Get();           // safe: GIL held
    if (!ts) return false;
    void* frame = PyThreadState_GetFrame(ts);  // non-NULL iff Python bytecode is on the stack
    bool running = (frame != nullptr);
    if (frame) Py_DecRef(frame);               // GetFrame returns a new reference
    return running;
}

extern "C" int __wrap__ZN7QDialog4execEv(void* self)
{
    if (fcweb_is_running_python()) {
        // A modal exec() here would asyncify-suspend across a CPython frame -> instance crash.
        // Degrade like the shim: show the dialog non-blocking (still visible/interactive) and
        // return Rejected(0) so the caller fails toward cancel / no-change and keeps running.
        _ZN7QDialog8setModalEb(self, false);
        _ZN7QWidget4showEv(self);
        _ZN7QWidget5raiseEv(self);
        return 0;   // QDialog::Rejected == QMessageBox::NoButton == 0
    }
    return __real__ZN7QDialog4execEv(self);
}
