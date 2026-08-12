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

/* Fortran-callable abort used by the generated stubs (tools/ccx_make_stubs.py).
 * f2c passes a hidden length for the character literal, so this takes two parameters.
 */
void ccxstb_(const char *name, int len)
{
    char buf[64];
    int n = (len > 0 && len < (int)sizeof(buf)) ? len : (int)sizeof(buf) - 1;
    for (int i = 0; i < n; i++) { buf[i] = name[i]; }
    buf[n] = '\0';
    while (n > 0 && buf[n - 1] == ' ') { buf[--n] = '\0'; }   /* Fortran pads with blanks */
    unavailable(buf, "This routine uses F90 constructs that FORTRAN 77 cannot express,\n"
                     "           so it could not be translated for WebAssembly.");
}
