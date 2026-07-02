// Link-time wrap of QCoreApplication::postEvent(QObject*, QEvent*, int) for the
// wasm build: validates receivers, tracks the known-corrupted object at
// TRACKED_ADDR (deterministic across runs), and brackets the moment its memory
// gets scribbled with 0xFFFFFFFF by polling on every post.
#include <stdio.h>
#include <stdint.h>

extern void __real__ZN16QCoreApplication9postEventEP7QObjectP6QEventi(void*, void*, int);

// The victim object lands deterministically near 0x236dexx (shifts slightly
// per binary). Track a RANGE and log the vptr at post time to identify its class.
#define TRACKED_LO 0x2368000u
#define TRACKED_HI 0x2372000u
static unsigned post_n = 0;
static uint32_t tracked_addr = 0;   // first in-range receiver seen
static uint32_t tracked_vp = 0;     // its vptr at post time
static int tracked_corrupt = 0;

uint32_t fcweb_tracked_addr(void) { return tracked_corrupt ? 0 : tracked_addr; }

void fcweb_poll_tracked(const char* site) {
    if (!tracked_addr || tracked_corrupt) return;
    uint32_t v = *(volatile uint32_t*)(uintptr_t)tracked_addr;
    if (v != tracked_vp) {
        tracked_corrupt = 1;
        fprintf(stderr, "[TRACK] 0x%x vptr CHANGED 0x%x -> 0x%x at site=%s post_n=%u\n",
                tracked_addr, tracked_vp, v, site, post_n);
        fflush(stderr);
    }
}

void __wrap__ZN16QCoreApplication9postEventEP7QObjectP6QEventi(void* r, void* e, int prio) {
    post_n++;
    uintptr_t rp = (uintptr_t)r;
    uint32_t vp = 0, d = 0;
    uint16_t t = 0;
    int bad = 0;
    if (rp == 0 || (rp & 3) || rp < 1024) {
        bad = 1;
    } else {
        vp = *(uint32_t*)rp;
        d = *(uint32_t*)(rp + 4);
        if ((d & 3) || d < 1024 || (vp & 3) || vp < 1024) bad = 2;
        else { extern char __heap_base; if (vp >= (uint32_t)(uintptr_t)&__heap_base) bad = 3; }
    }
    if (e) t = *(uint16_t*)((char*)e + 4);
    if (rp >= TRACKED_LO && rp < TRACKED_HI) {
        fprintf(stderr, "[TRACK] post#%u to 0x%x: vp=0x%x d=0x%x evtype=%u bad=%d\n",
                post_n, (uint32_t)rp, vp, d, t, bad);
        fflush(stderr);
        if (!bad) {
            if (!tracked_addr) tracked_addr = (uint32_t)rp;
            if (rp == tracked_addr) { tracked_vp = vp; tracked_corrupt = 0; }  // refresh (vptr moves during ctor)
        }
    }
    fcweb_poll_tracked("postEvent");
    if (bad) {
        fprintf(stderr, "[POST-BAD %d] post#%u r=%p vp=0x%x d=0x%x t=%u — DROPPED\n",
                bad, post_n, r, vp, d, t);
        fflush(stderr);
        return;
    }
    __real__ZN16QCoreApplication9postEventEP7QObjectP6QEventi(r, e, prio);
}
