// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// Decide whether threaded CalculiX may ship, by comparing RESULTS.
//
//     node tools/ccx-compare.js --a play-gui/ccx.js --b build-ccx-pthreads/ccx.js
//     node tools/ccx-compare.js --a ... --b ... --decks scratchpad/ccxval --repeat 3
//
// WHY NOT EXIT CODES
//
// Threading was turned off in this project for a reason that is written down in
// build-ccx-weh.sh: without -pthread, pthread_create is a stub that fails, ccx never
// checks its return value, and the assembled matrix came out identically zero. The solver
// returned 0. The run "succeeded". Every number in it was wrong.
//
// So a comparison that looks at rc, or at whether an .frd was produced, cannot see the
// failure it exists to catch. This reads the fields out of both runs and compares them
// value by value, and it fails a field that is identically zero even when both sides agree
// -- because two identical zeros is exactly what that bug produced.
//
// A race in parallel assembly does not crash. It shifts a digit. That is the whole reason
// the tolerance here is tight (1e-9 relative by default) rather than the 5% the end-to-end
// FEM gate uses: the gate is asking "did it solve the beam", this is asking "is it the
// same solver".
//
// ON THE TIMINGS
//
// This answers "is it the same solver", and only incidentally "is it faster". The decks in
// scratchpad/ccxval run in about a tenth of a second, and a tenth of a second on a laptop
// is noise -- measuring the same module against itself produced a 1.39x "speedup" -- so
// anything under half a second is labelled as such rather than reported as a result. The
// speed question belongs to a deck big enough to answer it: the 8,640-element beam, where
// serial was measured at 2.80 s on 2026-08-25.
'use strict';

const fs = require('fs');
const path = require('path');

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt;
}

const A = arg('a', 'play-gui/ccx.js');
const B = arg('b', null);
const DECKDIR = arg('decks', 'scratchpad/ccxval');
const REPEAT = parseInt(arg('repeat', '1'), 10);
const RELTOL = parseFloat(arg('reltol', '1e-9'));
// Values this small are noise against the field's own scale; comparing them relatively
// turns 1e-300 vs 2e-300 into a 100% difference and says nothing.
const ABSFLOOR = parseFloat(arg('absfloor', '1e-12'));

if (!B) {
  console.error('usage: node tools/ccx-compare.js --a <serial ccx.js> --b <threaded ccx.js> '
                + '[--decks DIR] [--repeat N] [--reltol R]');
  process.exit(2);
}

// One .frd, parsed into {field: [values...]} in file order. Order is what makes this a
// value-by-value comparison rather than a comparison of summary statistics, which is a
// thing a race can slip past.
function parseFrd(text) {
  const fields = {};
  let field = null;
  for (const line of text.split('\n')) {
    if (line.startsWith(' -4')) {
      field = line.trim().split(/\s+/)[1];
      if (!fields[field]) fields[field] = [];
      continue;
    }
    if (line.startsWith(' -1') && field) {
      // Fixed 12-character columns after the 13-character node record.
      const cols = line.slice(13).match(/.{1,12}/g) || [];
      for (const c of cols) {
        const x = parseFloat(c);
        if (isFinite(x)) fields[field].push(x);
      }
    }
  }
  return fields;
}

async function runDeck(modPath, deck, job) {
  // Load fresh each time: the module holds solver state and a reused instance would let one
  // deck's results answer for the next.
  delete require.cache[require.resolve(path.resolve(modPath))];
  const CcxModule = require(path.resolve(modPath));
  const M = await CcxModule();
  try { M.FS.mkdir('/work'); } catch (e) { /* already there */ }
  M.FS.chdir('/work');
  M.FS.writeFile('/work/' + job + '.inp', fs.readFileSync(deck));
  // An abort inside the solver -- this build stubs out routines that use F90 constructs
  // FORTRAN 77 cannot express, and contact.inp reaches one -- unwinds as a JS throw and
  // would otherwise take the whole comparison down on the first deck. Catch it here so
  // each deck stands alone, and so that "both builds abort identically" can be told apart
  // from "one of them does".
  const t0 = process.hrtime.bigint();
  let rc = null, aborted = null;
  try {
    rc = M.ccall('fcweb_ccx_run', 'number', ['string'], [job]);
  } catch (e) {
    aborted = String((e && e.message) || e).split(String.fromCharCode(10))[0].slice(0, 120);
  }
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  const read = (ext) => {
    try { return new TextDecoder().decode(M.FS.readFile('/work/' + job + ext)); }
    catch (e) { return ''; }
  };
  return { rc: rc, ms: ms, aborted: aborted, frd: read('.frd'), dat: read('.dat') };
}

function compare(fa, fb) {
  const problems = [];
  const names = Array.from(new Set(Object.keys(fa).concat(Object.keys(fb)))).sort();
  const report = [];
  // No fields at all is not agreement. Without this, a parser that silently matched
  // nothing would compare an empty set to an empty set and report a clean pass -- the
  // same shape of lie as the zero matrix this tool exists to catch.
  if (!names.length) {
    return { problems: ['no result fields were parsed from either .frd'], report: [] };
  }
  for (const n of names) {
    const a = fa[n] || [], b = fb[n] || [];
    if (a.length !== b.length) {
      problems.push(n + ': ' + a.length + ' values from A but ' + b.length + ' from B');
      continue;
    }
    if (!a.length) { problems.push(n + ': no values at all'); continue; }
    let worst = 0, worstAt = -1, maxAbs = 0;
    for (let i = 0; i < a.length; i++) {
      maxAbs = Math.max(maxAbs, Math.abs(a[i]), Math.abs(b[i]));
      const scale = Math.max(Math.abs(a[i]), Math.abs(b[i]), ABSFLOOR);
      const rel = Math.abs(a[i] - b[i]) / scale;
      if (rel > worst) { worst = rel; worstAt = i; }
    }
    report.push({ field: n, n: a.length, worst: worst, at: worstAt, maxAbs: maxAbs });
    // The zero-matrix failure: both sides agree perfectly, and both are wrong.
    //
    // EXACTLY zero, not "small". The first version of this tested maxAbs <= ABSFLOOR and
    // immediately failed the elas deck, whose ERROR field is a numerical residual with a
    // magnitude of 1.7e-14 -- a real, correct, tiny number. A tolerance-based test cannot
    // tell a residual from an unassembled matrix. An exact-zero test can: the bug this
    // guards produced 0.0 everywhere, not something small.
    if (maxAbs === 0) {
      problems.push(n + ': every value is exactly zero in BOTH runs -- that is the '
                    + 'signature of the failed-pthread_create bug, not agreement');
    } else if (worst > RELTOL) {
      problems.push(n + ': differs by ' + worst.toExponential(2) + ' at value ' + worstAt
                    + ' (tolerance ' + RELTOL.toExponential(0) + ')');
    }
  }
  return { problems: problems, report: report };
}

(async () => {
  const decks = fs.readdirSync(DECKDIR).filter((f) => /\.inp$/i.test(f)).sort();
  if (!decks.length) { console.error('no .inp decks in ' + DECKDIR); process.exit(2); }
  console.log('A (reference): ' + A);
  console.log('B (candidate): ' + B);
  console.log(decks.length + ' deck(s) from ' + DECKDIR + ', ' + REPEAT + ' timed run(s) each, '
              + 'relative tolerance ' + RELTOL.toExponential(0));
  console.log('');

  let failed = 0, skipped = 0;
  for (const d of decks) {
    const job = d.replace(/\.inp$/i, '');
    const deck = path.join(DECKDIR, d);
    let ra = null, rb = null, ta = [], tb = [];
    // One untimed run of each first. Comparing the same module against itself measured
    // 188 ms then 74 ms -- that 2.5x is V8 compiling the wasm, not the solver, and without
    // a warmup whichever build ran first would always look slower.
    await runDeck(A, deck, job);
    await runDeck(B, deck, job);
    for (let i = 0; i < REPEAT; i++) {
      const x = await runDeck(A, deck, job); ta.push(x.ms); if (!ra) ra = x;
      const y = await runDeck(B, deck, job); tb.push(y.ms); if (!rb) rb = y;
    }
    const med = (v) => v.slice().sort((p, q) => p - q)[v.length >> 1];
    const ma = med(ta), mb = med(tb);
    const speed = mb > 0 ? ma / mb : 0;
    console.log('=== ' + job);
    console.log('    rc     A=' + (ra.aborted ? 'ABORT' : ra.rc)
                + '  B=' + (rb.aborted ? 'ABORT' : rb.rc));
    console.log('    time   A=' + ma.toFixed(0) + ' ms   B=' + mb.toFixed(0) + ' ms   '
                + (speed >= 1 ? speed.toFixed(2) + 'x faster' : (1 / speed).toFixed(2) + 'x SLOWER')
                + (Math.max(ma, mb) < 500 ? '   (too short to time -- noise)' : ''));

    // A deck this build cannot solve at all is not evidence either way about threading,
    // as long as BOTH builds refuse it for the same reason. Say so rather than counting it.
    if (ra.aborted && rb.aborted) {
      console.log('    SKIP   both builds abort on this deck: ' + ra.aborted);
      skipped++; console.log(''); continue;
    }
    if (!!ra.aborted !== !!rb.aborted) {
      console.log('    FAIL   only one build aborted -- A=' + (ra.aborted || 'ok')
                  + '  B=' + (rb.aborted || 'ok'));
      failed++; console.log(''); continue;
    }
    if (ra.rc !== rb.rc) { console.log('    FAIL   exit codes differ'); failed++; continue; }
    if (!ra.frd && !rb.frd) {
      console.log('    FAIL   neither run produced an .frd, so there is nothing to compare');
      failed++; continue;
    }
    const c = compare(parseFrd(ra.frd), parseFrd(rb.frd));
    for (const r of c.report) {
      console.log('    ' + r.field.padEnd(12) + r.n + ' values, worst relative difference '
                  + r.worst.toExponential(2) + ', magnitude up to ' + r.maxAbs.toExponential(3));
    }
    if (c.problems.length) {
      failed++;
      for (const p of c.problems) console.log('    FAIL   ' + p);
    } else {
      console.log('    OK     every field matches the reference');
    }
    console.log('');
  }

  if (failed) {
    console.log('VERDICT: ' + failed + ' deck(s) disagree. Threading does not ship.');
    process.exit(1);
  }
  console.log('VERDICT: every comparable deck matches the serial reference'
              + (skipped ? ' (' + skipped + ' deck(s) skipped: unsupported by both builds).' : '.'));
  process.exit(0);
})().catch((e) => { console.error('DRIVER ' + (e && e.stack || e)); process.exit(1); });
