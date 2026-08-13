// Static server for play-gui that mimics the production nginx for the one thing that
// matters here: /FreeCAD.data.gz carries Content-Encoding: gzip, plus COOP/COEP so
// SharedArrayBuffer works. Used to verify the edge-cache URL change before deploying it,
// because a broken data URL is a total outage.
const http = require('http');
const fs = require('fs');
const path = require('path');
// serve an alternate root when testing a candidate build before promoting it
const ROOT = process.argv[2] || path.join(__dirname, '..', 'play-gui');
const PORT = +(process.argv[3] || 8792);
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.wasm': 'application/wasm',
                '.css': 'text/css', '.json': 'application/json', '.png': 'image/png',
                '.webmanifest': 'application/manifest+json' };
http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  const file = path.join(ROOT, url === '/' ? 'index.html' : url);
  fs.readFile(file, (e, buf) => {
    if (e) { res.writeHead(404); return res.end('not found'); }
    const h = {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
      'Cross-Origin-Resource-Policy': 'cross-origin',
      'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream',
    };
    if (file.endsWith('.data.gz')) { h['Content-Encoding'] = 'gzip'; }
    if (file.endsWith('sw.js')) { h['Service-Worker-Allowed'] = '/'; h['Cache-Control'] = 'no-cache'; }
    res.writeHead(200, h);
    res.end(buf);
  });
}).listen(PORT, () => console.log('test server on ' + PORT + ' root=' + ROOT));
