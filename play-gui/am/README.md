# Addon Manager overlay

Five Python modules, served by nginx from `/am/` and fetched at runtime by
`freecad-gui.html`, which writes them into `/fcweb-am` and imports `fcweb_am_boot`.

| file | what it is |
|---|---|
| `addonmanager_fcweb_async.py` | new — the callback-based HTTP primitive everything else is built on |
| `addonmanager_workers_utility.py` | **fork** of upstream — `ConnectionChecker` off QThread |
| `addonmanager_workers_startup.py` | **fork** of upstream — the five startup workers off QThread |
| `fcweb_am_install.py` | new — install/uninstall class patches |
| `fcweb_am_boot.py` | new — loads the shadows, applies the class patches |

`UPSTREAM.txt` pins the sha256 of every upstream file a fork was derived from;
`tools/check-addon-overlay-drift.py` fails CI when one moves.

## Why these are not in patches/freecad.patch

The plan's M11 called for folding the three shadow modules into the patch. That was
considered and **deliberately not done**. The reasoning, so nobody has to re-derive it:

- **It would not remove the overlay.** Only the two forks and the async primitive are
  module shadows. `fcweb_am_boot` and `fcweb_am_install` patch *classes* — rebuilding the
  connection checker the registered command already owns, making `AddonManager.ui` open
  non-modally, no-op'ing `moveToThread`, replacing the request builder. None of that can
  be expressed as a module replacement, so `/fcweb-am` has to keep loading regardless.
  Folding therefore yields **two** delivery mechanisms where there is currently one.

- **The cost is a relink.** These files live in `FreeCAD.data`, the preload, so changing
  one means a full rebuild and link (~1.5–2.5 h) instead of an image rebuild (seconds).
  That is the difference between fixing a reported Addon Manager bug the same hour and
  fixing it the next day.

- **Drift was the real argument for folding**, and it is addressed directly by the
  `UPSTREAM.txt` pins plus the CI check, which fail loudly when upstream moves — rather
  than indirectly, by hoping a patch stops applying.

What the patch *does* carry, because it genuinely cannot live here: the `sslErrors` guard
in `NetworkManager.py` and the `PreferencePackManager` bindings in `ApplicationPy.cpp`.
Those are C++ and engine-side Python, not overlay-able.

Revisit if the class patches ever disappear — at that point the overlay would be pure
module shadows and folding would remove a mechanism instead of adding one.
