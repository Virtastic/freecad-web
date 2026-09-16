#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""The session container's HTTP process.

    uvicorn app:app --host 0.0.0.0 --port 8000

Three things, one process:
  * /share/* and /api/*  -> share.handle(), the transport-agnostic core, in a thread
                            (the relay's /cmd long-polls for up to 25 s and must not block
                            the event loop).
  * /mcp/<id>/<token>    -> FastMCP, Streamable HTTP, STATELESS. The path is the
                            capability: a wrong or absent token is 404, never 401, so a
                            closed endpoint cannot be told apart from a nonexistent one.
                            Stateless so every tool call runs in its own request task,
                            where the gate's contextvar naming the session is visible.

The tools are thin: each one is one relay command to the attached browser tab, where
play-gui/am/fcweb_share.py runs it inside the live FreeCAD. fc_eval is the entire FreeCAD
Python API; fc_run_command is every GUI command; fc_screenshot is what the human sees.
The typed tools exist for ease, not reach.
"""
import base64
import contextvars
import json
import os
import re
import sys

import anyio
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Mount, Route

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import share  # noqa: E402

share.CFG.update(share._cfg())
os.makedirs(share.CFG['dir'], exist_ok=True)

CURRENT = contextvars.ContextVar('fcweb_session', default=None)   # (session id, token)
# The public origin, for share_url: FCWEB_PUBLIC_URL when the operator set it, else what
# the request itself came in on (nginx forwards Host and X-Forwarded-Proto).
ORIGIN = contextvars.ContextVar('fcweb_origin', default='')

INSTRUCTIONS = """You are attached to a live FreeCAD session running in someone's browser tab.

Work like this:
1. Call fc_session_info first, then fc_screenshot, so you know what is open and what the
   person sees. fc_tree and fc_get_object give you the model in detail.
2. Before changing anything, hold control: fc_session_info tells you; if not,
   fc_control_request(). Everyone watching sees your edits the moment they land.
3. Put a short, human `note` on every change ("added a 3 mm fillet to the top edges").
   Watchers read it as it happens. It is the difference between watching a model change
   and watching someone work.
4. Prefer the typed tools (fc_set_property, fc_add_object, fc_run_command, ...). fc_eval
   runs any FreeCAD Python (App, Gui, every workbench) when nothing typed fits.
5. After a change, fc_recompute if needed, then fc_screenshot or fc_shape_info to verify.
6. Every failure returns {ok:false, code, hint}. Do what the hint says: `not_holder` ->
   fc_control_request(); `no_tab` -> the person must open the session with the assistant
   enabled; `consent_required` -> the person must click Install in their tab.
7. A typical build: create -> fc_recompute -> fc_shape_info -> fc_screenshot -> fc_export.
   fc_export downloads the file in the person's browser; you get its name, size and hash.
8. fc_session_info returns share_url: the link a human opens to watch this same session.
   The MCP URL you were given came from Edit > Share Session > Allow an AI assistant, in
   the owner's FreeCAD tab; that tab must stay open for you to act.
Worked examples: read the prompt `freecad-quickstart`.
Object names AND labels are accepted wherever an object is named. Standard views:
front, top, right, rear, bottom, left, isometric, axonometric.
The people watching keep their own camera: describe what you changed in `note`
rather than relying on them seeing the same view.
"""

# DNS-rebinding protection OFF, deliberately. The SDK turns it on whenever it binds
# localhost and then only accepts Host: localhost:<port> -- but this server always sits
# behind our own nginx, which forwards the site's own Host ("localhost", "fc.example.com"),
# and every one of those is refused with 421 Invalid Host header. The check also buys
# nothing here: the capability is the unguessable token in the path, a browser cannot
# reach /mcp/ cross-origin under COOP/COEP anyway, and the operator chooses the origin.
# Measured 2026-09-15 against the real container: with it on, "claude mcp add" fails to
# connect and the gates cannot see it, because they talk to 127.0.0.1 directly.
mcp = FastMCP('freecad-web', instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
              streamable_http_path='/',
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


# --------------------------------------------------------------------------- relay glue
def _sess():
    c = CURRENT.get()
    if not c:
        raise RuntimeError('no session bound to this request')
    return c


async def _call(kind, args=None, timeout=30.0):
    sid, tok = _sess()
    r = await anyio.to_thread.run_sync(share.submit, sid, tok, kind, args or {}, float(timeout))
    if r.get('ok'):
        out = r.get('result', {})
        if isinstance(out, dict):
            out.setdefault('ok', True)
        return out
    return {'ok': False, 'code': r.get('code', 'error'), 'error': r.get('error', ''),
            'hint': r.get('hint', ''), 'trace': r.get('trace', '')}


def _note(args, note):
    if note:
        args['note'] = str(note)[:200]
    return args


# --------------------------------------------------------------------------- seeing
@mcp.tool()
async def fc_session_info() -> dict:
    """Who is in the session, who holds control, whether a browser tab is attached for you,
    the document name, version and expiry. Call this first."""
    sid, tok = _sess()
    with share.LOCK:
        m = share._meta(sid) or {}
        s = share._st(sid)
        live = [t for t, v in s['tabs'].items() if share._now() - v['seen'] <= share.HOLDER_SILENCE_S]
        holder = s['holder']
        hn = share._name(s, holder)
        # the assistant edits through the attached tab, so it can edit exactly when that
        # tab's client holds control -- compared by client id, never by display name
        attached_holder = holder is not None and any(s['tabs'][t].get('client') == holder for t in live)
        pub = share.CFG['public_url'].rstrip('/') or ORIGIN.get()
        return {'ok': True, 'session': sid, 'document': m.get('n', ''), 'version': m.get('v', 0),
                'env_version': m.get('env_v', 0), 'owner': m.get('owner', ''),
                'holder': hn, 'holder_silent': holder is not None and share._now() - s['holder_seen'] > share.HOLDER_SILENCE_S,
                'pending': share._name(s, s['pending']), 'watching': share._watching(s),
                'attached': bool(live), 'you_can_edit': attached_holder,
                'share_url': (pub + '/?s=' + sid) if pub else None,   # the human link
                'expires': m.get('expires'), 'last_updated': m.get('t', 0),
                'hint': None if live else share.HINTS['no_tab']}


@mcp.tool()
async def fc_status() -> dict:
    """Short form of fc_session_info: attached?, can edit?, busy?"""
    i = await fc_session_info()
    return {'ok': True, 'attached': i['attached'], 'you_can_edit': i['you_can_edit'],
            'holder': i['holder'], 'document': i['document'], 'hint': i.get('hint')}


@mcp.tool()
async def fc_screenshot(region: str = 'viewport', max_px: int = 1280):
    """What the person sees: an IMAGE block (PNG) you can look at, plus a text block with
    {width, height, region, cropped, mean_luminance}.

    region='viewport' crops to the 3D view alone -- use it to look at the model.
    region='window' is the whole FreeCAD window: tree, property editor, task panel,
    report view. cropped=false means no 3D view rect was available yet, so you got the
    whole frame. mean_luminance 0 is a black image: nothing has been drawn yet, rather
    than the model being missing. On failure returns {ok:false, code, hint} as text."""
    r = await _call('screenshot', {'region': region, 'max_px': int(max_px)}, 20)
    if not r.get('ok') or not r.get('png_b64'):
        return r
    # No return annotation on purpose: a dict/list annotation makes FastMCP emit the
    # result as structured JSON too, which would duplicate the PNG as base64 text.
    png = base64.b64decode(r.pop('png_b64'))
    return [Image(data=png, format='png'), TextContent(type='text', text=json.dumps(r))]


@mcp.tool()
async def fc_document_info() -> dict:
    """Active document: name, file, modified flag, object count, undo/redo depth, workbench."""
    return await _call('document_info')


@mcp.tool()
async def fc_env_info() -> dict:
    """The session's environment: installed add-ons, unit schema, decimals, FreeCAD version,
    available workbenches."""
    return await _call('env_info')


@mcp.tool()
async def fc_tree() -> dict:
    """Every object in the active document with type, label, parents, children, visibility,
    touched and valid flags."""
    return await _call('tree')


@mcp.tool()
async def fc_list_objects(filter: str = '') -> dict:
    """Objects whose name, label or type contains `filter` (case-insensitive)."""
    return await _call('list_objects', {'filter': filter})


@mcp.tool()
async def fc_find(label: str) -> dict:
    """Objects with exactly this label."""
    return await _call('find', {'label': label})


@mcp.tool()
async def fc_get_object(name: str) -> dict:
    """All properties of one object (by name or label): type, value, enum choices, status
    flags, expression bindings, plus shape info (volume, area, bounding box)."""
    return await _call('get_object', {'name': name})


@mcp.tool()
async def fc_shape_info(name: str) -> dict:
    """Volume, area, bounding box, centre of mass, validity, face/edge/vertex counts. How to
    verify geometry without a picture."""
    return await _call('shape_info', {'name': name})


@mcp.tool()
async def fc_selection_get() -> dict:
    """Selected objects and sub-elements (faces, edges, vertexes)."""
    return await _call('selection_get')


@mcp.tool()
async def fc_console_tail(n: int = 50) -> dict:
    """The last n lines of FreeCAD's report view: recompute errors, warnings, the output of
    the previous fc_eval."""
    return await _call('console_tail', {'n': int(n)})


@mcp.tool()
async def fc_list_workbenches() -> dict:
    """All workbenches FreeCAD ships here, and the active one."""
    return await _call('list_workbenches')


@mcp.tool()
async def fc_list_commands(workbench: str = '') -> dict:
    """Every GUI command FreeCAD has (hundreds), with menu text and tooltip. Run one with
    fc_run_command(name)."""
    return await _call('list_commands', {'workbench': workbench}, 60)


# --------------------------------------------------------------------------- controlling
@mcp.tool()
async def fc_control_request(force: bool = False) -> dict:
    """Ask for control of the session (the current editor is asked to grant). force=True takes
    it immediately; the person you displace keeps their unpublished changes as a copy."""
    return await _call('control_request', {'force': bool(force)}, 20)


@mcp.tool()
async def fc_control_release() -> dict:
    """Hand control back so the people in the session can edit again. You keep seeing
    everything; mutating tools return not_holder until you request control again."""
    return await _call('control_release', {}, 20)


@mcp.tool()
async def fc_session_set_passwords(viewer: str = None, editor: str = None) -> dict:
    """Set or clear (empty string) the viewer and/or editor password. Owner only."""
    a = {}
    if viewer is not None:
        a['viewer'] = viewer
    if editor is not None:
        a['editor'] = editor
    return await _call('session_set_passwords', a, 20)


@mcp.tool()
async def fc_session_set_expiry(days: int = 0) -> dict:
    """Make the share link expire after `days` days (0 = never). Owner only."""
    return await _call('session_set_expiry', {'days': int(days)}, 20)


@mcp.tool()
async def fc_session_stop() -> dict:
    """Stop sharing: the link stops working for everyone. Owner only."""
    return await _call('session_stop', {}, 20)


@mcp.tool()
async def fc_install_addon(repo: str, note: str = '') -> dict:
    """Ask the person to install an add-on (GitHub owner/repo). Returns consent_required until
    they click Install in their tab; call again afterwards."""
    return await _call('install_addon', _note({'repo': repo}, note), 20)


@mcp.tool()
async def fc_activate_workbench(name: str, note: str = '') -> dict:
    """Switch workbench, e.g. PartDesignWorkbench, SketcherWorkbench."""
    return await _call('activate_workbench', _note({'name': name}, note), 60)


@mcp.tool()
async def fc_run_command(name: str, note: str = '', item: int = 0) -> dict:
    """Run any FreeCAD GUI command by name (fc_list_commands), e.g. Std_ViewFitAll,
    Part_Box, PartDesign_Pad. Acts on the current selection like a menu click would."""
    return await _call('run_command', _note({'name': name, 'item': int(item)}, note), 60)


@mcp.tool()
async def fc_add_object(type: str, name: str = '', note: str = '') -> dict:
    """Create an object, e.g. type='Part::Box', 'Part::Cylinder', 'PartDesign::Body',
    'Sketcher::SketchObject'. Returns its name."""
    return await _call('add_object', _note({'type': type, 'name': name}, note))


@mcp.tool()
async def fc_set_property(name: str, prop: str, value, note: str = '') -> dict:
    """Set one property, e.g. fc_set_property('Box', 'Length', 30). Values are typed:
    numbers for lengths, strings for enums, [x,y,z] for vectors. Quantities accept a
    string with units: '10 mm', '0.5 in', '45 deg'. Read-only properties (Shape, computed
    outputs) are refused with a hint naming the property."""
    return await _call('set_property', _note({'name': name, 'prop': prop, 'value': value}, note))


@mcp.tool()
async def fc_set_expression(name: str, prop: str, expr: str = '', note: str = '') -> dict:
    """Bind a property to an expression, e.g. 'Sketch.Constraints.width * 2'. Empty clears."""
    return await _call('set_expression', _note({'name': name, 'prop': prop, 'expr': expr}, note))


@mcp.tool()
async def fc_call(name: str, method: str, args: list = None, note: str = '') -> dict:
    """Call a method on an object, e.g. fc_call('Sketch', 'addGeometry', [...]). args must
    be JSON values: numbers, strings, lists; give a vector as [x, y, z]. For anything
    needing FreeCAD objects as arguments (Part.LineSegment, Placement) use fc_eval."""
    return await _call('call', _note({'name': name, 'method': method, 'args': args or []}, note))


@mcp.tool()
async def fc_delete_object(name: str, note: str = '') -> dict:
    """Remove an object from the document."""
    return await _call('delete_object', _note({'name': name}, note))


@mcp.tool()
async def fc_recompute(note: str = '') -> dict:
    """Recompute the document; returns per-object errors if any."""
    return await _call('recompute', _note({}, note), 120)


@mcp.tool()
async def fc_undo(note: str = '') -> dict:
    """Undo the last transaction (one document-level step, like Ctrl+Z)."""
    return await _call('undo', _note({}, note))


@mcp.tool()
async def fc_redo(note: str = '') -> dict:
    """Redo the last undone transaction (like Ctrl+Y)."""
    return await _call('redo', _note({}, note))


@mcp.tool()
async def fc_selection_set(items: list, note: str = '') -> dict:
    """Select objects/sub-elements: items=[{"name":"Box","sub":["Face6"]}, ...]. Many GUI
    commands act on the selection."""
    return await _call('selection_set', _note({'items': items}, note))


@mcp.tool()
async def fc_selection_clear() -> dict:
    """Clear the selection in the active document."""
    return await _call('selection_clear')


@mcp.tool()
async def fc_view_set(standard: str = '', camera: str = '', note: str = '') -> dict:
    """Move the camera for everyone watching: standard='top'|'front'|'isometric'|..., or a
    camera string from a previous call."""
    return await _call('view_set', _note({'standard': standard, 'camera': camera}, note))


@mcp.tool()
async def fc_fit_all() -> dict:
    """Fit the whole model in view. Returns the camera string. Watchers keep their own
    viewpoint -- say what you are looking at in the `note` instead."""
    return await _call('fit_all')


@mcp.tool()
async def fc_fit_selection() -> dict:
    """Fit the selection in view. Returns the camera string. Watchers keep their own
    viewpoint -- say what you are looking at in the `note` instead."""
    return await _call('fit_selection')


@mcp.tool()
async def fc_export(format: str = 'step', objects: list = None, name: str = '',
                    linear_deflection: float = 0.1, angular_deflection: float = 0.5,
                    inline: bool = False) -> dict:
    """Export objects (default: all) as step|iges|stl|3mf|obj|brep|fcstd. The file is
    DOWNLOADED IN THE PERSON'S BROWSER (they get a toast with the name); you get
    {name, bytes, sha256, format}. bytes_b64 is included only when inline=True or the
    file is under 256 KB -- a print-ready STL is often megabytes, and base64 in your
    context helps nobody. For stl/3mf the mesh is tessellated with linear_deflection (mm,
    smaller = finer; 0.1 is fine for FDM printing, 0.02 for resin) and angular_deflection
    (degrees). name is the file stem; default is the document name."""
    r = await _call('export', {'format': format, 'objects': objects or [], 'name': name,
                               'linear_deflection': float(linear_deflection),
                               'angular_deflection': float(angular_deflection),
                               'inline': bool(inline)}, 120)
    if isinstance(r, dict) and len(r.get('bytes_b64') or '') > 4 * 1024 * 1024:
        r.pop('bytes_b64', None)
        r['hint'] = 'Too large to inline; the person has the download.'
    return r


@mcp.tool()
async def fc_import_bytes(name: str, bytes_b64: str, format: str = '', note: str = '') -> dict:
    """Import a STEP/IGES/STL/3MF/OBJ file (base64) into the active document. format
    (step|iges|stl|3mf|obj) picks the importer; when empty it is taken from name's
    extension."""
    return await _call('import_bytes', _note({'name': name, 'bytes_b64': bytes_b64, 'format': format}, note), 120)


@mcp.tool()
async def fc_open_bytes(name: str, bytes_b64: str, note: str = '') -> dict:
    """Open a .FCStd file (base64) as a new document."""
    return await _call('open_bytes', _note({'name': name, 'bytes_b64': bytes_b64}, note), 120)


@mcp.tool()
async def fc_eval(code: str, note: str = '', timeout_s: int = 30) -> dict:
    """Run Python inside the live FreeCAD: App, Gui, every workbench module, PySide. This is
    the whole FreeCAD API. Like a REPL: printed output comes back in `out`, and if the
    last line is an expression its repr comes back in `value` (so fc_eval('6*7') gives
    value '42'). Exceptions come back in `error` with a `trace`.

    timeout_s bounds how long this call WAITS; the code itself keeps running in the tab
    and cannot be interrupted (no KeyboardInterrupt under JSPI) -- only a page reload ends
    a runaway loop. Keep long loops out of a single call."""
    return await _call('eval', _note({'code': code}, note), int(timeout_s))


# --------------------------------------------------------------------------- resources
@mcp.resource('freecad://tree')
async def res_tree() -> str:
    """The object tree of the active document."""
    return json.dumps(await _call('tree'))


@mcp.resource('freecad://selection')
async def res_selection() -> str:
    """The current selection."""
    return json.dumps(await _call('selection_get'))


@mcp.resource('freecad://console')
async def res_console() -> str:
    """The last 50 report-view lines."""
    return json.dumps(await _call('console_tail', {'n': 50}))


@mcp.resource('freecad://screenshot.png', mime_type='image/png')
async def res_screenshot() -> bytes:
    """The 3D view as a PNG."""
    r = await _call('screenshot', {'region': 'viewport', 'max_px': 1280}, 20)
    if not r.get('ok') or not r.get('png_b64'):
        raise RuntimeError('%s: %s' % (r.get('code', 'error'), r.get('hint') or r.get('error', '')))
    return base64.b64decode(r['png_b64'])


@mcp.resource('freecad://session')
async def res_session() -> str:
    """Session state: holder, watchers, version."""
    return json.dumps(await fc_session_info())


# --------------------------------------------------------------------------- prompts
QUICKSTART = """FreeCAD over MCP -- worked examples. Every mutating call needs control
(fc_session_info -> you_can_edit; otherwise fc_control_request()) and takes a `note` that
the people watching read as it lands.

1. Look first
   fc_session_info()            # who is here, can you edit, the human share_url
   fc_screenshot()              # the 3D view as an image
   fc_tree()                    # every object

2. A box, checked
   fc_add_object('Part::Box', 'Base', note='a 40x25x12 base')
   fc_set_property('Base', 'Length', 40); fc_set_property('Base', 'Width', 25)
   fc_set_property('Base', 'Height', '12 mm')
   fc_recompute(); fc_shape_info('Base')   # volume 12000, valid true

3. A sketch and a pad (PartDesign) -- fc_eval when the typed tools do not fit
   fc_eval('''import FreeCAD as App, Part, Sketcher
d = App.ActiveDocument; body = d.addObject('PartDesign::Body', 'Body')
sk = body.newObject('Sketcher::SketchObject', 'Sketch'); sk.Support = (d.getObject('XY_Plane'), ['']); sk.MapMode = 'FlatFace'
sk.addGeometry(Part.Circle(App.Vector(0,0,0), App.Vector(0,0,1), 10), False)
pad = body.newObject('PartDesign::Pad', 'Pad'); pad.Profile = sk; pad.Length = 5
d.recompute(); print(pad.Shape.Volume)''', note='a 20 mm disc padded 5 mm')

4. Fillet the top edges
   fc_eval('''import FreeCAD as App
d = App.ActiveDocument; f = d.addObject('Part::Fillet', 'Fillet'); f.Base = d.Base
f.Edges = [(i+1, 2.0, 2.0) for i, e in enumerate(d.Base.Shape.Edges) if abs(e.BoundBox.ZMin - 12) < 1e-6]
d.Base.Visibility = False; d.recompute()''', note='2 mm fillet on the top edges')

5. Units for the person
   fc_eval('''import FreeCAD as App
p = App.ParamGet('User parameter:BaseApp/Preferences/Units'); p.SetInt('UserSchema', 0); p.SetInt('Decimals', 2)''')

6. Print-ready STL, then look at it
   fc_fit_all(); fc_screenshot()
   fc_export('stl', objects=['Fillet'], name='phone-case', linear_deflection=0.05)
   # -> downloaded in their browser; you get {name, bytes, sha256}
"""


@mcp.prompt('freecad-quickstart')
def freecad_quickstart() -> str:
    """Six worked examples: look, box, sketch+pad, fillet, units, STL for printing."""
    return QUICKSTART


# --------------------------------------------------------------------------- ASGI
_MCP_PATH = re.compile(r'^/([0-9a-f]{32})/([0-9a-f]{32,64})/?$')


class McpGate:
    """404 -- never 401 -- unless the path carries a valid capability; bind the session for
    the tools; hand the inner app a path of '/'."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        # Starlette >= 0.33 keeps scope['path'] as the FULL path under a Mount and reports the
        # mount in root_path; older versions strip it. Handle both.
        rp = scope.get('root_path', '') or ''
        path = scope.get('path', '')
        rel = path[len(rp):] if rp and path.startswith(rp) else path
        m = _MCP_PATH.match(rel)
        if not m or not share._agent_ok(m.group(1), m.group(2)):
            body = json.dumps({'error': 'not found', 'code': 'not_found', 'hint': 'No such endpoint.'}).encode()
            await send({'type': 'http.response.start', 'status': 404,
                        'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]})
            await send({'type': 'http.response.body', 'body': body})
            return
        token = CURRENT.set((m.group(1), m.group(2)))
        hdr = {k.decode().lower(): v.decode() for k, v in scope.get('headers', [])}
        host = hdr.get('x-forwarded-host') or hdr.get('host', '')
        proto = hdr.get('x-forwarded-proto') or scope.get('scheme', 'http')
        otoken = ORIGIN.set(proto + '://' + host if host else '')
        try:
            inner = dict(scope, path=rp + '/', raw_path=(rp + '/').encode())
            await self.app(inner, receive, send)
        finally:
            CURRENT.reset(token)
            ORIGIN.reset(otoken)


async def share_route(request):
    body = await request.body()
    path = request.url.path + ('?' + request.url.query if request.url.query else '')
    st, h, b = await run_in_threadpool(share.handle, request.method, path, dict(request.headers), body)
    return Response(b, status_code=st, headers=h)


def _lifespan(app):
    return mcp.session_manager.run()


app = Starlette(
    routes=[
        Route('/share/{p:path}', share_route, methods=['GET', 'HEAD', 'POST', 'PUT', 'DELETE']),
        Route('/api/{p:path}', share_route, methods=['GET', 'POST']),
        Mount('/mcp', app=McpGate(mcp.streamable_http_app())),
    ],
    lifespan=_lifespan,
)

if __name__ == '__main__':
    import uvicorn
    sys.stderr.write('[session] listening on :8000 dir=%s max=%dMB quota=%.1fGB sessions=%d\n' % (
        share.CFG['dir'], share.CFG['max_bytes'] // 1048576, share.CFG['quota'] / 1073741824, len(share._sessions())))
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8000')), log_level='warning')
