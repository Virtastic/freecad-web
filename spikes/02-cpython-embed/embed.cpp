// Spike (c): embed CPython in wasm and import a STATICALLY-LINKED builtin C++
// module via the inittab — the exact mechanism FreeCAD uses to expose its
// App/Base/Gui C++ extension modules to the embedded interpreter.
#include <Python.h>
#include <cstdio>
#include <cstdlib>
#include <string>

// A tiny built-in extension module: freecad_probe.ping() -> str
static PyObject *probe_ping(PyObject *, PyObject *)
{
    return PyUnicode_FromString("pong from C++ builtin");
}

static PyMethodDef ProbeMethods[] = {
    {"ping", probe_ping, METH_NOARGS, "return a string from C++"},
    {nullptr, nullptr, 0, nullptr},
};

static PyModuleDef ProbeModule = {
    PyModuleDef_HEAD_INIT, "freecad_probe", "spike builtin", -1, ProbeMethods,
    nullptr, nullptr, nullptr, nullptr,
};

static PyObject *PyInit_freecad_probe(void) { return PyModule_Create(&ProbeModule); }

int main(int argc, char **argv)
{
    std::fprintf(stderr, "[spike-c] main entered\n"); std::fflush(stderr);
    // Must register the builtin BEFORE Py_Initialize so `import` can find it.
    if (PyImport_AppendInittab("freecad_probe", PyInit_freecad_probe) != 0) {
        std::fprintf(stderr, "[spike-c] AppendInittab failed\n");
        return 1;
    }

    // Explicitly point the interpreter at the stdlib (no build-tree autodetect
    // since our embed binary isn't co-located with CPython's build markers).
    // Path comes from env FCWEB_PYLIB (set by the runner).
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    const char* pylib = std::getenv("FCWEB_PYLIB");
    if (pylib) {
        config.module_search_paths_set = 1;
        wchar_t* wlib = Py_DecodeLocale(pylib, nullptr);
        PyWideStringList_Append(&config.module_search_paths, wlib);
        PyMem_RawFree(wlib);
    }
    PyStatus status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        std::fprintf(stderr, "[spike-c] Py_InitializeFromConfig failed\n");
        return 1;
    }

    // Do the import + call in C (report via C stderr, which is wired to node);
    // Python's own sys.stdout isn't routed to node stdout in this minimal embed.
    int rc = 1;
    PyObject *mod = PyImport_ImportModule("freecad_probe");   // the inittab builtin
    if (!mod) { std::fprintf(stderr, "[spike-c] import freecad_probe FAILED\n"); }
    else {
        std::fprintf(stderr, "[spike-c] imported builtin module freecad_probe\n");
        PyObject *res = PyObject_CallMethod(mod, "ping", nullptr);
        if (res && PyUnicode_Check(res)) {
            const char *v = PyUnicode_AsUTF8(res);
            std::fprintf(stderr, "[spike-c] python->C++ ping() returned: \"%s\"\n", v);
            rc = (v && std::string(v) == "pong from C++ builtin") ? 0 : 1;
        } else {
            std::fprintf(stderr, "[spike-c] ping() call failed\n");
        }
        Py_XDECREF(res);
    }
    // Prove the embedded interpreter is real: read sys.version from C.
    PyObject *sysmod = PyImport_ImportModule("sys");
    if (sysmod) {
        PyObject *ver = PyObject_GetAttrString(sysmod, "version");
        if (ver) { std::fprintf(stderr, "[spike-c] sys.version: %s\n", PyUnicode_AsUTF8(ver)); Py_DECREF(ver); }
        Py_DECREF(sysmod);
    }
    std::fprintf(stderr, "%s\n", rc == 0 ? "[spike-c] PASS" : "[spike-c] FAIL");
    std::fflush(stderr);

    Py_XDECREF(mod);
    Py_Finalize();
    return rc;
}
