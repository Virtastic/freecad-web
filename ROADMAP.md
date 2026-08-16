# Roadmap: from "works" to "someone can do their job in it"

> **Status 2026-08-16.** Items 1 and 3 are **shipped and live**. Item 8 is a decision, taken.
> Items 4 and 5 are unblocked but need the deploy to apply the patch table (see below).
> **Items 6 and 7 cannot be done from CI at all** — they need a relink, and a relink is a
> local build against the multi-gigabyte `deps/` tree on the build machine. CI only downloads
> release assets; it never compiles. Those two need someone at that machine.
>
> A note that changes items 4 and 5: the shipped `FreeCAD.js` comes from the GitHub Release
> already patched, and the deploy does **not** re-run `tools/patch-freecad-js.py`. So a change
> to the patch table currently has no way to reach production without a relink. Adding one
> idempotent patcher step to the deploy fixes that and makes both rendering items shippable
> without touching the binary — it is the first task of item 4, not a side quest.

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
