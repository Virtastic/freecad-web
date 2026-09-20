// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// The launch video: title cards (HTML photographed at 1280x720) cut between the real clips
// from scratchpad/clips.js. No narration; every card is a README sentence. ~75 s.
//
//   node scratchpad/montage.js [clips-dir] [out.mp4]
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const puppeteer = require('puppeteer-core');

const DIR = process.argv[2] || 'launch/assets/clips';
const OUT = process.argv[3] || 'launch/assets/clips/launch-montage.mp4';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const TMP = path.join(process.env.TEMP || '/tmp', 'fc-montage');
const W = 1280, H = 720;

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: ${W}px; height: ${H}px; overflow: hidden; font-family: Inter, sans-serif; color: #e7ecf3;
         background: radial-gradient(800px 380px at 18% 108%, rgba(198,90,46,.30) 0%, rgba(198,90,46,0) 70%),
                     radial-gradient(900px 500px at 85% 15%, #171a21 0%, #0a0b0d 65%); }
  .c { position: absolute; left: 90px; top: 0; height: 100%; width: 1100px; display: flex; flex-direction: column; justify-content: center; }
  .k { font-family: 'JetBrains Mono', monospace; font-size: 15px; letter-spacing: .1em; text-transform: uppercase; color: #d3a84e; margin-bottom: 18px; }
  h1 { font-family: 'Hoefler Text', Baskerville, 'Palatino Linotype', Palatino, Georgia, serif; font-weight: 600; font-size: 66px; line-height: 1.06; }
  h1 b { color: #eecb78; font-weight: 600; }
  p { font-size: 24px; color: #9aa4b4; margin-top: 22px; line-height: 1.4; max-width: 900px; }
  .u { font-family: 'JetBrains Mono', monospace; color: #eecb78; font-size: 24px; margin-top: 34px; }
`;
const card = (k, h, p, u) => `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}</style></head><body>
  <div class="c">${k ? `<div class="k">${k}</div>` : ''}<h1>${h}</h1>${p ? `<p>${p}</p>` : ''}${u ? `<div class="u">${u}</div>` : ''}</div></body></html>`;

// [card html | null, clip name | null, seconds for a card]
const SEQ = [
  [card('Virtastic · freecad-web 1.0', 'FreeCAD 1.1.3,<br>in your <b>browser</b>.', 'The real application, compiled to WebAssembly. Nothing installed, nothing uploaded.'), null, 4],
  [card('A first visit', 'One download,<br>then it is <b>yours</b>.', 'The engine is fetched once and kept in the browser. Return visits fetch nothing.'), 'boot', 3],
  [card('Every workbench', 'All 20 <b>workbenches</b>.', 'Part, PartDesign, Sketcher, Draft, BIM, FEM, CAM, TechDraw, Assembly, Mesh, Spreadsheet and the rest, on first click.'), 'workbenches', 3],
  [card('Real geometry', 'The same <b>OCCT</b> kernel.', 'Booleans and fillets on real solids. A pad measures 8262.4 mm³ against an analytic 8262.4.'), 'engineblock', 3],
  [card('A real project', '42 MB, 34 parts,<br>opened in a <b>tab</b>.', 'Loaded from disk into the browser and orbited with a real mouse.'), 'project-42mb', 3],
  [card('Meshes too', 'An 18 MB <b>STL</b>.', 'Imported and shaded. Opens in about five seconds.'), 'helm-stl', 3],
  [card('Shared sessions', 'Send a link.<br>They get the <b>model</b>.', 'Your units, your theme, your add-ons, in their browser. Read-only until you hand over control.'), 'share-join', 3],
  [card('Open source', 'LGPL. One Docker<br>command to <b>self-host</b>.', 'docker run -d -p 8080:80 ghcr.io/virtastic/freecad-web:1.0.0', 'freecad.virtastic.app · github.com/Virtastic/freecad-web'), null, 6],
];

(async () => {
  fs.mkdirSync(TMP, { recursive: true });
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const p = await b.newPage();
  await p.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  const parts = [];
  let i = 0;
  for (const [html, clip, secs] of SEQ) {
    const png = path.join(TMP, 'card' + i + '.png');
    await p.setContent(html, { waitUntil: 'load', timeout: 120000 });
    await p.evaluate(() => document.fonts.ready);
    await new Promise((r) => setTimeout(r, 300));
    await p.screenshot({ path: png });
    const seg = path.join(TMP, 'card' + i + '.mp4');
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-loop', '1', '-i', png, '-t', String(secs),
      '-vf', `fade=t=in:st=0:d=0.5,fade=t=out:st=${secs - 0.5}:d=0.5,format=yuv420p`,
      '-r', '30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', seg]);
    parts.push(seg);
    if (clip) {
      const src = path.join(DIR, clip + '.mp4');
      const seg2 = path.join(TMP, 'clip' + i + '.mp4');
      // share-join is 45 s of joining; keep the last 14 s (the model arriving and the orbit)
      const trim = clip === 'share-join' ? ['-sseof', '-14'] : [];
      execFileSync('ffmpeg', ['-v', 'error', '-y', ...trim, '-i', src,
        '-vf', `scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,fade=t=in:st=0:d=0.3,format=yuv420p`,
        '-r', '30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-an', seg2]);
      parts.push(seg2);
    }
    i++;
  }
  await b.close();
  const list = path.join(TMP, 'list.txt');
  fs.writeFileSync(list, parts.map((f) => "file '" + f.replace(/\\/g, '/') + "'").join('\n'));
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', OUT]);
  const d = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', OUT]).toString().trim();
  console.log(OUT + ' ' + Math.round(Number(d)) + ' s ' + Math.round(fs.statSync(OUT).size / 1024) + ' KB');
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
