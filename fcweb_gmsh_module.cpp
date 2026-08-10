// Python builtin `_fcwebgmsh` — runs the gmsh wasm module and blocks until it finishes.
//
// FreeCAD's femmesh/gmshtools.py normally launches the gmsh binary (QProcess or
// subprocess) and then reads the .unv it produced. There is no fork/exec in the browser,
// so the Python side calls _fcwebgmsh.run(geo, brep, unv) instead. The heavy lifting is
// in JS (window.fcwebGmshRun) because gmsh lives in a SEPARATE wasm module with its own
// filesystem: the bytes have to be handed across.
//
// EM_ASYNC_JS makes this a WebAssembly.Suspending import, so when it is called from the
// promising fcweb_run_python export the whole wasm stack — CPython frame included —
// suspends until the JS promise settles. Same mechanism as the blocking HTML dialogs in
// fcweb_dlg_module.cpp; it is what lets a synchronous-looking Python call wait for an
// asynchronous module load without freezing the browser.
//
// Compile: em++ -fwasm-exceptions -pthread -O2 -I<python-include> -c fcweb_gmsh_module.cpp \
//              -o weh-objs/fcweb_gmsh_module.o

#include <Python.h>
#include <emscripten.h>

#include <string>

// Runs gmsh on `geoPath` (which Merges `brepPath`) and writes `unvPath`, all paths in
// FreeCAD's FS. Returns 0 on success, non-zero on failure; -1 if the bridge is missing.
EM_ASYNC_JS(int, fcweb_gmsh_run_js,
            (const char* geoPath, const char* brepPath, const char* unvPath, int verbosity), {
    var g = (typeof window !== 'undefined') ? window : globalThis;
    if (!g || typeof g.fcwebGmshRun !== 'function') { return -1; }
    try {
        var rc = await g.fcwebGmshRun(UTF8ToString(geoPath),
                                      UTF8ToString(brepPath),
                                      UTF8ToString(unvPath),
                                      verbosity | 0);
        return rc | 0;
    } catch (e) {
        try { console.error('[fcweb] gmsh run failed', e); } catch (_) {}
        return 1;
    }
});

EM_ASYNC_JS(char*, fcweb_gmsh_version_js, (), {
    var g = (typeof window !== 'undefined') ? window : globalThis;
    if (!g || typeof g.fcwebGmshVersion !== 'function') { return 0; }
    try {
        var v = await g.fcwebGmshVersion();
        if (v === null || v === undefined) { return 0; }
        var s = String(v);
        var len = lengthBytesUTF8(s) + 1;
        var buf = _malloc(len);          // caller (C) frees
        stringToUTF8(s, buf, len);
        return buf;
    } catch (e) { return 0; }
});

// _fcwebgmsh.run(geo_path, brep_path, unv_path, verbosity=4) -> int return code
static PyObject* fcwebgmsh_run(PyObject* /*self*/, PyObject* args)
{
    const char* geo = "";
    const char* brep = "";
    const char* unv = "";
    int verbosity = 4;
    if (!PyArg_ParseTuple(args, "sss|i", &geo, &brep, &unv, &verbosity)) {
        return nullptr;
    }
    int rc = fcweb_gmsh_run_js(geo, brep, unv, verbosity);
    return PyLong_FromLong(rc);
}

// _fcwebgmsh.version() -> str | None
static PyObject* fcwebgmsh_version(PyObject* /*self*/, PyObject* /*args*/)
{
    char* v = fcweb_gmsh_version_js();
    if (!v) { Py_RETURN_NONE; }
    PyObject* s = PyUnicode_FromString(v);
    free(v);
    return s;
}

// _fcwebgmsh.available() -> bool. Cheap check that does not load the module, so the
// preferences page and the mesh task panel can tell the user up front.
static PyObject* fcwebgmsh_available(PyObject* /*self*/, PyObject* /*args*/)
{
    int ok = EM_ASM_INT({
        var g = (typeof window !== 'undefined') ? window : globalThis;
        return (g && typeof g.fcwebGmshRun === 'function') ? 1 : 0;
    });
    return PyBool_FromLong(ok);
}

static PyMethodDef fcwebgmsh_methods[] = {
    {"run", fcwebgmsh_run, METH_VARARGS,
     "run(geo, brep, unv, verbosity=4) -> int. Mesh with the gmsh wasm module; blocks."},
    {"version", fcwebgmsh_version, METH_NOARGS, "version() -> str|None"},
    {"available", fcwebgmsh_available, METH_NOARGS, "available() -> bool"},
    {nullptr, nullptr, 0, nullptr}
};

static PyModuleDef fcwebgmsh_module = {
    PyModuleDef_HEAD_INIT, "_fcwebgmsh", "FreeCAD-Web in-browser gmsh bridge", -1,
    fcwebgmsh_methods, nullptr, nullptr, nullptr, nullptr
};

extern "C" PyObject* PyInit__fcwebgmsh(void)
{
    return PyModule_Create(&fcwebgmsh_module);
}
