# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Constrain OpaqueCoordinate's forwarding constructor so it stops hijacking copies.

    python tools/patch-ifcopenshell.py deps/src/ifcopenshell

IfcOpenShell 0.8 declares, in src/ifcgeom/ConversionResult.h:

    template <typename... Args>
    OpaqueCoordinate(Args... args) {
        static_assert(sizeof...(args) == N, "Incorrect number of arguments provided");
        init_<0>(args...);
    }

    OpaqueCoordinate() { ... }
    OpaqueCoordinate(const OpaqueCoordinate& other) { ... }

The variadic constructor is unconstrained, so it participates in overload resolution for
ANY argument list -- including a single one. Copy-constructing from a non-const lvalue:

    OpaqueCoordinate<3> a;
    OpaqueCoordinate<3> b(a);      // a is non-const

deduces Args = {OpaqueCoordinate<3>&}, an exact match, while the real copy constructor
needs a qualification conversion to bind const. The template wins, and the static_assert
fires with one argument where three were expected:

    ConversionResult.h:205: static assertion failed due to requirement
        'sizeof...(args) == 3UL': Incorrect number of arguments provided
    IfcPythonPYTHON_wrap.cxx:11501: error: calling a private constructor of class
        'SwigValueWrapper<IfcGeom::OpaqueCoordinate<3>>'

SWIG's generated wrapper copies by value in exactly that way, which is why this surfaces
in the Python bindings and not in the C++ library.

The fix moves the arity requirement from a static_assert in the body to SFINAE in the
template parameter list, so a wrong-arity call is simply not a candidate and overload
resolution reaches the copy constructor. Behaviour for correct calls is unchanged: the
same constructor is selected, and wrong arity is still rejected at compile time.

Idempotent -- safe to re-run.
"""
import io
import os
import re
import sys

REL = 'src/ifcgeom/ConversionResult.h'

# Match the declaration regardless of tabs/spaces, and capture the body call so the
# rewrite keeps whatever init_ line is actually there.
PATTERN = re.compile(
    r'template\s*<\s*typename\s*\.\.\.\s*Args\s*>\s*\n'
    r'(?P<ind>[ \t]*)OpaqueCoordinate\(Args\.\.\.\s*args\)\s*\{\s*\n'
    r'[ \t]*static_assert\(sizeof\.\.\.\(args\)\s*==\s*N,[^\n]*\n'
    r'(?P<body>[ \t]*init_<0>\(args\.\.\.\);\s*\n)'
    r'[ \t]*\}\s*\n'
)

REPLACEMENT = (
    # no {ind} on the first line: the text before the match already ends with the original
    # indentation, so prefixing it again doubles it.
    '// Constrained to exactly N arguments. Unconstrained, this template is an exact\n'
    '{ind}// match when copy-constructing from a NON-CONST lvalue -- Args deduces to\n'
    '{ind}// OpaqueCoordinate& -- while the real copy constructor needs a qualification\n'
    '{ind}// conversion to bind const. The template therefore won, and the arity check\n'
    '{ind}// failed with one argument instead of N. SWIG-generated wrappers copy exactly\n'
    '{ind}// that way, so the Python bindings did not compile.\n'
    '{ind}template <typename... Args,\n'
    '{ind}          typename = typename std::enable_if<sizeof...(Args) == N>::type>\n'
    '{ind}OpaqueCoordinate(Args... args) {{\n'
    '{body}'
    '{ind}}}\n'
)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = os.path.join(sys.argv[1], REL)
    if not os.path.exists(path):
        sys.exit('not found: %s' % path)

    src = io.open(path, encoding='utf-8', errors='replace').read()

    if 'std::enable_if<sizeof...(Args) == N>' in src:
        print('  already constrained: %s' % REL)
        return

    m = PATTERN.search(src)
    if not m:
        print('!! could not find the unconstrained OpaqueCoordinate constructor in %s' % REL)
        print('   Upstream may have fixed or restructured it. What is there now:')
        for i, line in enumerate(src.split('\n'), 1):
            if 'OpaqueCoordinate(' in line or 'sizeof...(args)' in line:
                print('     %d: %s' % (i, line.rstrip()))
        sys.exit(1)

    ind = m.group('ind')
    new = REPLACEMENT.format(ind=ind, body=m.group('body'))
    src = src[:m.start()] + new + src[m.end():]

    # <type_traits> for enable_if. Almost certainly pulled in transitively, but relying on
    # that is how a build breaks on a different standard library.
    if '#include <type_traits>' not in src:
        anchor = '#include <array>'
        if anchor in src:
            src = src.replace(anchor, anchor + '\n#include <type_traits>', 1)
        else:
            src = re.sub(r'(#include [<"][^\n]*[>"]\n)', r'\1#include <type_traits>\n', src, count=1)

    io.open(path, 'w', encoding='utf-8', newline='').write(src)
    print('  constrained OpaqueCoordinate ctor in %s' % REL)


if __name__ == '__main__':
    main()
