// Python builtin `_fcwebccx` — runs the CalculiX wasm module and blocks until it finishes.
//
// FreeCAD's FEM solver normally writes an .inp and launches the ccx binary (subprocess or
// QProcess), then reads back the .frd and .dat. There is no fork/exec in the browser, so
// the Python side calls _fcwebccx.run(inp) instead. The heavy lifting is in JS
// (window.fcwebCcxRun) because ccx lives in a SEPARATE wasm module with its own
// filesystem: the files have to be handed across.
//
// EM_ASYNC_JS makes this a WebAssembly.Suspending import, so when it is called from the
// promising fcweb_run_python export the whole wasm stack — CPython frame included —
// suspends until the JS promise settles. Same mechanism as the gmsh bridge.
//
// Compile: em++ -fwasm-exceptions -pthread -O2 -I<python-include> -c fcweb_ccx_module.cpp \
//               -o weh-objs/fcweb_ccx_module.o

#include <Python.h>
#include <emscripten.h>

// Runs ccx on `inpPath` (a full path in FreeCAD's FS) and writes the results next to it.
// Returns ccx's exit code, or -1 if the bridge is missing.
EM_ASYNC_JS(int, fcweb_ccx_run_js, (const char* inpPath), {
    var g = (typeof window !== 'undefined') ? window : globalThis;
    if (!g || typeof g.fcwebCcxRun !== 'function') { return -1; }
    try {
        var rc = await g.fcwebCcxRun(UTF8ToString(inpPath));
        return rc | 0;
    } catch (e) {
        try { console.error('[fcweb] ccx run failed', e); } catch (_) {}
        return 1;
    }
});

EM_ASYNC_JS(char*, fcweb_ccx_version_js, (), {
    var g = (typeof window !== 'undefined') ? window : globalThis;
    if (!g || typeof g.fcwebCcxVersion !== 'function') { return 0; }
    try {
        var v = await g.fcwebCcxVersion();
        if (v === null || v === undefined) { return 0; }
        var s = String(v);
        var len = lengthBytesUTF8(s) + 1;
        var buf = _malloc(len);          // caller (C) frees
        stringToUTF8(s, buf, len);
        return buf;
    } catch (e) { return 0; }
});

// _fcwebccx.run(inp_path) -> int return code
static PyObject* fcwebccx_run(PyObject* /*self*/, PyObject* args)
{
    const char* inp = "";
    if (!PyArg_ParseTuple(args, "s", &inp)) {
        return nullptr;
    }
    int rc = fcweb_ccx_run_js(inp);
    return PyLong_FromLong(rc);
}

// _fcwebccx.version() -> str | None
static PyObject* fcwebccx_version(PyObject* /*self*/, PyObject* /*args*/)
{
    char* v = fcweb_ccx_version_js();
    if (!v) { Py_RETURN_NONE; }
    PyObject* s = PyUnicode_FromString(v);
    free(v);
    return s;
}

// _fcwebccx.available() -> bool. Cheap check that does not load the module, so the
// solver task panel can tell the user up front.
static PyObject* fcwebccx_available(PyObject* /*self*/, PyObject* /*args*/)
{
    int ok = EM_ASM_INT({
        var g = (typeof window !== 'undefined') ? window : globalThis;
        return (g && typeof g.fcwebCcxRun === 'function') ? 1 : 0;
    });
    return PyBool_FromLong(ok);
}

static PyMethodDef fcwebccx_methods[] = {
    {"run", fcwebccx_run, METH_VARARGS,
     "run(inp_path) -> int. Solve with the CalculiX wasm module; blocks."},
    {"version", fcwebccx_version, METH_NOARGS, "version() -> str|None"},
    {"available", fcwebccx_available, METH_NOARGS, "available() -> bool"},
    {nullptr, nullptr, 0, nullptr}
};

static PyModuleDef fcwebccx_module = {
    PyModuleDef_HEAD_INIT, "_fcwebccx", "FreeCAD-Web in-browser CalculiX bridge", -1,
    fcwebccx_methods, nullptr, nullptr, nullptr, nullptr
};

extern "C" PyObject* PyInit__fcwebccx(void)
{
    return PyModule_Create(&fcwebccx_module);
}
