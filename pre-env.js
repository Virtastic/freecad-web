// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
// Injected via --pre-js. Emscripten/node does not import the host process env,
// so copy process.env into the wasm ENV during preRun (runs in module scope).
Module['preRun'] = Module['preRun'] || [];
Module['preRun'].push(function () {
  try {
    if (typeof process !== 'undefined' && process.env) {
      for (var k in process.env) { ENV[k] = process.env[k]; }
    }
  } catch (e) { /* ENV may not exist yet on some builds */ }
});
