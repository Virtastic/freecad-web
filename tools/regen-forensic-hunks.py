"""Regenerate the four boot-forensics hunks with real diff(1) and splice them in.

    python tools/regen-forensic-hunks.py <freecad-tree>

Replaces the hand-assembled hunks at @@ -259 / @@ -1293 / @@ -1665 (App/Application.cpp)
and @@ -695 (Gui/Application.cpp) in patches/freecad.patch.

WHY diff and not hand assembly: two rounds of hand-built hunks passed
tools/check-patch-applies.py (context byte-for-byte at the declared position, counts
consistent) and were still rejected by GNU patch 2.8 on BOTH Linux (CI) and Windows,
while a hunk diff(1) generated for the identical edit applied cleanly. Whatever format
subtlety GNU patch objects to, the fix is to stop hand-writing what diff exists to write.

The edits themselves (see the strings below): fprintf forensics for the startup failure
where GetParameterGroupByPath() misses on an Application whose map iterates as garbage.
"""
import io
import os
import subprocess
import sys

BS = chr(92)
NL = BS + 'n'          # two-character C escape, built without a backslash in source
Q = BS + '"'


def edit_app(lines, CR):
    def A(s):
        return s.encode() + CR
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if b'mpcPramManager["System parameter"]' in line:
            out += [
                A('    // FCWEB: boot-failure forensics. The startup exception pointed at an Application'),
                A('    // whose parameter map iterated as garbage -- these prints (ctor, destruct, failed'),
                A('    // lookup) say in one run whether the object queried later is the one built here,'),
                A('    // a freed one, or null. stderr reaches the page directly.'),
                A('    fprintf(stderr, "[fcweb] App::Application ctor this=%p' + NL + '", static_cast<void*>(this));'),
            ]
            out.append(line)
        elif b'GetParameterGroupByPath() no parameter set name specified' in line:
            out += [
                A('        // FCWEB: name the offending path; the bare message costs a debugging cycle'),
                A('        // in the browser.'),
                A('        throw Base::ValueError(std::string("Application::GetParameterGroupByPath()"'),
                A('                                           " no parameter set name in ' + Q + '") + sName + "' + Q + '");'),
            ]
        elif line.rstrip(b'\r').strip() == b'if (It == mpcPramManager.end())':
            out.append(A('    if (It == mpcPramManager.end()) {'))
        elif b'GetParameterGroupByPath() unknown parameter set name specified' in line:
            out += [
                A('        // FCWEB: print identity BEFORE touching the map further. "User parameter" is'),
                A('        // inserted unconditionally by the ctor, so a miss means this object is not a'),
                A('        // live Application. (An earlier diagnostic iterated the map into the message:'),
                A('        // on the corrupt object it appended empty-quoted keys until the 2 GB heap'),
                A('        // died. Nothing that walks the map belongs here.)'),
                A('        fprintf(stderr, "[fcweb] GetParameterGroupByPath MISS set=%s path=%s"'),
                A('                        " this=%p singleton=%p mapsize=%zu' + NL + '",'),
                A('                cTemp.c_str(), sName, static_cast<void*>(this),'),
                A('                static_cast<void*>(_pcSingleton), mpcPramManager.size());'),
                A('        throw Base::ValueError(std::string("Application::GetParameterGroupByPath()"'),
                A('                               " unknown parameter set ' + Q + '") + cTemp + "' + Q + ' in ' + Q + '" + sName + "' + Q + '");'),
                A('    }'),
            ]
        elif line.rstrip(b'\r') == b'void Application::destruct()':
            out.append(line)
            out.append(lines[i + 1])          # '{'
            out += [
                A('    // FCWEB: see the ctor print. If this ever appears before the failed lookup, the'),
                A('    // teardown-during-startup theory is back on.'),
                A('    fprintf(stderr, "[fcweb] App::Application::destruct() singleton=%p' + NL + '",'),
                A('            static_cast<void*>(_pcSingleton));'),
            ]
            i += 1
        else:
            out.append(line)
        i += 1
    return out


def edit_gui(lines, CR):
    def A(s):
        return s.encode() + CR
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if line.rstrip(b'\r') == b'Application::~Application()':
            out.append(lines[i + 1])          # '{'
            out.append(lines[i + 2])          # Base::Console().log(...)
            out += [
                A('    // FCWEB: boot-failure forensics, pair of the prints in App/Application.cpp.'),
                A('    fprintf(stderr, "[fcweb] Gui::Application DTOR' + NL + '");'),
            ]
            i += 2
        i += 1
    return out


def edit_sketcher(lines, CR):
    """The root cause the forensics found. Two anonymous-namespace globals call
    Gui::ViewParams::instance() -> GetParameterGroupByPath() at static-init time. On
    desktop SketcherGui is a shared library loaded after App::Application::init(); in the
    static wasm monolith every static ctor runs in __wasm_call_ctors, BEFORE main(), so
    the App singleton is null and the lookup throws Base::ValueError with nothing to catch
    it -- the boot failure this whole chain of diagnostics was chasing. Identified by
    scanning __wasm_call_ctors' call sequence in the binary (tools/find-ctor-caller.py):
    one SbColor ctor, instance(), color-unpack, instance(), color-unpack, then the long
    run of SbColor statics -- exactly this file, lines 58-66.

    The values are only PLACEHOLDERS: DrawingParameters' constructor re-assigns
    CrossColorH/V from ViewParams when Sketcher edit mode starts, post-App-init. So the
    fix is the ViewParams DEFAULTS (AxisXColor 0xCC333300, AxisYColor 0x33CC3300 --
    ViewParams.h lines 69-70), constant-initialized, no call at all."""
    def A(t):
        return t.encode() + CR
    out = []
    for line in lines:
        if b'HColorLong = Gui::ViewParams::instance()->getAxisXColor();' in line:
            out += [A('// FCWEB: ViewParams::instance() here ran in __wasm_call_ctors, before main()'),
                    A('// created the App::Application singleton, and threw Base::ValueError out of the'),
                    A('// static initializer -- the wasm boot failure. (Desktop never sees this:'),
                    A('// SketcherGui is a shared library, loaded after App init.) These are only'),
                    A('// placeholders: the DrawingParameters ctor re-reads ViewParams when edit mode'),
                    A('// starts -- so use the ViewParams defaults and make no call at all.'),
                    A('unsigned long HColorLong = 0xCC333300;  // ViewParams AxisXColor default')]
        elif b'VColorLong = Gui::ViewParams::instance()->getAxisYColor();' in line:
            out.append(A('unsigned long VColorLong = 0x33CC3300;  // ViewParams AxisYColor default'))
        else:
            out.append(line)
    return out


def edit_maingui(lines, CR):
    """Prove the Python error machinery works BEFORE any Gui/PySide code runs. The
    post-boot crash is an infinite _PyErr_SetObject/_PyErr_Format mutual recursion --
    raising ANY exception loops until the stack dies, which requires even
    PyExceptionClass_Check(PyExc_SystemError) to fail. If this selftest already loops or
    prints exc_check=0, core interpreter state is broken from init (a duplicate CPython
    static winning under --allow-multiple-definition); if it prints ok=1 exc_check=1, the
    machinery is intact here and a LATER import (PySide, most likely) breaks it."""
    def A(t):
        return t.encode() + CR
    out = []
    for line in lines:
        if line.rstrip(bytes([13])).strip() == b'// to set window icon on wayland, the desktop file has to be available to the compositor':
            out += [A('#if defined(__EMSCRIPTEN__)'),
                    A('        {'),
                    A('            // FCWEB: selftest of the Python error machinery, pre-Gui. See the'),
                    A('            // regen tool for the full account of the PyErr recursion this probes.'),
                    A('            // emscripten_log, not fprintf: stderr writes from the main phase'),
                    A('            // never reached the page (the pre-main MISS print did), while the'),
                    A('            // PyEM prints via emscripten_log always arrive.'),
                    A('            Base::PyGILStateLocker fcwebLock;'),
                    A('            emscripten_log(EM_LOG_ERROR, "[fcweb] pyerr selftest: raising...");'),
                    A('            PyErr_SetString(PyExc_ValueError, "fcweb selftest");'),
                    A('            const int fcwebOk = PyErr_ExceptionMatches(PyExc_ValueError);'),
                    A('            PyErr_Clear();'),
                    A('            emscripten_log(EM_LOG_ERROR, "[fcweb] pyerr selftest: ok=%d exc_check=%d",'),
                    A('                           fcwebOk, PyExceptionClass_Check(PyExc_SystemError));'),
                    A('        }'),
                    A('#endif')]
        out.append(line)
    return out


def main():
    tree = sys.argv[1]
    tmp = os.path.join(tree, '..', 'dgen')
    os.makedirs(tmp, exist_ok=True)
    specs = [('src/App/Application.cpp', edit_app), ('src/Gui/Application.cpp', edit_gui),
             ('src/Mod/Sketcher/Gui/EditModeCoinManagerParameters.cpp', edit_sketcher),
             ('src/Main/MainGui.cpp', edit_maingui)]
    blocks = {}
    for rel, fn in specs:
        raw = io.open(os.path.join(tree, rel), 'rb').read()
        lines = raw.split(b'\n')
        CR = b'\r' if lines[0].endswith(b'\r') else b''
        edited = fn(lines, CR)
        a = os.path.join(tmp, 'a.tmp')
        b = os.path.join(tmp, 'b.tmp')
        io.open(a, 'wb').write(b'\n'.join(lines))
        io.open(b, 'wb').write(b'\n'.join(edited))
        r = subprocess.run(['diff', '-u', a, b], capture_output=True)
        assert r.returncode == 1, (rel, r.returncode, r.stderr[:200])
        dl = r.stdout.split(b'\n')
        h0 = next(k for k, l in enumerate(dl) if l.startswith(b'@@'))
        hunks = dl[h0:]
        while hunks and hunks[-1] == b'':
            hunks.pop()
        blocks[rel] = hunks
        print(rel, 'diff produced', sum(1 for l in hunks if l.startswith(b'@@')), 'hunk(s)')

    patch_path = 'patches/freecad.patch'
    raw = io.open(patch_path, 'rb').read().split(b'\n')

    def block_range(name):
        i = next(k for k, l in enumerate(raw) if l.startswith(b'diff -ruNp a/' + name))
        j = next((k for k in range(i + 1, len(raw)) if raw[k].startswith(b'diff -ruNp ')), len(raw))
        return i, j

    def spans(lst, i, j):
        hs = [k for k in range(i, j) if lst[k].startswith(b'@@')]
        return [(h, (hs[x + 1] if x + 1 < len(hs) else j)) for x, h in enumerate(hs)]

    kills = {'src/App/Application.cpp': (b'@@ -260,', b'@@ -1293,', b'@@ -1301,', b'@@ -1667,'),
             'src/Gui/Application.cpp': (b'@@ -698,',),
             'src/Mod/Sketcher/Gui/EditModeCoinManagerParameters.cpp': (b'@@ -56,', b'@@ -57,', b'@@ -58,'),
             'src/Main/MainGui.cpp': ()}
    for rel, kill in kills.items():
        try:
            i, j = block_range(rel.encode())
        except StopIteration:
            # file not previously in the patch -- append a fresh block at the end
            raw.append('diff -ruNp a/%s b/%s' % (rel, rel))
            raw.append('--- a/%s' % rel)
            raw.append('+++ b/%s' % rel)
            raw[-3:] = [x.encode() for x in raw[-3:]]
            i, j = len(raw) - 3, len(raw)
        keep = []
        for h, he in spans(raw, i, j):
            if not any(raw[h].startswith(k) for k in kill):
                keep += raw[h:he]
        new = blocks[rel]

        def hunklist(lst):
            hs = [k for k, l in enumerate(lst) if l.startswith(b'@@')]
            return [(int(lst[h].split(b'-')[1].split(b',')[0]),
                     lst[h:(hs[x + 1] if x + 1 < len(hs) else len(lst))])
                    for x, h in enumerate(hs)]

        merged = sorted(hunklist(keep) + hunklist(new), key=lambda t: t[0])
        body = [x for _, chunk in merged for x in chunk]
        raw = raw[:i + 3] + body + raw[j:]
    out = b'\n'.join(raw)
    if not out.endswith(b'\n'):
        out += b'\n'        # "patch unexpectedly ends in middle of line" otherwise
    io.open(patch_path, 'wb').write(out)
    print('spliced diff-generated hunks into', patch_path)


if __name__ == '__main__':
    main()
