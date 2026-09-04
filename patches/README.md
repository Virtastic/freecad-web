# Patches — source changes to the vendored `deps/` trees

The `deps/` tree (FreeCAD, PySide6, OCCT, pivy, CPython source) is gitignored
because it is multi-GB vendored source. This directory snapshots every source
change made on top of those pristine checkouts so the work is preserved
independently of the working copy.

## Apply / regenerate (one command each)

- **`bash patches/apply.sh`** — apply every stored patch onto pristine `deps/src/*`
  checkouts (idempotent: already-applied patches are detected and skipped) and copy the
  PySide package glue into `deps/wasm/`. Run once after cloning the deps trees at their
  pinned commits, before configuring.
- **`bash patches/regen.sh`** — regenerate every `.patch` from the current tree state.
  **Run this after ANY edit under `deps/src/*`** so the fix is captured (deps/ is
  gitignored, so an uncaptured edit is lost on a fresh checkout). Then commit the
  updated patch files.

Covered trees: `freecad`, `pyside-setup`, `occt`, `cpython`, `numpy`. Each patch is
verified coherent with `git -C deps/src/<repo> apply --reverse --check patches/<x>.patch`
(passes = the patch exactly reproduces the current source). Manual equivalent:

```bash
git -C deps/src/freecad       apply /path/to/patches/freecad.patch
git -C deps/src/pyside-setup  apply /path/to/patches/pyside-setup.patch
git -C deps/src/occt          apply /path/to/patches/occt.patch
git -C deps/src/cpython       apply /path/to/patches/cpython-ctypes-wasm.patch
git -C deps/src/numpy         apply /path/to/patches/numpy.patch
```

## Which FreeCAD does `freecad.patch` target?

**FreeCAD 1.1.3**, recorded in `patches/freecad.version`. `apply.sh` reads that file and
refuses to patch a `deps/src/freecad` reporting a different `PACKAGE_VERSION` -- because
`deps/` is gitignored, nothing else in this repository records which upstream tree the port
was written against, and a patch applied to the wrong source does not fail loudly. It places
hunks in plausible but wrong scopes.

### Rebasing: two checks worth running before you trust the result

```bash
python tools/check-patch-applies.py patches/freecad.patch deps/src/freecad
python tools/check-hunk-placement.py OLD.patch NEW.patch     # both need `diff -p` context
```

The first compares every context line to the tree byte for byte, because GNU patch and the
msys patch(1) disagree about line endings and the lenient one must not be the judge.

The second is the more interesting one. `patch` will place a hunk in a *different function*
that happens to look similar, report success, and leave a file that is brace-balanced,
preprocessor-balanced and completely wrong. Three such survived every structural check here
and were found only by compiling FreeCAD: the save-path block inside
`getSuffixesDescription()` instead of `getSaveFileName()`; the wasm menu branch inside
`getHistoryGroupName()`, where the `#else` swallowed the end of the enclosing class; and the
composite blit at the end of `getDimensions()` instead of `renderScene()`. The check compares
each added line's enclosing function between the old and new patch. Expect some noise from
module-level Python and from upstream signature changes -- it reports, it does not judge.

`apply.sh` also applies at **zero fuzz** (`-F0`). The 1.0.0 -> 1.1.3 rebase found four hunks
that patch(1) had placed wrongly at the default fuzz of 2: an `if(EMSCRIPTEN)` block inside a
`SET(...)` source list (CMake would not parse it), the same block nested inside `if (MSVC)` in
two other CMakeLists (parses, but dead code on the only target that needs it), and a Python
statement moved into the wrong method. Only the first of those four failed loudly.

`freecad.patch` bundles the full wasm C++ port including the crash-fix set (OCC serial
thread-pool in `Mod/Part/App/AppPart.cpp`, TechDraw lazy static-init in `Rez.cpp`/
`QGIViewPart.cpp`, MEFISTO f2c signature fixes) and the native browser File-dialog
routing in `Gui/FileDialog.cpp`.

- **freecad.patch** — the wasm port of FreeCAD's C++/CMake: heap-allocated
  MainWindow/QApplication, 3D viewport gating, NavigationStyle camera fix,
  PySide/Shiboken/Draft/pivy inittab registration in `MainGui.cpp`, the wasm
  dialog-trap guard in `Gui/Application.cpp::activateWorkbench`,
  `ToolBarManager` dtor change, etc.
- **pyside-setup.patch** — `PySideModules.cmake`: the `EMSCRIPTEN` cross-compile
  branch (`--compiler-path=em++`, `--target=wasm64-unknown-emscripten`).
- **occt.patch** — one wasm build fix in `StdPrs_BRepFont`.

## Python-package glue (`pyside-pkg-glue/`)

Hand-authored files that get preloaded into MEMFS at `/pyside-pkg` (on
`FCWEB_PYLIB`). They alias the statically-linked builtin extension modules
(registered under `QtCore_fcweb`, `Shiboken_fcweb`, `_coin`, …) to their
canonical dotted names. Copy them into place:

```bash
cp pyside-pkg-glue/PySide6/__init__.py            deps/wasm/pyside-pkg/PySide6/__init__.py
cp pyside-pkg-glue/shiboken6/__init__.py          deps/wasm/pyside-pkg/shiboken6/__init__.py
cp pyside-pkg-glue/pivy/__init__.py               deps/wasm/pyside-pkg/pivy/__init__.py   # after copying the built pivy pkg
cp pyside-pkg-glue/include-shiboken/sbkversion.h  deps/wasm/include/shiboken/sbkversion.h
```

## Regenerable (NOT stored here — reproduce with one command)

- **The rest of `deps/wasm/pyside-pkg/pivy/`** (`coin.py`, `coin.pyi`, `quarter/`,
  `interactive/`, …): copied from `build-pivy-wasm/pivy/` after building pivy
  (see `pivy-pre.cmake` + the build in memory notes). Re-apply the glue
  `pivy/__init__.py` on top afterward.
- **`deps/wasm/pyside-pkg/Arch_rc.py`** (14 MB Qt resource for Draft):
  ```bash
  qt/6.11.2/macos/libexec/rcc -g python \
    -o deps/wasm/pyside-pkg/Arch_rc.py \
    deps/src/freecad/src/Mod/BIM/Resources/Arch.qrc
  ```
- **CPython trampoline**: rebuild libpython with
  `EXTRA_CFLAGS="-pthread -DPY_CALL_TRAMPOLINE"` (fixes wasm typed-call traps on
  shiboken METH_NOARGS functions).
- **PySide6/Shiboken/pivy static `.a`s**: built with `-DFORCE_LIMITED_API=no`
  and `-pthread -fexceptions`, then re-archived with `emar` (the cmake builds
  use host `ar`, which produces archives wasm-ld rejects).
