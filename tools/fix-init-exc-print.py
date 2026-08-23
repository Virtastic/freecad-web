# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Make the port's Py_InitializeFromConfig failure branch print the pending exception.

One-shot patch-text surgery on the existing @@ -641 Interpreter.cpp hunk (port-authored
lines, so the pristine-diff regenerator cannot express this edit).

WHY: _PyImport_InitCore fails during importlib's _install -- the first real bytecode
execution -- and the current print gates the exception dump behind Py_IsInitialized(),
which is 0 during a failed init even though a thread state exists and PyErr_Occurred()
would answer. The real error is sitting right there unprinted.
"""
import io

NL = chr(92) + 'n'

OLD = [
    '+        if (Py_IsInitialized() && PyErr_Occurred()) {',
    '+            fprintf(stderr, "[FCWEB] pending Python exception:' + NL + '");',
    '+            PyErr_Print();',
    '+        } else {',
    '+            fprintf(stderr, "[FCWEB] no pending Python exception (Py_IsInitialized=%d)' + NL + '",',
    '+                    Py_IsInitialized());',
    '+        }',
]
NEW = [
    '+        // Py_IsInitialized() is 0 during a FAILED init, but a thread state exists and',
    '+        // the real error is pending -- fetch and print it unconditionally.',
    '+        if (PyErr_Occurred()) {',
    '+            PyObject* fcT = nullptr;',
    '+            PyObject* fcV = nullptr;',
    '+            PyObject* fcTb = nullptr;',
    '+            PyErr_Fetch(&fcT, &fcV, &fcTb);',
    '+            PyObject* fcTs = fcT ? PyObject_Str(fcT) : nullptr;',
    '+            PyObject* fcVs = fcV ? PyObject_Str(fcV) : nullptr;',
    '+            fprintf(stderr, "[FCWEB] pending: %s :: %s' + NL + '",',
    '+                    (fcTs && PyUnicode_Check(fcTs)) ? PyUnicode_AsUTF8(fcTs) : "(?)",',
    '+                    (fcVs && PyUnicode_Check(fcVs)) ? PyUnicode_AsUTF8(fcVs) : "(?)");',
    '+            // walk the traceback in C: PyErr_Print needs sys/io, which do not exist',
    '+            // this early, so it renders a bare header with no frames.',
    '+            for (PyObject* fcCur = fcTb; fcCur && fcCur != Py_None;) {',
    '+                PyTracebackObject* fcTbo = reinterpret_cast<PyTracebackObject*>(fcCur);',
    '+                PyFrameObject* fcFr = fcTbo->tb_frame;',
    '+                PyCodeObject* fcCo = fcFr ? PyFrame_GetCode(fcFr) : nullptr;',
    '+                if (fcCo) {',
    '+                    fprintf(stderr, "[FCWEB]   at %s (%s:%d)' + NL + '",',
    '+                            PyUnicode_AsUTF8(fcCo->co_name),',
    '+                            PyUnicode_AsUTF8(fcCo->co_filename), fcTbo->tb_lineno);',
    '+                }',
    '+                fcCur = reinterpret_cast<PyObject*>(fcTbo->tb_next);',
    '+            }',
    '+        } else {',
    '+            fprintf(stderr, "[FCWEB] init failed, NO pending exception (Py_IsInitialized=%d)' + NL + '",',
    '+                    Py_IsInitialized());',
    '+        }',
    '+        // The raise is inside frozen _setup, whose direct C calls consume collections',
    '+        // built from the inittab (sys.builtin_module_names). Dump both: a garbage or',
    '+        // NULL entry here convicts the table machinery in one run.',
    '+        {',
    '+            int fcN = 0;',
    '+            for (struct _inittab* fcP = PyImport_Inittab; fcP && fcP->name; ++fcP, ++fcN) {',
    '+                if (fcN < 6 || !fcP->initfunc) {',
    '+                    fprintf(stderr, "[FCWEB]   inittab[%d] name=%s init=%p' + NL + '",',
    '+                            fcN, fcP->name, reinterpret_cast<void*>(fcP->initfunc));',
    '+                }',
    '+            }',
    '+            fprintf(stderr, "[FCWEB] inittab total=%d' + NL + '", fcN);',
    '+            PyObject* fcBn = PySys_GetObject("builtin_module_names");',
    '+            if (fcBn && PyTuple_Check(fcBn)) {',
    '+                const Py_ssize_t fcL = PyTuple_GET_SIZE(fcBn);',
    '+                fprintf(stderr, "[FCWEB] builtin_module_names len=%zd:' + NL + '", fcL);',
    '+                for (Py_ssize_t fcI = 0; fcI < fcL; ++fcI) {',
    '+                    PyObject* fcIt = PyTuple_GET_ITEM(fcBn, fcI);',
    '+                    const char* fcNm = "<NULL>";',
    '+                    if (fcIt) {',
    '+                        fcNm = PyUnicode_Check(fcIt) ? PyUnicode_AsUTF8(fcIt) : "<non-str>";',
    '+                    }',
    '+                    fprintf(stderr, "[FCWEB]   bn[%zd]=%s' + NL + '", fcI, fcNm);',
    '+                }',
    '+            } else {',
    '+                fprintf(stderr, "[FCWEB] builtin_module_names: %s' + NL + '",',
    '+                        fcBn ? "<non-tuple>" : "<absent>");',
    '+            }',
    '+            // Replay the _setup direct C calls one by one; whichever reproduces the',
    '+            // null-argument SystemError is the culprit. (The table and tuple dumped',
    '+            // clean, so the data is fine and one of these CALLS is not.)',
    '+            PyObject* fcMods = PyImport_GetModuleDict();',
    '+            fprintf(stderr, "[FCWEB] sys.modules: %s' + NL + '",',
    '+                    fcMods ? Py_TYPE(fcMods)->tp_name : "<NULL>");',
    '+            if (fcMods) {',
    '+                PyObject* fcKey = nullptr;',
    '+                PyObject* fcVal = nullptr;',
    '+                Py_ssize_t fcPos = 0;',
    '+                while (PyDict_Next(fcMods, &fcPos, &fcKey, &fcVal)) {',
    '+                    fprintf(stderr, "[FCWEB]   modules[%s] type=%s' + NL + '",',
    '+                            PyUnicode_Check(fcKey) ? PyUnicode_AsUTF8(fcKey) : "<?>",',
    '+                            fcVal ? Py_TYPE(fcVal)->tp_name : "<NULL>");',
    '+                }',
    '+                PyObject* fcImp = PyDict_GetItemString(fcMods, "_imp");',
    '+                if (fcImp) {',
    '+                    PyErr_Clear();',
    '+                    PyObject* fcR = PyObject_CallMethod(fcImp, "is_frozen", "s", "_frozen_importlib");',
    '+                    if (fcR) {',
    '+                        fprintf(stderr, "[FCWEB] replay _imp.is_frozen: OK (%s)' + NL + '",',
    '+                                Py_TYPE(fcR)->tp_name);',
    '+                    } else {',
    '+                        PyObject* fcEt = nullptr;',
    '+                        PyObject* fcEv = nullptr;',
    '+                        PyObject* fcEb = nullptr;',
    '+                        PyErr_Fetch(&fcEt, &fcEv, &fcEb);',
    '+                        PyObject* fcEs = fcEv ? PyObject_Str(fcEv) : nullptr;',
    '+                        fprintf(stderr, "[FCWEB] replay _imp.is_frozen FAILED: %s' + NL + '",',
    '+                                (fcEs && PyUnicode_Check(fcEs)) ? PyUnicode_AsUTF8(fcEs) : "(?)");',
    '+                    }',
    '+                    PyErr_Clear();',
    '+                    PyObject* fcMeth = PyObject_GetAttrString(fcImp, "is_frozen");',
    '+                    fprintf(stderr, "[FCWEB] replay getattr(_imp,is_frozen): %s' + NL + '",',
    '+                            fcMeth ? Py_TYPE(fcMeth)->tp_name : "FAILED");',
    '+                }',
    '+            }',
    '+        }',
]


def main():
    p = 'patches/freecad.patch'
    raw = io.open(p, 'rb').read().split(b'\n')
    # locate the OLD block inside the Interpreter.cpp @@ -641 hunk
    old_b = [x.encode() for x in OLD]
    start = None
    for k in range(len(raw) - len(old_b)):
        if all(raw[k + n].rstrip(b'\r') == old_b[n] for n in range(len(old_b))):
            start = k
            break
    assert start is not None, 'old block not found'
    CR = b'\r' if raw[start].endswith(b'\r') else b''
    new_b = [x.encode() + CR for x in NEW]
    raw[start:start + len(old_b)] = new_b

    # fix the enclosing hunk header's new-side count (+13 lines: 20 new - 7 old)
    h = max(k for k in range(start) if raw[k].startswith(b'@@'))
    import re
    m = re.match(rb'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', raw[h])
    raw[h] = b'@@ -%s,%s +%s,%d @@' % (m.group(1), m.group(2), m.group(3),
                                       int(m.group(4)) + len(new_b) - len(old_b)) + \
             (CR if raw[h].endswith(b'\r') else b'')
    io.open(p, 'wb').write(b'\n'.join(raw))
    print('replaced at line %d; hunk header now %s' % (start + 1, raw[h][:26]))


if __name__ == '__main__':
    main()
