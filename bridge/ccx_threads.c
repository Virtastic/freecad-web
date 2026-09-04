/* Run CalculiX's worker threads inline.
 *
 * ccx parallelises assembly and stress recovery by handing each thread a disjoint range
 * of elements:
 *
 *     for (i=0; i<num_cpus; i++) pthread_create(&tid[i], NULL, mafillsmmt, &ithread[i]);
 *     for (i=0; i<num_cpus; i++) pthread_join(tid[i], NULL);
 *
 * This module is not built with -pthread, so emscripten's pthread_create is a stub that
 * fails -- and ccx never checks the return value. The workers simply never ran: the
 * matrix came out identically zero, SPOOLES reported it singular, and nothing anywhere
 * said why. That is the worst kind of failure, so it is worth being explicit that these
 * wrappers are what make the solver produce numbers at all.
 *
 * Running the body inline at create time is safe because the ranges are disjoint and the
 * join immediately follows; it just serialises what would have been parallel. Linked via
 * -Wl,--wrap so libc's real symbols stay intact for anything else.
 *
 * ponytail: inline execution, revisit if a -pthread build is ever wanted for speed.
 */
#include <stdio.h>

/* emscripten's pthread_t is a pointer (struct __pthread *), so this must be
 * pointer-width. It was `unsigned long`, which is 4 bytes on wasm32 and 8 on wasm64 --
 * right on both by luck rather than by construction. --wrap requires the wrapper and the
 * real symbol to agree on wasm parameter types, and a width mismatch there is a link
 * error at best and a wild pointer at worst. void* is correct by definition on any
 * target, and needs no <pthread.h> in a module that is deliberately built without
 * -pthread. */
typedef void *fcweb_thread_t;

int __wrap_pthread_create(fcweb_thread_t *thread, const void *attr,
                          void *(*start_routine)(void *), void *arg)
{
    (void)attr;
    if (thread) { *thread = 0; }
    if (start_routine) { start_routine(arg); }
    return 0;
}

int __wrap_pthread_join(fcweb_thread_t thread, void **retval)
{
    (void)thread;
    if (retval) { *retval = 0; }
    return 0;                     /* the body already ran in __wrap_pthread_create */
}
