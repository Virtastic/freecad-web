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
  branch (`--compiler-path=em++`, `--target=wasm32-unknown-emscripten`).
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
  qt/6.9.0/macos/libexec/rcc -g python \
    -o deps/wasm/pyside-pkg/Arch_rc.py \
    deps/src/freecad/src/Mod/BIM/Resources/Arch.qrc
  ```
- **CPython trampoline**: rebuild libpython with
  `EXTRA_CFLAGS="-pthread -DPY_CALL_TRAMPOLINE"` (fixes wasm typed-call traps on
  shiboken METH_NOARGS functions).
- **PySide6/Shiboken/pivy static `.a`s**: built with `-DFORCE_LIMITED_API=no`
  and `-pthread -fexceptions`, then re-archived with `emar` (the cmake builds
  use host `ar`, which produces archives wasm-ld rejects).
