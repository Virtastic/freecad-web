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
      if (qs.has('render3d'))  { ENV.FCWEB_ENABLE_3D = '1'; ENV.FCWEB_NO_FBO0 = '1'; }
      if (qs.has('nofbo0'))    { ENV.FCWEB_NO_FBO0 = '1'; }
    } catch (e) {}
    FS.mkdirTree('/home/web_user/.FreeCAD');
    FS.mkdirTree('/home/web_user/.local/share');
    FS.mkdirTree('/home/web_user/.config');
    FS.mkdirTree('/home/web_user/.cache');
  } catch (e) { if (typeof err === 'function') err('[pre-gui] ' + e); }
});
