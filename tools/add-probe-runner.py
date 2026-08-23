"""Extend the init-failure diagnostics with a bytecode replay and an ENV probe runner.

Run AFTER tools/fix-init-exc-print.py (patch-text surgery on the same hunk).

WHY: every _setup ingredient replayed fine from C (is_frozen returns bool, sys.modules
pristine), yet the same operations fail from _setup's BYTECODE. Two additions:
  1. replay _frozen_importlib._install(sys, _imp) wholesale from C -- if that
     reproduces the SystemError we own an on-demand repro at the failure point;
  2. FCWEB_PROBE: arbitrary Python source from the environment, compiled and run at
     the failure point with sys/_imp/_bootstrap injected -- every future hypothesis
     becomes a 3.5-minute browser reload instead of a two-hour rebuild.
"""
import io
import re

NL = chr(92) + 'n'

ANCHOR = [
    "+                    PyObject* fcMeth = PyObject_GetAttrString(fcImp, \"is_frozen\");",
    '+                    fprintf(stderr, "[FCWEB] replay getattr(_imp,is_frozen): %s' + NL + '",',
    '+                            fcMeth ? Py_TYPE(fcMeth)->tp_name : "FAILED");',
    '+                }',
    '+            }',
]

ADD = [
    '+            if (fcMods) {',
    '+                PyObject* fcSysM = PyDict_GetItemString(fcMods, "sys");',
    '+                PyObject* fcImpM = PyDict_GetItemString(fcMods, "_imp");',
    '+                PyObject* fcBoot = PyDict_GetItemString(fcMods, "_frozen_importlib");',
    '+                // 1. replay the whole frozen _install from C. Same bytecode, same',
    '+                //    inputs -- reproducing here gives an on-demand repro.',
    '+                if (fcBoot && fcSysM && fcImpM) {',
    '+                    PyErr_Clear();',
    '+                    PyObject* fcR2 = PyObject_CallMethod(fcBoot, "_install", "OO", fcSysM, fcImpM);',
    '+                    if (fcR2) {',
    '+                        fprintf(stderr, "[FCWEB] replay _install: OK' + NL + '");',
    '+                    } else {',
    '+                        PyObject* fcT2 = nullptr;',
    '+                        PyObject* fcV2 = nullptr;',
    '+                        PyObject* fcB2 = nullptr;',
    '+                        PyErr_Fetch(&fcT2, &fcV2, &fcB2);',
    '+                        PyObject* fcS2 = fcV2 ? PyObject_Str(fcV2) : nullptr;',
    '+                        fprintf(stderr, "[FCWEB] replay _install FAILED: %s' + NL + '",',
    '+                                (fcS2 && PyUnicode_Check(fcS2)) ? PyUnicode_AsUTF8(fcS2) : "(?)");',
    '+                        for (PyObject* fcC2 = fcB2; fcC2 && fcC2 != Py_None;) {',
    '+                            PyTracebackObject* fcO2 = reinterpret_cast<PyTracebackObject*>(fcC2);',
    '+                            PyCodeObject* fcK2 = fcO2->tb_frame ? PyFrame_GetCode(fcO2->tb_frame) : nullptr;',
    '+                            if (fcK2) {',
    '+                                fprintf(stderr, "[FCWEB]   at %s:%d' + NL + '",',
    '+                                        PyUnicode_AsUTF8(fcK2->co_name), fcO2->tb_lineno);',
    '+                            }',
    '+                            fcC2 = reinterpret_cast<PyObject*>(fcO2->tb_next);',
    '+                        }',
    '+                    }',
    '+                }',
    '+                // 2. FCWEB_PROBE: run arbitrary Python from the environment at this',
    '+                //    exact failure point. Iterating hypotheses via ENV costs a page',
    '+                //    reload; iterating via patch costs a two-hour CI round.',
    '+                const char* fcProbe = getenv("FCWEB_PROBE");',
    '+                if (fcProbe && fcProbe[0]) {',
    '+                    PyErr_Clear();',
    '+                    PyObject* fcG = PyDict_New();',
    '+                    PyObject* fcBins = PyDict_GetItemString(fcMods, "builtins");',
    '+                    if (fcG && fcBins) {',
    '+                        PyDict_SetItemString(fcG, "__builtins__", fcBins);',
    '+                        if (fcSysM) PyDict_SetItemString(fcG, "sys", fcSysM);',
    '+                        if (fcImpM) PyDict_SetItemString(fcG, "_imp", fcImpM);',
    '+                        if (fcBoot) PyDict_SetItemString(fcG, "_bootstrap", fcBoot);',
    '+                        PyObject* fcPR = PyRun_String(fcProbe, Py_file_input, fcG, fcG);',
    '+                        if (fcPR) {',
    '+                            PyObject* fcOut = PyDict_GetItemString(fcG, "OUT");',
    '+                            PyObject* fcOS = fcOut ? PyObject_Str(fcOut) : nullptr;',
    '+                            fprintf(stderr, "[FCWEB] probe OK: %s' + NL + '",',
    '+                                    (fcOS && PyUnicode_Check(fcOS)) ? PyUnicode_AsUTF8(fcOS) : "(no OUT)");',
    '+                        } else {',
    '+                            PyObject* fcT3 = nullptr;',
    '+                            PyObject* fcV3 = nullptr;',
    '+                            PyObject* fcB3 = nullptr;',
    '+                            PyErr_Fetch(&fcT3, &fcV3, &fcB3);',
    '+                            PyObject* fcTS = fcT3 ? PyObject_Str(fcT3) : nullptr;',
    '+                            PyObject* fcVS = fcV3 ? PyObject_Str(fcV3) : nullptr;',
    '+                            fprintf(stderr, "[FCWEB] probe FAILED: %s :: %s' + NL + '",',
    '+                                    (fcTS && PyUnicode_Check(fcTS)) ? PyUnicode_AsUTF8(fcTS) : "(?)",',
    '+                                    (fcVS && PyUnicode_Check(fcVS)) ? PyUnicode_AsUTF8(fcVS) : "(?)");',
    '+                            for (PyObject* fcC3 = fcB3; fcC3 && fcC3 != Py_None;) {',
    '+                                PyTracebackObject* fcO3 = reinterpret_cast<PyTracebackObject*>(fcC3);',
    '+                                PyCodeObject* fcK3 = fcO3->tb_frame ? PyFrame_GetCode(fcO3->tb_frame) : nullptr;',
    '+                                if (fcK3) {',
    '+                                    fprintf(stderr, "[FCWEB]   at %s:%d' + NL + '",',
    '+                                            PyUnicode_AsUTF8(fcK3->co_name), fcO3->tb_lineno);',
    '+                                }',
    '+                                fcC3 = reinterpret_cast<PyObject*>(fcO3->tb_next);',
    '+                            }',
    '+                        }',
    '+                    }',
    '+                }',
    '+            }',
]


def main():
    p = 'patches/freecad.patch'
    raw = io.open(p, 'rb').read().split(b'\n')
    anc = [x.encode() for x in ANCHOR]
    start = None
    for k in range(len(raw) - len(anc)):
        if all(raw[k + n].rstrip(b'\r') == anc[n] for n in range(len(anc))):
            start = k
            break
    assert start is not None, 'anchor not found'
    CR = b'\r' if raw[start].endswith(b'\r') else b''
    ins = [x.encode() + CR for x in ADD]
    pos = start + len(anc)
    raw[pos:pos] = ins

    h = max(k for k in range(start) if raw[k].startswith(b'@@'))
    m = re.match(rb'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', raw[h])
    raw[h] = b'@@ -%s,%s +%s,%d @@' % (m.group(1), m.group(2), m.group(3),
                                       int(m.group(4)) + len(ins)) + \
             (CR if raw[h].endswith(b'\r') else b'')
    io.open(p, 'wb').write(b'\n'.join(raw))
    print('inserted %d lines at %d; hunk header now %s' % (len(ins), pos + 1, raw[h][:26]))


if __name__ == '__main__':
    main()
