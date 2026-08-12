#!/usr/bin/env python3
"""Give CalculiX's F90 automatic arrays a fixed bound plus a runtime guard.

An automatic array is a local whose size is a runtime expression:

    subroutine mafilldm(..., ncmat_, ...)
    real*8 elconloc(ncmat_)          <- ncmat_ is a dummy argument, elconloc is local

FORTRAN 77 -- all that f2c implements -- has no such thing, so these files cannot be
translated at all. Where the dimension is an element-level quantity with a small,
well-understood maximum, replacing it with a constant is safe *provided the run stops
if the real value ever exceeds it*. That guard is the whole point: without it this
would silently overrun the array, which for a solver means quietly wrong stresses.

Only the entries in BOUNDS are touched. Mesh-level dimensions (nk, neq(2), nktet ...)
are deliberately absent -- there is no defensible constant for "number of nodes", and
a large fixed local would blow the stack besides. Those routines stay unconverted and
are stubbed in bridge/ccx_stubs.c so they abort with a named message.

Usage: ccx_bound_automatic.py <ccx-src-dir> [--check]
"""
import re
import sys
import pathlib

# exact declaration text -> (replacement, expression to test, bound, array name)
#
# Keyed on the whole declaration, not on the dimension variable, because the same
# variable needs different answers: xlayer(mi(3),4) at mi(3)=200 is 6 kB, while
# extrapolatefem's field(999,20*mi(3)) at the same bound would be a 32 MB local. That
# one has no safe constant and is stubbed instead.
#
# Everything here is element-level: material constants, layers, DOF per node,
# optimisation objectives. Mesh-level dimensions (nk, neq(2), nfronteq, nktet) are
# deliberately absent -- "number of nodes" has no defensible maximum.
BOUNDS = {
    'elconloc(ncmat_)':  ('elconloc(1000)',  'ncmat_',  1000, 'elconloc'),
    'xlayer(mi(3),4)':   ('xlayer(200,4)',   'mi(3)',   200,  'xlayer'),
    'voldl(0:mi(2),20)': ('voldl(0:20,20)',  'mi(2)',   20,   'voldl'),
    'ff(0:mi(2),8)':     ('ff(0:20,8)',      'mi(2)',   20,   'ff'),
    'bounds(nobject)':   ('bounds(100)',     'nobject', 100,  'bounds'),
    'yiloc(6,mi(1))':    ('yiloc(6,100)',    'mi(1)',   100,  'yiloc'),
    'coords(3,mi(1))':   ('coords(3,100)',   'mi(1)',   100,  'coords'),
    # mi(3) is the layer count; 8 keeps this local at ~1.3 MB instead of tens of MB
    'field(999,20*mi(3))': ('field(999,160)', 'mi(3)',   8,    'field'),
    # shell/beam/2D path: gen3dfrom2d expands S3/S4/S6/S8 shells, beams and
    # plane-stress/strain/axisymmetric elements into solids, so it gates all of them.
    'neworien(0:norien)': ('neworien(0:1000)', 'norien',  1000, 'neworien'),
    'pmean1(nfield)':     ('pmean1(100)',      'nfield',  100,  'pmean1'),
    'pmean2(nfield)':     ('pmean2(100)',      'nfield',  100,  'pmean2'),
    'yig(nfield,mi(1))':  ('yig(100,100)',     'max(nfield,mi(1))', 100, 'yig'),
}

# file -> [(array, declaration to replace, allocate expression, bound)]
#
# A handful of routines use F90 ALLOCATE, which f2c cannot translate either. Where the
# routine is on a path every model takes -- multistages runs during input processing for
# every deck, so stubbing it would break the solver outright -- the allocatable becomes a
# fixed-size local and the guard goes exactly where the ALLOCATE was, which is the point
# the real size is known.
ALLOCATABLES = {
    'multistages.f': [
        ('ksegmcs', 'integer,dimension(:),allocatable::ksegmcs',
         'noder(4)', 100000),
    ],
}

# Pattern rule, not an exact-declaration key: ccx declares a whole family of small
# per-element work arrays as NAME(0:mi(2),N) -- vl, q, veoldl, voldl, vconl. mi(2) is the
# highest DOF number per node (3 for mechanical, up to 7 with temperature/EM), so 20 is
# generous; the array stays a few kB either way. The guard makes an underestimate loud.
RE_MI2_DECL = re.compile(r'\b([a-z]\w*)\(0:mi\(2\),(\d+)\)', re.I)
MI2_BOUND = 20


def patch_mi2(text):
    """Bound every NAME(0:mi(2),N) local in one file, with a single shared guard."""
    if not RE_MI2_DECL.search(text) or 'mi(2) bound' in text:
        return None
    lines = text.split('\n')
    idx = first_executable(lines)
    if idx is None:
        return None
    lines = [RE_MI2_DECL.sub(r'\1(0:%d,\2)' % MI2_BOUND, l) for l in lines]
    lines[idx:idx] = [
        'C',
        'C     The 0:mi(2) work arrays are F90 automatic arrays upstream; FORTRAN 77',
        'C     has no such thing, so they get a fixed mi(2) bound in the WebAssembly',
        'C     build and the run stops rather than overrun them.',
        'C',
        '      if(mi(2).gt.%d) then' % MI2_BOUND,
        "         write(*,*) '*ERROR: mi(2) > %d (mi(2) bound'" % MI2_BOUND,
        "         write(*,*) '        in the WebAssembly build)'",
        '         call exit(201)',
        '      endif',
    ]
    return '\n'.join(lines)


RE_DECL_KEYWORD = re.compile(
    r'^\s{6,}(real|integer|logical|character|double\s+precision|complex|dimension|'
    r'common|data|implicit|parameter|external|intrinsic|save|equivalence|include)\b', re.I)
RE_CONT = re.compile(r'^\s{5}\S')


def first_executable(lines):
    """Index of the first executable statement, i.e. where a guard may be inserted."""
    for i, l in enumerate(lines):
        if not l.strip() or l[:1] in 'cC*!' or RE_CONT.match(l):
            continue
        if l.strip().lower().startswith(('subroutine', 'function', 'end', 'entry')):
            continue
        if RE_DECL_KEYWORD.match(l):
            continue
        if re.match(r'^\s{6,}\S', l):
            return i
    return None


def guard_lines(var, bound, arr):
    return [
        'C',
        'C     %s(%s) is an F90 automatic array upstream; FORTRAN 77 has no' % (arr, var),
        'C     such thing, so it gets a fixed bound in the WebAssembly build.',
        'C     The check below stops the run rather than overrun the array.',
        'C',
        '      if(%s.gt.%d) then' % (var, bound),
        "         write(*,*) '*ERROR: %s > %d (%s bound'" % (var, bound, arr),
        "         write(*,*) '        in the WebAssembly build)'",
        '         call exit(201)',
        '      endif',
    ]


def patch(text):
    """Return patched text, or None if there is nothing left to do."""
    changed = False
    for spec, (repl, var, bound, arr) in BOUNDS.items():
        if spec not in text:
            continue
        lines = text.split('\n')
        if any('%s bound' % arr in l for l in lines):
            continue                          # this array is already bounded
        idx = first_executable(lines)
        if idx is None:
            continue
        lines = [l.replace(spec, repl) for l in lines]
        lines[idx:idx] = guard_lines(var, bound, arr)
        text = '\n'.join(lines)
        changed = True
    return text if changed else None


def patch_allocatable(text, entries):
    for arr, decl, expr, bound in entries:
        if decl not in text.replace(' ', '') and decl not in text:
            continue
        if 'C     %s(%s) was ALLOCATE' % (arr, expr) in text:
            continue                                   # already patched
        lines = text.split('\n')
        out = []
        for l in lines:
            if l.replace(' ', '').startswith(decl.replace(' ', '')):
                out.append('      integer %s(%d)' % (arr, bound))
                continue
            stripped = l.strip().lower().replace(' ', '')
            if stripped == 'allocate(%s(%s))' % (arr, expr.replace(' ', '')):
                out.append('C')
                out.append('C     %s(%s) was ALLOCATEd upstream; f2c cannot translate' % (arr, expr))
                out.append('C     F90 dynamic memory, so it is a fixed-size local here and')
                out.append('C     the run stops if the real size would not fit.')
                out.append('C')
                out.append('      if(%s.gt.%d) then' % (expr, bound))
                out.append("         write(*,*) '*ERROR: %s too large for the'" % arr)
                out.append("         write(*,*) '        WebAssembly build'")
                out.append('         call exit(201)')
                out.append('      endif')
                continue
            if stripped == 'deallocate(%s)' % arr:
                out.append('      continue')
                continue
            out.append(l)
        text = '\n'.join(out)
    return text


def main():
    d = pathlib.Path(sys.argv[1])
    check = '--check' in sys.argv
    n = 0
    for p in sorted(d.glob('*.f')):
        src = p.read_text(errors='replace', newline='')
        entries = ALLOCATABLES.get(p.name)
        new = patch_allocatable(src, entries) if entries else src
        m2 = patch_mi2(new)
        if m2 is not None:
            new = m2
        if any(spec in new for spec in BOUNDS):
            bounded = patch(new)
            if bounded is not None:
                new = bounded
        if new == src:
            continue
        if not check:
            # newline='' on both sides: ccx ships CRLF in places and rewriting the
            # line endings would turn a two-line change into a whole-file diff
            with open(p, 'w', newline='') as f:
                f.write(new)
        n += 1
    print(('would patch' if check else 'patched') + ' %d files' % n)


def selftest():
    src = ('      subroutine t(ncmat_)\n'
           '      integer ncmat_\n'
           '      real*8 elconloc(ncmat_)\n'
           '      x=1\n'
           '      end\n')
    out = patch(src)
    assert 'elconloc(1000)' in out and 'ncmat_.gt.1000' in out, out
    # the guard goes before the first executable, never among the declarations
    assert out.index('ncmat_.gt.1000') < out.index('x=1'), out
    assert out.index('real*8 elconloc') < out.index('ncmat_.gt.1000'), out
    assert patch(out) is None, 'must be idempotent'
    # every emitted CODE line must fit fixed-form's 72 columns, or a string literal
    # gets truncated mid-quote (comments are not column-limited)
    for l in out.split('\n'):
        if l[:1] not in 'cC*!':
            assert len(l) <= 72, repr(l)
    alloc = ('      integer,dimension(:),allocatable::ksegmcs\n'
             '      allocate(ksegmcs(noder(4)))\n'
             '      x=1\n'
             '      deallocate(ksegmcs)\n')
    a = patch_allocatable(alloc, ALLOCATABLES['multistages.f'])
    assert 'integer ksegmcs(100000)' in a, a
    assert 'allocatable' not in a and 'deallocate' not in a, a
    assert 'noder(4).gt.100000' in a, a
    assert patch_allocatable(a, ALLOCATABLES['multistages.f']) == a, 'must be idempotent'
    for l in a.split('\n'):
        if l[:1] not in 'cC*!':
            assert len(l) <= 72, repr(l)
    mi2 = ('      subroutine r(mi)\n      integer mi(*)\n'
           '      real*8 vl(0:mi(2),20),q(0:mi(2),8)\n      x=1\n      end\n')
    g = patch_mi2(mi2)
    assert 'vl(0:20,20)' in g and 'q(0:20,8)' in g, g
    assert g.count('mi(2).gt.20') == 1, 'one guard per file'
    assert g.index('mi(2).gt.20') < g.index('x=1'), g
    assert patch_mi2(g) is None, 'must be idempotent'
    print('ccx_bound_automatic selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
