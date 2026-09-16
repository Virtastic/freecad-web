// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic

#ifndef BASE_FCWEBWORKER_H
#define BASE_FCWEBWORKER_H

// FCWEB (wasm only): run one heavy call on a persistent worker thread while the main thread
// parks. A document load is one synchronous run of wasm on the browser's main thread; the
// two calls nothing can yield inside -- BRepTools::Read of a big part and its
// BRepMesh_IncrementalMesh -- froze the a2plus assembly's open for 3-5 s each
// (scratchpad/yield-probe.py, gpu-open-profile.py, 2026-09-15/16). Here the call runs on a
// std::thread and the main thread parks in fcweb_wait_flag() (gl_legacy_stubs.c:
// Atomics.waitAsync on the done flag, woken by a JS Atomics.notify from the worker -- wasm's
// own notify does not reach it (gl_legacy_stubs.c) -- holding Qt's resume
// slot so events queue instead of running C++ meanwhile). The GIL is released for the
// wait, as Document.cpp's yield point does. ONE thread for the page's lifetime, created on
// first use: a thread per object, joined on the main thread, cost ~50 ms each (BIMExample
// 7.4 -> 26.1 s). Only legal on a promising stack -- usable() -- which a load through the
// Python bridge or a recompute from real input is; callers keep the inline path otherwise.
// Include AFTER Python.h (any *Py.h does), like every FreeCAD unit that touches the GIL.
#if defined(__EMSCRIPTEN__)

#include <atomic>
#include <condition_variable>
#include <exception>
#include <functional>
#include <mutex>
#include <thread>
#include <emscripten/threading.h>

extern "C" int fcweb_yield_ok(void);
extern "C" void fcweb_wait_flag(volatile int* flag);
extern "C" void fcweb_notify_flag(volatile int* flag);

namespace Base
{

class FcwebWorker
{
public:
    static bool usable()
    {
        return fcweb_yield_ok() != 0;
    }
    // Runs fn on the worker, parks the caller until it returns, rethrows what fn threw.
    // The caller must own everything fn touches until run() returns.
    static void run(const std::function<void()>& fn)
    {
        static FcwebWorker worker;
        worker.exec(fn);
    }

private:
    std::mutex mutex;
    std::condition_variable wake;
    const std::function<void()>* job = nullptr;
    std::exception_ptr error;
    std::atomic<int> done {0};
    std::thread thread;

    void exec(const std::function<void()>& fn)
    {
        done = 0;
        error = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex);
            job = &fn;
        }
        if (!thread.joinable()) {
            thread = std::thread([this]() { loop(); });
        }
        wake.notify_one();
        PyThreadState* ts = PyGILState_Check() ? PyEval_SaveThread() : nullptr;
        fcweb_wait_flag(reinterpret_cast<volatile int*>(&done));
        if (ts) {
            PyEval_RestoreThread(ts);
        }
        if (error) {
            std::rethrow_exception(error);
        }
    }

    void loop()
    {
        for (;;) {
            const std::function<void()>* fn = nullptr;
            {
                std::unique_lock<std::mutex> lock(mutex);
                wake.wait(lock, [this]() { return job != nullptr; });
                fn = job;
                job = nullptr;
            }
            try {
                (*fn)();
            }
            catch (...) {
                error = std::current_exception();
            }
            done = 1;
            emscripten_futex_wake(&done, 1);
            fcweb_notify_flag(reinterpret_cast<volatile int*>(&done));   // the wake waitAsync actually hears
        }
    }
};

}  // namespace Base

#endif  // __EMSCRIPTEN__
#endif  // BASE_FCWEBWORKER_H
