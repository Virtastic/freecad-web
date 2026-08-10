/* Replacements for CalculiX routines that cannot be translated for wasm.
 *
 * emscripten has no Fortran frontend, so ccx goes through f2c, which implements FORTRAN
 * 77 only. Almost all of ccx's F90 is mechanically rewritable (tools/f77ify.py), but an
 * *automatic array* -- a local whose size is a runtime expression -- has no F77 spelling
 * at all. Where the bound is small and known, the source gets a fixed size plus a guard.
 * Where it is not, the routine lands here.
 *
 * These abort rather than return: a solver that quietly reports wrong numbers is worse
 * than one that refuses. The message names the routine so the failure is diagnosable
 * from a browser console.
 */
#include <stdio.h>
#include <stdlib.h>

static void unavailable(const char *name, const char *why)
{
    fprintf(stderr,
            "\n[ccx-wasm] %s is not available in this build.\n"
            "           %s\n"
            "           The analysis has been stopped rather than continue with\n"
            "           undefined results.\n\n", name, why);
    fflush(stderr);
    abort();
}

/* effectivemodalmass(neq,nactdof,mi,adb,aub,jq,irow,nev,z,co,nk) -- 11 arguments, all by
 * reference, no CHARACTER arguments (so f2c adds no hidden lengths). Called only from
 * arpack.c and arpackcs.c, both C, so there is exactly one arity to match.
 *
 * Blocked by `real*8 x(neq(2)),y(neq(2))`: work arrays sized by the equation count,
 * which is a runtime value in the millions -- no fixed bound is defensible.
 */
void effectivemodalmass_(void *neq, void *nactdof, void *mi, void *adb, void *aub,
                         void *jq, void *irow, void *nev, void *z, void *co, void *nk)
{
    (void)neq; (void)nactdof; (void)mi; (void)adb; (void)aub;
    (void)jq; (void)irow; (void)nev; (void)z; (void)co; (void)nk;
    unavailable("Effective modal mass (frequency analysis)",
                "It needs runtime-sized local arrays, which FORTRAN 77 cannot express.");
}
