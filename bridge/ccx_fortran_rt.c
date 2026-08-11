/* Runtime pieces CalculiX needs that f2c does not supply.
 *
 * Unlike bridge/ccx_stubs.c, these are real implementations -- nothing here aborts.
 *
 * Names carry two trailing underscores where the Fortran name contains one: that is
 * f2c's convention (it appends a second underscore to disambiguate), and since these
 * are intrinsics there is no .f file for tools/f2c_single_underscore.py to key on, so
 * the f2c spelling is what the generated callers actually reference.
 *
 * The trailing ftnlen parameters are f2c's hidden CHARACTER lengths. They must be
 * declared here: tools/f2c_strip_ftnlen.py only removes lengths for routines defined
 * in the generated set, so calls to these keep passing them.
 */
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef int ftnlen;

static void blank_pad(char *dst, ftnlen len, const char *src)
{
    ftnlen i = 0;
    for (; src[i] && i < len; i++) { dst[i] = src[i]; }
    for (; i < len; i++) { dst[i] = ' '; }      /* Fortran strings are blank-padded */
}

/* call date_and_time(date, clock) -- ccx uses it only to timestamp its output.
 * A build in the browser has no business reading the wall clock for results, and a
 * fixed stamp keeps runs byte-reproducible, which makes regression diffs meaningful.
 */
void date_and_time__(char *date, char *clock, ftnlen date_len, ftnlen clock_len)
{
    blank_pad(date, date_len, "00000000");
    blank_pad(clock, clock_len, "000000.000");
}

/* CalculiX perturbs coordinates with random_number in a few tie-breaking paths.
 * A fixed-seed LCG is deliberate: an unseeded generator would make the solver
 * non-deterministic, so two runs of the same model could disagree.
 */
static unsigned long long rng_state = 88172645463325252ULL;

void random_seed__(void) { rng_state = 88172645463325252ULL; }

void random_number__(double *harvest)
{
    rng_state = rng_state * 6364136223846793005ULL + 1442695040888963407ULL;
    *harvest = (double)(rng_state >> 11) / 9007199254740992.0;   /* 2^53 */
}

/* LAPACK's error reporter. Reference LAPACK's own xerbla.f uses len_trim, an F90
 * intrinsic f2c does not implement, so it is written out here instead.
 */
void xerbla_(const char *srname, int *info, ftnlen srname_len)
{
    ftnlen n = srname_len;
    while (n > 0 && srname[n - 1] == ' ') { n--; }
    fprintf(stderr, "[ccx-wasm] ** On entry to %.*s parameter number %d had an "
                    "illegal value\n", (int)n, srname, info ? *info : 0);
    fflush(stderr);
    abort();
}

/* dnrm2 is NOT defined here on purpose: CalculiX bundles its own in dgmres.f (SLATEC
 * ships one), and defining a second would be a duplicate symbol. LAPACK 3.12's copy is
 * free-form .f90 and unreadable by f2c, so ccx's is the one that gets linked.
 */

/* ---- LAPACK routines that 3.12 ships as free-form .f90, which f2c cannot read ---- */

/* dlamch('E') etc. -- machine parameters. LAPACK's own definition of "eps" is half an
 * ULP (EPSILON(ZERO)*0.5), not DBL_EPSILON; convergence tests are written against that.
 */
double dlamch_(const char *cmach, ftnlen cmach_len)
{
    const double eps = DBL_EPSILON * 0.5;
    double sfmin, small;
    (void)cmach_len;
    switch (cmach && *cmach ? (*cmach | 0x20) : 'e') {
    case 'e': return eps;
    case 's':
        sfmin = DBL_MIN;
        small = 1.0 / DBL_MAX;
        if (small >= sfmin) { sfmin = small * (1.0 + eps); }
        return sfmin;
    case 'b': return (double)FLT_RADIX;
    case 'p': return eps * (double)FLT_RADIX;
    case 'n': return (double)DBL_MANT_DIG;
    case 'r': return 1.0;                       /* rounding, not chopping */
    case 'm': return (double)DBL_MIN_EXP;
    case 'u': return DBL_MIN;
    case 'l': return (double)DBL_MAX_EXP;
    case 'o': return DBL_MAX;
    default:  return 0.0;
    }
}

/* Givens rotation, LAPACK 3.10+ convention: r carries the sign of f. hypot() supplies
 * the overflow-safe scaling the Fortran does by hand.
 */
void dlartg_(const double *f, const double *g, double *c, double *s, double *r)
{
    double ff = *f, gg = *g, d;
    if (gg == 0.0) { *c = 1.0; *s = 0.0; *r = ff; return; }
    if (ff == 0.0) { *c = 0.0; *s = (gg > 0.0) ? 1.0 : -1.0; *r = fabs(gg); return; }
    d = hypot(ff, gg);
    *c = fabs(ff) / d;
    *r = copysign(d, ff);
    *s = gg / *r;
}

/* Scaled sum of squares: on exit scale^2 * sumsq == sum(x_i^2) + scale_in^2*sumsq_in.
 * Updates in place -- callers accumulate across several calls.
 */
void dlassq_(const int *n, const double *x, const int *incx, double *scale, double *sumsq)
{
    int i, ix, nn = n ? *n : 0, ic = incx ? *incx : 1;
    if (nn <= 0) { return; }
    for (i = 0, ix = 0; i < nn; i++, ix += ic) {
        double a = fabs(x[ix]);
        if (a == 0.0) { continue; }
        if (*scale < a) {
            double r = *scale / a;
            *sumsq = 1.0 + *sumsq * r * r;
            *scale = a;
        }
        else {
            double r = a / *scale;
            *sumsq += r * r;
        }
    }
}
