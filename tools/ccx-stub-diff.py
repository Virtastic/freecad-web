#!/usr/bin/env python3
"""Which routines does the DEPLOYED CalculiX module stub?

docs-ccx-stubbed-routines.md said the binary "cannot be mined for a stub list" because the
routine name reaches the abort as a runtime `%s`. That is true of the format string and false
of the argument: `tools/ccx_make_stubs.py` emits `call ccxstb('<name>')`, and f2c turns that
Fortran character literal into an ordinary NUL-terminated C string in the data section. So the
name of every STUBBED routine is sitting in the binary, and the name of a COMPILED one is not.

The control that makes this trustworthy: routines documented as compiled in production --
e_c3d, mafilldm, resultsmech, resultstherm, e_c3d_th, extrapolate, zienzhu -- produce no such
literal. Every one of them comes back False.

    python3 tools/ccx-stub-diff.py play-gui/ccx.wasm [more.wasm ...]

Give it the deployed module and a CI-built one to see exactly where they differ. This matters
because "still stubbed here" and "stubbed in production too" are completely different problems:
the first is a gap to close, the second is a limit the shipped product already has.
"""
import re
import sys
import urllib.request

# The 977 routines are not all worth probing; these are the ones that have ever been stubbed.
CANDIDATES = [
    'basis', 'calcview', 'cavity_refine', 'cavityext_refine', 'e_c3d_us3', 'e_c3d_us45',
    'extendmesh', 'gen3dfrom2d', 'interpolateinface', 'patch', 'resultsmech_us3',
    'resultsmech_us45', 'slavintmortar', 'slavintpoints', 'umat_ciarlet_el', 'us3_sub',
    'us4_sub', 'near2d', 'near3d', 'extrapolatecontact', 'zienzhu',
]

# Routines the docs record as compiled in production. If any of these reports "stubbed", the
# method is wrong and the output must not be trusted.
CONTROL = ['e_c3d', 'mafilldm', 'resultsmech', 'resultstherm', 'e_c3d_th', 'extrapolate']


def load(path):
    if path.startswith(('http://', 'https://')):
        with urllib.request.urlopen(path) as r:
            return r.read()
    with open(path, 'rb') as f:
        return f.read()


def stubbed(data, name):
    """A stub passes its name as a Fortran literal, which f2c emits as a C string."""
    return data.find(b'\x00' + name.encode() + b'\x00') >= 0


def main():
    paths = sys.argv[1:]
    if not paths:
        print(__doc__)
        return 2

    mods = [(p, load(p)) for p in paths]
    for p, d in mods:
        if b'is not available in this build' not in d:
            print('WARNING: %s carries no stub message -- it may not be a ccx module '
                  'built by this repo' % p)

    bad = [(p, n) for p, d in mods for n in CONTROL if stubbed(d, n)]
    if bad:
        print('CONTROL FAILED -- these are documented as compiled yet look stubbed:')
        for p, n in bad:
            print('   %s: %s' % (p, n))
        print('The detection is unreliable here; do not use this output.')
        return 1
    print('control ok: %d routines known to be compiled produce no literal\n' % len(CONTROL))

    width = max(len(n) for n in CANDIDATES) + 2
    print('%-*s %s' % (width, 'routine', '  '.join('%-10s' % p.split('/')[-1] for p, _ in mods)))
    for n in CANDIDATES:
        cells = ['STUBBED   ' if stubbed(d, n) else 'compiled  ' for _, d in mods]
        star = '  <-- differs' if len(set(cells)) > 1 else ''
        print('%-*s %s%s' % (width, n, '  '.join(cells), star))
    return 0


if __name__ == '__main__':
    sys.exit(main())
