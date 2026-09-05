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
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Mount, Route

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import share  # noqa: E402

share.CFG.update(share._cfg())
os.makedirs(share.CFG['dir'], exist_ok=True)

CURRENT = contextvars.ContextVar('fcweb_session', default=None)   # (session id, token)

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
Object names AND labels are accepted wherever an object is named. Standard views:
front, top, right, rear, bottom, left, isometric, axonometric.
"""

mcp = FastMCP('freecad-web', instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
              streamable_http_path='/')


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
        # the attached tab is a client too; if it is the holder, the assistant can edit
        attached_holder = bool(live) and holder is not None and any(
            c.get('name') == m.get('owner') for cid, c in s['clients'].items() if cid == holder)
        return {'ok': True, 'session': sid, 'document': m.get('n', ''), 'version': m.get('v', 0),
                'env_version': m.get('env_v', 0), 'owner': m.get('owner', ''),
                'holder': hn, 'holder_silent': holder is not None and share._now() - s['holder_seen'] > share.HOLDER_SILENCE_S,
                'pending': share._name(s, s['pending']), 'watching': share._watching(s),
                'attached': bool(live), 'you_can_edit': attached_holder,
                'expires': m.get('expires'), 'last_updated': m.get('t', 0),
                'hint': None if live else share.HINTS['no_tab']}


@mcp.tool()
async def fc_status() -> dict:
    """Short form of fc_session_info: attached?, can edit?, busy?"""
    i = await fc_session_info()
    return {'ok': True, 'attached': i['attached'], 'you_can_edit': i['you_can_edit'],
            'holder': i['holder'], 'document': i['document'], 'hint': i.get('hint')}


@mcp.tool()
async def fc_screenshot(region: str = 'viewport', max_px: int = 1280) -> dict:
    """What the person sees. region='viewport' is the 3D view; 'window' is the whole FreeCAD
    window (tree, property editor, task panel, report view). Returns PNG as png_b64 plus
    width/height and mean_luminance (0 means a black frame: nothing is drawn yet)."""
    return await _call('screenshot', {'region': region, 'max_px': int(max_px)}, 20)


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
    """Hand control back."""
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
    numbers for lengths, strings for enums, [x,y,z] for vectors."""
    return await _call('set_property', _note({'name': name, 'prop': prop, 'value': value}, note))


@mcp.tool()
async def fc_set_expression(name: str, prop: str, expr: str = '', note: str = '') -> dict:
    """Bind a property to an expression, e.g. 'Sketch.Constraints.width * 2'. Empty clears."""
    return await _call('set_expression', _note({'name': name, 'prop': prop, 'expr': expr}, note))


@mcp.tool()
async def fc_call(name: str, method: str, args: list = None, note: str = '') -> dict:
    """Call a method on an object, e.g. fc_call('Sketch', 'addGeometry', [...])."""
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
    """Undo the last transaction."""
    return await _call('undo', _note({}, note))


@mcp.tool()
async def fc_redo(note: str = '') -> dict:
    """Redo."""
    return await _call('redo', _note({}, note))


@mcp.tool()
async def fc_selection_set(items: list, note: str = '') -> dict:
    """Select objects/sub-elements: items=[{"name":"Box","sub":["Face6"]}, ...]. Many GUI
    commands act on the selection."""
    return await _call('selection_set', _note({'items': items}, note))


@mcp.tool()
async def fc_selection_clear() -> dict:
    """Clear the selection."""
    return await _call('selection_clear')


@mcp.tool()
async def fc_view_set(standard: str = '', camera: str = '', note: str = '') -> dict:
    """Move the camera for everyone watching: standard='top'|'front'|'isometric'|..., or a
    camera string from a previous call."""
    return await _call('view_set', _note({'standard': standard, 'camera': camera}, note))


@mcp.tool()
async def fc_fit_all() -> dict:
    """Fit the whole model in view."""
    return await _call('fit_all')


@mcp.tool()
async def fc_fit_selection() -> dict:
    """Fit the selection in view."""
    return await _call('fit_selection')


@mcp.tool()
async def fc_export(format: str = 'step', objects: list = None) -> dict:
    """Export objects (default: all) as step|iges|stl|obj|brep|fcstd. Returns bytes_b64."""
    return await _call('export', {'format': format, 'objects': objects or []}, 120)


@mcp.tool()
async def fc_import_bytes(name: str, bytes_b64: str, note: str = '') -> dict:
    """Import a STEP/IGES/STL/OBJ file (base64) into the active document."""
    return await _call('import_bytes', _note({'name': name, 'bytes_b64': bytes_b64}, note), 120)


@mcp.tool()
async def fc_open_bytes(name: str, bytes_b64: str, note: str = '') -> dict:
    """Open a .FCStd file (base64) as a new document."""
    return await _call('open_bytes', _note({'name': name, 'bytes_b64': bytes_b64}, note), 120)


@mcp.tool()
async def fc_eval(code: str, note: str = '', timeout_s: int = 30) -> dict:
    """Run Python inside the live FreeCAD: App, Gui, every workbench module, PySide. This is
    the whole FreeCAD API. Output (print) comes back in `out`; exceptions in `error`."""
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


@mcp.resource('freecad://session')
async def res_session() -> str:
    """Session state: holder, watchers, version."""
    return json.dumps(await fc_session_info())


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
        try:
            inner = dict(scope, path=rp + '/', raw_path=(rp + '/').encode())
            await self.app(inner, receive, send)
        finally:
            CURRENT.reset(token)


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
