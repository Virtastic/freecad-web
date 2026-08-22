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


def main():
    tree = sys.argv[1]
    tmp = os.path.join(tree, '..', 'dgen')
    os.makedirs(tmp, exist_ok=True)
    specs = [('src/App/Application.cpp', edit_app), ('src/Gui/Application.cpp', edit_gui)]
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

    for rel, kill in (('src/App/Application.cpp', (b'@@ -259,', b'@@ -1293,', b'@@ -1665,')),
                      ('src/Gui/Application.cpp', (b'@@ -695,',))):
        i, j = block_range(rel.encode())
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
    io.open(patch_path, 'wb').write(b'\n'.join(raw))
    print('spliced diff-generated hunks into', patch_path)


if __name__ == '__main__':
    main()
