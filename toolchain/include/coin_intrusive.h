/* boost::intrusive_ptr adapters for Coin's SoBase — force-included into every
 * FreeCAD translation unit by configure-gui-weh.sh.
 *
 * WHY THIS FILE IS HERE RATHER THAN ON ONE MACHINE
 *
 * Until 2026-08-18 this header existed ONLY at deps/wasm/include/coin_intrusive.h on the
 * build machine. deps/ is gitignored, so nothing in the repository produced it and nothing
 * documented it, while five tracked scripts force-included it. A clean checkout therefore
 * could not configure FreeCAD at all. That is the same failure mode BUILD-WEH.md records
 * for CalculiX -- uncaptured build-machine state -- and it is now captured.
 *
 * WHAT IT DOES
 *
 * boost::intrusive_ptr<T> calls unqualified intrusive_ptr_add_ref/intrusive_ptr_release and
 * resolves them by ADL. SoBase lives in the global namespace, so the adapters must too, and
 * they must be DECLARED before the first instantiation -- which is why this is a force-
 * include rather than an ordinary header.
 *
 * A Coin built from source does not supply them (the packaged builds FreeCAD normally links
 * against do). The DEFINITIONS live in src/Gui/SoFCDB.cpp under __EMSCRIPTEN__ and are
 * applied by patches/freecad.patch; this file is only the declaration half of that pair.
 * The two must agree exactly, so if you change a signature here, change it there.
 *
 * RECONSTRUCTED, NOT CAPTURED. The signatures are dictated by the definitions in
 * patches/freecad.patch, so any correct version is equivalent to the build machine's. If
 * that machine's copy is ever recovered (tools/capture-build-machine-headers.sh), diff it
 * against this one and prefer the original.
 *
 * C-safe on purpose: configure-gui-weh.sh force-includes this into CMAKE_C_FLAGS as well as
 * CMAKE_CXX_FLAGS, so the C compiler must see an empty file rather than a syntax error.
 */
#ifndef FCWEB_COIN_INTRUSIVE_H
#define FCWEB_COIN_INTRUSIVE_H

#ifdef __cplusplus

class SoBase;

void intrusive_ptr_add_ref(const SoBase* p);
void intrusive_ptr_release(const SoBase* p);

#endif /* __cplusplus */

#endif /* FCWEB_COIN_INTRUSIVE_H */
