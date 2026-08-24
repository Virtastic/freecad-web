# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Serve a linked FreeCAD artifact with the headers the engine requires.

    python tools/serve-artifact.py <dir> [port]

Cross-origin isolation (COOP same-origin + COEP require-corp) is mandatory: the build is
-pthread, so it needs SharedArrayBuffer, and browsers only expose that to a cross-origin
isolated page. Without these two headers the module fails at startup with no useful message.

FreeCAD.data.gz is served with Content-Encoding: gzip so the browser transparently inflates
it -- the page asks for that name (see the DATA_URL/locateFile pair in freecad-gui.html).

This is the committed twin of the scratch harness in build-artifact-serve/: the boot gate
runs in CI, so the server it depends on cannot live in an ignored directory.
"""
import functools
import http.server
import os
import socketserver
import sys


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def guess_type(self, path):
        if path.endswith('.data.gz'):
            return 'application/octet-stream'
        if path.endswith('.wasm'):
            return 'application/wasm'
        return super().guess_type(path)

    # Same allow-list as infra/nginx.conf. Kept in step deliberately: the gate is meant to
    # prove the APP routes through /proxy correctly, so if the two ever disagree the gate
    # would pass against a proxy production does not have.
    PROXY_HOSTS = {
        'github': 'github.com',
        'api': 'api.github.com',
        'codeload': 'codeload.github.com',
        'raw': 'raw.githubusercontent.com',
        'objects': 'objects.githubusercontent.com',
        'wiki': 'wiki.freecad.org',
        'docs': 'freecad.org',
    }

    def _serve_proxy(self, path):
        """Stand in for nginx's /proxy/<key>/<path> so the gate can exercise the routing."""
        import http.client
        rest = path[len('/proxy/'):]
        key, _, tail = rest.partition('/')
        host = self.PROXY_HOSTS.get(key)
        if host is None:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'proxy: destination not allowed\n')
            return
        try:
            conn = http.client.HTTPSConnection(host, timeout=30)
            conn.request('GET', '/' + tail, headers={'User-Agent': 'fcweb-gate'})
            resp = conn.getresponse()
            body = resp.read(8 * 1024 * 1024)
        except Exception as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(('proxy: %s\n' % exc).encode())
            return
        self.send_response(resp.status)
        self.send_header('Content-Type', resp.getheader('Content-Type', 'application/octet-stream'))
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/proxy/'):
            return self._serve_proxy(self.path.split('?')[0])
        return super().do_GET()

    def send_head(self):
        self._gz = self.path.split('?')[0].endswith('.data.gz')
        return super().send_head()

    def send_response_only(self, code, message=None):
        super().send_response_only(code, message)
        if getattr(self, '_gz', False) and code == 200:
            self.send_header('Content-Encoding', 'gzip')

    def do_POST(self):
        # The shell beacons anonymous counters to /t. Answering 204 keeps a harmless
        # telemetry call from showing up as a red 501 in a gate log, where every error
        # line costs someone time to rule out.
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length:
                self.rfile.read(length)
        except (ValueError, OSError):
            pass
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        # Quiet by default: a 145 MB preload logs a request per range otherwise.
        if os.environ.get('FCWEB_SERVE_VERBOSE'):
            sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else '.'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8791
    handler = functools.partial(Handler, directory=directory)
    with Server(('127.0.0.1', port), handler) as httpd:
        sys.stderr.write('serving %s on http://127.0.0.1:%d (COOP/COEP on)\n'
                         % (os.path.abspath(directory), port))
        sys.stderr.flush()
        httpd.serve_forever()


if __name__ == '__main__':
    main()
