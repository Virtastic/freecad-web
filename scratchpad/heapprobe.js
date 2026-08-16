// Does this build survive pointers above 2 GB?
//
// Run this FIRST after linking with FCWEB_HEAP_BYTES > 2147483648. It exists because the
// hazard is not "the build fails" -- if it were, you would already know. Above 2 GB a
// pointer exceeds INT32_MAX, and any C++ in OCCT, Coin, Qt or CPython that stores one in a
// signed int, or compares one, misbehaves. The plausible symptom is CORRUPT GEOMETRY with no
// crash and nothing in the console, which is the hardest kind of bug to attribute -- so it
// gets a probe that forces allocations up there deliberately and then checks arithmetic that
// would be wrong if a pointer had been truncated or sign-flipped.
//
//   CHROME_PATH=... node scratchpad/heapprobe.js [url]
//
// Exits non-zero on failure. On a 2 GB build it reports "not applicable" and exits 0, so it
// is safe to leave in a release script.
const puppeteer = require('puppeteer-core');

const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TWO_GB = 2147483648;

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: false,
    args: ['--enable-features=SharedArrayBuffer', '--window-size=1400,900'],
    defaultViewport: { width: 1280, height: 720 },
  });
  const page = (await browser.pages())[0];
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 0 });
  await page.waitForFunction(
    () => /Ready/i.test((document.getElementById('bootstatus') || {}).textContent || ''),
    { timeout: 900000 });
  await sleep(10000);

  const heapBytes = await page.evaluate(() => {
    const m = window.fcInstance;
    return (m && m.HEAPU8) ? m.HEAPU8.buffer.byteLength : 0;
  });
  console.log('heap:', heapBytes, 'bytes (' + Math.round(heapBytes / 1048576) + ' MB)');
  if (heapBytes <= TWO_GB) {
    console.log('PASS (not applicable) — this is a 2 GB build; nothing can exceed INT32_MAX');
    await browser.close(); process.exit(0);
  }

  // Walk allocations up past 2 GB and check each pointer is sane. A truncated or
  // sign-flipped pointer shows up here as a negative or absurdly small value.
  const alloc = await page.evaluate((TWO_GB) => {
    const m = window.fcInstance, kept = [], out = { ptrs: [], bad: [], above2g: 0 };
    try {
      for (let i = 0; i < 4096; i++) {
        const p = m._malloc(1024 * 1024);          // 1 MB at a time
        if (!p) { out.mallocFailedAt = i; break; }
        kept.push(p);
        if (p < 0 || !Number.isSafeInteger(p)) { out.bad.push(p); }
        if (p > TWO_GB) {
          out.above2g++;
          if (out.ptrs.length < 5) { out.ptrs.push(p); }
          // Round-trip a byte through a pointer above 2 GB: catches a heap view that
          // was indexed with a sign-extended offset.
          m.HEAPU8[p] = 0xAB; m.HEAPU8[p + 1023] = 0xCD;
          if (m.HEAPU8[p] !== 0xAB || m.HEAPU8[p + 1023] !== 0xCD) { out.bad.push('rw@' + p); }
        }
        if (out.above2g > 64) { break; }
      }
    } catch (e) { out.threw = String(e); }
    for (const p of kept) { try { m._free(p); } catch (e) {} }
    return out;
  }, TWO_GB);

  console.log('allocations above 2 GB:', alloc.above2g, alloc.ptrs);
  if (alloc.bad && alloc.bad.length) { console.error('BAD pointers/read-back:', alloc.bad); }
  if (alloc.threw) { console.error('threw:', alloc.threw); }

  // The part that matters: geometry computed while the heap is that large must still be
  // exact. A silently wrong number here is the signed-pointer hazard showing itself.
  const vol = await page.evaluate(async () => {
    const m = window.fcInstance;
    const py = (c) => { const n = new TextEncoder().encode(c).length + 1;
                        const p = m._malloc(n); m.stringToUTF8(c, p, n); window.fcRunPy(m, p); };
    try { m.FS.unlink('/tmp/hp.txt'); } catch (e) {}
    py("import FreeCAD\n" +
       "for d in list(FreeCAD.listDocuments()): FreeCAD.closeDocument(d)\n" +
       "d=FreeCAD.newDocument('HeapProbe')\n" +
       "b=d.addObject('Part::Box','B'); b.Length=13; b.Width=17; b.Height=19\n" +
       "d.recompute()\n" +
       "open('/tmp/hp.txt','w').write('%.4f' % b.Shape.Volume)");
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      try { return new TextDecoder().decode(m.FS.readFile('/tmp/hp.txt')); } catch (e) {}
    }
    return null;
  });

  const want = 4199.0;
  const got = vol === null ? NaN : parseFloat(vol);
  console.log('13x17x19 volume:', vol, '(want', want + ')');
  console.log('page errors:', errors.length);

  const pass = alloc.above2g > 0 && (!alloc.bad || !alloc.bad.length) && !alloc.threw
               && Math.abs(got - want) < 1e-6 && errors.length === 0;
  console.log(pass
    ? 'PASS — pointers above 2 GB behave and geometry is still exact'
    : 'FAIL — do NOT ship this heap size; see above');
  await browser.close();
  process.exit(pass ? 0 : 1);
})();
