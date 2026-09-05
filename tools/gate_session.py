# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Boot-gate scenarios for shared sessions. Registered by tools/boot-gate.py; run as

    python tools/boot-gate.py <dir> --page freecad-gui.html --scenario share|control|mcp|env

Two browser CONTEXTS per scenario (a fresh profile each), served by serve-artifact.py,
whose /share/ stand-in runs the real infra/session/share.py same-origin. Every marker
waited on here is one the page or the interpreter writes for a human too; the gate reads
window.__fcSessionRing and the console rather than anything test-only.

The MCP scenario speaks Streamable HTTP with urllib: the container runs the server
stateless with JSON responses, so a POST is a plain request/response and the gate needs
no SDK.
"""
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

GROUP = 'User parameter:BaseApp/Preferences/FCWeb/Sharing'

MAKE_DOC_PY = r'''
import FreeCAD as App, sys
_d = App.newDocument("GateShare")
_b = _d.addObject("Part::Box", "Box")
_b.Length, _b.Width, _b.Height = 10, 20, 30
_d.recompute()
sys.__stderr__.write("GATE_DOC ready %s\n" % _d.Name)
'''

VOLUME_PY = r'''
import FreeCAD as App, sys
_out = {}
for _n, _d in App.listDocuments().items():
    _b = _d.getObject("Box")
    if _b is not None:
        _out[_n] = {"volume": _b.Shape.Volume, "length": _b.Length.Value, "label": _d.Label,
                    "modified": _d.Modified, "ro": "ReadOnly" in _b.getPropertyStatus("Length")}
sys.__stderr__.write("GATE_VOL " + repr(_out) + "\n")
'''


def _Session():
    return sys.modules['__main__'].Session


def _ring(s):
    try:
        return s.page.evaluate('(window.__fcSessionRing || []).map(r => r.sub + ": " + r.msg)')
    except Exception:
        return []


def _wait(s, needle, seconds, where='ring'):
    """Wait for a substring in the session ring (or console); return the matching line."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        lines = _ring(s) if where == 'ring' else s.lines()
        for c in lines:
            if needle in c:
                return c
        time.sleep(0.5)
    return None


def _state(s):
    try:
        return s.page.evaluate('({id: window.__fcSession.id, holder: window.__fcSession.holder, role: window.__fcSession.role, v: window.__fcSession.v, applied: window.__fcSession.applied, silent: window.__fcSession.silent, ended: window.__fcSession.ended, agentUrl: window.__fcSession.agentUrl, tab: window.__fcSession.tab, holderName: window.__fcSession.holderName, note: window.__fcSession.note, cam: window.__fcSession.cam})')
    except Exception:
        return {}


def _wait_state(s, pred, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        st = _state(s)
        if pred(st):
            return st
        time.sleep(0.5)
    return None


def _volumes(s, fail, seconds=60):
    s.run_python(VOLUME_PY)
    r = s.wait_for('GATE_VOL', seconds)
    if not isinstance(r, dict):
        fail('no volume report from the interpreter in %ds' % seconds)
        return {}
    return r


def _enable_sharing(s, name='Alice', extra=''):
    s.run_python("import FreeCAD as A\np = A.ParamGet(%r)\np.SetString('DisplayName', %r)\n%s\np.SetBool('Enabled', True)\nA.saveParameter()\n"
                 % (GROUP, name, extra))


def _dialogs(page, name='Bob', vpw='', epw=''):
    def on_dialog(d):
        m = (d.message or '').lower()
        if 'editor password' in m:
            d.accept(epw)
        elif 'password' in m:
            d.accept(vpw)
        elif 'your name' in m:
            d.accept(name)
        else:
            d.accept()
    page.on('dialog', on_dialog)


def _viewer(ctx, url, sid, args, name='Bob', vpw='', epw=''):
    S = _Session()
    ctx2 = ctx.browser.new_context()
    s2 = S(ctx2, url + ('&' if '?' in url else '?') + 's=' + sid, args.timeout)
    _dialogs(s2.page, name, vpw, epw)
    return s2


def _owner_up(ctx, url, args, fail, extra=''):
    S = _Session()
    s1 = S(ctx, url, args.timeout)
    if not s1.load():
        fail('owner never reached Ready (%s)' % s1.phase())
        return None, None
    s1.run_python(MAKE_DOC_PY)
    if not _wait(s1, 'GATE_DOC ready', 120, 'console'):
        fail('the gate document was not created')
        return None, None
    _enable_sharing(s1, extra=extra)
    st = _wait_state(s1, lambda x: x.get('id'), 40)
    if not st:
        fail('sharing never started: no session id after 40 s (ring: %s)' % _ring(s1)[-5:])
        return s1, None
    if not _wait(s1, 'publish: pushed v1', 60):
        fail('the pinned document was never published (ring: %s)' % _ring(s1)[-6:])
    print('==> owner shares %s as %s' % (st['id'][:8], 'holder' if st['holder'] else 'NOT holder'))
    if not st['holder']:
        fail('the owner does not hold control of their own new session')
    return s1, st['id']


def _http(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    rq = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    try:
        r = urllib.request.urlopen(rq, timeout=60)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


# --------------------------------------------------------------------------- scenarios
def scenario_share(ctx, url, args, fail):
    """Publish -> apply chain, live update, camera follow, stale banner, resume on the same id."""
    s1, sid = _owner_up(ctx, url, args, fail)
    if not sid:
        return s1
    s2 = _viewer(ctx, url, sid, args)
    if not s2.load():
        fail('viewer never reached Ready in session mode (%s)' % s2.phase())
        return s1
    if not _wait(s2, 'session mode: own home NOT mounted', 30):
        fail('session mode did not materialize the ephemeral home (isolation lost)')
    if not _wait(s2, 'share applied v1', 90, 'console'):
        fail('viewer never applied v1 (ring: %s)' % _ring(s2)[-6:])
    v = _volumes(s2, fail)
    got = [x for x in v.values()]
    if not got or abs(got[0]['volume'] - 6000.0) > 1e-6:
        fail('viewer sees %r, expected a 6000.0 box' % v)
    else:
        print('==> viewer opened the shared document: volume %.1f, read-only=%s' % (got[0]['volume'], got[0]['ro']))
        if not got[0]['ro']:
            fail('the viewer copy is not read-only')
    # the live half
    s1.run_python("import FreeCAD as A\n_d=A.getDocument('GateShare'); _d.getObject('Box').Length=20; _d.recompute()")
    if not _wait(s1, 'publish: pushed v2', 40):
        fail('the edit was never published as v2')
    if not _wait(s2, 'share applied v2', 60, 'console'):
        fail('viewer never applied v2')
    v = _volumes(s2, fail)
    got = [x for x in v.values() if abs(x['volume'] - 12000.0) < 1e-6]
    if not got:
        fail('viewer did not receive the live edit (volumes %r)' % {k: x['volume'] for k, x in v.items()})
    else:
        print('==> live edit reached the viewer: volume 12000.0')
    # camera follows without a reopen
    s1.run_python("import FreeCADGui as G\nG.ActiveDocument.ActiveView.viewTop()")
    before = _state(s2).get('applied')
    st = _wait_state(s2, lambda x: x.get('cam') and 'GATE' not in x['cam'], 20)
    time.sleep(8)
    if _state(s2).get('applied') != before:
        fail('a camera-only change caused a document reopen on the viewer')
    print('==> camera followed (%s), no reopen' % ('yes' if st else 'not observed'))
    # stale banner after the owner goes silent
    s1.page.close()
    st = _wait_state(s2, lambda x: x.get('silent'), 90)
    if not st:
        fail('the viewer never learned the owner went silent')
    else:
        print('==> owner silent -> viewer shows "last updated"')
    # the owner resumes on the same id
    S = _Session()
    s3 = S(ctx, url, args.timeout)
    if not s3.load():
        fail('owner could not reboot')
        return s2
    line = _wait(s3, 'resumed session ' + sid[:8], 60)
    if not line:
        fail('owner did not resume the SAME session after a reload (ring: %s)' % _ring(s3)[-6:])
    else:
        print('==> ' + line)
    return s2


def scenario_control(ctx, url, args, fail):
    """Read-only is enforced, handover flips roles, force keeps displaced work, auto-grant."""
    s1, sid = _owner_up(ctx, url, args, fail, extra="p.SetString('EditorPassword', 'e1')")
    if not sid:
        return s1
    if not _wait(s1, 'share: passwords updated', 40):
        fail('the editor password never reached the server')
    s2 = _viewer(ctx, url, sid, args, epw='e1')
    if not s2.load() or not _wait(s2, 'share applied v1', 90, 'console'):
        fail('viewer never applied v1')
        return s1
    # 1. a bridge-driven edit on a non-holder does not stick
    s2.run_python("import FreeCAD as A\nfor _d in A.listDocuments().values():\n    _b=_d.getObject('Box')\n    if _b: _b.Length = 99; _d.recompute()")
    time.sleep(8)
    v = _volumes(s2, fail)
    if any(abs(x['length'] - 99) < 1e-6 for x in v.values()):
        fail('a read-only viewer changed the shared document and it stuck: %r' % v)
    else:
        print('==> read-only edit did not stick (guard reverted to the session version)')
    # 2. request -> grant on the owner's side (a real click on the toast)
    s2.page.evaluate('window.fcwebShareRequest(false)')
    try:
        s1.page.click('text=Grant', timeout=20000)
    except Exception as e:
        fail('the owner never saw a Grant toast: %s' % e)
    st = _wait_state(s2, lambda x: x.get('holder'), 30)
    if not st:
        fail('control was granted but the viewer never became holder')
        return s1
    st1 = _wait_state(s1, lambda x: not x.get('holder'), 30)
    if not st1:
        fail('the owner still believes it holds control after handing over')
    print('==> handover: Bob holds control, owner read-only')
    s2.run_python("import FreeCAD as A\nfor _d in A.listDocuments().values():\n    _b=_d.getObject('Box')\n    if _b: _b.Length = 25; _d.recompute()")
    if not _wait(s2, 'publish: pushed v', 40):
        fail('the new holder never published')
    if not _wait(s1, 'share applied v', 60, 'console'):
        fail('the owner never received the new holder\'s version')
    v = _volumes(s1, fail)
    if not any(abs(x['volume'] - 15000.0) < 1e-6 for x in v.values()):
        fail('the owner did not get Bob\'s edit (volumes %r)' % {k: x['volume'] for k, x in v.items()})
    else:
        print('==> Bob\'s edit reached the owner: volume 15000.0')
    # 3. force: Bob edits, owner forces immediately; Bob's unpublished edit must survive
    s2.run_python("import FreeCAD as A\nfor _d in A.listDocuments().values():\n    _b=_d.getObject('Box')\n    if _b: _b.Length = 26; _d.recompute()")
    time.sleep(0.5)
    s1.page.evaluate('window.fcwebShareRequest(true)')
    st1 = _wait_state(s1, lambda x: x.get('holder'), 30)
    if not st1:
        fail('the owner could not force control back')
    st2 = _wait_state(s2, lambda x: not x.get('holder'), 30)
    if not st2:
        fail('Bob still believes he holds control after being displaced')
    time.sleep(6)
    v = _volumes(s2, fail)
    kept = [x for x in v.values() if '(my changes)' in x['label']]
    if not kept:
        fail('Bob\'s unpublished change was not kept as a separate document: %r' % {k: x['label'] for k, x in v.items()})
    elif abs(kept[0]['length'] - 26) > 1e-6:
        fail('the detached copy lost the edit: length %r' % kept[0]['length'])
    else:
        print('==> displaced work kept as "%s" with the edit intact' % kept[0]['label'])
    # 4. a killed holder: Bob takes control then vanishes; the owner gets it after the silence window
    s2.page.evaluate('window.fcwebShareRequest(true)')
    _wait_state(s2, lambda x: x.get('holder'), 30)
    s2.page.close()
    time.sleep(65)
    s1.page.evaluate('window.fcwebShareRequest(false)')
    st1 = _wait_state(s1, lambda x: x.get('holder'), 30)
    if not st1:
        fail('control was not auto-granted after the holder vanished')
    else:
        print('==> auto-grant after the holder vanished')
    return s1


def scenario_mcp(ctx, url, args, fail):
    """The MCP endpoint from the exact URL the page shows: everything, seeing, live edit."""
    s1, sid = _owner_up(ctx, url, args, fail, extra="p.SetBool('AllowAgent', True)")
    if not sid:
        return s1
    st = _wait_state(s1, lambda x: x.get('agentUrl'), 40)
    if not st:
        fail('no MCP URL was minted after enabling the assistant')
        return s1
    mcp_url = st['agentUrl']
    base = url.split('/freecad-gui')[0]
    print('==> MCP URL minted: %s' % mcp_url[:len(base) + 44] + '...')
    st = _wait_state(s1, lambda x: x.get('tab'), 20)
    if not st:
        fail('the owner tab never attached as the relay target')
    hdr = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    n = [0]

    def rpc(u, method, params=None):
        n[0] += 1
        st_, body, _ = _http(base, 'POST', u.replace(base, ''), json.dumps({'jsonrpc': '2.0', 'id': n[0], 'method': method, 'params': params or {}}).encode(), hdr)
        try:
            return st_, json.loads(body)
        except Exception:
            return st_, {'raw': body[:200]}

    def tool(name, arguments=None, timeout=90):
        st_, j = rpc(mcp_url, 'tools/call', {'name': name, 'arguments': arguments or {}})
        if st_ != 200:
            return {'ok': False, 'code': 'http_%d' % st_, 'hint': str(j)[:200]}
        try:
            return json.loads(j['result']['content'][0]['text'])
        except Exception:
            return {'ok': False, 'code': 'bad_response', 'hint': str(j)[:300]}

    st_, j = rpc(mcp_url, 'initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'gate', 'version': '0'}})
    if st_ != 200 or 'result' not in j:
        fail('initialize failed: %s %s -- the MCP transport needs the real service: set FCWEB_SESSION_PYTHON to an interpreter with mcp<2, uvicorn and starlette installed so the gate can run infra/session/app.py behind serve-artifact.py' % (st_, str(j)[:160]))
        return s1
    if 'fc_session_info' not in (j['result'].get('instructions') or ''):
        fail('the server instructions do not tell the model where to start')
    st_, j = rpc(mcp_url, 'tools/list')
    names = sorted(t['name'] for t in j.get('result', {}).get('tools', []))
    print('==> %d tools listed' % len(names))
    for must in ('fc_eval', 'fc_run_command', 'fc_screenshot', 'fc_tree', 'fc_set_property', 'fc_control_request'):
        if must not in names:
            fail('tool missing: ' + must)
    # negatives: wrong token, other session, all 404
    for bad in (mcp_url[:-1] + ('0' if mcp_url[-1] != '0' else '1'), mcp_url.replace(sid, '0' * 32)):
        st_, _ = rpc(bad, 'initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'x', 'version': '0'}})
        if st_ != 404:
            fail('a bad MCP URL answered %s, expected 404' % st_)
    # seeing
    info = tool('fc_session_info')
    if not info.get('attached'):
        fail('fc_session_info says no tab is attached: %r' % info)
    r = tool('fc_eval', {'code': 'print(6*7)'})
    if not r.get('ok') or '42' not in r.get('out', ''):
        fail('fc_eval print(6*7) -> %r' % r)
    else:
        print('==> fc_eval: 42')
    r = tool('fc_tree')
    if not r.get('ok') or not any(o['name'] == 'Box' for o in r.get('objects', [])):
        fail('fc_tree does not list the Box: %r' % str(r)[:200])
    r = tool('fc_shape_info', {'name': 'Box'})
    if not r.get('ok') or abs(r.get('volume', 0) - 6000.0) > 1e-6:
        fail('fc_shape_info volume %r' % r.get('volume'))
    r = tool('fc_list_commands', {}, 120)
    if not r.get('ok') or r.get('count', 0) < 500:
        fail('fc_list_commands returned %r commands, expected > 500' % r.get('count'))
    else:
        print('==> fc_list_commands: %d commands' % r['count'])
    r = tool('fc_run_command', {'name': 'Std_ViewFitAll'})
    if not r.get('ok'):
        fail('fc_run_command Std_ViewFitAll -> %r' % r)
    r = tool('fc_list_workbenches')
    if not r.get('ok') or len(r.get('workbenches', [])) < 10:
        fail('fc_list_workbenches -> %r' % str(r)[:200])
    r = tool('fc_console_tail', {'n': 20})
    if not r.get('ok'):
        fail('fc_console_tail -> %r' % r)
    r = tool('fc_screenshot', {'region': 'viewport'}, 30)
    if getattr(args, 'with_3d', False):
        if not r.get('ok') or r.get('mean_luminance', 0) <= 0:
            fail('fc_screenshot with 3D on: %r' % {k: r.get(k) for k in ('ok', 'code', 'hint', 'mean_luminance')})
        else:
            print('==> fc_screenshot: %dx%d, luminance %d' % (r['width'], r['height'], r['mean_luminance']))
    else:
        if r.get('ok') or not r.get('hint'):
            fail('fc_screenshot under ?no3d must fail honestly with a hint: %r' % str(r)[:200])
        else:
            print('==> fc_screenshot under ?no3d: honest failure (%s)' % r.get('hint'))
    # every error carries code + hint
    r = tool('fc_set_property', {'name': 'NoSuchObject', 'prop': 'Length', 'value': 1})
    if r.get('ok') or not (r.get('code') and r.get('hint')):
        fail('a failing tool must carry code and hint: %r' % r)
    # live edit while a viewer watches: one poll tick
    s2 = _viewer(ctx, url, sid, args)
    if not s2.load() or not _wait(s2, 'share applied v1', 90, 'console'):
        fail('viewer never applied v1')
        return s1
    t0 = time.time()
    r = tool('fc_set_property', {'name': 'Box', 'prop': 'Length', 'value': 30, 'note': 'stretched the box'})
    if not r.get('ok'):
        fail('fc_set_property -> %r' % r)
    if not _wait(s2, 'share applied v2', 20, 'console'):
        fail('the viewer did not see the assistant\'s edit within ~one poll tick')
    else:
        print('==> assistant edit reached the viewer in %.1fs' % (time.time() - t0))
    st = _wait_state(s2, lambda x: 'stretched the box' in (x.get('note') or ''), 15)
    if not st:
        fail('the assistant\'s note never reached the viewer\'s activity line')
    v = _volumes(s2, fail)
    if not any(abs(x['volume'] - 18000.0) < 1e-6 for x in v.values()):
        fail('viewer volume after the assistant edit: %r' % {k: x['volume'] for k, x in v.items()})
    r = tool('fc_view_set', {'standard': 'top'})
    if not r.get('ok'):
        fail('fc_view_set -> %r' % r)
    r = tool('fc_install_addon', {'repo': 'FreeCAD/FreeCAD-addons'})
    if r.get('ok') or r.get('code') != 'consent_required':
        fail('fc_install_addon must return consent_required until a click: %r' % r)
    else:
        print('==> fc_install_addon: consent_required')
    # not holding control -> not_holder with a hint pointing at fc_control_request
    s1.page.evaluate('window.fcwebShareRelease()')
    _wait_state(s1, lambda x: not x.get('holder'), 20)
    r = tool('fc_set_property', {'name': 'Box', 'prop': 'Length', 'value': 31})
    if r.get('ok') or r.get('code') != 'not_holder' or 'fc_control_request' not in r.get('hint', ''):
        fail('without control the tool must refuse with not_holder + hint: %r' % r)
    r = tool('fc_control_request', {'force': True})
    if not r.get('ok') or not r.get('granted'):
        fail('fc_control_request(force) -> %r' % r)
    r = tool('fc_set_property', {'name': 'Box', 'prop': 'Length', 'value': 31})
    if not r.get('ok'):
        fail('after taking control the edit still failed: %r' % r)
    else:
        print('==> not_holder -> fc_control_request -> edit succeeds')
    return s1


def scenario_env(ctx, url, args, fail):
    """The environment travels; the visitor's own home is untouched; secrets are redacted."""
    S = _Session()
    # the visitor first: a document and a distinctive setting in their OWN home
    ctx2 = ctx.browser.new_context()
    v0 = S(ctx2, url, args.timeout)
    if not v0.load():
        fail('visitor could not boot normally')
        return None
    v0.run_python("import FreeCAD as A, sys\nA.ParamGet('User parameter:BaseApp/Preferences/GateProbe').SetString('Mine', 'yes')\nA.saveParameter()\n_d=A.newDocument('MyOwnWork'); _d.addObject('Part::Box','Own'); _d.recompute()\nsys.__stderr__.write('GATE_DOC ready own\\n')")
    _wait(v0, 'GATE_DOC ready own', 60, 'console')
    time.sleep(6)          # let autosave + IDBFS persist the visitor's own work
    v0.page.close()
    # the owner: imperial units, 4 decimals, a macro; share with the environment
    s1, sid = _owner_up(ctx, url, args, fail, extra=(
        "A.ParamGet('User parameter:BaseApp/Preferences/Units').SetInt('UserSchema', 2)\n"
        "A.ParamGet('User parameter:BaseApp/Preferences/Units').SetInt('Decimals', 4)\n"
        "import os\nos.makedirs(A.getUserMacroDir(True), exist_ok=True)\n"
        "open(os.path.join(A.getUserMacroDir(True), 'GateMacro.FCMacro'), 'w').write('print(1)')\n"))
    if not sid:
        return s1
    if not _wait(s1, 'env published', 60):
        fail('the environment bundle was never published (ring: %s)' % _ring(s1)[-6:])
    # redaction, as a plain viewer over HTTP
    base = url.split('/freecad-gui')[0]
    st, body, _ = _http(base, 'POST', '/share/%s/join' % sid, {'name': 'Probe'}, {'Content-Type': 'application/json'})
    cid = json.loads(body)['client']
    st, env, _ = _http(base, 'GET', '/share/%s/env' % sid, None, {'X-Fcweb-Client': cid})
    txt = env.decode('utf-8', 'replace')
    for secret in ('WriteKey', 'AgentUrl', 'ViewerPassword', 'EditorPassword'):
        if secret in txt:
            fail('REDACTION FAILED: the published bundle contains %s' % secret)
    if '"cfg"' not in txt or 'GateMacro' not in txt:
        fail('the bundle lacks the config or the macro: %s' % txt[:200])
    else:
        print('==> bundle published: cfg + macro, no secrets')
    # the visitor joins LATER, with the owner gone
    s1.page.close()
    time.sleep(2)
    s2 = S(ctx2, url + ('&' if '?' in url else '?') + 's=' + sid, args.timeout)
    _dialogs(s2.page)
    if not s2.load():
        fail('visitor never reached Ready in session mode (%s)' % s2.phase())
        return None
    if not _wait(s2, 'session mode: own home NOT mounted', 30):
        fail('session mode did not materialize (isolation lost)')
    line = _wait(s2, 'units=', 60, 'console')
    print('==> ' + (line or 'no units line'))
    s2.run_python("import FreeCAD as A, os, sys\n_u=A.ParamGet('User parameter:BaseApp/Preferences/Units')\nsys.__stderr__.write('GATE_ENV ' + repr({'schema': _u.GetInt('UserSchema', 0), 'decimals': _u.GetInt('Decimals', 2), 'probe': A.ParamGet('User parameter:BaseApp/Preferences/GateProbe').GetString('Mine', ''), 'docs': sorted(A.listDocuments()), 'macro': os.path.exists(os.path.join(A.getUserMacroDir(True), 'GateMacro.FCMacro'))}) + '\\n')")
    r = s2.wait_for('GATE_ENV', 60)
    if not isinstance(r, dict):
        fail('no environment report from inside the session')
    else:
        print('==> inside the session: %r' % r)
        if r['schema'] != 2 or r['decimals'] != 4:
            fail('the owner\'s units did not travel: schema %r decimals %r' % (r['schema'], r['decimals']))
        if not r['macro']:
            fail('the macro did not travel')
        if r['probe']:
            fail('ISOLATION FAILED: the visitor\'s own setting is visible inside the session')
        if 'MyOwnWork' in r['docs']:
            fail('ISOLATION FAILED: the visitor\'s own document is open inside the session')
    if not _wait(s2, 'share applied v1', 90, 'console'):
        fail('the shared document did not open with the owner offline')
    else:
        print('==> opened with the owner offline')
    # leave: the visitor's own home is back, untouched
    s2.page.close()
    v1 = S(ctx2, url, args.timeout)
    if not v1.load():
        fail('visitor could not boot normally after leaving')
        return None
    time.sleep(15)          # restore-on-boot reopens their document
    v1.run_python("import FreeCAD as A, sys\nsys.__stderr__.write('GATE_BACK ' + repr({'probe': A.ParamGet('User parameter:BaseApp/Preferences/GateProbe').GetString('Mine', ''), 'docs': sorted(A.listDocuments())}) + '\\n')")
    r = s2 and v1.wait_for('GATE_BACK', 60)
    if not isinstance(r, dict) or r['probe'] != 'yes' or not any('MyOwnWork' in d for d in r['docs']):
        fail('after leaving, the visitor\'s own home is not back intact: %r' % r)
    else:
        print('==> left the session: own setting and document back, untouched')
    return v1
