// Static server for play-gui that mimics the production nginx for the things that
// matter here: /FreeCAD.data.gz carries Content-Encoding: gzip, COOP/COEP so
// SharedArrayBuffer works, and /proxy/<key>/<path> forwards to the same fixed host map
// as infra/nginx.conf (GET only, same keys) so the Addon Manager's catalogue, add-on
// installs and the PyPI wheel path can be driven against the raw tree without an image
// build. Used to verify page-side changes before deploying them, because a broken data
// URL or proxy key is a total outage.
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
// serve an alternate root when testing a candidate build before promoting it
const ROOT = process.argv[2] || path.join(__dirname, '..', 'play-gui');
const PORT = +(process.argv[3] || 8792);
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.wasm': 'application/wasm',
                '.css': 'text/css', '.json': 'application/json', '.png': 'image/png',
                '.py': 'text/x-python', '.ui': 'application/xml',
                '.webmanifest': 'application/manifest+json' };
// Mirror of the `map $fcproxy_key $fcproxy_host` block in infra/nginx.conf. Keep in sync.
const PROXY = {
  github: 'github.com', api: 'api.github.com', codeload: 'codeload.github.com',
  raw: 'raw.githubusercontent.com', objects: 'objects.githubusercontent.com',
  wiki: 'wiki.freecad.org', docs: 'www.freecad.org', docswww: 'www.freecad.org',
  addons: 'addons.freecad.org', pypi: 'pypi.org', pyfiles: 'files.pythonhosted.org',
};
const ISO = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
  'Cross-Origin-Resource-Policy': 'cross-origin',
};

function proxy(req, res, key, rest, hops) {
  const host = PROXY[key];
  if (!host) { res.writeHead(403, ISO); return res.end('proxy: destination not allowed\n'); }
  if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405, ISO); return res.end(); }
  const up = https.request({ host, path: '/' + rest, method: req.method,
    headers: { 'user-agent': 'freecad-web testserver', accept: req.headers.accept || '*/*' } }, (r) => {
    // Follow redirects the way nginx's proxy_redirect map does for the hosts we know.
    if ([301, 302, 303, 307, 308].includes(r.statusCode) && r.headers.location && (hops || 0) < 5) {
      try {
        const u = new URL(r.headers.location, 'https://' + host);
        const k = Object.keys(PROXY).find((kk) => PROXY[kk] === u.host);
        r.resume();
        if (k) return proxy(req, res, k, u.pathname.slice(1) + u.search, (hops || 0) + 1);
      } catch (e) { /* fall through to the raw response */ }
    }
    const h = Object.assign({}, ISO, { 'content-type': r.headers['content-type'] || 'application/octet-stream' });
    if (r.headers['content-length']) h['content-length'] = r.headers['content-length'];
    res.writeHead(r.statusCode, h);
    r.pipe(res);
  });
  up.on('error', (e) => { res.writeHead(502, ISO); res.end('proxy: ' + e.message + '\n'); });
  up.end();
}

http.createServer((req, res) => {
  const m = /^\/proxy\/([a-z]+)\/(.*)$/.exec(req.url);
  if (m) return proxy(req, res, m[1], m[2]);
  if (req.url.startsWith('/t?')) { res.writeHead(204, ISO); return res.end(); }
  const url = req.url.split('?')[0];
  // FCJS_OVERRIDE serves an instrumented FreeCAD.js in place of the shipped one, so the
  // engine's own GL glue can be counted without a 2 h relink (scratchpad/glinstrument.js).
  const file = (process.env.FCJS_OVERRIDE && url === '/FreeCAD.js')
    ? process.env.FCJS_OVERRIDE
    : path.join(ROOT, url === '/' ? 'index.html' : url);
  fs.readFile(file, (e, buf) => {
    if (e) { res.writeHead(404); return res.end('not found'); }
    const h = Object.assign({}, ISO, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    if (file.endsWith('.data.gz')) { h['Content-Encoding'] = 'gzip'; }
    if (file.endsWith('sw.js')) { h['Service-Worker-Allowed'] = '/'; h['Cache-Control'] = 'no-cache'; }
    res.writeHead(200, h);
    res.end(buf);
  });
}).listen(PORT, () => console.log('test server on ' + PORT + ' root=' + ROOT));
