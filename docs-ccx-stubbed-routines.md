# CalculiX: making a clean build reproduce production's solver

Measured by `.github/workflows/build-ccx.yml` from CalculiX 2.22 upstream. Started at 69
stubbed routines (run 31985042689); now **27**, and all four validation decks reproduce
production exactly (run 31992713435).

## What this is

f2c implements FORTRAN 77. CalculiX uses some F90, so 69 of its 977 routines failed to
translate and `build-ccx-weh.sh` **stubs** them. A stub compiles and links; at run time it
prints which routine is missing and ABORTS, rather than returning undefined results. So the
failure is loud -- but a build can still print `failed: 0` while the analysis a user actually
wants cannot run.

## Why this matters more than a size number

`e_c3d.f` is the 3D element stiffness routine. Stub it and solid FEM does not work at all.
Production's solver demonstrably DOES work -- validated to under 1% against beam theory --
so the build machine has f2c workarounds that were never captured into `patches/`.

(An earlier version of this file also called `gauss.f` a stubbed routine. It is not a
routine at all: it is an INCLUDE file of Gauss-point data, pulled into 60 others. Its
appearing in `UNCONVERTED.txt` is meaningless -- f2c cannot translate a bare data include on
its own, and `e_c3d.f` translating proves the include resolves fine.)

That is the actual defect: `deps/` is gitignored, so those edits are invisible until
someone builds from clean. Nobody had, until 2026-08-16.

## Measured progress

| | stubbed | translated | ccx.wasm | gap to production |
|---|---|---|---|---|
| clean build, no patches | 69 | 908/977 | 3,797,838 | 986,945 |
| + `ccx-wasm-automatic-array.patch` | 68 | 910/977 | 3,846,632 | 938,151 |
| + `f77ify` rule, `ncmat_` only | 60 | 918/977 | 3,883,782 | 901,001 |
| + `mi(2)`/`mi(3)` bounds | 30 | 948/977 | 4,543,921 | 240,862 |
| + `mi(1)` + static problem-size bounds | **27** | **951/977** | **4,599,882** | **184,901** |
| production (target) | ? | ? | 4,784,783 | — |

## Reproduced

**All four validation decks now give production's numbers exactly** (run 31992713435):

```
IDENTICAL — every deck gives production's numbers
```

elastic, frequency, plastic and thermal — matching digit for digit, including the 1e-13 and
1e-14 round-off noise. That last part is what makes it a reproduction rather than a
resemblance: round-off is where two differently-built solvers diverge first.

So the original defect is closed. A clean build from this repo plus upstream sources now
produces a CalculiX module that behaves like the one in production, with no undocumented
edits on a build machine. The gate is blocking as of that run.

A note on what the numbers do and do not say. 27 routines are still stubbed and the wasm is
still 184,901 bytes smaller than production's, so the two modules are not byte-identical and
this does not prove they agree on analyses the decks do not cover. What it does prove is that
every path these four exercise is reproduced, and that a regression on them now fails the
build.

**`e_c3d.f` translates.** The 3D element stiffness routine — the one whose absence breaks
solid FEM outright, and the reason any of this mattered — is no longer stubbed. So are
`gauss.f`'s callers, `mafilldm.f`, `resultsmech.f`, `resultstherm.f`, `e_c3d_th.f` and the
rest of the core solid/thermal set. The size gap is down by 73%.

## Where the bounds came from

Not from judgement — from CalculiX's own source. `mi` is its limits array: `mi(1)`
integration points, `mi(2)` DOF per node, `mi(3)` composite layers.

`mi(2)` is initialised to 3 (`ini_cal.c:217`) and every site that raises it uses a small
constant (`allocation.f`: 3, 4, 5, 6) except two — and CalculiX rejects both itself:

```
userelements.f:75       *USER ELEMENT     -> '*ERROR ... exceeds 255'
matrix2userelem.f:136   *MATRIX ASSEMBLE  -> refuses any ndof but 3 or 6
```

So **255 is the limit CalculiX enforces, not one we chose**; no deck it accepts can exceed
it, and that guard can never fire. `mi(3)` is different: `allocation.f:2092` grows it from
`nlayer`, counted from input lines with no upstream limit. 255 there *is* a chosen ceiling —
the one entry that can really fire, which is exactly why the guard is mandatory.

Two constraints shaped the implementation:

- **One dimension of several.** These are `vl(0:mi(2),20)`, not `elconloc(ncmat_)`, so the
  rule rewrites one dimension of a multi-dimensional declaration and tracks declaration
  context across continuation lines — an executable subscript mentioning `mi(2)` must not be
  touched, and neither must a dummy argument, whose adjustable dimension is legal F77.
- **A stack budget.** f2c runs with `-a`, so these are stack arrays, and the link sets
  `STACK_SIZE=16MB`. `field(999,20*mi(3))` costs 160 KB *per layer*, so `mi(3)=255` would ask
  for 40 MB — fine on paper, memory corruption at run time. The rule computes the size and
  refuses above 4 MB, leaving the routine stubbed; `field` takes a named override at 16.

## What is still stubbed, and why it no longer blocks the decks

| cause | routines | note |
|---|---|---|
| `wr_ardecls: nonconstant array size` | ~20 | the same construct on problem-size dimensions (`netet_`, `nk`, `nfront`, `ncont`, `numpts`, …). These scale with the MODEL, so a fixed bound is the wrong tool -- see below |
| US3/US45 user shell elements | 6 | `e_c3d_us3/us45`, `resultsmech_us3/us45`, `us3_sub`, `us4_sub`. BUILD-WEH.md records FreeCAD never emits them; these can stay stubbed |
| `xlocal.f` | 1 | `subscripts on scalar variable`, a separate root cause |

None of them is reached by the four decks, which is why those now pass. That is a statement
about coverage, not about correctness: an analysis that does reach one will stop with a
message naming it.

### Two techniques, and knowing which applies

- **Per-element constants** (`mi(1)`, `mi(2)`, `mi(3)`, `ncmat_`) take a fixed bound on the
  stack. A generous bound costs a few KB, and for `mi(1)`/`mi(2)` the bound is the one
  CalculiX enforces itself, so the guard can never fire.
- **Problem-size dimensions** (`neq(2)`, `nev`, and the `wr_ardecls` group) take a large
  bound plus `save`, i.e. static storage -- the convention this file already used for F90
  allocatables. 1.6 MB arrays do not belong on a 16 MB stack.

The distinction matters more than either bound: applying the first technique to a
problem-size array either overflows the stack or refuses legitimate models.

## Validating any of this

`.github/workflows/build-ccx.yml` now runs the four decks in `scratchpad/ccxval` (elastic,
modal, plastic, thermal) through both the module it just built and the one production is
serving, and diffs the result extremes. **Results must match, not converge** — a bounded
array that is subtly wrong is a slightly different number, not a crash, and there is nowhere
else it shows up.

**Blocking as of run 31992713435**, where all four first agreed. Before that a difference
could be a known gap; now it is a regression. It has already caught two defects that every
other check called green -- a routine the stress path needs left stubbed, and an 80-line scan
window silently rewriting ARPACK's dummy-argument array shapes.

## Root cause: one construct explained 63 of the original 68

Every failing routine's f2c error is now preserved (the build used to delete them). Grouped:

| cause | routines |
|---|---|
| **F90 automatic array** — `Declaration error for <name>: adjustable dimension on non-argument` | **63** |
| US3/US45 user shell elements — `transpose`/`matmul`/syntax | 4 |
| `xlocal.f` — `subscripts on scalar variable` | 1 |

An *automatic array* is one sized by a variable that is not a dummy argument. FORTRAN 77
has no such thing, and f2c implements only F77. `e_c3d.f` — the 3D element stiffness
routine, whose absence breaks solid FEM outright — fails on exactly this, at line 2171:

```
Error on line 2171 of e_c3d.f: Declaration error for elconloc:
                               adjustable dimension on non-argument
```

The same handful of arrays recur across the whole set, which is why one rule covers them:

| array | routines declaring it |
|---|---|
| `elconloc` | 26 |
| `xlayer` | 15 |
| `vl` | 15 |
| `voldl` | 14 |
| `q` | 7 |
| `field` | 4 |
| `y`, `x`, `veoldl` | 3 each |
| `z`, `yiloc`, `vconl` | 2 each |

## Why this is now a small, well-defined job

`patches/ccx-wasm-automatic-array.patch` already fixes **exactly this construct**, by hand,
for one file: it gives `elconloc(ncmat_)` a fixed bound and adds a guard that *stops the
run* rather than overrunning. The same shape applied to the arrays above turns 63 stubs
back into working routines.

Two ways to do it, and the second is better:

1. Extend that patch by hand, per file — reliable, tedious, 63 files.
2. Teach `tools/f77ify.py` the transformation. It already rewrites F90 attribute
   declarations, `(/ /)` constructors, `reshape`, and `maxval`/`sum`; one more rule there
   covers every file, now and for the next CalculiX release.

**The bound must carry a guard.** A fixed bound that is too small overruns silently and
produces wrong stresses — the worst possible failure for a solver, because nothing looks
broken. With the guard the only outcomes are "correct" or "stops and says so", which is
what makes the existing hand patch safe and what any generic version must preserve.
Choosing those bounds needs CalculiX's dimensioning conventions, so it is written down here
rather than guessed at.

## The old work list is obsolete

Every routine in the "core solid/thermal FEM" group that this document used to list as
needing hand work now translates, including `e_c3d.f`. The current list is the 30 above,
which the build prints on every run — read it there rather than from a copy that goes stale.

## Note on US3/US45

`e_c3d_us3`, `e_c3d_us45`, `resultsmech_us3/45`, `us3_sub`, `us4_sub` are the *user*
shell elements. BUILD-WEH.md records that FreeCAD never emits them, so those are the
one group that can stay stubbed.
