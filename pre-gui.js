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
        var flush = function (cb) {
          if (syncing) { if (cb) cb('busy'); return; }
          syncing = true;
          FS.syncfs(false, function (e) {
            syncing = false;
            if (e && typeof err === 'function') err('[pre-gui] IDBFS persist failed: ' + e);
            if (cb) cb(e);
          });
        };
        Module.fcwebSyncFS = flush;                 // explicit flush for the harness/UI
        setInterval(flush, 15000);                  // periodic autosave of /home/web_user
        if (typeof window !== 'undefined') {
          window.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'hidden') flush();
          });
        }
      }
    } catch (e3) { if (typeof err === 'function') err('[pre-gui] IDBFS setup: ' + e3); }
  } catch (e) { if (typeof err === 'function') err('[pre-gui] ' + e); }
});
