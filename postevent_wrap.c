// Link-time wrap of QCoreApplication::postEvent(QObject*, QEvent*, int) for the
// wasm build: validates receivers, tracks the known-corrupted object at
// TRACKED_ADDR (deterministic across runs), and brackets the moment its memory
// gets scribbled with 0xFFFFFFFF by polling on every post.
#include <stdio.h>
#include <stdint.h>

extern void __real__ZN16QCoreApplication9postEventEP7QObjectP6QEventi(void*, void*, int);

// The victim object lands deterministically near 0x236dexx (shifts slightly
// per binary). Track a RANGE and log the vptr at post time to identify its class.
// NOTE: TRACKED_LO/HI are wasm32 heap-layout constants. They gate DIAGNOSTICS only --
// the [TRACK] logging and the tracked-object identification in spe_sanitize.cpp. The
// event-dropping below does not depend on them. Under a different pointer width or heap
// layout the window simply stops matching and the tracking goes quiet; it cannot cause a
// wrong decision. Re-derive the range from a real run before trusting [TRACK] again.
#define TRACKED_LO 0x2368000u
#define TRACKED_HI 0x2372000u
static unsigned post_n = 0;
static uintptr_t tracked_addr = 0;  // first in-range receiver seen
static uintptr_t tracked_vp = 0;    // its vptr at post time
static int tracked_corrupt = 0;

uintptr_t fcweb_tracked_addr(void) { return tracked_corrupt ? 0 : tracked_addr; }

void fcweb_poll_tracked(const char* site) {
    if (!tracked_addr || tracked_corrupt) return;
    uintptr_t v = *(volatile uintptr_t*)tracked_addr;
    if (v != tracked_vp) {
        tracked_corrupt = 1;
        fprintf(stderr, "[TRACK] %p vptr CHANGED %p -> %p at site=%s post_n=%u\n",
                (void*)tracked_addr, (void*)tracked_vp, (void*)v, site, post_n);
        fflush(stderr);
    }
}

void __wrap__ZN16QCoreApplication9postEventEP7QObjectP6QEventi(void* r, void* e, int prio) {
    post_n++;
    uintptr_t rp = (uintptr_t)r;
    uintptr_t vp = 0, d = 0;
    uint16_t t = 0;
    int bad = 0;
    if (rp == 0 || (rp & (sizeof(void*) - 1)) || rp < 1024) {
        bad = 1;
    } else {
        vp = *(uintptr_t*)rp;
        d = *(uintptr_t*)(rp + sizeof(void*));  // d_ptr follows the vptr
        if ((d & (sizeof(void*) - 1)) || d < 1024 || (vp & (sizeof(void*) - 1)) || vp < 1024) bad = 2;
        else { extern char __heap_base; if (vp >= (uintptr_t)&__heap_base) bad = 3; }
    }
    if (e) t = *(uint16_t*)((char*)e + sizeof(void*));  // type follows the vptr
    if (rp >= TRACKED_LO && rp < TRACKED_HI) {
        fprintf(stderr, "[TRACK] post#%u to %p: vp=%p d=%p evtype=%u bad=%d\n",
                post_n, (void*)rp, (void*)vp, (void*)d, t, bad);
        fflush(stderr);
        if (!bad) {
            if (!tracked_addr) tracked_addr = rp;
            if (rp == tracked_addr) { tracked_vp = vp; tracked_corrupt = 0; }  // refresh (vptr moves during ctor)
        }
    }
    fcweb_poll_tracked("postEvent");
    if (bad) {
        fprintf(stderr, "[POST-BAD %d] post#%u r=%p vp=%p d=%p t=%u — DROPPED\n",
                bad, post_n, r, (void*)vp, (void*)d, t);
        fflush(stderr);
        return;
    }
    __real__ZN16QCoreApplication9postEventEP7QObjectP6QEventi(r, e, prio);
}
