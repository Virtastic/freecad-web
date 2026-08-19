# Roadmap: from "works" to "someone can do their job in it"

> **Status 2026-08-18.** Four things changed today and two of them were defects nobody knew
> about, so read this table before the prose below it -- the prose is older.
>
> | # | item | state |
> |---|---|---|
> | 9 | **Edge caching** | **fixed and live.** `FreeCAD.wasm` and `FreeCAD.data` returned `cf-cache-status: DYNAMIC` -- Cloudflare judged them ineligible and went to the origin every time, so every cold visitor pulled ~119 MB off the single OVH VPS. The rule `infra/terraform` declares had never been applied. Applied via `.github/workflows/cache-rules.yml` (run 32209996790); all three assets now HIT. |
> | 10 | **CalculiX stubs** | **19 -> 3**, 974/975 routines translate, and the module is within **1,079 bytes** of production (was 986,945). Of the three left, `e_c3d_us45` is stubbed in production too, and the two mortar-contact routines are refused on purpose. See `docs-ccx-stubbed-routines.md`. |
> | 11 | **Clean-checkout build** | **still blocked, but by one command.** `gl_compat.h` and `qprocess_stub.h` are force-included into everything and exist only on the build machine. `bash tools/capture-build-machine-headers.sh` there, and commit. |
> | 12 | **CI trustworthiness** | Coin3D had never been built at all; `patches/apply.sh` had never applied a patch in CI; OCCT was compiling with two exception models at once; CPython lost JSPI entirely without `-DPY_CALL_TRAMPOLINE=1`. All fixed, all gated. Eight of 23 dependencies now build on a hosted runner. |
>
> **Status 2026-08-19: what "fully usable" still needs.** Asked directly whether the app has
> network access and plugins. Checked rather than assumed, and the answer is *partly*, with
> four gaps that are now tracked items rather than surprises.
>
> | # | item | state |
> |---|---|---|
> | 13 | **Outbound HTTP** | **works in principle, constrained in practice.** QtNetwork is part of qtbase and IS built (`-submodules qtbase,qtsvg,qtdeclarative,qttools`), and Qt-for-wasm implements `QNetworkAccessManager` over the browser's fetch. `DownloadItem`/`DownloadManager` use it. BUT `infra/nginx.conf` sets `Cross-Origin-Embedder-Policy: require-corp`, which SharedArrayBuffer (and therefore threads) requires -- and under it every cross-origin response must carry CORP/CORS headers or the browser refuses it. Most third-party hosts do not. So requests to arbitrary sites will mostly fail, and anything that needs to reach the wider web needs a same-origin proxy. Not yet built. |
> | 14 | **`NetworkRetriever` is inert** | FreeCAD's own "fetch from the web" helper shells out to **wget through QProcess**, and Qt-for-wasm has no QProcess -- `toolchain/include/qprocess_stub.h` makes it compile by making it do nothing. Anything routed through it silently does nothing. Should be rewritten onto QNetworkAccessManager, or removed so it fails honestly. |
> | 15 | **Addon Manager / plugins** | **off entirely.** `BUILD_ADDONMGR=OFF`, because AddonManager is a git *submodule* and GitHub tarballs carry none. Beyond fetching it, installing an addon at runtime assumes `git` and a writable install tree, both via QProcess -- so it needs a wasm-native install path (fetch a zip over HTTP, unpack into IDBFS) before it means anything. This is the single biggest gap against "usable by anyone". |
> | 16 | **Compiled Python addons** | **not possible by construction, and that is worth stating.** This is one static monolith: every C extension is registered in `MainGui.cpp`'s inittab at link time. There is no `pip`, no dynamic loading. Pure-Python addons can be dropped into the virtual filesystem and will work; an addon shipping a compiled extension cannot be installed without relinking the whole binary. |
> | 17 | **Web workbench** | `BUILD_WEB=ON` compiles, but Qt is built `-skip qtwebengine`, so the embedded browser view has no engine behind it. Needs checking against what the workbench actually does at runtime before it can be called working. |

> **Status 2026-08-16** (the original table; items 1-8 below are unchanged unless noted).
>
> | # | item | state |
> |---|---|---|
> | 1 | QInputDialog | **shipped** — natives restored, live, harness written |
> | 2 | Error reporting | **shipped** — four anonymous counters, live and recording |
> | 3 | Storage evictable | **shipped** — user-nominated backup folder, live |
> | 4 | GL no-op inventory | **done, and acted on** — 49 empty entry points down to 34. `glMaterialf` was discarding `GL_SHININESS`; eight immediate-mode doubles were discarding geometry outright. `tools/gl-noop-inventory.py` tracks the rest and ci.yml compiles the shims. |
> | 5 | Display lists / 11 fps | **scoped** — C change + relink + pixel gate, not a JS patch |
> | 6 | 2 GB heap | **implemented, opt-in** — `FCWEB_HEAP_BYTES`; needs a link + `heapprobe.js` |
> | 7 | CalculiX threading | **reproducibility closed; threading still unshipped** — see below |
> | 8 | Chrome/Edge only | **decided** — track, don't build |
>
> **Item 7, corrected 2026-08-18. The reproducibility verdict below has been superseded, and
> this entry said the opposite of the truth for two days.** It read "production's ccx.wasm is
> not reproducible" and "the ccx.wasm currently in production cannot be reproduced from this
> repository plus upstream sources". That was accurate when written (run 31996275820's
> predecessors) and is no longer: `docs-ccx-stubbed-routines.md` is the authority and records
> the work that closed it.
>
> | | then | now |
> |---|---|---|
> | stubbed routines | 69 | **19** |
> | translated | 908/977 | **959/977** |
> | gap to production's code section | 986,945 B | **97,074 B** |
> | validation decks vs production | differ | **identical, digit for digit** |
>
> All four decks (elastic, frequency, plastic, thermal) reproduce production's numbers
> exactly, including the 1e-13 round-off noise — which is what makes it a reproduction rather
> than a resemblance, since round-off is where two differently-built solvers diverge first.
> The gate has been blocking since run 31992713435 and the workflow is green (run 32013729412).
> So a clean build from this repository plus upstream sources now produces a CalculiX that
> behaves like the one in production, with no undocumented edits on a build machine.
>
> **What is genuinely still open, and it is not the schedule:**
>
> - **Mortar contact is deliberately stubbed** (`SKIP_FILES` in `tools/f77ify.py`). Bounding
>   `slavintmortar`/`slavintpoints` produced a converged but *physically invalid* answer —
>   negative contact pressure, asymmetric response to a symmetric model — where production is
>   correct. A stub aborts by name; a bounded routine returns a wrong number, and for a solver
>   the second is far worse. Carried as a KNOWN GAP because mortar contact was 100% stubbed in
>   a clean build, so there is no working state to have regressed from.
> - **Threading is still unshipped.** `FCWEB_CCX_PTHREADS=1 bash build-ccx-weh.sh` builds
>   clean, but the decks must **match** today's numbers rather than merely converge — a race in
>   the assembly is a slightly different answer, not a crash. The threaded artifact is attached
>   to the run as `ccx-wasm-pthreads`.
>
> The lesson worth keeping is the one about status blocks: this table asserted a blocker that
> the work had already removed, and nothing in the repository noticed. Check the gate, not the
> summary.
>
> **Item 6 is still one command, and still needs the build machine.** Both are implemented and
> parameterised, and both default to exactly today's behaviour so nothing changes until
> someone opts in:
>
> ```bash
> FCWEB_HEAP_BYTES=3221225472 bash configure-gui-weh.sh   # 3 GB heap
> FCWEB_CCX_PTHREADS=1        bash build-ccx-weh.sh       # threaded CalculiX
> ```
>
> What still needs the build machine is the *link and the verification*, which CI genuinely
> cannot do — it only downloads release assets, it never compiles. Neither should be believed
> because it built: `scratchpad/heapprobe.js` exists because the heap hazard shows up as a
> wrong number rather than a crash, and the CalculiX decks must **match** today's results
> rather than merely converge. Do the heap one alone, in its own link.
>
> **Item 5, scoped properly — and my earlier guess about it was wrong.** I said display lists
> were "plausibly a new patch at untouched sites", i.e. shippable without a relink. Checked,
> and they are not. The display-list entry points are **entirely absent from the JS glue** —
> not stubbed, absent — because they are stubbed in C, in `gl_legacy_stubs.c`, which is linked
> into the binary:
>
> ```c
> GLuint glGenLists(GLsizei range) { return 0; }  /* 0 => no display lists => immediate mode */
> void glNewList(GLuint, GLenum) {}   void glEndList(void) {}
> void glCallList(GLuint) {}          void glDeleteLists(GLuint, GLsizei) {}
> ```
>
> So this is lane C: a C change, a relink, and real work — a display list means recording and
> replaying a GL command stream, not filling in a function. The stub is also deliberate, and
> its comment explains the trade: returning 0 makes Coin fall back to immediate mode, which
> the emulation *does* support.
>
> It also needs pixel verification, which is not optional here: re-enabling render caching is
> the change that once made **nothing draw at all**. Canvas capture was tried and is unusable
> with a hidden browser pane — the page stops compositing and `toDataURL` returned a
> byte-identical frame across an empty scene, a solid, and a camera change. Use
> `scratchpad/shot.js` on a machine with a visible browser, behind a query flag.
>
> **Worth pricing the alternative first.** Coin can draw through VBOs instead of display
> lists, which is also lane C but avoids implementing a command recorder at all. Given the
> batching work already took the heavy scene from 10 to 21–34 fps, compare both before
> committing a day to either.
>
> **Two corrections worth keeping, both found by trying.** First, the deploy now runs
> `tools/patch-freecad-js.py` over the release asset, so patch-table changes are deployable at
> all — they previously had no route to production except a relink. Second, I claimed item 4
> then needed a relink anyway, because the release's `FreeCAD.js` is already patched and the
> `throw` sites are long gone. That was wrong: re-deriving each site from its surrounding
> context (`if(face!=1028&&face!=1032){0}`, `var _glTexGeni=(coord,pname,param)=>{0}`, …), with
> every anchor verified unique against the deployed file first, worked. Item 4 is done and the
> measurement is in BUILD-WEH.md.

Seven known gaps, planned. Written after a production verification pass on
`build-20260813-eventstack+c41d84b`, so the starting facts are measured rather than assumed.

**The single most useful thing to know first:** the cost of a change here is decided by which
lane it lives in, not by how hard it sounds.

| lane | cost | what's in it |
|---|---|---|
| **A — front-end** (`play-gui/*`) | minutes; deploy needs no relink | dialogs, storage, error reporting |
| **A2 — re-patch `FreeCAD.js`** via `tools/patch-freecad-js.py` | hours; still no relink | **the GL fixed-function gaps, and display lists** |
| **B — payload Python** (inside `FreeCAD.data`) | ~2 h relink | FreeCAD's own `.py` |
| **C — C++ / link line** | ~2 h relink | heap size, Coin, CalculiX threading |

Lane A2 is the surprise: the nine no-op'd GL calls and the stubbed display lists are patches to
emscripten's *generated JS glue*, already rewritten post-link by `tools/patch-freecad-js.py`.
Fixing them needs **no relink at all**. That moves the two rendering items from "expensive" to
"a day each", and it reorders this whole list.

---

## Tier 1 — blocks daily work, and costs almost nothing

### 1. `QInputDialog` always returns "cancelled" *(lane A, 0.5–3 d)*

Measured live today:

```
getText   -> ('', False)      getInt    -> (5, False)
getDouble -> (12.5, False)    getItem   -> ('a', False)
```

Every prompt-for-a-value dialog silently reports cancellation, so any macro or Python
workbench command that asks for a name, count or length quietly does nothing. Draft, BIM and
OpenSCAD tooling all rely on these.

**Do the cheap check first.** Commit `1c10855` measured *native* `QInputDialog` working under
JSPI and deleted the HTML bridge — yet the JSPI shim still stubs it. So either the shim is
stale dead weight, or that measurement didn't hold. Removing the four stub lines and testing
native behaviour is an hour, and might close the whole item.

If native genuinely doesn't work, build an HTML input modal on the **existing** blocking
pattern: `_fcwebdlg.confirm` already suspends under JSPI and returns the user's real choice
for `QMessageBox`. Same mechanism, one extra field.

**Prerequisite either way:** extract the JSPI shim to `play-gui/wasm_dialog_shim_jspi.py` with
a generator. It currently exists *only* as base64 inside `freecad-gui.html`, and its comment
points at the wrong source file. Nobody should hand-edit base64 to fix a dialog.

**Done when:** a macro calling `getText` receives what the user typed, and `getInt`/`getDouble`
round-trip a value, verified by real typing rather than through the Python bridge.

### 2. Documents can be evicted *(lane A, 3–4 d)*

`navigator.storage.persisted()` is **false** on a normal profile — confirmed again today.
Chrome only grants persistence to an installed app, so until someone installs the PWA the
browser may clear their work to reclaim disk.

The install prompt now fires after a first successful save (already shipped), but that is a
nudge, not a guarantee. The real fix is to stop depending on browser-managed storage at all:

**Let the user nominate a real folder.** `showDirectoryPicker()` returns a
`FileSystemDirectoryHandle` that can be persisted in IndexedDB and re-permissioned on later
visits. Autosave writes there as well as to IDBFS. Work then lives in an ordinary directory on
their machine — survives eviction, survives clearing site data, and is visible in their file
manager, which is what a CAD user expects anyway.

Steps: picker + handle persistence + permission re-request on boot; autosave writes both
places; a clear indicator of which mode is active; fall back silently to IDBFS-only where the
API is absent.

**Also verify the untested assumption:** that the Phase 2 engine cache survives PWA
installation rather than forcing a fresh 115 MB.

**Done when:** clearing site data does not lose a document that was open when it happened.

### 3. No error reporting *(lane A + a small endpoint, 2–3 d)*

Today a failure dies in the user's tab. `window.fcwebCrash` already builds a good report (120-line
ring buffer, heap, autosave list, UA) — it just has nowhere to go but the clipboard.

Two pieces, deliberately separate:

- **Anonymous counters** — boot started / boot succeeded / abort-by-kind / browser-gate
  rejection. No document names, no free text, no identifiers. This alone answers "what fraction
  of visitors never reach Ready?", which nothing currently can.
- **Opt-in detailed report** — the existing blob, sent only when the user presses the button,
  with **document names redacted first** (they're in there today, at `freecad-gui.html:614`).

Keep it first-party: a tiny endpoint on the existing nginx/Caddy writing JSONL, not a
third-party SDK. Cross-origin isolation constrains what can be embedded anyway, and this avoids
the privacy and CSP questions entirely.

**Done when:** a deliberately triggered abort appears server-side within a minute, carrying the
build id and no document names.

---

## Tier 2 — rendering, and much cheaper than it looks

### 4. Nine fixed-function GL calls silently do nothing *(lane A2, 1–2 d)*

`tools/patch-freecad-js.py` rewrites these from `throw` to `0`:

```
glLightModelf   glLightModelfv   glLightfv
glMaterialfv (×2)                glTexGenfv   glTexGeni
glTexCoord3f    glTexCoord4f
```

Turning a throw into a no-op was correct — a throw unwinds through Coin's render traversal and
takes the viewport with it. But **`glMaterialfv` and `glLightfv` are how Coin sets material
colour and lighting.** If they do nothing, shading and colour differ from desktop, and nobody
has ever inventoried by how much. That's a parity claim the project can't currently make.

1. **Inventory before implementing.** Add a counting wrapper (same mechanism as `?gltrace=1`)
   and drive the eight `workflows.js` scenarios plus each bundled example. Which of the nine
   are actually called, how often, and from which workbenches?
2. **Compare against desktop.** Same model, same camera, screenshot both. This is the only way
   to know whether "no-op" means "invisible" or "everything is the wrong colour".
3. **Implement what matters**, in the JS glue, as new entries in the patch table — material and
   light state feeding the emulation's existing uniform path. `glTexGen*` only matters if a
   workbench uses generated texture coordinates; the inventory says whether to bother.

**Done when:** every call site is either implemented or recorded, with a screenshot diff, as a
known and bounded divergence.

### 5. ~11 fps on heavy scenes; render caching forced off *(lane A2 spike → C, 3–8 d)*

> **Note on verifying this one.** Frame rate cannot be sampled from a hidden or headless-
> without-compositor page: `requestAnimationFrame` does not fire, so a probe just hangs
> rather than returning a low number. Confirmed 2026-08-17. Any measurement of this item
> needs a *visible* viewport — which is what `scratchpad/shot.js` and the pixel gate provide.
> Do not treat a timed-out probe as evidence of anything.

The cause is one line, and it is upstream of the symptom:

> `patches/freecad.patch:18060` — *"wasm: display lists are stubbed (glGenLists returns 0), so
> ON/AUTO render caching produces permanently-empty caches — children are never traversed after
> the first frame and nothing draws. Force caching OFF."*

So Coin re-traverses and re-emits the entire scene graph every frame, forever. The draw-call
batching already landed (10 → 21–34 fps); caching is the next order of magnitude, because it
skips the traversal rather than making it cheaper.

**Spike first, in lane A2 (~1 d):** implement display lists in the GL glue —
`glGenLists`/`glNewList`/`glEndList`/`glCallList` recording and replaying a command buffer. If
that works, `COIN_AUTO_CACHING` can go back on with **no relink and no C++ change**, and the
`patches/freecad.patch` hunk plus the two `pre-gui.js` env vars are simply reverted.

If recording proves impractical, fall back to Coin's VBO path (`SoVBO`), which is lane C and a
relink.

**Risk to respect:** caching was turned off because turning it on made *nothing draw*. Re-enable
behind a query flag first, verify with `scratchpad/shot.js`'s pixel gate before trusting fps
numbers, and measure load average before believing any timing — this repo has a documented
"50% regression" that was the machine's own build load.

**Done when:** BIMExample holds a materially higher fps with a pixel-identical render.

---

## Tier 3 — real limits, real cost

### 6. The 2 GB heap *(lane C, 2–5 d, genuine risk)*

**Measured on live production, 2026-08-17** (`build-20260813-eventstack+e835c2b`), via memory
reflection in the browser rather than from the build flags:

```
currentHeapMB : 2048      growthAllowed : false
```

So the shipped heap is exactly 2 GB and fixed, which confirms the flags below and means
`FCWEB_HEAP_BYTES`'s default (2147483648) is precisely what is already live. **There is
nothing to do to "reach" 2 GB — this item is only ever about going past it**, and everything
past it is the signed-pointer hazard, which needs the relink plus `scratchpad/heapprobe.js`.

Current: `-sINITIAL_MEMORY=2147483648 -sALLOW_MEMORY_GROWTH=0`. Measured ~72 KB per simple
solid → roughly 20,000 of them. Fine for parts; not for a large assembly.

`BUILD-WEH.md` rejected `ALLOW_MEMORY_GROWTH=1` for a good reason: it rewrites **841** heap
accesses into accessor form (`GROWABLE_HEAP_F32()[x>>>2>>>0]`), which invalidates the entire
hand-derived patch table, and the hot path *is* the JS GL emulation.

**That reasoning does not apply to simply asking for more.** With growth still off, emscripten
keeps direct `HEAPU8[...]` access, so **the patch table stays valid.** Raising `INITIAL_MEMORY`
toward 3–4 GB is therefore far cheaper than enabling growth.

The catch, and it is the whole risk: above 2 GB, pointers exceed `INT32_MAX`. Any C++ in OCCT,
Coin, Qt or CPython that stores a pointer in a signed `int`, or compares one, breaks — and
plausibly in a way that looks like corrupt geometry rather than a crash.

Sequence: measure what a real assembly actually needs → spike `INITIAL_MEMORY=3GB` with
`MAXIMUM_MEMORY` set → boot, run the full workflow suite, FEM end to end, and the pixel gate →
only then consider 4 GB. Keep 2 GB as the shipped fallback until a suite passes clean. Do **not**
pair this with other changes in the same link; if geometry goes strange you want one variable.

**Longer term:** wasm64 (`MEMORY64`) removes the ceiling properly, but it means rebuilding the
entire dependency stack for 64-bit pointers. Worth tracking, not worth starting.

### 7. CalculiX is single-threaded *(lane C, ccx module only, 2–4 d)*

Not an oversight — a deliberate stopgap that is honest about itself in `bridge/ccx_threads.c`:

> *"This module is not built with `-pthread`, so emscripten's `pthread_create` is a stub that
> fails — and ccx never checks the return value. The workers simply never ran: the matrix came
> out identically zero… ponytail: inline execution, revisit if a `-pthread` build is ever wanted
> for speed."*

The `__wrap_pthread_create` shim runs each worker inline, serialising what CalculiX intended to
parallelise. The main app already runs `-pthread` with `PTHREAD_POOL_SIZE=16` and the site is
cross-origin isolated, so `SharedArrayBuffer` is available — the ingredients are there.

Build `ccx.wasm` with `-pthread`, drop the `--wrap`, and let ccx's own `pthread_create` calls
run. Only the ccx module rebuilds; FreeCAD is untouched.

**Verify against the existing decks** (`scratchpad/ccxval/`: elas, freq, plast, therm) — results
must match the current numbers, not merely converge. Then measure speedup on the e2e box model;
if assembly parallelises but SPOOLES factorisation dominates, the win may be small, and that is
worth knowing before spending the time.

### 8. Chrome/Edge 137+ only *(not ours to fix)*

JSPI is the hard dependency, and it is what makes modal dialogs return real answers. Firefox has
it in development; Safari does not. The Asyncify fallback still exists in the tree but is the
known-broken variant — it cannot return a user's real choice and can corrupt the CPython stack.

**Plan: track, don't build.** The gate already refuses cleanly having downloaded nothing, which
is the right behaviour. Re-check Firefox each release; a second Asyncify build lane would double
the build matrix to ship a worse product.

---

## Suggested order

1. **QInputDialog** — cheapest fix to a thing that actively breaks work, and may be a deletion.
2. **Error reporting** — do it early; every later item is easier when failures reach you.
3. **Storage durability** — removes the one failure mode users cannot forgive.
4. **GL inventory** — cheap, and it either closes a parity claim or exposes a real one.
5. **Display-list spike** — highest performance upside per day spent, still no relink.
6. **Heap** — first change worth a relink; do it alone.
7. **CalculiX threads** — batch with the heap link if the decks pass.

Tiers 1 and 2 are all lane A/A2: **no relink, deployable the same day.** That is most of the
user-visible gap.

## A standing note

Two defects found on 2026-08-16 were invisible because every failure path was a swallowed
exception: autosave had never installed, and a debug gate had silently disabled autosave, the
out-of-memory warning and draw-call batching at once. Both looked completely normal.

So for every item here: **add a positive signal that the thing is alive**, not just an absence of
errors. "Nothing threw" has already proven itself worthless twice in this codebase.
