# What the QProcess stub actually disables

FreeCAD 1.1.3, wasm build. Read against the real source tree, one call site at a time --
not inferred from the fact that a stub exists.

A browser has no subprocesses. Qt for WebAssembly is built with `QT_CONFIG(process)` false,
so `<QProcess>` resolves to nothing, and `toolchain/include/qprocess_stub.h` is
force-included to keep FreeCAD compiling. This file records what that costs.

**The stub fails honestly.** `state()` returns `NotRunning`, every `waitFor*()` returns
false at once, `startDetached()` returns false, `execute()` returns `-2` (QProcess's own
"failed to start"), `error()` returns `FailedToStart` and `errorString()` says
"QProcess is not available in the WebAssembly build". It never blocks -- blocking would
freeze the browser's main thread -- and it never claims a process it did not start has
finished. It has no signals, because a force-included header cannot be run through moc, so
every `connect()` to a QProcess signal is `#if`'d out in `patches/freecad.patch`.

That distinction decides everything below: a call site that **checks a return value** gets a
real error and tells the user; a call site that **waits for a signal** gets silence.

## The 24 files, by what actually happens

### Works -- not the stub at all (2 files)

`App/Application.cpp`, `App/ApplicationDirectories.cpp` use only
`QProcessEnvironment::systemEnvironment()`. `processenvironment` is a *separate* Qt feature
from `process` and is still enabled for wasm, so this is the real Qt class, and
`getenv`/`environ` work under emscripten. Nothing is lost.

### Include only -- no call sites (6 files)

`Gui/Dialogs/DlgAbout.cpp` (`<QProcessEnvironment>`), `Gui/SoFCDB.cpp`,
`Gui/StartupProcess.cpp`, `Mod/Start/App/DisplayedFilesModel.cpp`, `Gui/QtAll.h`,
`Mod/Start/App/PreCompiled.h` and `App/PreCompiled.h`. Nothing to lose.

### Dead upstream -- nothing calls it (2 files)

`Gui/NetworkRetriever.{cpp,h}`. In 1.1.3 it is referenced by **its own two files,
`src/Gui/CMakeLists.txt`, and the translation catalogues -- and by nothing else**. The live
download path is `DownloadManager`/`DownloadItem`, which use `QNetworkAccessManager` and
work in the browser.

This corrects an earlier claim in `ROADMAP.md` that "anything routed through it silently
does nothing": nothing is routed through it. It is dead code that happens to mention wget.

### Fails honestly -- the user is told (4 files)

| site | feature | what the user sees |
|---|---|---|
| `Gui/Tree.cpp:3280` | "reveal containing folder" on a document | `startDetached()` is false -> **"Failed to open directory."** |
| `Gui/Assistant.cpp:169` | offline help through Qt Assistant | `waitForStarted()` is false -> the dialog's "unable to launch" path |
| `Gui/GraphvizView.cpp:319,441` | dependency graph rendered by `dot` | `waitForStarted()` is false -> the error path, no graph |
| `Mod/Start/App/ThumbnailSource.cpp:70,143,177` | document thumbnails via a helper process | `waitForFinished()` is false, `exitStatus()` is `CrashExit` -> no thumbnail |

### Silent -- waits for a signal that cannot fire (2 files)

| site | feature | what the user sees |
|---|---|---|
| `Mod/Mesh/Gui/RemeshGmsh.cpp:198` | Mesh -> remeshing with gmsh | `start()`, then the elapsed-time label ticks and nothing else ever happens |
| `Gui/Dialogs/DlgRunExternal.cpp:78` | run an external program on a file, via `DlgEditFileIncludePropertyExternal` | `start()` then `exec()`; the modal never gets `finished`, so it sits until cancelled |

These two are the only genuinely silent failures in the build.

### Impossible by construction -- restarting the process (3 files)

`Gui/CommandStd.cpp:372` (Std_SafeMode), `Gui/Dialogs/DlgPreferencesImp.cpp:979`
(restart after a preference change) and `Gui/Dialogs/DlgVersionMigrator.cpp:574` all do
`QProcess::startDetached(QApplication::applicationFilePath(), args)` -- re-exec self. A page
cannot re-exec itself, and `startDetached()` returning false means the restart simply does
not happen after the dialog says it will.

## What could be done, in order of value

1. **gmsh remeshing** (`RemeshGmsh.cpp`) -- gmsh is already a wanted archive for the link.
   Compiled to wasm it is an in-process call, not a subprocess, so this becomes a real
   feature rather than a repair.
2. **Restart** (3 sites) -- the browser equivalent is `location.reload()`, with the safe-mode
   flag carried in the query string. Small, and it makes three dialogs stop lying.
3. **Reveal containing folder** (`Tree.cpp`) -- there is no file manager, but "download this
   document" is the honest browser analogue of the same intent.
4. **Dependency graph** (`GraphvizView.cpp`) -- needs a wasm `dot`; viz.js exists, but this
   is a nice-to-have.
5. **Offline help** (`Assistant.cpp`) -- Qt Assistant will never exist here; the replacement
   is opening the online help in a new tab.
6. **`NetworkRetriever`** -- delete it from the wasm build rather than reimplement it.
   Nothing calls it.

## How to re-check this

The inventory is `grep -rln QProcess src/ --include=*.cpp --include=*.h` against the
FreeCAD source tree, then reading each hit for whether it checks a return value or waits on
a signal. It is worth redoing on every FreeCAD upgrade: the list changed shape between 1.0
and 1.1.3 (`Dialogs/` and `Navigation/` moved, and `StartupProcess.cpp` is new).
