# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""`requests` in the browser build, over a synchronous XMLHttpRequest.

Add-ons written for a desktop use `requests` (the Lens add-on's whole API client is
requests.get/post/patch/delete against api.lens.freecad.org, and its InitGui.py calls
requests.get at startup). `requests` opens sockets, and there are none under emscripten;
urllib is no better here (the SSL module is a stub).

The transport has to block WITHOUT suspending: under JSPI only a promising export may
suspend, and FreeCAD's Mod loop, where InitGui.py runs, is not one -- a QEventLoop wait
there killed the interpreter (measured 2026-09-22). A synchronous XMLHttpRequest is the
browser's one blocking network primitive, and the emscripten filesystem is Python's one
synchronous channel to JS, so the page registers a character device, /dev/fcweb-http,
whose read op performs the XHR (freecad-gui.html, __fcHttpDeviceInstall).

So this module replaces requests.Session.send with one that writes the prepared request
to the device and turns the answer into a genuine requests.Response (status, headers,
body, url, elapsed), so `.json()`, `.status_code`, `raise_for_status()` and friends all
behave. Everything above the transport (auth flow, sessions, JSON encoding, multipart)
is requests' own code.

Cross-origin: the browser applies CORS to every call. A server that answers preflight
with Access-Control-Allow-Origin (api.lens.freecad.org does, with `*`, and allows the
authorization header) works directly with the user's token never leaving their tab;
one that does not fails with a connection error, which requests' callers already
handle. Hosts in NetworkManager.FCWEB_PROXY_HOSTS are rewritten onto /proxy so the
GitHub API keeps working for add-ons that call it through requests.

Not touched on a desktop (sys.platform check). `requests` itself is installed on demand
as a pure wheel through fcweb_wheels when an add-on declares it. urllib3's Pyodide
backend, which would break the import here, is disarmed in sitecustomize.py because that
has to happen before an add-on's InitGui.py runs.
"""

import sys
import time


def _proxy_rewrite(url):
    try:
        import NetworkManager
        return NetworkManager.fcweb_proxy_url(url)
    except Exception:
        return url


DEVICE = "/dev/fcweb-http"


def device_send(prepared, timeout=None, stream=False):
    """Send a requests.PreparedRequest through /dev/fcweb-http; return a requests.Response.

    One JSON document out, one back. The device (freecad-gui.html, __fcHttpDeviceInstall)
    performs a synchronous XMLHttpRequest inside its read op, so this blocks exactly the
    way requests blocks on a desktop and needs no event loop and no suspension -- it is
    safe from an add-on's InitGui.py, from a click, from a timer. Bodies travel base64."""
    import base64
    import json
    import os
    import requests
    from requests.structures import CaseInsensitiveDict
    from requests.utils import get_encoding_from_headers

    url = _proxy_rewrite(prepared.url)   # a root-relative /proxy URL is fine for XMLHttpRequest
    body = prepared.body
    if isinstance(body, str):
        body = body.encode("utf-8")
    headers = {}
    for k, v in (prepared.headers or {}).items():
        # the browser owns these; XMLHttpRequest refuses them with a console warning
        if k.lower() in ("content-length", "host", "connection", "accept-encoding", "user-agent"):
            continue
        headers[k] = v.decode("latin-1") if isinstance(v, bytes) else str(v)
    payload = json.dumps({
        "method": (prepared.method or "GET").upper(),
        "url": url,
        "headers": headers,
        "body": base64.b64encode(body).decode("ascii") if body else None,
    }).encode("utf-8")

    t0 = time.time()
    try:
        fd = os.open(DEVICE, os.O_RDWR)
    except OSError as e:
        raise requests.exceptions.ConnectionError("%s is not available (%s)" % (DEVICE, e))
    try:
        os.write(fd, payload)
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    res = json.loads(b"".join(chunks).decode("utf-8"))

    if not res.get("status"):
        # No HTTP status at all: DNS, CORS refusal, network down. The browser console has
        # the real reason; requests' callers see a connection error, as on a desktop.
        raise requests.exceptions.ConnectionError(
            "no response from %s (%s). If this is a cross-origin API, its server must "
            "answer CORS preflight; see the browser console." % (url, res.get("error", "")))

    resp = requests.Response()
    resp.status_code = int(res["status"])
    resp.reason = res.get("reason") or ""
    hdrs = CaseInsensitiveDict()
    for line in (res.get("headers") or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            hdrs[k.strip()] = v.strip()
    resp.headers = hdrs
    resp.encoding = get_encoding_from_headers(hdrs)
    resp._content = base64.b64decode(res.get("body") or "")
    resp._content_consumed = True
    resp.url = res.get("url") or prepared.url
    resp.request = prepared
    resp.elapsed = __import__("datetime").timedelta(seconds=time.time() - t0)
    resp.raw = None
    return resp


def install():
    """Route every requests.Session.send through the device. Idempotent; a no-op on a desktop."""
    if sys.platform != "emscripten":
        return "fcweb_requests: not emscripten, left alone"
    try:
        import requests
    except ImportError:
        return "fcweb_requests: requests not installed yet (hooked when an add-on brings it)"
    return _hook(requests)


def _hook(requests):
    from requests.sessions import Session
    if getattr(Session, "_fcweb_hooked", False):
        return "requests -> /dev/fcweb-http (already)"
    orig = Session.send

    def send(self, request, **kwargs):
        # Cookies, hooks and history handling are requests' own; only the wire moves.
        resp = device_send(request, timeout=kwargs.get("timeout"), stream=kwargs.get("stream", False))
        for hook in (request.hooks or {}).get("response", []):
            r = hook(resp, **kwargs)
            if r is not None:
                resp = r
        try:
            self.cookies.extract_cookies(_CookieJarResponse(resp), _CookieJarRequest(request))
        except Exception:
            pass
        return resp

    Session.send = send
    Session._fcweb_hooked = True
    Session._fcweb_orig_send = orig
    return "requests -> /dev/fcweb-http"


class _CookieJarRequest:
    def __init__(self, req):
        self._r = req

    def get_full_url(self):
        return self._r.url

    def get_host(self):
        from urllib.parse import urlsplit
        return urlsplit(self._r.url).netloc

    def get_type(self):
        return "https"

    def unverifiable(self):
        return True

    def has_header(self, name):
        return name in self._r.headers

    def get_header(self, name, default=None):
        return self._r.headers.get(name, default)

    def add_unredirected_header(self, name, value):
        self._r.headers[name] = value

    def get_origin_req_host(self):
        return self.get_host()

    is_unverifiable = unverifiable
    origin_req_host = property(get_origin_req_host)
    host = property(get_host)


class _CookieJarResponse:
    def __init__(self, resp):
        self._h = resp.headers

    def info(self):
        return self

    def get_all(self, name, default=None):
        v = self._h.get(name)
        return [v] if v is not None else (default or [])


def install_import_hook():
    """Hook `requests` the moment it is imported, from wherever (an add-on's InitGui.py
    at startup, the Addon Manager later). Called by sitecustomize.py, so it runs before
    FreeCAD's Mod loop. A meta-path finder that wraps the real loader of
    requests.sessions and applies the hook after the module executes."""
    if sys.platform != "emscripten":
        return
    import importlib.abc

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name != "requests.sessions":
                return None
            spec = None
            for finder in sys.meta_path:
                if finder is self or not hasattr(finder, "find_spec"):
                    continue
                spec = finder.find_spec(name, path, target)
                if spec is not None:
                    break
            if spec is None or spec.loader is None:
                return None
            loader = spec.loader
            orig_exec = loader.exec_module

            def exec_module(module):
                orig_exec(module)
                try:
                    import requests
                    print("[fcweb] " + _hook(requests))
                except Exception as e:
                    print("[fcweb] requests hook failed: %r" % (e,))

            loader.exec_module = exec_module
            return spec

    if not any(isinstance(f, _Finder) for f in sys.meta_path):
        sys.meta_path.insert(0, _Finder())


if __name__ == "__main__":
    # Desktop check of the parts that need no browser: the cookie-jar shims and hook
    # idempotence against a stub Session. The transport itself is measured in the engine
    # by scratchpad/lens.js.
    class _S:
        def __init__(self):
            self.headers = {"X": "1"}
            self.url = "https://api.example/x"
    r = _CookieJarRequest(_S())
    assert r.get_host() == "api.example" and r.has_header("X") and r.get_header("X") == "1"
    class _R:
        headers = {"Set-Cookie": "a=b"}
    assert _CookieJarResponse(_R()).info().get_all("Set-Cookie") == ["a=b"]
    assert _CookieJarResponse(_R()).get_all("Nope") == []
    try:
        import requests
        from requests.sessions import Session
        before = Session.send
        note = _hook(requests)
        assert "fcweb-http" in note and Session.send is not before
        assert _hook(requests) == "requests -> /dev/fcweb-http (already)"
        Session.send = before; Session._fcweb_hooked = False
    except ImportError:
        print("(requests not installed here; hook test skipped)")
    print("fcweb_requests self-check ok")
