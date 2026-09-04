// Link-time wraps of QCoreApplicationPrivate::sendPostedEvents and
// ::notify_helper for the wasm build. Multiple QObjects get freed/scribbled
// during FreeCAD init while events for them are still queued (zone ~0x236dxxx)
// — delivery then traps (unaligned atomic / wild indirect call). These shims
// validate receivers with a decisive invariant — a live QObject's vptr must
// point into STATIC data (below __heap_base) — and neutralize poisoned
// entries so the event loop survives.
#include <QtCore/private/qthread_p.h>
#include <QtCore/qmutex.h>
#include <cstdio>
#include <cstdint>

extern "C" char __heap_base;  // linker-provided: end of static data

static bool badPtr(uintptr_t p)
{
    // Alignment is pointer-width, not a hardcoded 4. On wasm64 a QObject carrying a
    // vptr is 8-aligned, and (p & 3) would wave a misaligned pointer straight through.
    return p == 0 || (p & (sizeof(void*) - 1)) || p < 1024;
}

// Deep receiver check: pointer sane, vptr sane AND static, d_ptr sane.
static int receiverBad(void* r)
{
    uintptr_t rp = (uintptr_t)r;
    if (badPtr(rp)) return 1;
    uintptr_t vp = *(uintptr_t*)rp;
    uintptr_t d  = *(uintptr_t*)(rp + sizeof(void*));  // d_ptr follows the vptr
    if (badPtr(vp) || badPtr(d)) return 2;
    if (vp >= (uintptr_t)&__heap_base) return 3;  // vtable must be static data
    return 0;
}

extern "C" void fcweb_poll_tracked(const char* site);
extern "C" uintptr_t fcweb_tracked_addr(void);

extern "C" void __real__ZN23QCoreApplicationPrivate16sendPostedEventsEP7QObjectiP11QThreadData(
    QObject*, int, QThreadData*);
extern "C" bool __real__ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent(
    QObject*, QEvent*);

extern "C" void __wrap__ZN23QCoreApplicationPrivate16sendPostedEventsEP7QObjectiP11QThreadData(
    QObject* receiver, int event_type, QThreadData* data)
{
    static unsigned call_n = 0;
    call_n++;
    fcweb_poll_tracked("sendPostedEvents");
    static bool named = false;
    if (!named && fcweb_tracked_addr()) {
        QObject* o = (QObject*)(uintptr_t)fcweb_tracked_addr();
        if (!receiverBad(o)) {
            fprintf(stderr, "[ID] tracked %p class=%s name='%s'\n", (void*)o,
                    o->metaObject()->className(), o->objectName().toUtf8().constData());
            fflush(stderr);
            named = true;
        }
    }
    uintptr_t dp = (uintptr_t)data;
    if (badPtr(dp)) {
        fprintf(stderr, "[SPE %u] BAD QThreadData=%p — skipping sendPostedEvents\n", call_n, (void*)data);
        fflush(stderr);
        return;
    }
    {
        QMutexLocker locker(&data->postEventList.mutex);
        const int n = data->postEventList.size();
        if (call_n <= 3 || (call_n % 256) == 0) {
            fprintf(stderr, "[SPE %u] data=%p listSize=%d startOffset=%d\n",
                    call_n, (void*)data, n, data->postEventList.startOffset);
            fflush(stderr);
        }
        for (int i = 0; i < n; i++) {
            QPostEvent& pe = const_cast<QPostEvent&>(data->postEventList.at(i));
            if (!pe.event) continue;  // already handled
            int bad = receiverBad(pe.receiver);
            if (!bad && badPtr((uintptr_t)pe.event)) bad = 4;
            if (!bad) {
                // the QEvent itself must be intact: its vptr must be static data
                uintptr_t evp = *(uintptr_t*)(uintptr_t)pe.event;
                if (badPtr(evp) || evp >= (uintptr_t)&__heap_base) bad = 5;
            }
            if (bad) {
                uintptr_t rp = (uintptr_t)pe.receiver;
                uintptr_t vp = badPtr(rp) ? 0 : *(uintptr_t*)rp;
                uintptr_t d  = badPtr(rp) ? 0 : *(uintptr_t*)(rp + sizeof(void*));
                fprintf(stderr,
                        "[SPE %u] POISONED entry i=%d/%d bad=%d recv=%p vp=%p d=%p ev=%p — neutralized\n",
                        call_n, i, n, bad, (void*)pe.receiver, (void*)vp, (void*)d, (void*)pe.event);
                fflush(stderr);
                pe.event = nullptr;  // Qt skips null-event entries; leaks one event, saves the loop
            }
        }
    }
    __real__ZN23QCoreApplicationPrivate16sendPostedEventsEP7QObjectiP11QThreadData(receiver, event_type, data);
}

extern "C" bool __wrap__ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent(
    QObject* receiver, QEvent* event)
{
    int bad = receiverBad(receiver);
    if (bad) {
        static unsigned drop_n = 0;
        if (++drop_n <= 32) {
            fprintf(stderr, "[NH] drop delivery to bad receiver %p (bad=%d)\n", (void*)receiver, bad);
            fflush(stderr);
        }
        return true;  // pretend consumed; do not touch the corpse
    }
    return __real__ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent(receiver, event);
}
