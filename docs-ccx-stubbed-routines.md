# CalculiX: making a clean build reproduce production's solver

Measured by `.github/workflows/build-ccx.yml` from CalculiX 2.22 upstream. Started at 69
stubbed routines (run 31985042689); now **17**, and all four validation decks reproduce
production exactly (run 31996275820).

The count was 19 until 2026-08-18, and two of those were never routines: `gauss.f` and
`xlocal.f` are INCLUDE files of Gauss-point data with no subprogram head anywhere in them.
The build handed each to f2c as though it were a translation unit, which cannot work, and
then recorded the failure as a stubbed routine. `build-ccx-weh.sh` now recognises a data
include and skips it -- verified against all 977 `.f` files, where the rule selects exactly
those two and nothing else.

## Diagnosing a stub without a CI run

`tools/build-f2c-local.sh` builds f2c natively using the clang that ships inside emsdk
(`emsdk/upstream/bin/clang` -- emsdk carries upstream LLVM, so no gcc, make or MSVC is
needed). The loop becomes: run `tools/f77ify.py` on a source, run that f2c on the result,
read the error. Seconds, against the exact bytes the build feeds it.

This matters more than convenience. f2c numbers ITS OWN input -- the rewritten file under
`build-ccx-weh/f77` -- so "Error on line 221 of e_c3d_us45.f" points at a file that only
exists on the runner, and several CI runs were spent reading line 221 of a locally
regenerated copy that might not have been the same bytes.

**And the reported line can be a long way from the cause.** For `e_c3d_us45.f`, line 221 is
`real*8 co(3,*),...` -- a declaration that is valid, and that f2c accepts on its own. What
was proven locally, in minutes rather than runs:

- f77ify's only change to that declaration is `elconloc(ncmat_)` -> `elconloc(1000)`, the
  bound the automatic-array rule must apply. So f2c is rejecting essentially upstream source.
- The subroutine header (80 dummy arguments, 12 lines) parses on its own.
- Everything between the header and line 221 is 172 comment lines and one blank.
- Splitting the declaration, or removing `elcon(0:ncmat_,ntmat_,*)`, does not help; the error
  simply moves.

So it is an f2c parse failure on stock CalculiX, not damage this repository does -- which
fits the last fact: **production stubs `e_c3d_us45` too**. Closing it would put this build
ahead of the module being served, on a US45 user shell element FreeCAD never emits, with no
deck able to validate the result.

## Where this ended up (run 32196565134)

**974 of 975 routines translate. Three stubs remain, and only two are a gap.**

| | production | this build |
|---|---|---|
| `e_c3d_us45` | STUBBED | STUBBED — matches |
| `slavintmortar`, `slavintpoints` | compiled | **STUBBED — the deliberate gap** |
| `e_c3d_us3`, `resultsmech_us3`, `resultsmech_us45`, `umat_ciarlet_el` | STUBBED | **compiled — ahead of production** |
| everything else probed | compiled | compiled |

Read off both binaries with `tools/ccx-stub-diff.py`, controls passing.

    ccx.wasm      4,783,704 bytes
    production    4,784,783 bytes
    gap               1,079 bytes      (was 986,945 when this document opened)

So the only routines this build refuses that production runs are the two mortar-contact
ones, and they are refused ON PURPOSE: bounded, they converge to a physically invalid
answer (negative contact pressure on a symmetric model), and an abort that names the routine
beats a solver that returns a wrong number. `e_c3d_us45` is stubbed in the module being
served today as well, so it is not a divergence; it is a US45 user shell element that
FreeCAD-web has never supported.

What closed the rest, in order: `gauss.f`/`xlocal.f` were never routines; bounds for
`netet`, `norien`, `nfront`/`nfronteq`, `numpts`, `netet_`, `ng`; `patch.f` via HYBSVD's
declared leading dimensions; F90 `matmul`/`transpose` (`bridge/ccx_matmul.f`); whole-array
assignment; sectioned operands inside the generated loops; and array expressions passed as
call arguments.

Every step was gated on the four decks staying identical to production, and two of them
caught real damage on the way -- a SIGPIPE race that deleted `allocation.f` from the build,
and a call-argument rewrite that broke seven contact files and was reverted.

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

(An earlier version of this file called `gauss.f` a stubbed routine. It is not a routine at
all: it is an INCLUDE file of Gauss-point data, pulled into 60 others. Its appearing in
`UNCONVERTED.txt` was meaningless -- f2c cannot translate a bare data include on its own, and
`e_c3d.f` translating proves the include resolves fine.

**The same was true of `xlocal.f`, and this file said otherwise for two days.** It listed it
under "separate root causes" as a routine needing a fix, and the root-cause table attributed
one failure to `subscripts on scalar variable`. It is an include of 3D local Gauss-point
coordinates, pulled into `calcexternalwork.f`, `printoutface.f` and `printoutfacefem.f` --
all three of which translate fine, which is the same proof used for `gauss.f`. Those
"errors" were the single largest group in the build: **375 of them in run 32140989422**, every
one an artifact of asking f2c to translate a bare data include.

Neither is handed to f2c any more, so both the error noise and the two phantom entries are
gone.)

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

    basis  calcview  cavity_refine  cavityext_refine  extendmesh  gen3dfrom2d
    interpolateinface  patch  slavintmortar  slavintpoints  umat_ciarlet_el
    e_c3d_us3  e_c3d_us45  resultsmech_us3  resultsmech_us45  us3_sub  us4_sub

(Read from CI run 32140989422's own output, not maintained by hand. The previous copy of
this list was wrong in both directions: it still named `near2d` and `near3d`, which the
file-scoped bounds fixed, and it omitted `slavintmortar`/`slavintpoints`, which the text
below explains are stubbed on purpose.)

| group | note |
|---|---|
| US3/US45 user shells (6) | BUILD-WEH.md records FreeCAD never emits them — these can stay stubbed |
| ~~`gauss.f`, `xlocal.f`~~ | INCLUDE files of Gauss-point data, not routines. No longer handed to f2c, so no longer listed |
| CalculiX's own remesher (`cavity_refine`, `cavityext_refine`, `extendmesh`, `basis`, `interpolateinface`) | FreeCAD meshes with gmsh, so this path is unused |
| deliberately excluded dimensions (`calcview`, `patch`) | see the exclusion list in `tools/f77ify.py` — each would be unsafe to token-match |
| mortar contact (`slavintmortar`, `slavintpoints`) | `SKIP_FILES` in `tools/f77ify.py` — bounded, they converge to a physically invalid answer, so an abort is the lesser evil. See the contact section below |
| `umat_ciarlet_el`, `gen3dfrom2d` | separate root causes |

None is reached by the four decks. That is a statement about coverage, not correctness: an
analysis that does reach one stops with a message naming it, rather than returning a wrong
answer.

### Production stubs five routines too, and the binary says which

`tools/ccx-stub-diff.py` reads the stub list straight out of a built module. This document
claimed the binary "cannot be mined for a stub list" because the routine name reaches the
abort as a runtime `%s`. That is true of the format string and false of the argument:
`ccx_make_stubs.py` emits `call ccxstb('<name>')`, and f2c turns that Fortran literal into an
ordinary NUL-terminated C string sitting in the data section.

The control that makes it trustworthy: `e_c3d`, `mafilldm`, `resultsmech`, `resultstherm`,
`e_c3d_th` and `extrapolate` are all documented as compiled in production, and not one of them
produces such a literal. The tool refuses to report if any control fails.

Run against the deployed `ccx.wasm`:

| routine | production | this build (run 32145598043) |
|---|---|---|
| `e_c3d_us3`, `e_c3d_us45` | **STUBBED** | STUBBED |
| `resultsmech_us3`, `resultsmech_us45` | **STUBBED** | STUBBED |
| `umat_ciarlet_el` | **STUBBED** | STUBBED |
| `us3_sub`, `us4_sub` | compiled | STUBBED |
| `patch` | compiled | STUBBED |
| `slavintmortar`, `slavintpoints` | compiled | STUBBED |
| everything else above | compiled | compiled |

**So five of the ten are not a gap at all.** US3/US45 user shell elements and the Ciarlet user
material abort in the module being served today, exactly as they do here. Converting them
would not restore functionality that production has; it would add functionality production
lacks, and the "must match production" gate could not validate it, because production aborts
on those paths.

That leaves five genuine divergences, and they are not equally hard:

- `us3_sub`, `us4_sub` — compiled in production, but their only callers (`e_c3d_us3`,
  `e_c3d_us45`) are stubbed there, so they are dead code in the shipped module. Converting
  them closes the byte gap and changes no behaviour.
- `patch` — compiled in production, reachable through `zienzhu`, and worth closing.
- `slavintmortar`, `slavintpoints` — compiled in production; bounded here they converge to a
  physically invalid answer, which is why they are in `SKIP_FILES`.

It also explains the size gap arithmetic. Those five files are 126,914 bytes of source
against a 137,647-byte gap between this build's `ccx.wasm` and production's.

### What would actually be needed to convert the rest

Measured against CalculiX 2.22 by running `tools/f77ify.py`'s own analysis over each stubbed
file, so this is the dimension names that have no bound rather than a guess:

| dimension | file(s) | note |
|---|---|---|
| `netet` | basis.f | tets in the master mesh |
| `netet_` | cavity_refine.f, cavityext_refine.f | all-or-nothing: `iecav`, `ifcav`, `ig`, `ige` stay adjustable and the file reverts |
| `nfront`, `nfronteq` | extendmesh.f | mesh front |
| `numpts` | interpolateinface.f | points on a face |
| `norien` | gen3dfrom2d.f | orientations |
| `ipoints`, `iterms` | patch.f | `z(ipoints,ipoints)` is SQUARE — any generous bound explodes, and the per-array budget refuses it |
| `x`, `y`, `idata`, `rdata`, `ng` | calcview.f | `fform(x,y,idata,rdata)` is a FUNCTION declaration, not an array |

Every one of these routines is CalculiX's own remesher, its cavity-radiation view factors, or
a user-element hook. **FreeCAD reaches none of them** — it meshes with gmsh — so converting
them buys a smaller number and nothing else, while spending stack or static memory and taking
on the stride and `save` hazards documented below. The decks cannot help either: they do not
exercise these paths, so a green run after converting them would prove only "no regression",
never "correct".

That is the argument for leaving them. It is written down so the next person weighs it rather
than rediscovering it.

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

### Two more hypotheses eliminated, 2026-08-18

Both were checked against the real 2.22 source and the code f77ify actually emits, and both
are wrong. Recorded so the next attempt starts further along.

**An out-of-bounds read at index 0.** `slavintmortar.f:392` has the guard commented out --

    c     if(id.ne.0 .and. icoveredmelem(id).eq.nelemm)then

-- which looks like `icoveredmelem(0)` could be read when `nident` returns id=0, giving a
value that depends on what precedes the array in memory, and therefore on the build. It is
not: the line below replaces the guard with `if(id.gt.0) then`, and the comparison sits
inside it. `slavintpoints.f:298` keeps the original combined form. Both are safe.

**The `cycle` rewrite jumping to the wrong place.** The `cycle` at `slavintmortar.f:397` sits
inside an `if ... endif` with the covered-stack insertion after it, so it must skip that
insertion -- and a rewrite that landed just after the `endif` would silently add master
elements that should have been skipped, which would look exactly like this defect. It does
not: f77ify emits `goto 8001`, and label 8001 is `continue` immediately before the loop's
`enddo`, ~300 lines later. Correct.

**The strongest remaining hypothesis, and how to test it.** `tools/ccx-stub-diff.py` now
shows production has both routines COMPILED, and the stub format string proves production was
built with this repo's tooling -- so the build machine's f2c accepted these automatic arrays
by some means this one does not. That points at the translator rather than at the source: an
f2c built with different flags, a patched f2c, or a post-processing step that emits C99
variable-length arrays instead of fixed bounds. If that is what happened, production's
routines are faithful translations and every bounded version here is an approximation, which
would explain why the bound VALUE provably does not reach the results (halving it gave
byte-identical wrong numbers) while the results are still wrong.

Test it by capturing the build machine's `deps/src/f2c` and diffing it against netlib's
`src.tgz`, the same way `tools/capture-build-machine-headers.sh` captures the compat headers.
That is a read-only command on that machine and it would settle the question.

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
