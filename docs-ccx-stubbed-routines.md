# CalculiX: making a clean build reproduce production's solver

Measured by `.github/workflows/build-ccx.yml` from CalculiX 2.22 upstream. Started at 69
stubbed routines (run 31985042689); now **19**, and all four validation decks reproduce
production exactly (run 31996275820).

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
| + `mi(1)` + static problem-size bounds | 27 | 951/977 | 4,599,882 | 184,901 |
| + mesh-size bounds (contact, ZZ estimator) | **19** | **959/977** | **4,687,709** | **97,074** |
| production (target) | ? | ? | 4,784,783 | — |

**69 stubs to 19; 90% of the size gap closed; all four decks identical throughout.**

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

A note on what the numbers do and do not say. 19 routines are still stubbed and the wasm is
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

## What is still stubbed

    basis  calcview  cavity_refine  cavityext_refine  extendmesh  gauss  gen3dfrom2d
    interpolateinface  patch  slavintmortar  slavintpoints  umat_ciarlet_el  xlocal
    e_c3d_us3  e_c3d_us45  resultsmech_us3  resultsmech_us45  us3_sub  us4_sub

(Read from CI run 32140989422's own output, not maintained by hand. The previous copy of
this list was wrong in both directions: it still named `near2d` and `near3d`, which the
file-scoped bounds fixed, and it omitted `slavintmortar`/`slavintpoints`, which the text
below explains are stubbed on purpose.)

| group | note |
|---|---|
| US3/US45 user shells (6) | BUILD-WEH.md records FreeCAD never emits them — these can stay stubbed |
| `gauss.f` | not a routine; an INCLUDE of Gauss-point data. Its presence here means nothing |
| CalculiX's own remesher (`cavity_refine`, `cavityext_refine`, `extendmesh`, `basis`, `interpolateinface`) | FreeCAD meshes with gmsh, so this path is unused |
| deliberately excluded dimensions (`calcview`, `patch`) | see the exclusion list in `tools/f77ify.py` — each would be unsafe to token-match |
| mortar contact (`slavintmortar`, `slavintpoints`) | `SKIP_FILES` in `tools/f77ify.py` — bounded, they converge to a physically invalid answer, so an abort is the lesser evil. See the contact section below |
| `xlocal.f`, `umat_ciarlet_el`, `gen3dfrom2d` | separate root causes |

None is reached by the four decks. That is a statement about coverage, not correctness: an
analysis that does reach one stops with a message naming it, rather than returning a wrong
answer.

### Two techniques, and knowing which applies

- **Per-element constants** (`mi(1)`, `mi(2)`, `mi(3)`, `ncmat_`) take a fixed bound on the
  stack. A generous bound costs a few KB, and for `mi(1)`/`mi(2)` the bound is the one
  CalculiX enforces itself, so the guard can never fire.
- **Problem-size dimensions** (`neq(2)`, `nev`, `nk`, `ne`, `nktet`, `ncont`, …) take a large
  bound plus `save`, i.e. static storage -- the convention this file already used for F90
  allocatables. 1.6 MB arrays do not belong on a 16 MB stack. Cost: **35 MB static**, against
  the module's 256 MB initial allocation.

The distinction matters more than either bound: applying the first technique to a
problem-size array either overflows the stack or refuses legitimate models.

Three rules earn their keep, and all three were found by measuring rather than reasoning:

1. **All or nothing per file.** f2c rejects a file if ANY automatic array survives, so a
   partial rewrite is stubbed anyway *and* still costs memory. Two files were emitting 1.5 MB
   each while staying stubbed.
2. **The ceiling picks the bound.** `nk` is 150000 rather than 200000 because the widest
   arrays on it are 6 columns of `real*8`; at 200000 those exceed the per-array static
   ceiling and the routines are refused outright. A bigger bound bought nothing but a stub.
3. **A PARAMETER dimension is not an automatic array.** `nmids(maxmid)` with
   `parameter(maxmid=400)` is legal F77. Treating it as automatic cost a working routine.

## Contact: a real gap, found by adding a deck for it

The four original decks (elastic, modal, plastic, thermal) never touch contact, so when the
mesh-size bounds turned `slavintmortar`, `slavintpoints` and `extrapolatecontact` from stubs
into code, **nothing verified them**. `scratchpad/ccxval/contact.inp` was added for that, and
it immediately earned its place:

1. It failed on `near3d`, a routine I had documented as *deliberately* excluded because its
   dimension `k` is one letter and unsafe to token-match globally. That exclusion read as
   considered; it was in fact removing contact analysis entirely. Fixed with file-scoped
   bounds — `k` now matches four declarations in two files instead of thousands everywhere.
2. It then exposed a bug in the deck itself. The upper block had no lateral restraint, so it
   was free to slide: a rigid-body mode. **Production answered `rc=0` with displacements of
   29,600 mm on a 10 mm cube**, while the CI build refused to converge. The CI build was
   right. Worth remembering that `rc=0` from CalculiX is not evidence of a usable answer —
   which is exactly why this gate compares numbers rather than exit codes.
3. With the deck corrected, production solves it (±5.3e-3 lateral, 569 MPa contact pressure)
   and **this build still does not converge**:

   ```
   divergence allowed: number of contact elements stabilized
   maximum number of iterations for face-to-face contact reached
   largest residual force= 113284.597073 in node 7 and dof 3
   *ERROR: too many cutbacks
   ```

   No `f77ify` guard fires and no stub aborts, so this is a **numerical difference in a
   translated routine, not a missing one**.

4. Softening the deck (1.e4 instead of 1.e6, 0.02 mm instead of 0.05 mm) to separate "contact
   is broken" from "these two disagree at the edge of convergence" gave the real answer, and
   it is worse than non-convergence. It converges — to a **physically invalid** result:

   | | production | this build |
   |---|---|---|
   | contact pressure | 0 .. **+107.1** | **−93.2** .. 3.06e-3 |
   | z displacement | −2.0000e-2 .. **0.0** | −2.0001e-2 .. **+4.07e-3** |
   | x/y | symmetric ±9.95e-4 | asymmetric |
   | error estimate | 11.2 | **68.5** |

   Negative contact pressure is impossible: contact pushes, it cannot pull. The model is
   perfectly symmetric, so an asymmetric response is a second tell.

### What the investigation established

Four hypotheses were tested and eliminated, and every transformation on the contact path was
then read line by line and found **faithful**:

| checked | verdict |
|---|---|
| `save` / storage class | not the cause — output byte-identical across static and automatic |
| non-last-dimension stride | real hazard, but `mi()` bounds are applied uniformly so caller and callee agree; a static check written to enforce it refused `e_c3d.f` and was reverted |
| `cycle`/`exit` → `goto` rewrite | correct in all four files: cycle targets sit immediately before their `enddo`, exit targets after |
| `field` first-dimension bound | safe — `field` never leaves `extrapolatecontact` (0 call sites) |

Divergence is at **iteration 1 of increment 1**: the displacement solve is identical
(`1.535714e-03` in both) while the residual force is 0.000000 in production and 319.444444
here. No iteration history exists at that point, which independently rules out anything
stateful.

Disassembling production's `ccx.wasm` closes the loop. It contains the stub format string
`[ccx-wasm] %s is not available in this build.` — byte-identical to what
`tools/ccx_make_stubs.py` emits — so **production was built with this repo's own tooling**.
The name is a runtime `%s`, so the binary cannot be mined for a stub list; but since
production solves the contact deck, it plainly does not stub these routines.

**The decisive test.** Halving every bound on the contact path — `ncont` and `near2d`/
`near3d`'s `k`, both 100000 → 50000 — produced **byte-identical wrong numbers**: the same
`-9.3215e+1` contact pressure, the same `68.475` error estimate, the same displacements to
every digit. The bound *value* does not reach the results at all, so these arrays are only
ever accessed within their true runtime extent; nothing reads uninitialised tail memory and a
fixed bound corrupts nothing.

That, with the line-by-line verification above, **exonerates the transformation**. The
remaining explanation is the only one left standing:

**So production translated them and this build does not translate them the same way.** The
build machine's uncaptured f2c workarounds (the original defect this whole document is about)
handled these automatic arrays by some means other than a fixed bound, and that means
difference is the remaining candidate — not a flaw in the rewrite, which is verified faithful
against upstream.

**So `slavintmortar` and `slavintpoints` are now deliberately left stubbed** — see
`SKIP_FILES` in `tools/f77ify.py`. A stub aborts with the routine's name; a bounded routine
with wrong numerics returns an answer. For a solver the second is far worse, and the stiff
version of the deck had been hiding it behind what looked like a tolerance problem.

It is carried as a KNOWN GAP in the workflow rather than a failure: mortar contact was 100%
stubbed in a clean build, so there is no working state to have regressed from, and a
permanently red gate would destroy its value for the four decks that do guard real
regressions. It reports in full on every run. Remove it from `KNOWN_GAP` once it passes.

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
needing hand work now translates, including `e_c3d.f`. The current list is the 19 above,
which the build prints on every run — read it there rather than from a copy that goes stale.

## Note on US3/US45

`e_c3d_us3`, `e_c3d_us45`, `resultsmech_us3/45`, `us3_sub`, `us4_sub` are the *user*
shell elements. BUILD-WEH.md records that FreeCAD never emits them, so those are the
one group that can stay stubbed.
