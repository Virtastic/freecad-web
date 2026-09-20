// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// Social cards for the release: HTML templates photographed at the exact pixel size each
// platform wants, built from the README screenshots (docs/images) so nothing on a card is
// a mock-up. Every number on a card is a README number.
//
//   CHROME_PATH=... node scratchpad/cards.js [out-dir]
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const OUT = process.argv[2] || 'launch/assets/images';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const IMG = path.resolve('docs/images');
const img = (n) => 'data:image/png;base64,' + fs.readFileSync(path.join(IMG, n)).toString('base64');

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

const page = (w, h, body, extra) => `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}
  body { width:${w}px; height:${h}px; } ${extra || ''}</style></head><body><div class="card">${body}</div></body></html>`;

const CARDS = [
  // Open Graph / link preview (website, Reddit, Mastodon, Bluesky, LinkedIn all read this size)
  { name: 'og-1200x630', w: 1200, h: 630, html: `
    <div style="position:absolute;left:64px;top:70px;width:560px">
      <div class="kicker" style="font-size:16px">Virtastic · freecad-web 1.0</div>
      <h1 style="font-size:66px;margin-top:18px">FreeCAD 1.1.3,<br>in your <b>browser</b>.</h1>
      <p class="sub" style="font-size:24px;margin-top:22px;width:520px">The real application, compiled to WebAssembly.
        Every workbench, the same solvers. No install, no account.</p>
      <div class="url" style="font-size:22px;margin-top:34px">freecad.virtastic.app</div>
    </div>
    <div class="shot vp" style="left:640px;top:130px;width:520px;height:364px;transform:perspective(1600px) rotateY(-8deg)">
      <img src="${img('project-42mb.png')}"></div>` },

  // GitHub repository social preview
  { name: 'github-social-1280x640', w: 1280, h: 640, html: `
    <div style="position:absolute;left:70px;top:76px;width:600px">
      <div class="kicker" style="font-size:16px">Virtastic / freecad-web</div>
      <h1 style="font-size:64px;margin-top:18px">FreeCAD, compiled<br>to <b>WebAssembly</b>.</h1>
      <p class="sub" style="font-size:23px;margin-top:22px;width:560px">wasm64 · JSPI · Qt 6 · CPython · OCCT · Coin3D ·
        Gmsh and CalculiX in the tab. An 18 MB STL opens in five seconds. LGPL, one Docker command to self-host.</p>
      <div class="url" style="font-size:24px;margin-top:30px">freecad.virtastic.app</div>
    </div>
    <div class="shot vp" style="left:700px;top:130px;width:540px;height:378px;transform:perspective(1600px) rotateY(-8deg)">
      <img src="${img('helm-stl.png')}" style="width:240%;height:212%;margin-left:-88%;margin-top:-52%"></div>` },

  // 16:9 post image (X, Bluesky, LinkedIn, Mastodon)
  { name: 'post-1600x900', w: 1600, h: 900, html: `
    <div style="position:absolute;left:80px;top:90px;width:700px">
      <div class="kicker" style="font-size:18px">freecad-web 1.0 · open source</div>
      <h1 style="font-size:84px;margin-top:20px">FreeCAD<br>in a <b>tab</b>.</h1>
      <p class="sub" style="font-size:28px;margin-top:26px;width:640px">Not a viewer. Not a remote desktop.
        Upstream FreeCAD 1.1.3 running locally in Chrome or Edge.</p>
      <div style="margin-top:34px;font-size:20px">
        <span class="pill">20 workbenches</span><span class="pill">FEM solves in-browser</span>
        <span class="pill">Share by link</span><span class="pill">MCP for AI assistants</span></div>
      <div class="url" style="font-size:26px;margin-top:30px">freecad.virtastic.app</div>
    </div>
    <div class="shot vp" style="left:860px;top:180px;width:660px;height:462px;transform:perspective(1800px) rotateY(-9deg)">
      <img src="${img('bim.png')}"></div>` },

  // Square (Mastodon, Instagram, LinkedIn carousel)
  { name: 'square-1080x1080', w: 1080, h: 1080, html: `
    <div style="position:absolute;left:70px;top:70px;width:940px">
      <div class="kicker" style="font-size:17px">freecad-web 1.0</div>
      <h1 style="font-size:76px;margin-top:16px">FreeCAD 1.1.3,<br>in your <b>browser</b>.</h1>
      <p class="sub" style="font-size:26px;margin-top:20px;width:860px">The real application, compiled to WebAssembly.
        No install, no account. Your files never leave the tab.</p>
    </div>
    <div class="shot vp" style="left:70px;top:400px;width:940px;height:600px">
      <img src="${img('partdesign.png')}"></div>
    <div class="url" style="position:absolute;left:70px;bottom:40px;font-size:24px;
         background:#0f1419;padding:8px 14px;border-radius:8px">freecad.virtastic.app</div>` },

  // Profile / header banner (X 1500x500, Bluesky 3:1)
  { name: 'banner-1500x500', w: 1500, h: 500, html: `
    <div style="position:absolute;left:70px;top:110px;width:640px">
      <h1 style="font-size:58px">FreeCAD in the <b>browser</b>.</h1>
      <p class="sub" style="font-size:22px;margin-top:16px">Compiled to WebAssembly. Every workbench, every solver, no install.</p>
      <div class="url" style="font-size:22px;margin-top:22px">freecad.virtastic.app</div>
    </div>
    <div class="grid" style="left:760px;top:40px;grid-template-columns:1fr 1fr;width:720px">
      <div class="shot" style="height:200px"><img src="${img('fem.png')}"></div>
      <div class="shot" style="height:200px"><img src="${img('assembly.png')}"></div>
      <div class="shot" style="height:200px"><img src="${img('archdetail.png')}"></div>
      <div class="shot" style="height:200px"><img src="${img('helm-stl.png')}"></div>
    </div>` },

  // Vertical (stories, shorts thumbnails)
  { name: 'story-1080x1920', w: 1080, h: 1920, html: `
    <div style="position:absolute;left:80px;top:160px;width:920px">
      <div class="kicker" style="font-size:20px">freecad-web 1.0</div>
      <h1 style="font-size:104px;margin-top:22px">FreeCAD<br>in your<br><b>browser</b>.</h1>
      <p class="sub" style="font-size:34px;margin-top:30px">The real FreeCAD 1.1.3, compiled to WebAssembly. No install.</p>
    </div>
    <div class="shot vp" style="left:80px;top:840px;width:920px;height:643px">
      <img src="${img('engineblock.png')}"></div>
    <div class="url" style="position:absolute;left:80px;top:1700px;font-size:38px">freecad.virtastic.app</div>` },

  // The eight README shots, one frame
  { name: 'workbench-grid-1600x900', w: 1600, h: 900, html: `
    <div class="grid" style="left:40px;top:40px;width:1520px;grid-template-columns:repeat(4,1fr)">
      ${['partdesign', 'engineblock', 'bim', 'archdetail', 'fem', 'assembly', 'draft', 'helm-stl']
        .map((n) => `<div class="shot" style="height:335px"><img src="${img(n + '.png')}"></div>`).join('')}
    </div>
    <div style="position:absolute;left:40px;bottom:36px;right:40px;display:flex;justify-content:space-between;align-items:baseline">
      <div style="font-size:30px;font-weight:800;letter-spacing:-.02em">Every one of these opened in the browser.</div>
      <div class="url" style="font-size:24px">freecad.virtastic.app</div>
    </div>` },

  // Numbers card
  { name: 'facts-1600x900', w: 1600, h: 900, html: `
    <div style="position:absolute;left:90px;top:90px;width:700px">
      <div class="kicker" style="font-size:18px">Measured on the shipped build</div>
      <h1 style="font-size:64px;margin-top:18px">Not a demo.<br>Not a <b>subset</b>.</h1>
      <div class="facts" style="margin-top:44px;font-size:22px">
        <div class="fact"><div class="n" style="font-size:52px">20 / 20</div><div class="l">workbenches activate on first click</div></div>
        <div class="fact"><div class="n" style="font-size:52px">~500</div><div class="l">of FreeCAD's own unit tests pass</div></div>
        <div class="fact"><div class="n" style="font-size:52px">&lt; 1%</div><div class="l">CalculiX FEM results vs beam theory, solved in the tab</div></div>
        <div class="fact"><div class="n" style="font-size:52px">42 MB</div><div class="l">real project, 34 top-level parts, opened from the browser</div></div>
      </div>
    </div>
    <div class="shot vp" style="left:880px;top:200px;width:640px;height:448px;transform:perspective(1800px) rotateY(-9deg)">
      <img src="${img('fem.png')}"></div>` },

  // Sharing card
  { name: 'sharing-1600x900', w: 1600, h: 900, html: `
    <div style="position:absolute;left:90px;top:90px;width:680px">
      <div class="kicker" style="font-size:18px">Shared sessions</div>
      <h1 style="font-size:66px;margin-top:18px">Send a link.<br>They get the <b>model</b>.</h1>
      <p class="sub" style="font-size:26px;margin-top:24px">Same document, same units, same add-ons, in their own browser.
        One person edits, everyone else watches live. No install, no account, no version to match.</p>
    </div>
    <div class="shot" style="left:820px;top:70px;width:720px;height:380px"><img src="${img('share-general.png')}"></div>
    <div class="shot" style="left:900px;top:430px;width:720px;height:400px"><img src="${img('share-viewer.png')}"></div>` },

  // MCP card
  { name: 'mcp-1600x900', w: 1600, h: 900, html: `
    <div style="position:absolute;left:90px;top:90px;width:680px">
      <div class="kicker" style="font-size:18px">Model Context Protocol</div>
      <h1 style="font-size:66px;margin-top:18px">Let an AI<br>drive <b>FreeCAD</b>.</h1>
      <p class="sub" style="font-size:26px;margin-top:24px">One URL from Preferences. Claude Code, Codex or any MCP client sees
        the tree, the properties, the selection and the view, and runs every GUI command. Off until you press Enable.</p>
    </div>
    <div class="shot" style="left:840px;top:110px;width:760px;height:680px;transform:perspective(1800px) rotateY(-9deg)">
      <img src="${img('share-mcp.png')}"></div>` },

  // What runs where
  { name: 'architecture-1600x900', w: 1600, h: 900, html: `
    <div style="position:absolute;left:90px;top:80px;width:1420px">
      <div class="kicker" style="font-size:18px">What runs where</div>
      <h1 style="font-size:60px;margin-top:16px">The server hands out files.<br>Your tab does <b>everything else</b>.</h1>
    </div>
    <div style="position:absolute;left:90px;top:330px;width:1420px;display:grid;grid-template-columns:1fr 90px 1.5fr;gap:0;align-items:center">
      <div style="border:1px solid rgba(255,255,255,.15);border-radius:14px;padding:30px;background:rgba(255,255,255,.03)">
        <div class="kicker" style="font-size:15px;color:#9fb0c0">Server (nginx)</div>
        <div style="font-size:30px;font-weight:700;margin-top:12px">Static files</div>
        <p class="sub" style="font-size:20px;margin-top:12px">FreeCAD.wasm, FreeCAD.js, FreeCAD.data. Cached for a year.
          Nothing computed, nothing rendered, nothing stored.</p>
        <p class="sub" style="font-size:18px;margin-top:14px;color:#8fa0b0">Optional: one small session container, only if you share a link.</p>
      </div>
      <div style="text-align:center;font-size:44px;color:#d3a84e">→</div>
      <div style="border:1px solid #d3a84e;border-radius:14px;padding:30px;background:rgba(211,168,78,.06)">
        <div class="kicker" style="font-size:15px">Your browser tab</div>
        <div style="font-size:30px;font-weight:700;margin-top:12px">All of FreeCAD</div>
        <p class="sub" style="font-size:20px;margin-top:12px">Qt 6 · OCCT geometry kernel · Coin3D on WebGL · CPython with
          every Python workbench · Gmsh · CalculiX. Your documents autosave to browser storage and never leave the machine.</p>
      </div>
    </div>
    <div class="url" style="position:absolute;left:90px;bottom:60px;font-size:24px">freecad.virtastic.app · github.com/Virtastic/freecad-web</div>` },
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const p = await b.newPage();
  for (const c of CARDS) {
    await p.setViewport({ width: c.w, height: c.h, deviceScaleFactor: 1 });
    await p.setContent(page(c.w, c.h, c.html), { waitUntil: 'load', timeout: 120000 });
    await p.evaluate(() => document.fonts.ready);
    await new Promise((r) => setTimeout(r, 300));
    const f = path.join(OUT, c.name + '.png');
    await p.screenshot({ path: f });
    console.log(c.name + ' -> ' + f + ' (' + Math.round(fs.statSync(f).size / 1024) + ' KB)');
  }
  await b.close();
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
