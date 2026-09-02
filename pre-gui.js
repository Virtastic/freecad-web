// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
// Injected via --pre-js for the browser GUI build. Sets FreeCAD's env + writable
// dirs in the wasm MEMFS before main runs (paths point at the preloaded resources).
Module['preRun'] = Module['preRun'] || [];
Module['preRun'].push(function () {
  try {
    ENV.FCWEB_PYLIB = '/pylib:/fc-ext:/pyside-pkg';
    ENV.FREECAD_WASM_HOME = '/freecad';
    ENV.HOME = '/home/web_user';
    ENV.QT_QPA_PLATFORM = 'wasm';
    // Disable Coin render caching: display lists are stubbed in wasm and cache
    // creation loops forever in the emulated GL path.
    ENV.COIN_AUTO_CACHING = '0';
    ENV.IV_SEPARATOR_MAX_CACHES = '0';
    // WASM init-bisection: forward ?skipCoin / ?skipWb URL params to env vars so
    // init substeps can be toggled across page reloads without a rebuild.
    try {
      var qs = new URLSearchParams((typeof location !== 'undefined' && location.search) || '');
      if (qs.has('skipCoin')) { ENV.FCWEB_SKIP_COIN = '1'; }
      if (qs.has('skipWb'))   { ENV.FCWEB_SKIP_WB = '1'; }
      // 3D viewport is ON by default now that the render pipeline works; ?no3d opts out.
      if (!qs.has('no3d'))     { ENV.FCWEB_ENABLE_3D = '1'; ENV.FCWEB_NO_FBO0 = '1'; }
      if (qs.has('nofbo0'))    { ENV.FCWEB_NO_FBO0 = '1'; }
      if (qs.has('debug'))     { ENV.FCWEB_DEBUG = '1'; }
      // VBOs are ON by default (2026-09). Verified pixel-identical to the immediate path
      // on the BIM example (Part shapes). Meshes are a DIFFERENT path: with VBOs on,
      // Mesh nodes draw through MeshRenderer with GL_UNSIGNED_INT indices, which
      // emscripten's emulation read as 16-bit -- a sphere rendered as a hemisphere, an
      // STL as spikes -- and the "correct" 51k-tri test was a flat plane that hid it.
      // tools/patch-freecad-js.py (INDEX_TYPE) fixes the emulation; ?vbo=0 opts back
      // into immediate mode for A/B and as the escape hatch.
      if (qs.get('vbo') !== '0') { ENV.FCWEB_VBO = '1'; }
    } catch (e) {}
    FS.mkdirTree('/home/web_user/.FreeCAD');
    FS.mkdirTree('/home/web_user/.local/share');
    FS.mkdirTree('/home/web_user/.config');
    FS.mkdirTree('/home/web_user/.cache');
    // IDBFS persistence (R4): mount the user's home on IndexedDB so documents
    // and settings survive page reloads. Restore BEFORE main() runs (run dep),
    // then persist on an interval + expose an explicit flush hook.
    // Disable with ?noidbfs (e.g. for pristine-boot tests). Node builds skip it.
    try {
      var qs2 = new URLSearchParams((typeof location !== 'undefined' && location.search) || '');
      var wantIdb = (typeof window !== 'undefined') && !qs2.has('noidbfs') &&
                    typeof IDBFS !== 'undefined';
      if (wantIdb) {
        FS.mount(IDBFS, {}, '/home/web_user');
        addRunDependency('fcweb-idbfs-restore');
        FS.syncfs(true, function (e) {
          if (e) { if (typeof err === 'function') err('[pre-gui] IDBFS restore failed: ' + e); }
          else {
            // Restore may have wiped the skeleton dirs on first run; re-ensure them.
            try {
              FS.mkdirTree('/home/web_user/.FreeCAD');
              FS.mkdirTree('/home/web_user/.local/share');
              FS.mkdirTree('/home/web_user/.config');
              FS.mkdirTree('/home/web_user/.cache');
            } catch (e2) {}
          }
          removeRunDependency('fcweb-idbfs-restore');
        });
        var syncing = false;
        var dirty = false;                          // a write happened since the last flush
        var flush = function (cb) {
          if (syncing) { if (cb) cb('busy'); return; }
          syncing = true;
          FS.syncfs(false, function (e) {
            syncing = false;
            dirty = false;
            if (e && typeof err === 'function') err('[pre-gui] IDBFS persist failed: ' + e);
            if (cb) cb(e);
          });
        };
        Module.fcwebSyncFS = flush;                 // explicit flush for the harness/UI

        // Persist as soon as something under the persisted home actually changes.
        // The old behaviour was a bare 15s timer, so "edit, then hit refresh" lost the
        // work: anything written inside the window never reached IndexedDB (measured —
        // a write + immediate reload was gone, the same write + 20s wait survived).
        // syncfs is async and unload handlers cannot await it, so the fix is to start
        // the write early rather than to try to squeeze it into unload: debounce a
        // flush ~1.2s after each change to the home tree.
        var timer = null;
        var touch = function () {
          dirty = true;
          if (timer) { return; }
          // 400ms, not 1200: the autosave writes then the user may reload immediately,
          // and every millisecond here is time the work exists only in memory.
          timer = setTimeout(function () { timer = null; if (dirty) flush(); }, 400);
        };
        Module.fcwebTouchFS = touch;
        try {
          // Hook the FS write paths that can reach the mounted home. Cheap: they only
          // set a flag; the debounce does the real work.
          ['write', 'unlink', 'rmdir', 'mkdir', 'rename', 'truncate', 'symlink'].forEach(function (op) {
            var orig = FS[op];
            if (typeof orig !== 'function') { return; }
            FS[op] = function () { var r = orig.apply(FS, arguments); try { touch(); } catch (e) {} return r; };
          });
        } catch (eh) { if (typeof err === 'function') err('[pre-gui] IDBFS hook: ' + eh); }

        setInterval(function () { if (dirty) flush(); }, 15000);   // backstop
        if (typeof window !== 'undefined') {
          // pagehide fires on reload/close/back-forward-cache where visibilitychange
          // alone does not; both are best-effort (the browser may cut us off).
          window.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'hidden') flush();
          });
          window.addEventListener('pagehide', function () { flush(); });
        }
      }
    } catch (e3) { if (typeof err === 'function') err('[pre-gui] IDBFS setup: ' + e3); }
  } catch (e) { if (typeof err === 'function') err('[pre-gui] ' + e); }
});
// CPython's reflection trampoline calls Module.PyEM_CountArgs from ANY thread.
// Module.preRun (which installs the wasm-parsing version below) only runs on the
// main thread, so on a pthread worker PyEM_CountArgs was undefined and the call
// threw "TypeError: Module.PyEM_CountArgs is not a function", aborting the whole
// instance (this is what killed FEM module imports -> FEM proxies restored as
// None). Define it at TOP LEVEL so every JS context that loads this file --
// including pthread workers -- has it.
//
// A WebAssembly exported function's JS `length` IS its declared parameter count
// (JS-API spec), so this needs no wasm parsing and works identically on workers.
// The postRun self-check below verifies it agrees with the parsed table.
Module.PyEM_CountArgs = Module.PyEM_CountArgs || function (idx) {
  try {
    var t = (typeof wasmTable !== 'undefined' && wasmTable) ? wasmTable : (Module.wasmTable || null);
    if (t) { var f = t.get(idx); if (f && typeof f.length === 'number') return f.length; }
  } catch (e) {}
  return 3; // safe default (max arity)
};
// Parse the module's wasm to map function-table index -> parameter count, so
// CPython's reflection trampoline can call C functions directly (no JS frame).
// Mirrors the wasm-feature-detect / Pyodide approach for browsers lacking the
// WebAssembly type-reflection proposal.
Module.fcweb_install_pyem_countargs = function(wasmBytes) {
  try {
    var b = new Uint8Array(wasmBytes), pos = 8; // skip magic+version
    function u32(){ var r=0,sh=0,by; do{ by=b[pos++]; r|=(by&0x7f)<<sh; sh+=7; }while(by&0x80); return r>>>0; }
    var typeParams = [];      // type index -> param count
    var funcTypeIdx = [];     // function index -> type index (imports first, then defined)
    var elemMap = {};         // table index -> function index
    while (pos < b.length) {
      var id = b[pos++]; var size = u32(); var end = pos + size;
      if (id === 1) { // Type
        var nt = u32();
        for (var i=0;i<nt;i++){ var form=b[pos++]; /*0x60*/ var np=u32(); pos+=np; var nr=u32(); pos+=nr; typeParams.push(np); }
      } else if (id === 2) { // Import
        var ni = u32();
        for (var j=0;j<ni;j++){ var ml=u32(); pos+=ml; var fl=u32(); pos+=fl; var kind=b[pos++];
          if (kind===0){ funcTypeIdx.push(u32()); }
          else if (kind===1){ pos++; var fl2=b[pos++]; u32(); if(fl2&1)u32(); } // table
          else if (kind===2){ var fl3=b[pos++]; u32(); if(fl3&1)u32(); } // mem
          else if (kind===3){ pos++; pos++; } // global: valtype + mut
        }
      } else if (id === 3) { // Function
        var nf = u32(); for (var k=0;k<nf;k++) funcTypeIdx.push(u32());
      } else if (id === 9) { // Element
        var ns = u32();
        for (var s2=0;s2<ns;s2++){
          var flags=u32();
          // handle the common active-func-index form (flags 0)
          if (flags===0){ // e: expr, then vec(funcidx)
            // expr: skip until 0x0b (end); typically i32.const N; end
            var base=0;
            if (b[pos]===0x41){ pos++; base=u32(); } // i32.const
            while(b[pos]!==0x0b) pos++; pos++; // end
            var nfn=u32();
            for (var e=0;e<nfn;e++){ elemMap[base+e]=u32(); }
          } else {
            // other element forms: bail (rare in emscripten main table). break out.
            pos = end; break;
          }
        }
      }
      pos = end;
    }
    Module.PyEM_CountArgs = function(tableIndex){
      var fi = elemMap[tableIndex];
      if (fi === undefined) return 3; // safe default (max arity)
      var ti = funcTypeIdx[fi];
      var p = typeParams[ti];
      return (p === undefined) ? 3 : p;
    };
    if (typeof err==='function') err('[fcweb] PyEM_CountArgs installed (types='+typeParams.length+' funcs='+funcTypeIdx.length+' elems='+Object.keys(elemMap).length+')');
    return true;
  } catch(e) { if(typeof err==='function') err('[fcweb] PyEM_CountArgs parse failed: '+e); return false; }
};
// Install as early as possible: emscripten exposes the wasm bytes as wasmBinary
// (when instantiated from an ArrayBuffer). Hook instantiateWasm-time via preRun.
Module.preRun = Module.preRun || [];
Module.preRun.push(function(){
  try {
    if (Module.wasmBinary) { Module.fcweb_install_pyem_countargs(Module.wasmBinary); }
  } catch(e){}
});
// Qt's DOM events must arrive on a stack that can suspend.
//
// With -sJSPI only ASYNCIFY_EXPORTS get WebAssembly.promising, and only a promising
// stack may suspend. Qt delivers every browser event through Module.QtEventListener
// (qstdweb.cpp EventCallback) -- an embind method, not promising -- so any nested event
// loop reached from a real click, key or drag threw "SuspendError: trying to suspend
// without WebAssembly.promising" and the action silently did nothing: Help > About
// opened no dialog, dragging a tree item onto a Group did not reparent it.
//
// So Qt gets our listener instead, entering wasm through fcweb_dispatch_event, which IS
// in ASYNCIFY_EXPORTS. Installed at onRuntimeInitialized: embind has registered its
// classes by then (initRuntime ran the ctors) and Qt has not yet created any listener
// (that happens inside main).
(function () {
  function install() {
    if (Module.__fcwebEventDispatchInstalled) { return; }
    var dispatch = Module._fcweb_dispatch_event;
    if (typeof dispatch !== 'function') {
      // Export missing (older binary): leave Qt's own listener in place rather than
      // breaking all input -- dialogs and drag stay broken, everything else works.
      if (typeof err === 'function') { err('[fcweb] no fcweb_dispatch_event; Qt events stay non-suspendable'); }
      return;
    }
    Module.__fcwebEventDispatchInstalled = true;

    function QtEventListener(handler) { this.handler = handler; }
    QtEventListener.prototype.handleEvent = function (event) {
      // Read synchronously by fcweb_dispatch_event before it can suspend, so an event
      // delivered during a suspend (which is the whole point -- a modal dialog keeps
      // processing input) cannot clobber this one.
      Module.__fcwebEvent = event;
      var r;
      try {
        r = dispatch(this.handler);
      } catch (e) {
        if (typeof err === 'function') { err('[fcweb] event handler threw: ' + e); }
        return;
      }
      // A promising export returns a Promise; without this a rejection is invisible.
      if (r && typeof r.catch === 'function') {
        r.catch(function (e) {
          if (typeof err === 'function') { err('[fcweb] event handler rejected: ' + e); }
        });
      }
    };
    Module.QtEventListener = QtEventListener;
  }
  var prev = Module.onRuntimeInitialized;
  Module.onRuntimeInitialized = function () {
    try { install(); } catch (e) {
      if (typeof err === 'function') { err('[fcweb] event dispatch install failed: ' + e); }
    }
    if (prev) { prev.apply(this, arguments); }
  };
})();

// Self-check (main thread, after instantiation): the worker fallback above uses
// the exported function's `length`; confirm it agrees with the parsed wasm types
// so a wrong arity can never silently corrupt a trampolined call. Logs one line.
Module.postRun = Module.postRun || [];
Module.postRun.push(function(){
  try {
    if (typeof wasmTable === 'undefined' || !wasmTable) return;
    var parsed = Module.PyEM_CountArgs; if (typeof parsed !== 'function') return;
    var checked = 0, mismatch = 0, step = Math.max(1, (wasmTable.length / 3000) | 0);
    for (var i = 1; i < wasmTable.length && checked < 3000; i += step) {
      var f; try { f = wasmTable.get(i); } catch (e) { continue; }
      if (!f || typeof f.length !== 'number') continue;
      checked++;
      if (parsed(i) !== f.length) mismatch++;
    }
    if (typeof err === 'function')
      err('[fcweb] PyEM_CountArgs selfcheck checked=' + checked + ' mismatch=' + mismatch);
  } catch (e) {}
});
