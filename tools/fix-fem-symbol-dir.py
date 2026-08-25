# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Make the FEM constraint symbol directory correct, not merely non-empty.

    python tools/fix-fem-symbol-dir.py

One-shot surgery on the existing ViewProviderFemConstraint.cpp hunk in
patches/freecad.patch (those are port-authored lines, so the pristine-diff regenerator
cannot express the edit). Idempotent: refuses to run twice.

WHY

Every FEM constraint failed to construct:

    ImportError: Error opening symbol file /Mod/Fem/Resources/symbols/ConstraintFixed.iv

which made the whole FEM workflow impossible -- an analysis cannot have a fixed face.

`resourceSymbolDir` is a static member initialised at namespace scope from
App::Application::getResourceDir(). In this static monolith every constructor runs in
__wasm_call_ctors, before the application exists, so getResourceDir() returned "" and the
member became the RELATIVE string "Mod/Fem/Resources/symbols/". Coin then resolved that
against the working directory, giving "/Mod/Fem/...".

The port already saw this coming and added a fix-up in the base constructor -- but guarded
it with `if (resourceSymbolDir.empty())`, and a wrong value is not an empty one. The guard
never fired, and the fix has been inert ever since it was written.

So compare against what the value SHOULD be now that the application exists, rather than
asking whether it is unset. That cannot be fooled by a wrong-but-non-empty value, costs a
string compare per constraint, and behaves identically on a desktop build where the
namespace-scope initializer was correct all along.

This is the same failure as `#ifdef FCWEB_REAL_CPYTHON` -- a fix that was written, never
ran, and looked like it had.
"""
import io
import re

PATCH = 'patches/freecad.patch'
MARK = 'const std::string want ='

OLD = [
    '+    // Fill the symbol dir on first construction, NOT at namespace scope: a file-scope',
    '+    // initializer runs in __wasm_call_ctors before App::Application exists, so',
    '+    // getResourceDir() returned an incomplete path and every constraint then logged',
    '+    // "Coin read error: Could not find \'share/Mod/Fem/Resources/symbols/...\'" before',
    '+    // falling back. Every subclass runs this base constructor before its own body builds',
    '+    // the path, so this is populated in time. (Same static-init-order class of bug as the',
    '+    // TechDraw Rez.cpp fix.)',
    '+    if (resourceSymbolDir.empty()) {',
    '+        resourceSymbolDir = App::Application::getResourceDir() + "Mod/Fem/Resources/symbols/";',
    '+    }',
]

NEW = [
    '+    // Fill the symbol dir on first construction, NOT at namespace scope: a file-scope',
    '+    // initializer runs in __wasm_call_ctors before App::Application exists, so',
    '+    // getResourceDir() returned "" and the member became the RELATIVE string',
    '+    // "Mod/Fem/Resources/symbols/", which Coin then resolved against the working',
    '+    // directory. Every FEM constraint died with',
    '+    //   Error opening symbol file /Mod/Fem/Resources/symbols/ConstraintFixed.iv',
    '+    //',
    '+    // An earlier version of this guard asked whether the value was EMPTY. A wrong value',
    '+    // is not an empty one, so it never fired and the fix sat here inert. Compare against',
    '+    // what it should be instead: it cannot be fooled by a wrong-but-non-empty value, and',
    '+    // on a desktop build, where the namespace-scope initializer was right all along, the',
    '+    // comparison simply matches. (Same static-init-order class as the TechDraw Rez.cpp',
    '+    // fix, and the same "a fix that never ran" shape as FCWEB_REAL_CPYTHON.)',
    '+    {',
    '+        const std::string want =',
    '+            App::Application::getResourceDir() + "Mod/Fem/Resources/symbols/";',
    '+        if (resourceSymbolDir != want) {',
    '+            resourceSymbolDir = want;',
    '+        }',
    '+    }',
]


def main():
    raw = io.open(PATCH, "rb").read()
    if MARK.encode() in raw:
        raise SystemExit("already applied")

    # patches/freecad.patch has MIXED line endings on purpose -- .gitattributes says so,
    # because 33 of the files this port touches are CRLF upstream and 47 are LF. Splitting
    # the whole file on one of them silently glues the other region into a single line, so
    # work on the bytes of this block instead.
    old_blob = b"\n".join(x.encode() for x in OLD)
    if raw.count(old_blob) != 1:
        raise SystemExit("the existing constructor block was not found exactly once "
                         "(found %d) -- has it changed?" % raw.count(old_blob))
    new_blob = b"\n".join(x.encode() for x in NEW)
    raw = raw.replace(old_blob, new_blob, 1)

    # the enclosing hunk header has to grow by the lines added
    # A unified-diff header carries "@@" twice, so search for the START of the line rather
    # than for the marker -- rfind lands on the closing one and matches nothing.
    i = raw.rfind(b"\n@@ ", 0, raw.find(new_blob)) + 1
    j = raw.find(b"\n", i)
    hdr = raw[i:j]
    m = re.match(rb"@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$", hdr, re.S)
    grown = b"@@ -%s,%s +%s,%d @@%s" % (m.group(1), m.group(2), m.group(3),
                                        int(m.group(4)) + len(NEW) - len(OLD), m.group(5))
    raw = raw[:i] + grown + raw[j:]
    io.open(PATCH, "wb").write(raw)
    print("symbol-dir guard now compares against the expected value; %s" % grown.decode())

if __name__ == '__main__':
    main()
