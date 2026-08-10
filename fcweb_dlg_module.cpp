// A tiny Python builtin module `_fcwebdlg` exposing a BLOCKING confirm dialog
// that returns the user's REAL choice. Native Qt QMessageBox windows don't
// composite their content on this Qt-for-WebAssembly build (frame paints, body
// + buttons don't), so a Python-triggered modal can't be completed by a click.
// Instead we render an HTML modal overlay and, under JSPI, SUSPEND the promising
// _fcweb_run_python call until the user clicks a button, returning its index.
//
// EM_ASYNC_JS makes fcweb_html_confirm a WebAssembly.Suspending import: when
// called from a promising export (fcweb_run_python is in JSPI_EXPORTS) it
// suspends the wasm stack — INCLUDING the CPython frame, which JSPI carries
// along natively — and resumes with the clicked button's index. This is exactly
// the capability Asyncify could not provide (it can't suspend across a CPython
// frame); JSPI can.
//
// Compile: em++ -fwasm-exceptions -pthread -O2 -I<python-include> -c fcweb_dlg_module.cpp -o fcweb_dlg_module.o

#include <Python.h>
#include <emscripten.h>
#include <string>

// Synchronously build the HTML modal and arm a result slot. The clicked button's
// index is written to window.__fcDlgResult. Uses EM_ASM (no suspend) — DOM
// creation from the main thread is known to work.
// EM_ASYNC_JS: show the harness HTML modal and SUSPEND on its own Promise
// (resolved by the button click), mirroring Qt's manual-promise resume
// (Module.qtAsyncifyWakeUp) rather than emscripten_sleep — the latter shares
// emscripten's global asyncify bookkeeping and does not resume from a second
// concurrent promising call while the Qt main loop is parked.
EM_ASYNC_JS(int, fcweb_html_confirm, (const char* title, const char* text, const char* buttons), {
    var g = (typeof window !== 'undefined') ? window : globalThis;
    g.__fcDlgBodyRan = (g.__fcDlgBodyRan | 0) + 1;
    var t = UTF8ToString(title), msg = UTF8ToString(text), bs = UTF8ToString(buttons);
    if (g && typeof g.fcwebConfirm === 'function') {
        var idx = await g.fcwebConfirm(t, msg, bs);
        return idx | 0;
    }
    return 0;
});

// Blocking HTML text-entry modal. Returns the entered string, or NULL (via the
// EM_ASYNC_JS sentinel) if the user cancels. Suspends (JSPI) until submit/cancel.
// window.fcwebPrompt(title, text, default) -> Promise<string|null> lives in the harness.
EM_ASYNC_JS(char*, fcweb_html_prompt, (const char* title, const char* text, const char* deflt), {
    var g = (typeof window !== 'undefined') ? window : globalThis;
    var t = UTF8ToString(title), msg = UTF8ToString(text), d = UTF8ToString(deflt);
    if (!g || typeof g.fcwebPrompt !== 'function') return 0;
    var v = await g.fcwebPrompt(t, msg, d);
    if (v === null || v === undefined) return 0;   // cancelled
    var s = String(v);
    var len = lengthBytesUTF8(s) + 1;
    var buf = _malloc(len);          // caller (C) frees
    stringToUTF8(s, buf, len);
    return buf;
});

// Python: _fcwebdlg.prompt(title, text, default="") -> str | None (None == cancel)
static PyObject* fcwebdlg_prompt(PyObject* /*self*/, PyObject* args)
{
    const char* title = "";
    const char* text = "";
    const char* deflt = "";
    if (!PyArg_ParseTuple(args, "ss|s", &title, &text, &deflt))
        return nullptr;
    char* res = fcweb_html_prompt(title, text, deflt);
    if (!res) { Py_RETURN_NONE; }
    PyObject* s = PyUnicode_FromString(res);
    free(res);
    return s;
}

// Blocking HTML color picker. `initial` is 0xRRGGBB. Returns the chosen color as
// 0xRRGGBB, or -1 if cancelled. Suspends (JSPI) until submit/cancel.
EM_ASYNC_JS(int, fcweb_html_color, (const char* title, int initial), {
    var g = (typeof window !== 'undefined') ? window : globalThis;
    var t = UTF8ToString(title);
    if (!g || typeof g.fcwebColor !== 'function') return -1;
    var v = await g.fcwebColor(t, initial | 0);
    return (v === null || v === undefined) ? -1 : (v | 0);
});

// Python: _fcwebdlg.color(title, initial_rgb_int) -> int 0xRRGGBB | None
static PyObject* fcwebdlg_color(PyObject* /*self*/, PyObject* args)
{
    const char* title = "";
    long initial = 0;
    if (!PyArg_ParseTuple(args, "s|l", &title, &initial))
        return nullptr;
    int rgb = fcweb_html_color(title, (int)initial);
    if (rgb < 0) { Py_RETURN_NONE; }
    return PyLong_FromLong(rgb);
}

// Python: _fcwebdlg.confirm(title, text, [labels...]) -> int index
static PyObject* fcwebdlg_confirm(PyObject* /*self*/, PyObject* args)
{
    const char* title = "";
    const char* text = "";
    PyObject* labels = nullptr;
    if (!PyArg_ParseTuple(args, "ssO", &title, &text, &labels))
        return nullptr;

    // join labels with '|'
    std::string joined;
    PyObject* seq = PySequence_Fast(labels, "labels must be a sequence");
    if (!seq) return nullptr;
    Py_ssize_t n = PySequence_Fast_GET_SIZE(seq);
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject* item = PySequence_Fast_GET_ITEM(seq, i);
        PyObject* str = PyObject_Str(item);
        if (str) {
            const char* c = PyUnicode_AsUTF8(str);
            if (c) { if (!joined.empty()) joined += '|'; joined += c; }
            Py_DECREF(str);
        }
    }
    Py_DECREF(seq);

    int idx = fcweb_html_confirm(title, text, joined.c_str());
    return PyLong_FromLong(idx);
}

static PyMethodDef fcwebdlg_methods[] = {
    {"confirm", fcwebdlg_confirm, METH_VARARGS,
     "confirm(title, text, labels) -> index. Blocking HTML modal; returns clicked button index."},
    {"prompt", fcwebdlg_prompt, METH_VARARGS,
     "prompt(title, text, default='') -> str|None. Blocking HTML text entry; None on cancel."},
    {"color", fcwebdlg_color, METH_VARARGS,
     "color(title, initial_rgb) -> int 0xRRGGBB | None. Blocking HTML color picker."},
    {nullptr, nullptr, 0, nullptr}
};

static PyModuleDef fcwebdlg_module = {
    PyModuleDef_HEAD_INIT, "_fcwebdlg", "FreeCAD-Web blocking HTML dialogs", -1, fcwebdlg_methods,
    nullptr, nullptr, nullptr, nullptr
};

extern "C" PyObject* PyInit__fcwebdlg(void)
{
    return PyModule_Create(&fcwebdlg_module);
}
