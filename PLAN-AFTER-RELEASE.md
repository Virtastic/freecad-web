# What is left after build-20260826-fem, and how to finish it

Written 2026-08-26, with the release in flight. Everything here is *after* the release: none
of it is a regression, and none of it blocks shipping what is built.

Ordered by value per hour, not by how interesting it is.

---

## 1. The 2 GB memory ceiling — 4 GB is one afternoon, and the blocker is named

**Why this is still open, precisely.** It is not a wasm limit and never was. wasm32 addresses
4 GB, `scratchpad/linkcmds/fc-linkcmd-weh-grow.sh` already exists and already carries
`ALLOW_MEMORY_GROWTH=1`, `INITIAL_MEMORY=1 GB`, `MAXIMUM_MEMORY=4 GB`, and it links.

What stops it is one mechanical thing. With growth enabled, emscripten changes the *form* of
every heap access in the generated JS:

    HEAPF32[param>>2]                 becomes    GROWABLE_HEAP_F32()[param>>>2>>>0]

`tools/patch-freecad-js.py` carries 27 GL patch sites whose anchors are written against the
first form. Against a growable build they stop matching — and because every throw-removal
patch replaces its site with the literal `0`, which occurs everywhere in minified JS, the
"already applied" arm fired for nine of them. The file reported success and still threw from
nine GL entry points, and a throw inside a GL call unwinds through Coin and takes the
viewport with it.

That was found once and the growth build was reverted. The tool now *detects* the condition
and refuses (`GROWABLE_HEAP accessors -- ... must be re-derived for it`), so it can no longer
fail silently. But refusing is not the same as working.

**Do.** Make the anchors form-agnostic rather than re-deriving 27 sites by hand:

- replace the literal heap-access text in each anchor with a pattern accepting both forms —
  `(?:HEAPF32\[|GROWABLE_HEAP_F32\(\)\[)` and the `>>2` / `>>>2>>>0` variants;
- keep `check_postconditions` exactly as it is, but drop the GROWABLE rejection once the
  table applies to both. The postcondition that matters — *none of the nine throw sites may
  survive* — is already checked against the file itself rather than against a status, which
  is the only reason the original failure was ever caught;
- link with `fc-linkcmd-weh-grow.sh`, and make it production if the cost is acceptable.

**Done when.** `tools/patch-freecad-js.py` reports all 27 applied on a growable build with
zero postcondition violations; the render gate still reads a shaded solid (it reported 196
distinct colours and 27.9% non-background on the 2 GB build, so a collapse to flat shading
would show); and a model that exhausts 2 GB today completes. Record the fps cost — growth
adds a bounds check to every access, and "it is bigger" is not the whole answer.

**Size.** Half a day, most of it one link cycle.

### How to measure the cost -- and how not to

Growth is re-enabled (commit 13de69e) and the link is running. The comparison uses **boot to
Ready**, because it is already collected on every gate run, it unpacks a 194 MB preload and
initialises CPython, Qt and OCCT -- about as heap-bound as this application gets -- and
growth taxes every heap access.

    2 GB, growable=False, five boots on one machine:  7, 9, 9, 11, 11 s  (median 9)

Run the same five against the 4 GB artifact, same machine, and the answer is there.

Three purpose-built benchmarks were tried first and all three measured something else:

| attempt | what it actually reported |
|---|---|
| `requestAnimationFrame` intervals | flat 16.67 ms at p50, p90 *and* worst — that is vsync. A CAD viewport is event driven, so rAF ticks whether or not Coin draws. |
| `viewRotateLeft` + `updateGui` | 0.01 ms for 92,000 triangles. The redraw is deferred; the call returns before any GL work. |
| tessellate + boolean in a loop | no result in 15 minutes — while the identical probe under `tools/run-in-app.py` finished in under a second |

Two of those would have gone into a document as fact. If a fourth is attempted, the bar is
that it must move when the thing it measures moves.

---

## 2. CalculiX threading — a flag and a verification

`build-ccx.yml` already has a `pthreads` input, described in its own text as "the unverified
fast path". The reason it is off is specific and good: without `-pthread`, `pthread_create`
is a stub that fails, ccx never checks the return value, and the matrix came out identically
zero. A solver that returns zeros is worse than a slow one.

**Do.** Dispatch the lane with `pthreads: true`, then solve the gate's own cantilever both
ways and compare the **CalculiX decks**, not just the exit codes — compile success, module
size and stub counts all stay green while the answer is wrong.

**Done when.** The threaded build reproduces the serial result within tolerance (the gate
already asserts 0.95–1.05 of the closed form) and is measurably faster on the 8,640-element
beam. If the matrix is zero again, it stays off and the finding is written down.

**Size.** One build lane plus an hour of comparison.

---

## 3. Firefox and Safari — NOT A TARGET

Chrome and Edge are the supported browsers, by decision. This is not a gap to close, and
the Asyncify fallback is not work anyone should schedule.

Recorded here because it keeps being re-raised as a limitation -- including by me, in the
first version of this plan, where it was sized at two to three days and called "the
audience doubler". That was an assumption about the product, not a requirement of it. The
app refuses other browsers up front, having downloaded nothing, which is the correct
behaviour for a deliberate support boundary.

## 4. Addons with compiled extensions — a spike with a go/no-go

The static monolith fixes the inittab at link time, so only pure-Python addons can work.
Pure-Python installs are proven end to end (2 MB fetched through the proxy, 217 entries
unpacked, still present after a reload).

**Do.** Evaluate `-sMAIN_MODULE=2` with a published side-module ABI. It costs size and some
speed, so this is an evaluation, not a commitment. In the meantime, pre-link the handful of
popular compiled addons so they simply work.

**Done when.** Either a `SIDE_MODULE` extension imports at runtime, or the curated set is in
and the trade-off is written down with numbers.

**Size.** A day to a go/no-go.

---

## 5. First load / payload size — NOT A PRIORITY

Descoped by decision. The second visit already costs nothing (Cache Storage), brotli is in,
and the numbers are known if it is ever wanted: 95.7 MB transferred on a cold load, of which
58.0 MB is FreeCAD.wasm and 37.6 MB the data package.

Recorded because I kept returning to it unprompted -- three separate proposals, including
one costed at a week to defer 82 MB of workbench data, which would have attacked the smaller
half of the download. The 4.79 MB of numpy C source already pruned stays, because it was an
hour and is pure waste either way. Nothing further is scheduled.

## 6. The human half — one scripted session

Four things a machine cannot check, all in `MANUAL-QA.md`: the PWA install and whether the
storage grant is given (**R5**), starting a native drag, the `showSaveFilePicker` dialog, and
whether it looks right.

**Do.** One pass against the released build, recorded in `MANUAL-QA.md` beside the measured
production baseline.

**Done when.** `navigator.storage.persisted()` returns true after install, and the other
three are recorded as pass or fail with a screenshot.

**Size.** Twenty minutes, but it needs a person.

---

## 7. Watch items — cheap, do them with the release

- **2.2c** — the Addon Manager's catalogue fetch may block the UI. With QtSvg present the
  real path can finally be driven; watch whether the window stops painting during the fetch.
- **R2** — `QEventLoop::exit` on a null function. Not reproducible, including against a 3D
  pipeline now demonstrably drawing. The detector stays in the gate's fatal list.
- **V7** — 90 minutes per link, because the source tree is kept pristine and re-patched every
  run. Caching the patched tree would fix it and is exactly the shape that cost this project
  its boot once. Left alone deliberately; revisit only with a content check, never a stamp.

---

## Order

1. Human pass (20 minutes, gates the release's credibility)
2. Memory ceiling (half a day, largest user-visible win)
3. CalculiX threading (one lane)
4. Compiled-addon spike (go/no-go)

These are about a week in total.
