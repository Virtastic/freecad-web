// Run a CalculiX deck through the wasm module under node and print result extremes.
//
// The browser bridge (freecad-gui.html) does the same three things -- write the .inp
// into the module FS, ccall fcweb_ccx_run, read the outputs back -- so a pass here is
// a pass on the same code path the app takes, minus the file plumbing.
const fs = require('fs');
const path = require('path');

const inp = process.argv[2];
const job = path.basename(inp).replace(/\.inp$/i, '');

(async () => {
  const CcxModule = require('/Users/mstavridis/Downloads/FreeCAD-Web/play-gui/ccx.js');
  const M = await CcxModule();
  try { M.FS.mkdir('/work'); } catch (e) {}
  M.FS.chdir('/work');
  M.FS.writeFile('/work/' + job + '.inp', fs.readFileSync(inp));
  const rc = M.ccall('fcweb_ccx_run', 'number', ['string'], [job]);
  const read = (ext) => {
    try { return new TextDecoder().decode(M.FS.readFile('/work/' + job + ext)); }
    catch (e) { return ''; }
  };
  const out = { rc, frd: read('.frd'), dat: read('.dat'), sta: read('.sta') };
  console.log('rc=' + rc + ' frd=' + out.frd.length + ' dat=' + out.dat.length);
  fs.writeFileSync('/tmp/' + job + '.frd', out.frd);
  fs.writeFileSync('/tmp/' + job + '.dat', out.dat);
  if (out.dat) console.log('--- dat ---\n' + out.dat.slice(0, 3000));
  // .frd blocks: -4 names the field, -1 lines carry the values
  const lines = out.frd.split('\n');
  let field = null; const ext = {};
  for (const l of lines) {
    if (l.startsWith(' -4')) { field = l.trim().split(/\s+/)[1]; continue; }
    if (l.startsWith(' -1') && field) {
      const v = l.slice(13).match(/.{1,12}/g) || [];
      const e = ext[field] || (ext[field] = []);
      v.forEach((s, i) => {
        const x = parseFloat(s);
        if (!isFinite(x)) return;
        if (!e[i]) e[i] = [x, x];
        e[i][0] = Math.min(e[i][0], x); e[i][1] = Math.max(e[i][1], x);
      });
    }
  }
  for (const k of Object.keys(ext)) {
    console.log(k + ': ' + ext[k].map((p) => p[0].toExponential(4) + '..' + p[1].toExponential(4)).join('  '));
  }
  process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
