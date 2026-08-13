// Give Qt's DOM event handlers a JSPI-suspendable (promising) stack.
//
// WHY: with -sJSPI only the exports named in ASYNCIFY_EXPORTS are wrapped in
// WebAssembly.promising, and only a promising stack may suspend. `fcweb_run_python` is
// in that list, so anything driven through the Python bridge can suspend and works --
// which is why every modal dialog verified so far (all triggered via Gui.runCommand from
// the harness) looked fine. Qt's DOM events take a completely different route: the
// browser calls Module.QtEventListener.handleEvent (qstdweb.cpp EventCallback), an
// embind method that is NOT promising. So any nested event loop entered from a real
// mouse or key event traps:
//
//     SuspendError: trying to suspend without WebAssembly.promising
//
// Measured consequences, both silent (the app survives, the action just never happens):
//   - clicking Help > About opens NO dialog          (QDialog::exec -> nested loop)
//   - dragging a tree item onto a Group does nothing (QDrag::exec  -> nested loop,
//     qwasmdrag.cpp:94-99, which Qt only even attempts when JSPI is available)
//
// WHAT: this is the one export Qt's event delivery goes through instead. Listed in
// ASYNCIFY_EXPORTS, so emscripten wraps it in WebAssembly.promising and every Qt event
// handler runs on a stack that can suspend -- the same footing the Python bridge has.
// pre-gui.js replaces Module.QtEventListener with a plain JS class that calls this.
//
// The event value is handed over through Module.__fcwebEvent rather than an embind
// handle so the JS side needs no access to emscripten's minified Emval internals. It is
// read here synchronously, before anything can suspend, so a nested event delivered
// while this one is suspended cannot clobber it.
//
// Compile:
//   em++ -fwasm-exceptions -pthread -O2 -c wasm_event_dispatch.cpp -o wasm_event_dispatch.o
// Link: add the object, -sEXPORTED_FUNCTIONS+=_fcweb_dispatch_event and
//   -sASYNCIFY_EXPORTS=fcweb_run_python,fcweb_dispatch_event

#include <emscripten/val.h>

#include <cstdint>
#include <functional>

extern "C" void fcweb_dispatch_event(std::uintptr_t handler)
{
    if (!handler) {
        return;
    }
    // Same type qstdweb::EventCallback allocates and passes to QtEventListener.
    auto* fn = reinterpret_cast<std::function<void(emscripten::val)>*>(handler);
    emscripten::val event = emscripten::val::module_property("__fcwebEvent");
    (*fn)(event);
}
