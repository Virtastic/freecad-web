> **Superseded, 2026-09-04.** This document reasons throughout about a wasm32 build and its
> 2 GB/4 GB heap limits. The project is now `wasm64-emscripten` with a 16 GiB ceiling, and
> the signed-pointer hazard that drives much of the analysis below does not exist at 64-bit.
> Kept as the record of how the decision was reached. Current state: `BUILD-WEH.md`.

# What is left after build-20260826-fem, and how to finish it

Written 2026-08-26, with the release in flight. Everything here is *after* the release: none
of it is a regression, and none of it blocks shipping what is built.

Ordered by value per hour, not by how interesting it is.

---

## 1. The 2 GB memory ceiling — DONE, and the last of it was a reporting bug

**Status 2026-09-02: shipped.** The link carries `ALLOW_MEMORY_GROWTH=1`,
`INITIAL_MEMORY=1 GB`, `MAXIMUM_MEMORY=4 GB`, and `tools/patch-freecad-js.py` was
re-derived for the `GROWABLE_HEAP_*()` accessor form — which is what the section below
says has to happen first. Measured on the live build: `malloc` grew the heap 1 → 1.9 →
3.0 → 3.58 GB.

The tail of it was not the link at all. The page's pressure monitor divided the used
bytes by `HEAPU8.buffer.byteLength` — the heap's CURRENT size, 1 GB at boot, not its
ceiling — so it warned "nearly full … cannot grow past 2 GB" at ~800 MB and force-saved
before the heap had grown once. `maxByteLength` is no better on a wasm shared memory
(it mirrors `byteLength`, because growth swaps the buffer), so the ceiling is now a build
constant kept in step with the link flag. Anything else reading `byteLength` as a ceiling
has the same bug.

The reasoning that got it here is kept below.

### (historical) 4 GB is one afternoon, and the blocker is named

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

**DONE 2026-08-26.** All 27 apply on a real growable build, proven both ways: the previous
patcher reports exactly the two sites CI reported (`glMaterialfv: EMISSION and
AMBIENT_AND_DIFFUSE`, `line batching drain: glDrawElements`) as NOT FOUND on that file, and
the current one applies them. Idempotent on a second pass, and unchanged on a 2 GB build.

Growth turned out to change **four** things, not one. The first was known; the other three
were found by diffing a real growable link against the 2 GB one, and each on its own is
enough to make an anchor miss:

    1. HEAPF32[i]                ->  GROWABLE_HEAP_F32()[i]
    2. [param>>2]                ->  [param>>>2>>>0]              unsigned-safe indexing
    3. var _f=(a,b)=>{...};      ->  function _f(a,b){...}        and the ";" goes with it
    4. a pointer argument gains a coercion prologue:
           function _glDrawElements(mode,count,type,indices,...){indices>>>=0;if(...

(4) is why this could not stay a string transform. The prologue is emitted per pointer
argument, is not derivable from the anchor, and dropping it would silently remove the
coercion that keeps the pointer valid past 2 GB -- which is the whole point of the build. So
the growable form is matched as a regex that CAPTURES the prologue and the replacement puts
it back.

The original plan for this item said to:

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

**And expect a cost.** emscripten warns about this exact pairing, in the toolchain this
project builds with:

    tools/link.py:493
        diagnostics.warning('pthreads-mem-growth',
            '-pthread + ALLOW_MEMORY_GROWTH may run non-wasm code slowly,
             see https://github.com/WebAssembly/design/issues/1271')

This build is `-pthread` and now also `ALLOW_MEMORY_GROWTH=1`. That is not a reason to
abandon the 4 GB ceiling -- a real `abort/oom` from a real session is in the event log, so
the ceiling is being hit -- but it is a reason the boot comparison has to actually be run
before growth is called production, rather than assumed harmless because the gates stay
green.

Three purpose-built benchmarks were tried first and all three measured something else:

| attempt | what it actually reported |
|---|---|
| `requestAnimationFrame` intervals | flat 16.67 ms at p50, p90 *and* worst — that is vsync. A CAD viewport is event driven, so rAF ticks whether or not Coin draws. |
| `viewRotateLeft` + `updateGui` | 0.01 ms for 92,000 triangles. The redraw is deferred; the call returns before any GL work. |
| tessellate + boolean in a loop | no result in 15 minutes — while the identical probe under `tools/run-in-app.py` finished in under a second |

Two of those would have gone into a document as fact. If a fourth is attempted, the bar is
that it must move when the thing it measures moves.

---

## 2. CalculiX threading — ANSWERED, and now re-runnable

**This was measured on 2026-08-25 and the answer is recorded in `ROADMAP.md` section 7.**
Writing it up here as outstanding work was a mistake of the same kind the R7 entry made
yesterday: the table said "untouched" about something that had already been measured.

What was found: a `-pthread` CalculiX was built and run against the serial one on the same
decks, through the real browser bridge.

| deck | serial | threaded | threaded, 4 threads configured |
|---|---|---|---|
| 1 element | 0.5 s | 0.5 s | — |
| 1,080 elements | 0.46 s | 0.45 s | — |
| 8,640 elements | **2.80 s** | 3.09 s | **4.71 s** |

Output was byte-identical — the same 2,008,434-byte `.frd`, the same maximum displacement
of 0.0199569 mm — so the threaded build is *correct*. It is simply not faster. Unconfigured
it pays for threading it never uses; given four threads it is 68% slower than serial.
Thread creation and atomics cost more in wasm than CalculiX's parallel sections save at
these sizes.

**So threading stays off, and that is a decision with numbers behind it, not a stopgap.**

**What was actually missing** was any way to repeat that. The comparison was done by hand,
so the next ccx rebuild would have been back to judging by exit code — and an exit code
cannot see this failure at all. That is what `tools/ccx-compare.js` is for:

    node tools/ccx-compare.js --a play-gui/ccx.js --b <candidate>/ccx.js --repeat 3

It parses both `.frd` files and compares them value by value at 1e-9 relative, because a
race in parallel assembly shifts a digit rather than crashing. It fails any field that is
exactly zero in both runs, since two identical zeros is precisely what the failed
`pthread_create` produced — rc 0, an `.frd` on disk, every number wrong.

Two things it will not do, both learned by running it against itself:

* it will not call a sub-half-second deck a speedup. The same module compared with itself
  reported "1.39x faster" before an untimed warmup was added; that was V8 compiling the
  wasm. The five decks in `scratchpad/ccxval` run in about 100 ms and are labelled as
  untimeable. Speed questions go to the 8,640-element beam.
* it will not treat a tiny value as a zero. `elas` has an `ERROR` field of magnitude
  1.7e-14 — a real residual — and the first version of the zero-check failed it. The test
  is now for exactly zero, which a residual never is and an unassembled matrix always is.

---

## 3. Firefox and Safari — NOT A TARGET

Chrome and Edge are the supported browsers, by decision. This is not a gap to close, and
the Asyncify fallback is not work anyone should schedule.

Recorded here because it keeps being re-raised as a limitation -- including by me, in the
first version of this plan, where it was sized at two to three days and called "the
audience doubler". That was an assumption about the product, not a requirement of it. The
app refuses other browsers up front, having downloaded nothing, which is the correct
behaviour for a deliberate support boundary.

## 4. Addons with compiled extensions — NO-GO for now, with the evidence

Asked for a spike to a go/no-go. The go/no-go is reachable without the spike, from the
toolchain this project actually builds with (emsdk 3.1.70 on the build box):

    tools/link.py:490
        diagnostics.warning('experimental', '-sMAIN_MODULE + pthreads is experimental')

This build cannot drop `-pthread`: it is what gives SharedArrayBuffer, `PTHREAD_POOL_SIZE=16`
and Qt's threading, and the Addon Manager's own network calls depend on a worker thread. So
dynamic linking here is not "supported with a size cost" — it is an experimental combination
stacked on top of JSPI, which is itself experimental, in the one component whose failure
mode is that nothing starts at all.

The surface is also larger than a normal `MAIN_MODULE=2` case: **247 static archives** on the
link line and **72 inittab entries** fixed at link time. A side module can reference any of
the FreeCAD, OCCT, Coin or Qt API, so "keep only what is referenced" keeps a great deal.

**Decision: no.** Pure-Python addons work today and are gated end to end — fetched through
the proxy, unpacked, surviving a reload. Compiled addons wait for `MAIN_MODULE + pthreads`
to stop being flagged experimental, or get pre-linked individually if a specific one is
worth it.

**If someone wants the number anyway,** the spike is: copy `fc-linkcmd-weh.sh` with
`-sMAIN_MODULE=2`, build one trivial `SIDE_MODULE`, and compare binary size, boot-to-Ready
and the render gate against the numbers already recorded here. One link cycle -- which
now costs ~45 minutes rather than the ~110 this document was written against, since the
compile is cached; see V7.

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

## 6a. The local gate "flake" that was not a flake

`tools/boot-gate.py --scenario all` appeared to die at exit 255 on Windows -- a different
scenario each time, no traceback, no watchdog message -- while every scenario passed when
run individually. It was reported twice as an unexplained flake, and Windows, memory
pressure and orphaned browsers were all investigated and cleared.

It was none of those. **Exit 255 is what a command returns when the harness running it kills
it at a timeout.** Verified directly: a process told to sleep 400 s under a 60 s limit exits
255 having printed only its first line.

Every symptom follows from that. It died at a different scenario each time because that is
wherever the run had reached at the cutoff. There was no traceback because SIGKILL leaves
none. Individual scenarios passed because each one finishes inside the limit. The full run
takes ~4 minutes against a warm tree and considerably longer against a cold one; it was
being given ten.

Recorded because the wrong diagnosis was expensive: it cost an instrumented re-run, a
faulthandler harness, and two status reports describing a healthy gate as unreliable.
Under instrumentation with a sufficient timeout the same gate passed 13/13 in 4m08s with a
clean exit.

## 7. Watch items — cheap, do them with the release

- **2.2c** — the Addon Manager's catalogue fetch may block the UI. With QtSvg present the
  real path can finally be driven; watch whether the window stops painting during the fetch.
- **R2** — `QEventLoop::exit` on a null function. Not reproducible, including against a 3D
  pipeline now demonstrably drawing. The detector stays in the gate's fatal list.
- **V7 -- FIXED AND MEASURED.** The compile went from 88 minutes to 22, and the five
  runs behind that number are worth keeping, because "it feels faster" is how a
  regression hides:

  | run | compile | cache state |
  |---|---|---|
  | 33004112792 | 87.9 min | none |
  | 33016454127 | 88.5 min | none (second baseline) |
  | 33026503108 | 88.0 min | cold -- populating, and it cost nothing measurable |
  | 33075218442 | 22.1 min | warm, 95.66% hits (2537/2652) |
  | 33079363822 | 22.1 min | warm, 95.63% hits (2536/2652) |

  Two baselines because one is an anecdote. Two steady-state runs for the same reason,
  and they agree to a tenth of a minute. The populate run is the honest part: enabling
  ccache did not make the first build slower in any way the clock could see, which was
  not guaranteed.

  The cause was never mysterious once measured. The ~200 files `patches/apply.sh`
  rewrites get a fresh mtime every run and fan out to 1,860 of ~2,700 ninja edges, so
  the compile ended `reached: [1860/1860]` with a 421 MB build-tree cache restoring
  perfectly. 1,860 was a deterministic floor, not bad luck: 22.7 CPU-seconds per
  translation unit, spent reproducing byte-identical objects.

  The remaining 4.4% of misses are the translation units carrying `__DATE__`/`__TIME__`.
  ccache refuses those by default and `sloppiness` is deliberately empty, so they are
  recompiled every run. That is the correct answer -- `time_macros` would cache a binary
  claiming a build date it does not have, which is the same class of lie as a stamp that
  says "patched" over an unpatched tree.

  Two alternatives are recorded as rejected, so they are not re-proposed as obvious wins:
  **caching the patched tree** (a claim beside content, the exact shape that once cost
  this project its boot) and **touching the patched files back to a fixed mtime** (faster
  than ccache, and wrong in the should-rebuild-but-doesn't direction, which is silent).
  ccache errs the other way: an unrecognised input is a miss, and a miss is slow, not
  wrong.

  It is not taken on trust either. A gate after every compile pulls ~15 objects spread
  across modules, re-runs each one's exact `ninja -t commands` line under
  `CCACHE_DISABLE=1`, and compares sha256. Two clean runs so far, 3m22s each, which also
  settles that these wasm objects are bit-reproducible -- an assumption the whole scheme
  rests on and which was worth confirming rather than believing.

  Link is now the largest single stage at 15.3 minutes. Out of scope; the feedback loop
  that made this session expensive is fixed.

---

## Where the production list stands

The six items, and what is actually true about each as of 2026-08-26.

| # | Item | State |
|---|---|---|
| 1 | Field visibility — errors and usage | **Done.** `tools/fcweb-events.py` |
| 2 | The 4 GB heap, and what it costs | **In flight.** Patcher fixed, link building |
| 3 | Save to disk — the half a machine can test | **Done.** `--scenario save` |
| 4 | Storage persistence — the half a machine can test | **Done.** `--scenario storage` |
| 5 | CalculiX threading | **Answered.** Measured 08-25; now re-runnable |
| 6 | Compiled addons — go/no-go | **No-go**, from the toolchain, above |

**1 — field visibility.** The beacons had been arriving since 2026-08-16 and nobody could
read them, so the questions were never asked. Now they are: sessions, boots that never
reached Ready, crashes and aborts by kind, time-to-Ready percentiles, and a per-build
breakdown. The per-build split is the part that matters — the aggregate said 23% of
sessions never reach Ready, which reads like a live emergency, and almost all of it was one
pre-port build that has not been deployed for days. The current build loses 6%; the newest
loses none. A rate means nothing without the thing it is a rate of.

**3 and 4 — save and storage.** Both are the machine-testable half of an item whose other
half needs a human (`showSaveFilePicker`, and the persistence grant Chrome ties to
installation). Both gates assert the thing that actually costs a user something rather than
the thing that is easy to assert: save reopens the delivered bytes and checks the geometry
came back, and storage drives the refusal branch to prove the app warns. Save immediately
earned its keep by catching a wrong-document download in `--scenario all`.

**What is left is item 2, and only its second half.** Growth is enabled, the patcher
handles the `GROWABLE_HEAP_*()` accessor form, and the link is running. The comparison is
five boots at 4 GB against the recorded 2 GB baseline of 7, 9, 9, 11, 11 s (median 9) on
the same machine — and it has to be run rather than assumed, because emscripten warns about
`-pthread` together with `ALLOW_MEMORY_GROWTH` in this exact toolchain.

Three attempts at a frame-time benchmark failed and were deleted rather than shipped; the
table above records how each one lied. Boot time is measured against a baseline that
already exists, which is why it is the number being used.
