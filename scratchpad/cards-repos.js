// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
// GitHub social preview cards (1280x640) for the other public repos, same look as cards.js.
//   node scratchpad/cards-repos.js [out-dir]
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');
const OUT = process.argv[2] || 'launch/assets/images';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SHOTS = path.resolve('../virtastic-web/public/screenshots');
const img = (n) => 'data:image/' + (n.endsWith('.jpg') ? 'jpeg' : 'webp') + ';base64,' + fs.readFileSync(path.join(SHOTS, n)).toString('base64');
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&family=JetBrains+Mono:wght@500&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 100%; height: 100%; overflow: hidden; }
  body { font-family: Inter, system-ui, sans-serif; background: #0a0b0d; color: #e7ecf3; }
  .card { position: relative; width: 100%; height: 100%; overflow: hidden;
          background: radial-gradient(900px 420px at 18% 108%, rgba(198,90,46,.30) 0%, rgba(198,90,46,0) 70%),
                      radial-gradient(1100px 600px at 85% 15%, #171a21 0%, #0a0b0d 65%); }
  .shot { position: absolute; border-radius: 10px; overflow: hidden;
          box-shadow: 0 30px 80px rgba(0,0,0,.7), 0 0 0 1px rgba(211,168,78,.25); background: #111318; }
  .shot img { display: block; width: 100%; height: 100%; object-fit: cover; object-position: left top; }
  .kicker { font-family: 'JetBrains Mono', monospace; font-weight: 500; letter-spacing: .08em;
            text-transform: uppercase; color: #d3a84e; }
  h1 { font-family: 'Hoefler Text', Baskerville, 'Palatino Linotype', Palatino, Georgia, serif; font-weight: 600; letter-spacing: .005em; line-height: 1.04; }
  h1 b { color: #eecb78; font-weight: 600; }
  p.sub { color: #9aa4b4; font-weight: 400; line-height: 1.35; }
  .url { font-family: 'JetBrains Mono', monospace; color: #eecb78; font-weight: 500; }
  .pill { display: inline-block; border: 1px solid rgba(255,255,255,.18); border-radius: 999px;
          padding: .35em .9em; color: #dfe6ec; font-weight: 500; margin: 0 .4em .5em 0; background: rgba(255,255,255,.04); }
  /* the 3D viewport only: x 27..100%, y 10..93% of a README shot (aspect ~1.43) */
  .vp img { width: 137%; height: 121%; margin-left: -37%; margin-top: -12%; object-fit: fill; }
  .grid { position: absolute; display: grid; gap: 10px; }
  .grid .shot { position: static; }
  .facts { display: grid; gap: 14px; }
  .fact { border-left: 3px solid #d3a84e; padding-left: 14px; }
  .fact .n { font-family: 'Hoefler Text', Baskerville, Georgia, serif; font-weight: 600; color: #eecb78; line-height: 1; }
  .fact .l { color: #9aa4b4; margin-top: 6px; }
`;
const page = (w, h, body) => `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}
  body { width:${w}px; height:${h}px; } .shot img { object-position: center; }</style></head><body><div class="card">${body}</div></body></html>`;
const CARDS = [
  { name: 'github-social-openmw-1280x640', html: `
    <div style="position:absolute;left:70px;top:76px;width:600px">
      <div class="kicker" style="font-size:16px">Virtastic / openmw-web</div>
      <h1 style="font-size:64px;margin-top:18px">Morrowind, in a<br><b>browser tab</b>.</h1>
      <p class="sub" style="font-size:23px;margin-top:22px;width:560px">The open-source OpenMW engine compiled to WebAssembly.
        60 fps on WebGL2, persistent saves, multiplayer since 1.1. Bring your own game data.</p>
      <div class="url" style="font-size:21px;margin-top:30px">morrowind.virtastic.app</div>
    </div>
    <div class="shot" style="left:700px;top:110px;width:540px;height:400px;transform:perspective(1600px) rotateY(-8deg)">
      <img src="${img('openmw-1.webp')}"></div>` },
  { name: 'github-social-ja2-1280x640', html: `
    <div style="position:absolute;left:70px;top:76px;width:600px">
      <div class="kicker" style="font-size:16px">Virtastic / ja2-web</div>
      <h1 style="font-size:64px;margin-top:18px">Jagged Alliance 2,<br>in a <b>browser tab</b>.</h1>
      <p class="sub" style="font-size:23px;margin-top:22px;width:560px">The Stracciatella engine compiled to WebAssembly: the full campaign
        and tactical combat, playing off your own copy of the game.</p>
      <div class="url" style="font-size:21px;margin-top:30px">ja2.virtastic.app</div>
    </div>
    <div class="shot" style="left:700px;top:110px;width:540px;height:400px;transform:perspective(1600px) rotateY(-8deg)">
      <img src="${img('ja2-combat.webp')}"></div>` },
];
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 640, deviceScaleFactor: 1 });
  for (const c of CARDS) {
    await p.setContent(page(1280, 640, c.html), { waitUntil: 'load', timeout: 120000 });
    await p.evaluate(() => document.fonts.ready); await new Promise((r) => setTimeout(r, 300));
    const f = path.join(OUT, c.name + '.png'); await p.screenshot({ path: f });
    console.log(c.name + ' (' + Math.round(fs.statSync(f).size / 1024) + ' KB)');
  }
  await b.close();
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
