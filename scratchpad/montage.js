// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// The launch video: title cards (HTML photographed at 1280x720) cut between the real clips
// from scratchpad/clips.js. No narration; every card is a README sentence. ~98 s.
// VERTICAL=1 makes the 9:16 short for Reels / TikTok / Shorts instead (~35 s): clips are
// scaled to full height and centre-cropped, which keeps the model and drops the panels.
//
//   node scratchpad/montage.js [clips-dir] [out.mp4]
//   VERTICAL=1 node scratchpad/montage.js launch/assets/clips launch/assets/clips/launch-short.mp4
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const puppeteer = require('puppeteer-core');

const DIR = process.argv[2] || 'launch/assets/clips';
const OUT = process.argv[3] || 'launch/assets/clips/launch-montage.mp4';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const TMP = path.join(process.env.TEMP || '/tmp', 'fc-montage');
const V = !!process.env.VERTICAL;
const NLN = String.fromCharCode(10);
const W = V ? 1080 : 1280, H = V ? 1920 : 720;

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: ${W}px; height: ${H}px; overflow: hidden; font-family: Inter, sans-serif; color: #e7ecf3;
         background: radial-gradient(800px 380px at 18% 108%, rgba(198,90,46,.30) 0%, rgba(198,90,46,0) 70%),
                     radial-gradient(900px 500px at 85% 15%, #171a21 0%, #0a0b0d 65%); }
  .c { position: absolute; left: ${V ? 80 : 90}px; top: 0; height: 100%; width: ${V ? 920 : 1100}px; display: flex; flex-direction: column; justify-content: center; }
  .k { font-family: 'JetBrains Mono', monospace; font-size: 15px; letter-spacing: .1em; text-transform: uppercase; color: #d3a84e; margin-bottom: 18px; }
  h1 { font-family: 'Hoefler Text', Baskerville, 'Palatino Linotype', Palatino, Georgia, serif; font-weight: 600; font-size: ${V ? 96 : 66}px; line-height: 1.06; }
  h1 b { color: #eecb78; font-weight: 600; }
  p { font-size: ${V ? 36 : 24}px; color: #9aa4b4; margin-top: 22px; line-height: 1.4; max-width: 900px; }
  .u { font-family: 'JetBrains Mono', monospace; color: #eecb78; font-size: ${V ? 34 : 24}px; margin-top: 34px; }
`;
// Over every clip: a lower-third naming what is on screen, and the wordmark with the URL.
const LOGO = 'data:image/png;base64,' + fs.readFileSync(path.resolve('../virtastic-web/public/logo.png')).toString('base64');
const overlay = (cap) => `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}
  body { background: transparent; }
  .lt { position: absolute; left: ${V ? 40 : 40}px; bottom: ${V ? 220 : 44}px; max-width: ${V ? 1000 : 820}px;
        background: rgba(10,11,13,.78); border-left: 3px solid #d3a84e; border-radius: 6px;
        padding: ${V ? '18px 26px' : '12px 18px'}; font-size: ${V ? 34 : 22}px; color: #e7ecf3; font-weight: 500; line-height: 1.3; }
  .wm { position: absolute; right: ${V ? 40 : 36}px; top: ${V ? 60 : 24}px; display: flex; align-items: center; gap: 12px;
        background: rgba(10,11,13,.6); border-radius: 8px; padding: ${V ? '12px 18px' : '8px 12px'}; }
  .wm img { height: ${V ? 44 : 28}px; }
  .wm span { font-family: 'JetBrains Mono', monospace; color: #eecb78; font-size: ${V ? 26 : 17}px; }
</style></head><body>
  <div class="wm"><img src="${LOGO}"><span>freecad.virtastic.app</span></div>
  ${cap ? `<div class="lt">${cap}</div>` : ''}
</body></html>`;

const card = (k, h, p, u) => `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}</style></head><body>
  <div class="c">${k ? `<div class="k">${k}</div>` : ''}<h1>${h}</h1>${p ? `<p>${p}</p>` : ''}${u ? `<div class="u">${u}</div>` : ''}</div></body></html>`;

// [card html | null, clip name | null, seconds for a card (0 = no card), caption over the clip, ffmpeg trim args]
const SEQ = [
  [card('Virtastic · freecad-web 1.0', 'FreeCAD 1.1.3,<br>in your <b>browser</b>.', 'The real application, compiled to WebAssembly. Nothing installed, nothing uploaded.'), null, 4],
  [card('A first visit', 'One download,<br>then it is <b>yours</b>.', 'The engine is fetched once and kept in the browser. Return visits fetch nothing.'), 'boot', 3, 'A first visit on a fresh profile · Ready in 24 s · 2x speed'],
  [card('Every workbench', 'All 20 <b>workbenches</b>.', 'The same ones desktop FreeCAD ships. Nine of them, each with the example it is for.'), 'wb-partdesign', 3, 'Part Design · pads, pockets and sketches on a body'],
  [null, 'wb-sketcher', 0, 'Sketcher · a constrained sketch in edit mode'],
  [null, 'wb-part', 0, 'Part · booleans and fillets on the EngineBlock'],
  [null, 'wb-assembly', 0, 'Assembly · 54 objects with joints'],
  [null, 'wb-draft', 0, 'Draft · 113 wires, arcs, dimensions and text, seen from the top'],
  [null, 'wb-bim', 0, 'BIM · 361 objects: walls, windows, a site, a section plane'],
  [null, 'wb-fem', 0, 'FEM · a CalculiX result, solved in the tab'],
  [null, 'wb-techdraw', 0, 'TechDraw · an A4 drawing sheet with a section and dimensions'],
  [null, 'wb-mesh', 0, 'Mesh · an 18 MB STL'],
  [card('Real geometry', 'The same <b>OCCT</b> kernel.', 'Booleans and fillets on real solids. A pad measures 8262.4 mm³ against an analytic 8262.4.'), 'engineblock', 3, 'EngineBlock, 36 objects · opened in 6 s · orbited with a real mouse'],
  [card('A real project', '42 MB, 34 parts,<br>opened in a <b>tab</b>.', 'Loaded from disk into the browser and orbited with a real mouse.'), 'project-42mb', 3, '42 MB a2plus assembly, 34 top-level parts · opened in 21 s'],
  [card('Shared sessions', 'Send a link.<br>They get the <b>model</b>.', 'Edit → Share Session…, press Start sharing, copy the link. Your units, your theme, your add-ons travel with it.'), 'share-owner', 3, 'Edit → Share Session… · Start sharing · the link appears · Copy', ['-t', '15']],
  [null, 'share-join', 0, 'A visitor opens the link · types a name · gets the model read-only in their own browser', ['-sseof', '-12']],
  [null, 'share-owner', 0, 'Back with the owner: the Session page, who is here and who is editing', ['-sseof', '-7']],
  [card('MCP', 'Let an AI<br>drive <b>FreeCAD</b>.', 'Preferences → Sharing → MCP. Enable assistant mints one URL. Claude Code, Codex or any MCP client sees the tree, the properties, the views, and runs every command.'), 'mcp', 3, 'MCP page · Enable assistant · the URL is minted · copy the Claude Code command'],
  [card('Open source', 'LGPL. One Docker<br>command to <b>self-host</b>.', 'docker run -d -p 8080:80 ghcr.io/virtastic/freecad-web:1.0.0', 'freecad.virtastic.app · github.com/Virtastic/freecad-web'), null, 6],
];

// The short keeps the beats a phone screen can carry.
const KEEP = new Set([null, 'wb-partdesign', 'wb-sketcher', 'wb-fem', 'project-42mb', 'share-owner', 'share-join', 'mcp']);
const SHORT = SEQ.filter(([h, c], i) => (KEEP.has(c) && !(c === 'share-owner' && i === SEQ.length - 3)) || i === 0 || i === SEQ.length - 1)
  .filter(([h, c]) => !(c === null && h && h.indexOf('A first visit') >= 0))
  .map(([h, c, t, cap, tr], i, a) => [h, c, h ? (i === a.length - 1 ? 4 : 3) : 0, cap, tr]);
(async () => {
  fs.mkdirSync(TMP, { recursive: true });
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const p = await b.newPage();
  await p.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  const parts = [];
  let i = 0, at = 0;
  const chapters = [];
  for (const [html, clip, secs, cap, tr] of (V ? SHORT : SEQ)) {
    if (html) {
      chapters.push(Math.round(at) + ' ' + html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').match(/<h1>?([^]*?)(?:\.|$)/) ? '' : '');
      chapters[chapters.length - 1] = String(Math.floor(at / 60)) + ':' + String(Math.floor(at % 60)).padStart(2, '0') + ' ' +
        (html.match(/<h1>(.*?)<\/h1>/) || ['', ''])[1].replace(/<[^>]+>/g, '');
      at += secs;
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
    }
    if (clip) {
      const src = path.join(DIR, clip + '.mp4');
      const seg2 = path.join(TMP, 'clip' + i + '.mp4');
      // share-join is 45 s of joining; keep the last 14 s (the model arriving and the orbit)
      const trim = tr ? tr : (V ? ['-t', '8'] : []);
      // Vertical: a model clip is scaled to full height and centre-cropped (the model is in
      // the middle of the 3D view). A dialog clip is framed on the Preferences dialog instead,
      // x 340..1460 of the 1600-wide recording, scaled so the dialog spans the phone's width.
      const dialog = clip === 'share-owner' || clip === 'mcp';
      const fit = !V ? `scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2`
        : dialog ? `scale=1543:-2,crop=1080:868:328:0,pad=${W}:${H}:0:(oh-ih)/2`
        : `scale=-2:${H},crop=${W}:${H}`;
      const ov = path.join(TMP, 'ov' + i + '.png');
      await p.setContent(overlay(cap), { waitUntil: 'load', timeout: 120000 });
      await p.evaluate(() => document.fonts.ready);
      await new Promise((r) => setTimeout(r, 200));
      await p.screenshot({ path: ov, omitBackground: true });
      execFileSync('ffmpeg', ['-v', 'error', '-y', ...trim, '-i', src, '-i', ov,
        '-filter_complex', `[0:v]${fit}[v];[v][1:v]overlay=0:0,fade=t=in:st=0:d=0.3,format=yuv420p`,
        '-r', '30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-an', seg2]);
      parts.push(seg2);
      at += Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', seg2]).toString().trim());
    }
    i++;
  }
  await b.close();
  const list = path.join(TMP, 'list.txt');
  fs.writeFileSync(list, parts.map((f) => "file '" + f.replace(/\\/g, '/') + "'").join('\n'));
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', OUT]);
  const d = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', OUT]).toString().trim();
  console.log(OUT + ' ' + Math.round(Number(d)) + ' s ' + Math.round(fs.statSync(OUT).size / 1024) + ' KB');
  console.log('chapters:' + NLN + chapters.join(NLN));
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
