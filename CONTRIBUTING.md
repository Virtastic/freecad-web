# Contributing

Thanks for looking. A few things are worth knowing before you spend time.

## Where to report problems

Open an issue at <https://github.com/Virtastic/freecad-web/issues>. Please report problems
with **this browser build** here, not to the FreeCAD project — they did not build it and
cannot debug it.

A useful report says **what you did, what you expected, and what you saw**. A screenshot beats
a description. If the app showed you a crash toast, its "Copy report" button puts a diagnostic
blob on your clipboard — paste that in. Include your browser and version.

Before reporting, please check the limits in [README.md](README.md#requirements-and-limits) —
Chrome/Edge 137+ only, a 16 GB heap ceiling, no AddonManager, single-threaded CalculiX. Those are
known and deliberate.

## Before changing code

Read [AGENTS.md](AGENTS.md). It is short, and it is the actual working agreement for this
repository — in particular:

- **The target is 1:1 parity with desktop FreeCAD.** We have the source in `deps/src/`, so the
  answer to "what should this do?" is *read the code that does it*, not reason about it.
- **Claims must be measured.** A change is done when it has been built, staged, driven with
  real input in a real browser, and has evidence attached — not when the code is written.
- **The Python bridge lies about the GUI.** Every scripted `Gui.runCommand` test passed while
  real mouse clicks could not open a single dialog. Anything user-facing is verified through
  real mouse and keyboard events.

[BUILD-WEH.md](BUILD-WEH.md) documents the build and, just as importantly, the traps. Several
of its sections exist because something silently shipped broken. Please read the section
covering the area you are touching before changing it, not after a fix fails.

## What a change costs

Know which lane you are in — it decides whether your change takes minutes or hours:

- **Front-end** (`play-gui/freecad-gui.html`, `sw.js`, the manifest) — no relink. Cheap.
- **CI, infra, docs** — no build at all.
- **FreeCAD's Python** — lives inside `FreeCAD.data`, so it needs a copy into the install tree
  **and a relink**. Editing `deps/src/freecad/**/*.py` alone changes nothing at runtime, and
  the failure is silent.
- **C++ / link line** — a full relink: ~1 h build plus 45–60 min link.

If you edit anything under `deps/src/`, run `bash patches/regen.sh` so the change is captured —
`deps/` is gitignored, so an uncaptured edit is lost on a fresh checkout.

After **every** link, run `python3 tools/patch-freecad-js.py` and check its exit status. A
relink silently drops 30 hand-applied GL patches; without them the 3D view never comes up.

## Testing

The verification harnesses live in `scratchpad/` and are Puppeteer scripts run by hand. They
default to the macOS Chrome path but honour **`CHROME_PATH`**, so they run anywhere:

```bash
CHROME_PATH="/c/Program Files/Google/Chrome/Application/chrome.exe" node scratchpad/reg-prod.js
```

They need a real Chrome, not headless-shell: Qt-wasm wants a compositor, and most of these
launch with `headless: false` for exactly that reason.

The ones worth knowing:

| harness | what it proves |
|---|---|
| `reg-prod.js` | the returning-user gate — the **only** one with a fixed `userDataDir`, and the one that caught a stale-cache boot failure that killed returning users while first-time visitors were fine |
| `workflows.js` | eight CAD workflows, each ending in a number that can be wrong |
| `guidrive.js` | menus and toolbars through **real Qt input**, not the Python bridge |
| `datasafety.js` | work survives a genuine reload, asserting geometry |
| `inputdialog.js` | a macro prompt returns what the user typed |
| `ccxe2e/run-prod.js` | FEM end to end, gmsh + CalculiX |

**Drive anything user-facing with real input.** Every scripted `Gui.runCommand` test passed
while real mouse clicks could not open a single dialog, and every scripted CalculiX run passed
while the Solve button had never worked. Events built with `dispatchEvent()` are *untrusted*
and Qt ignores them — that is why these are Puppeteer scripts and not page scripts.

CI runs the patch-tool selftest and a set of repo-hygiene checks; the harnesses above are
still run by hand.

## Commits

- Write a message that explains *why*, in sentences. The existing history is the house style.
- No `Co-Authored-By:` trailers and no tool-attribution lines on commits.
- Stage deliberately — never `git add -A`. The tree sits alongside gitignored multi-gigabyte
  toolchains and build directories.
- `main` is the default branch. `ovhcloud` is a deploy pointer: pushing to it deploys
  production, so do not treat it as a working branch.
