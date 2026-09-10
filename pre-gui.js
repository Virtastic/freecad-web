// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
// Injected via --pre-js for the browser GUI build. Sets FreeCAD's env + writable
// dirs in the wasm MEMFS before main runs (paths point at the preloaded resources).
Module['preRun'] = Module['preRun'] || [];
Module['preRun'].push(function () {
  try {
    ENV.FCWEB_PYLIB = '/pylib:/fc-ext:/pyside-pkg';
    // NO OpenSSL IN THIS BUILD, AND THAT KILLED THE ADDON MANAGER.
    //
    // CPython is linked without _ssl, so the stdlib ssl.py raises on import, so
    // FreeCAD's Mod/AddonManager/InitGui.py dies during startup and Std_AddonMgr is
    // never registered -- NO addon can be installed, on the shipped release as much as
    // on dev. Measured by the addonmgr gate scenario, which fails with
    // FreeCADError(No such command Std_AddonMgr).
    //
    // FCWEB_PYLIB becomes config.pythonpath_env, which sits AHEAD of the stdlib in
    // sys.path, so a stub at the front of it shadows the broken module. It has to be
    // written here, before main(): the Addon Manager overlay is injected from the page
    // long after InitGui.py has already run and failed.
    try {
      FS.mkdirTree('/fcweb-py');
      FS.writeFile('/fcweb-py/ssl.py', [
        '# SPDX-License-Identifier: LGPL-2.1-or-later',
        '\'\'\'Import-only stand-in for the stdlib ssl module.',
        '',
        'CPython here is linked WITHOUT OpenSSL: there is no _ssl in the build (no _ssl.so, no',
        'lib-dynload), and the stdlib ssl.py imports it on its first line with an explicit',
        'comment that the error should propagate. So `import ssl` raises ImportError, and',
        'FreeCAD dies on it while running Mod/AddonManager/InitGui.py -- which means',
        'Std_AddonMgr is never registered and NO addon can be installed at all. Measured by the',
        'addonmgr gate scenario, on the shipped release as well as on dev.',
        '',
        'Nothing in this port does TLS from Python -- every request is proxied through the',
        'page\'s fetch() -- so the import needs to SUCCEED, not to work. Anything that actually',
        'reaches for a TLS socket raises with the reason rather than failing obscurely later.',
        '\'\'\'',
        '',
        '_REASON = (\'this build has no OpenSSL: CPython was linked without _ssl, and network\'',
        '           \' access goes through the page proxy instead\')',
        '',
        '',
        'class SSLError(OSError):',
        '    pass',
        '',
        '',
        'class SSLZeroReturnError(SSLError):',
        '    pass',
        '',
        '',
        'class SSLWantReadError(SSLError):',
        '    pass',
        '',
        '',
        'class SSLWantWriteError(SSLError):',
        '    pass',
        '',
        '',
        'class SSLSyscallError(SSLError):',
        '    pass',
        '',
        '',
        'class SSLEOFError(SSLError):',
        '    pass',
        '',
        '',
        'class SSLCertVerificationError(SSLError, ValueError):',
        '    pass',
        '',
        '',
        'CertificateError = SSLCertVerificationError',
        '',
        'OPENSSL_VERSION = \'none (built without OpenSSL)\'',
        'OPENSSL_VERSION_NUMBER = 0',
        'OPENSSL_VERSION_INFO = (0, 0, 0, 0, 0)',
        'HAS_SNI = HAS_ECDH = HAS_ALPN = HAS_NPN = HAS_TLSv1_3 = False',
        'CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED = 0, 1, 2',
        'VERIFY_DEFAULT = 0',
        'PROTOCOL_TLS = PROTOCOL_TLS_CLIENT = PROTOCOL_TLS_SERVER = PROTOCOL_TLSv1_2 = 2',
        'OP_NO_SSLv2 = OP_NO_SSLv3 = OP_NO_COMPRESSION = OP_ALL = 0',
        '',
        '',
        'class Purpose(object):',
        '    SERVER_AUTH = \'serverAuth\'',
        '    CLIENT_AUTH = \'clientAuth\'',
        '',
        '',
        'class SSLContext(object):',
        '    def __init__(self, *a, **k):',
        '        self.check_hostname = False',
        '        self.verify_mode = CERT_NONE',
        '        self.options = 0',
        '        self.protocol = PROTOCOL_TLS_CLIENT',
        '',
        '    def load_default_certs(self, *a, **k):',
        '        pass',
        '',
        '    def load_verify_locations(self, *a, **k):',
        '        pass',
        '',
        '    def load_cert_chain(self, *a, **k):',
        '        pass',
        '',
        '    def set_ciphers(self, *a, **k):',
        '        pass',
        '',
        '    def set_alpn_protocols(self, *a, **k):',
        '        pass',
        '',
        '    def wrap_socket(self, *a, **k):',
        '        raise SSLError(_REASON)',
        '',
        '    def wrap_bio(self, *a, **k):',
        '        raise SSLError(_REASON)',
        '',
        '',
        'class SSLSocket(object):',
        '    def __init__(self, *a, **k):',
        '        raise SSLError(_REASON)',
        '',
        '',
        'class SSLObject(object):',
        '    def __init__(self, *a, **k):',
        '        raise SSLError(_REASON)',
        '',
        '',
        'def create_default_context(*a, **k):',
        '    return SSLContext()',
        '',
        '',
        'def _create_unverified_context(*a, **k):',
        '    return SSLContext()',
        '',
        '',
        '_create_default_https_context = create_default_context',
        '',
        '',
        'def wrap_socket(*a, **k):',
        '    raise SSLError(_REASON)',
        '',
        '',
        'def match_hostname(*a, **k):',
        '    return True',
        '',
        '',
        'def get_default_verify_paths():',
        '    return (None, None, None, None)',
        '',
        '',
        'def cert_time_to_seconds(*a, **k):',
        '    return 0',
        '',
        '',
        'def RAND_status():',
        '    return False',
        '',
        '',
        'def RAND_add(*a, **k):',
        '    pass',
        '',
        '',
        'def __getattr__(name):',
        '    # Anything not modelled above still IMPORTS; it only fails if something calls it.',
        '    # A stub whose whole job is to let an import succeed must not fall over on the one',
        '    # attribute I did not think of.',
        '    if name.startswith(\'__\'):',
        '        raise AttributeError(name)',
        '',
        '    def _missing(*a, **k):',
        '        raise SSLError(\'ssl.%s: %s\' % (name, _REASON))',
        '',
        '    return _missing'
      ].join('\n'));
      ENV.FCWEB_PYLIB = '/fcweb-py:' + ENV.FCWEB_PYLIB;
    } catch (e) {}
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
      // Part face sets specifically. SoBrepFaceSet::renderShape force-disables its
      // VBO path on wasm because it rasterised NOTHING under LEGACY_GL_EMULATION,
      // so every Part solid draws through immediate mode instead: measured at 47,000
      // draw calls per frame on a 1.13M-triangle assembly, 99.8% of them under 100
      // vertices, against ~34 indexed draws the VBO path would issue. That is the
      // whole performance story for large assemblies.
      //
      // ON by default (2026-09-09). It is much faster, two emulation bugs behind it are
      // fixed (the VBO branch never called bindBuffer; then the generated shader had no
      // GL_COLOR_MATERIAL, so every face came out black), and the colour question that
      // kept it off for a week is settled below.
      //
      // Everything here was measured on a REAL GPU (RTX 4080, ANGLE/D3D11) with ONE
      // document per browser. That is not a detail: every earlier verdict on this flag
      // was taken from a session with several documents open, which is exactly when the
      // compositor served a stale frame, so those measurements were of the bug.
      //
      // SPEED, on the user's own 42 MB a2plus assembly:
      //
      //   faces OFF   1404 ms/frame   109.9 MB uploaded per frame
      //   faces ON     367 ms/frame    23.7 MB uploaded per frame
      //
      // 3.8x, and the mechanism is data movement rather than draw calls: both paths
      // issue ~140 draws for the same 4.2M vertices, and the immediate path re-uploads
      // the entire scene every single frame.
      //
      // COLOUR, per object: the two paths agree. Identical hue counts pixel for pixel on
      // four primary-coloured boxes and on AssemblyExample, and on the a2plus assembly
      // 0.0% of pixels differ (191 of 921,600). What differs is SHADING -- a flat face
      // reads (242,0,0) on the immediate path and (208,17,17) here: ~14% darker with a
      // small ambient term, hue exact.
      //
      // COLOUR, per FACE: the immediate path is the broken one. A cube with six
      // different DiffuseColor entries, viewed from a corner:
      //
      //   faces OFF   the whole cube is RED          -- one colour for the whole object
      //   faces ON    green / blue / cyan in thirds  -- the three faces actually visible
      //
      // A default flip is a new code path (VBO-on once routed Mesh nodes onto emulation
      // code that had never run), so one document per node class was checked in a fresh
      // browser each: Part primitives with curved surfaces, an STL through Mesh,
      // draft_test_objects and BIMExample all render with the same lit-pixel count in
      // both modes.
      //
      // ?vbofaces=0 is the escape hatch back to immediate mode.
      if (qs.get('vbofaces') !== '0') { ENV.FCWEB_VBO_FACES = '1'; }
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
      // Shared sessions: with ?s=<id> the page fetches the session's environment and
      // writes it into the FS from its own preRun, BEFORE main() reads user.cfg and Mod.
      // The visitor's own IDBFS home must not be mounted over that -- their documents and
      // settings stay unreachable from a link someone sent them, which is the whole
      // isolation story. The page sets this on the Module before qtLoad.
      //
      // tools/patch-freecad-js.py carries the same change POST-link, because pre-gui.js is
      // --pre-js and baked into FreeCAD.js: every build older than this line needs it
      // patched in. That site detects this form and reports 'already applied', so once a
      // link carries this natively the patch is an idempotent no-op.
      var wantIdb = (typeof window !== 'undefined') && !qs2.has('noidbfs') &&
                    !Module.fcwebSessionMode &&
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
        // Per type: the parameter count, plus bit 4 when the RESULT is a 32-bit int (valtype
        // 0x7f). On wasm64 a pointer is i64, so a function returning int -- a getset setter
        // -- has a different wasm type from one returning PyObject*, and CPython's trampoline
        // must call it through the int-returning signature or call_indirect traps with
        // 'function signature mismatch' (the first setattr after Ready, link 33969348139).
        // On wasm32 both were i32 and the count alone was enough.
        for (var i=0;i<nt;i++){ var form=b[pos++]; /*0x60*/ var np=u32(); pos+=np; var nr=u32(); var r0=nr?b[pos]:0; pos+=nr; typeParams.push(np | ((nr===1 && r0===0x7f) ? 0x10 : 0)); }
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
            // i32.const on a 32-bit table, i64.const (0x42) on wasm64's 64-bit table. Missing the
            // second left base at 0: every arity came from the NEXT table entry, and CPython's
            // direct call_indirect trapped 'function signature mismatch' on the first method call
            // after Ready (local boot of link 33969348139). The offset is 1, whose signed and
            // unsigned LEB encodings coincide.
            if (b[pos]===0x41 || b[pos]===0x42){ pos++; base=u32(); }
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
        // BigInt: a JSPI export takes its pointer as a raw i64 on wasm64 (emscripten's
        // signature conversion skips promising exports); BigInt(BigInt) is a no-op if the
        // handler already arrives as one through Embind.
        r = dispatch(BigInt(this.handler));
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
      var f; try { f = wasmTable.get(BigInt(i)); } catch (e) { continue; }  // 64-bit table index on wasm64
      if (!f || typeof f.length !== 'number') continue;
      checked++;
      if ((parsed(i) & 0xf) !== f.length) mismatch++;  // low 4 bits: the count; bit 4: int result
    }
    if (typeof err === 'function')
      err('[fcweb] PyEM_CountArgs selfcheck checked=' + checked + ' mismatch=' + mismatch);
  } catch (e) {}
});
