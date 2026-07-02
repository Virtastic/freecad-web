// Injected via --post-js. Qt-for-WebAssembly's event glue calls getWasmTableEntry
// from callback scopes where emscripten 3.1.70's module-local definition isn't
// visible; expose it (and setWasmTableEntry) globally so those calls resolve.
(function () {
  try {
    if (typeof getWasmTableEntry !== 'undefined') {
      Module['getWasmTableEntry'] = getWasmTableEntry;
      globalThis.getWasmTableEntry = getWasmTableEntry;
    }
    if (typeof setWasmTableEntry !== 'undefined') {
      Module['setWasmTableEntry'] = setWasmTableEntry;
      globalThis.setWasmTableEntry = setWasmTableEntry;
    }
  } catch (e) { /* ignore */ }
})();
