/* Weak fallback so link-time try-compiles (cmake feature checks) that carry the
 * app's EXPORTED_FUNCTIONS / JSPI export flags succeed. The real (strong)
 * definition in src/Main/MainGui.cpp overrides this in the actual app link. */
#include <emscripten.h>
__attribute__((weak)) EMSCRIPTEN_KEEPALIVE void fcweb_run_python(const char* code) { (void)code; }
