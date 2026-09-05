#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Shared sessions for freecad-web: the transport-agnostic core.

    python share.py --selftest            # the check: asserts the whole protocol, no sockets
    python share.py --serve [port]        # stdlib http.server, for tools/serve-artifact.py
    python share.py --stats | --list | --purge-expired

Everything is a pure function of (method, path, headers, body) -> (status, headers, bytes).
Three callers share it: infra/session/app.py (Starlette + FastMCP in the container),
tools/serve-artifact.py (the boot gate's same-origin stand-in), and --selftest.

IDENTITY. The owner's browser invents a 128-bit key; the public session id is
sha256(key)[:32]. Proving you are the admin is showing a preimage, so this server keeps no
key, no admin token and no session table. Losing the key loses admin rights, which is why
the page also keeps it in the owner's own parameter tree.

ROLES. A viewer has the link (plus the viewer password if set) and gets a client id on
/join. An editor additionally presents the editor password and gets an EDIT TOKEN. Exactly
one edit token holds CONTROL at a time; only the holder may publish the document. The admin
alone publishes the environment, sets passwords and expiry, mints the MCP token, and can
force-release.

DURABILITY. A session has no expiry unless the admin sets one. Storage is quota-managed:
past FCWEB_SHARE_MAX_GB the least recently VIEWED no-expiry session is evicted and the
eviction is remembered, so its owner is told rather than silently losing it.

ERRORS. Every non-2xx is {"error", "code", "hint"} -- the hint is the next step, and the
page shows it verbatim. The selftest fails if any error path forgets one.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time

ID_RE = re.compile(r'[0-9a-f]{32}\Z')
TOK_RE = re.compile(r'[0-9a-f]{32,64}\Z')
PBKDF_ROUNDS = 200_000
HOLDER_SILENCE_S = 60      # a holder unseen this long can be auto-granted away
WATCHER_TTL_S = 20         # /v polls keep a watcher alive this long
ACTIVITY_MAX = 100         # bounded ring per session; no IPs, ever
LOCK = threading.RLock()   # ponytail: one global lock; per-id locks if this ever serves a crowd

CFG = {}
_now = time.time            # monkeypatched by the selftest to simulate days passing


def _cfg():
    return dict(
        dir=os.environ.get('FCWEB_SHARE_DIR', '/data'),
        max_bytes=int(os.environ.get('FCWEB_SHARE_MAX_MB', '25')) * 1048576,
        quota=int(float(os.environ.get('FCWEB_SHARE_MAX_GB', '5')) * 1073741824),
        public_url=os.environ.get('FCWEB_PUBLIC_URL', ''),   # e.g. https://fc.example.com
    )


# --------------------------------------------------------------------------- storage
def _p(i, ext):
    return os.path.join(CFG['dir'], i + ext)


def _meta(i):
    try:
        with open(_p(i, '.json'), 'rb') as f:
            return json.load(f)
    except Exception:
        return None


def _write_atomic(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_meta(i, m):
    _write_atomic(_p(i, '.json'), json.dumps(m).encode())


def _remove(i, why):
    for ext in ('.fcstd', '.env.json', '.json'):
        try:
            os.remove(_p(i, ext))
        except OSError:
            pass
    ev = _evicted()
    ev[i] = {'t': int(_now()), 'why': why}
    _write_atomic(os.path.join(CFG['dir'], 'evicted.json'), json.dumps(ev).encode())
    STATE.pop(i, None)


def _evicted():
    try:
        with open(os.path.join(CFG['dir'], 'evicted.json'), 'rb') as f:
            return json.load(f)
    except Exception:
        return {}


def _size(i):
    n = 0
    for ext in ('.fcstd', '.env.json', '.json'):
        try:
            n += os.path.getsize(_p(i, ext))
        except OSError:
            pass
    return n


def _sessions():
    out = []
    try:
        names = os.listdir(CFG['dir'])
    except OSError:
        return out
    for n in names:
        if n.endswith('.json') and not n.endswith('.env.json') and n != 'evicted.json':
            i = n[:-5]
            if ID_RE.match(i):
                out.append(i)
    return out


def _expired(m):
    return bool(m.get('expires')) and _now() > m['expires']


def _gc(incoming=0):
    """Expiry on touch, then quota: evict least-recently-viewed sessions WITHOUT an expiry
    until the incoming write fits. Never evicts a session whose owner set a date -- they
    made a decision, and quota pressure is not a reason to override it silently."""
    total = 0
    rows = []
    for i in _sessions():
        m = _meta(i)
        if m is None:
            continue
        if _expired(m):
            _remove(i, 'expired')
            continue
        s = _size(i)
        total += s
        rows.append((m.get('last_viewed', m.get('created', 0)), i, s, bool(m.get('expires'))))
    rows.sort()
    for lv, i, s, dated in rows:
        if total + incoming <= CFG['quota']:
            break
        if dated:
            continue
        _remove(i, 'quota')
        total -= s
    return total


def _pw_hash(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), PBKDF_ROUNDS).hex()


def _pw_ok(m, field, given):
    if not m.get(field):
        return True
    if not given:
        return False
    return hmac.compare_digest(_pw_hash(given, m['salt']), m[field])


def _is_admin(i, key):
    return bool(key) and TOK_RE.match(key) is not None and \
        hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest()[:32], i)


def _tok_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


# --------------------------------------------------------------------------- live state
# In memory on purpose: a restart drops control and "anyone requests and gets it" is the
# harmless recovery. Per session id.
STATE = {}


def _st(i):
    s = STATE.get(i)
    if s is None:
        s = STATE[i] = dict(
            clients={},      # client id -> {name, role, seen, edit}
            edits={},        # edit token -> client id
            holder=None,     # client id
            holder_seen=0.0,
            pending=None,    # client id asking
            tabs={},         # tab token -> {seen}
            queue=None,      # {id, code, kind, args}
            inflight=None,
            result=None,
            ev=threading.Event(),
            cmd_ev=threading.Event(),
        )
    return s


def _watching(s):
    t = _now()
    return sum(1 for c in s['clients'].values() if t - c['seen'] <= WATCHER_TTL_S)


def _name(s, cid):
    c = s['clients'].get(cid)
    return c['name'] if c else None


def _activity(m, s, cid, event):
    ring = m.setdefault('activity', [])
    ring.append({'t': int(_now()), 'name': _name(s, cid) or 'owner', 'event': event})
    del ring[:-ACTIVITY_MAX]


def _grant(s, cid, m, how):
    s['holder'] = cid
    s['holder_seen'] = _now()
    s['pending'] = None
    _activity(m, s, cid, how)


# --------------------------------------------------------------------------- responses
def _json(status, obj, extra=None):
    h = {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}
    if extra:
        h.update(extra)
    return status, h, json.dumps(obj).encode()


def _err(status, code, hint, error=None):
    return _json(status, {'error': error or code.replace('_', ' '), 'code': code, 'hint': hint})


HINTS = {
    'bad_id': 'The link is malformed. Ask the sender to copy it again from Edit > Share Session.',
    'no_session': 'This session does not exist or has ended. Ask the sender for a fresh link.',
    'evicted': 'This session was removed to free space on the server. Ask the sender to share it again.',
    'expired': 'This link has expired. Ask the sender to extend or re-share it.',
    'password_required': 'Enter the password the sender gave you.',
    'not_joined': 'Join the session first (this happens automatically when the page loads).',
    'not_editor': 'Only editors can do this. Ask the sender for the editor password.',
    'not_holder': 'Request control from the Edit menu, or fc_control_request() over MCP.',
    'not_admin': 'Only the person who shared this session can do this.',
    'too_big': 'The document is over the size limit for this server.',
    'quota': 'The server is out of space; the operator can raise FCWEB_SHARE_MAX_GB.',
    'already_pending': 'Someone else is already asking for control. Try again in a moment.',
    'no_tab': 'No browser tab is attached to this session. Open the session and tick "Allow an AI assistant" in Edit > Share Session.',
    'busy': 'One command at a time. Wait for the previous call to return.',
    'bad_request': 'The request body was not what this endpoint expects.',
}


def _fail(status, code, **kw):
    return _err(status, code, HINTS[code], **kw)


# --------------------------------------------------------------------------- handler
def handle(method, path, headers, body=b''):
    """One request in, (status, headers, bytes) out. Adds X-Fcweb-Req and logs one line."""
    rid = secrets.token_hex(2)
    t0 = _now()
    h = {k.lower(): v for k, v in headers.items()}
    with LOCK:
        status, out_h, out_b = _route(method, path.split('?', 1)[0], path, h, body)
    out_h = dict(out_h)
    out_h['X-Fcweb-Req'] = rid
    code = ''
    if status >= 400:
        try:
            code = json.loads(out_b).get('code', '')
        except Exception:
            pass
    sys.stderr.write('[share] %s %s %s %d %s %dms\n' % (
        rid, method, path[:48], status, code, int((_now() - t0) * 1000)))
    return status, out_h, out_b


def _q(fullpath, key, default=''):
    if '?' not in fullpath:
        return default
    for kv in fullpath.split('?', 1)[1].split('&'):
        if kv.startswith(key + '='):
            return kv[len(key) + 1:]
    return default


def _route(method, path, fullpath, h, body):
    if path == '/share/health':
        used = _gc()
        return _json(200, {'ok': True, 'v': 1, 'n': len(_sessions()), 'used': used,
                           'quota': CFG['quota'], 'max_mb': CFG['max_bytes'] // 1048576})

    m_share = re.match(r'/share/([0-9a-f]{32})(/[a-z/]+)?\Z', path)
    m_api = re.match(r'/api/s/([0-9a-f]{32})/(attach|cmd|result)\Z', path)
    m_mcp = re.match(r'/mcp/([0-9a-f]{32})/([0-9a-f]{32,64})\Z', path)

    if path.startswith('/share/') and not m_share:
        return _fail(400, 'bad_id')
    if m_mcp:
        return _mcp_probe(m_mcp.group(1), m_mcp.group(2))
    if m_api:
        return _relay(method, m_api.group(1), m_api.group(2), fullpath, h, body)
    if not m_share:
        return _err(404, 'not_found', 'No such endpoint.')

    i, sub = m_share.group(1), (m_share.group(2) or '')
    admin = _is_admin(i, h.get('x-fcweb-key', ''))
    s = _st(i)
    m = _meta(i)

    # ---- creation: the owner's own /join with the admin key ------------------------
    if m is None and method == 'POST' and sub == '/join' and admin:
        m = {'v': 0, 'env_v': 0, 'n': '', 't': 0, 'seen': 0, 'cam': '', 'note': '',
             'acting_as': 'human', 'salt': secrets.token_hex(16), 'pw_view': '',
             'pw_edit': '', 'agent': '', 'agent_on': False, 'expires': None,
             'created': int(_now()), 'last_viewed': int(_now()), 'activity': [],
             'owner': ''}
        _save_meta(i, m)
    if m is None:
        why = _evicted().get(i)
        if why:
            return _fail(404, 'evicted' if why['why'] == 'quota' else 'expired')
        return _fail(404, 'no_session')
    if _expired(m):
        _remove(i, 'expired')
        return _fail(404, 'expired')

    # ---- who is calling -------------------------------------------------------------
    cid = h.get('x-fcweb-client', '')
    client = s['clients'].get(cid)
    edit_tok = h.get('x-fcweb-edit', '')
    editor_cid = s['edits'].get(edit_tok)
    if client is None and editor_cid is not None:      # a valid edit token proves membership
        cid = editor_cid
        client = s['clients'].get(cid)
    is_holder = editor_cid is not None and editor_cid == s['holder']
    if client:
        client['seen'] = _now()

    if method == 'POST' and sub == '/join':
        try:
            b = json.loads(body or b'{}')
        except Exception:
            return _fail(400, 'bad_request')
        if not admin and not _pw_ok(m, 'pw_view', b.get('viewer_pw', '')):
            return _fail(401, 'password_required')
        cid = secrets.token_hex(8)
        role = 'admin' if admin else 'viewer'
        tok = None
        if admin or (m.get('pw_edit') and _pw_ok(m, 'pw_edit', b.get('editor_pw', ''))
                     and b.get('editor_pw')):
            role = 'admin' if admin else 'editor'
            tok = secrets.token_hex(16)
            s['edits'][tok] = cid
        name = re.sub(r'[^\w .\-]', '', str(b.get('name', '')))[:32] or 'Guest'
        s['clients'][cid] = {'name': name, 'role': role, 'seen': _now(), 'edit': tok}
        if admin:
            m['owner'] = name
            if s['holder'] is None or s['holder'] not in s['clients']:
                _grant(s, cid, m, 'owner joined')
        m['last_viewed'] = int(_now())
        _activity(m, s, cid, 'joined as ' + role)
        _save_meta(i, m)
        try:
            env = json.loads(open(_p(i, '.env.json'), 'rb').read()) if os.path.exists(_p(i, '.env.json')) else None
        except Exception:
            env = None
        return _json(200, {'client': cid, 'role': role, 'edit': tok, 'name': name,
                           'owner': m.get('owner', ''), 'document': m.get('n', ''),
                           'addons': (env or {}).get('addons', []), 'v': m['v'],
                           'env_v': m['env_v'], 'holder': _name(s, s['holder'])})

    # everything below needs a joined client or the admin key
    if not client and not admin:
        return _fail(401, 'not_joined')

    if method == 'GET' and sub == '/v':
        stale = s['holder'] is not None and _now() - s['holder_seen'] > HOLDER_SILENCE_S
        return _json(200, {
            'v': m['v'], 'env_v': m['env_v'], 'n': m['n'], 't': m['t'], 'seen': m['seen'],
            'cam': m['cam'], 'acting_as': m['acting_as'],
            'note': m['note'] if _now() - m.get('note_t', 0) < 60 else '',   # an activity line, not a label
            'holder': {'name': _name(s, s['holder']), 'silent': stale} if s['holder'] else None,
            'pending': {'name': _name(s, s['pending'])} if s['pending'] else None,
            'watching': _watching(s), 'expires': m['expires'], 'owner': m.get('owner', ''),
            'you': {'holder': client is not None and cid == s['holder'],
                    'role': client['role'] if client else 'admin'}})

    if method == 'GET' and sub == '':
        try:
            data = open(_p(i, '.fcstd'), 'rb').read()
        except OSError:
            return _fail(404, 'no_session')
        if h.get('if-none-match') == '"%d"' % m['v']:
            return 304, {'ETag': '"%d"' % m['v']}, b''
        m['last_viewed'] = int(_now())
        _save_meta(i, m)
        return 200, {'Content-Type': 'application/octet-stream', 'ETag': '"%d"' % m['v'],
                     'Cache-Control': 'no-store'}, data

    if method == 'GET' and sub == '/env':
        try:
            return 200, {'Content-Type': 'application/json', 'Cache-Control': 'no-store',
                         'ETag': '"%d"' % m['env_v']}, open(_p(i, '.env.json'), 'rb').read()
        except OSError:
            return _json(200, {})

    # ---- holder-only writes --------------------------------------------------------
    if method == 'PUT' and sub == '':
        if editor_cid is None:
            return _fail(403, 'not_editor')
        if not is_holder:
            return _fail(409, 'not_holder')
        if len(body) == 0 or len(body) > CFG['max_bytes']:
            return _fail(413, 'too_big')
        if _gc(len(body)) + len(body) > CFG['quota']:
            return _fail(507, 'quota')
        _write_atomic(_p(i, '.fcstd'), body)
        m['v'] += 1
        m['t'] = int(_now())
        m['seen'] = _now()
        s['holder_seen'] = _now()
        m['n'] = re.sub(r'[^\w .\-]', '', h.get('x-fcweb-name', ''))[:64] or m['n'] or 'shared.FCStd'
        _save_meta(i, m)
        return _json(200, {'v': m['v']})

    if method == 'PUT' and sub == '/live':
        if editor_cid is None:
            return _fail(403, 'not_editor')
        if not is_holder:
            return _fail(409, 'not_holder')
        try:
            b = json.loads(body or b'{}')
        except Exception:
            return _fail(400, 'bad_request')
        m['cam'] = str(b.get('cam', m['cam']))[:2000]
        if b.get('note'):                      # a heartbeat carries no note and must not wipe one
            m['note'] = str(b['note'])[:200]
            m['note_t'] = _now()
        m['acting_as'] = 'agent' if b.get('acting_as') == 'agent' else 'human'
        m['seen'] = _now()
        s['holder_seen'] = _now()
        _save_meta(i, m)
        return _json(200, {'ok': True})

    # ---- control -------------------------------------------------------------------
    if method == 'POST' and sub == '/control/request':
        if editor_cid is None:
            return _fail(403, 'not_editor')
        try:
            b = json.loads(body or b'{}')
        except Exception:
            return _fail(400, 'bad_request')
        if s['holder'] == editor_cid:
            return _json(200, {'granted': True, 'already': True})
        free = s['holder'] is None or s['holder'] not in s['clients'] \
            or _now() - s['holder_seen'] > HOLDER_SILENCE_S
        if free or b.get('force'):
            _grant(s, editor_cid, m, 'took control' if b.get('force') and not free else 'granted control')
            _save_meta(i, m)
            return _json(200, {'granted': True, 'forced': bool(b.get('force')) and not free})
        if s['pending'] and s['pending'] != editor_cid and s['pending'] in s['clients']:
            return _fail(409, 'already_pending')
        s['pending'] = editor_cid
        _activity(m, s, editor_cid, 'asked for control')
        _save_meta(i, m)
        return _json(202, {'granted': False, 'holder': _name(s, s['holder'])})

    if method == 'POST' and sub == '/control/grant':
        if not is_holder:
            return _fail(409, 'not_holder')
        try:
            b = json.loads(body or b'{}')
        except Exception:
            return _fail(400, 'bad_request')
        if not s['pending']:
            return _json(200, {'ok': True, 'pending': None})
        if b.get('deny'):
            s['pending'] = None
            return _json(200, {'ok': True, 'denied': True})
        _grant(s, s['pending'], m, 'was granted control')
        _save_meta(i, m)
        return _json(200, {'ok': True, 'holder': _name(s, s['holder'])})

    if method == 'POST' and sub == '/control/release':
        if not is_holder and not admin:
            return _fail(409, 'not_holder')
        who = s['holder']
        s['holder'] = None
        _activity(m, s, who, 'released control' if is_holder else 'control released by owner')
        _save_meta(i, m)
        return _json(200, {'ok': True})

    # ---- admin ---------------------------------------------------------------------
    if not admin:
        return _fail(403, 'not_admin')

    if method == 'PUT' and sub == '/env':
        try:
            env = json.loads(body)
            assert isinstance(env, dict)
        except Exception:
            return _fail(400, 'bad_request')
        if len(body) > CFG['max_bytes']:
            return _fail(413, 'too_big')
        old = b''
        try:
            old = open(_p(i, '.env.json'), 'rb').read()
        except OSError:
            pass
        if hashlib.sha256(old).digest() != hashlib.sha256(body).digest():
            _write_atomic(_p(i, '.env.json'), body)
            m['env_v'] += 1
            _save_meta(i, m)
        return _json(200, {'env_v': m['env_v']})

    if method == 'PUT' and sub == '/passwords':
        try:
            b = json.loads(body or b'{}')
        except Exception:
            return _fail(400, 'bad_request')
        for k, f in (('viewer', 'pw_view'), ('editor', 'pw_edit')):
            if k in b:
                m[f] = _pw_hash(b[k], m['salt']) if b[k] else ''
        _save_meta(i, m)
        return _json(200, {'ok': True})

    if method == 'PUT' and sub == '/expiry':
        try:
            b = json.loads(body or b'{}')
            exp = b.get('expires')
            assert exp is None or isinstance(exp, (int, float))
        except Exception:
            return _fail(400, 'bad_request')
        m['expires'] = exp
        _save_meta(i, m)
        return _json(200, {'expires': exp})

    if method == 'GET' and sub == '/activity':
        return _json(200, {'activity': m.get('activity', []), 'watching': _watching(s),
                           'views': sum(1 for a in m.get('activity', []) if a['event'].startswith('joined'))})

    if sub == '/agent' and method in ('POST', 'DELETE'):
        if method == 'DELETE':
            m['agent'] = ''
            m['agent_on'] = False
            _save_meta(i, m)
            return _json(200, {'ok': True})
        tok = secrets.token_hex(16)
        m['agent'] = _tok_hash(tok)
        m['agent_on'] = True
        _save_meta(i, m)
        s['tabs'].clear()      # a regenerated URL invalidates every attached tab too
        return _json(200, {'url': '%s/mcp/%s/%s' % (CFG['public_url'].rstrip('/'), i, tok)})

    if method == 'DELETE' and sub == '':
        _remove(i, 'stopped')
        return 204, {}, b''

    return _err(405, 'method_not_allowed', 'This endpoint does not accept that method.')


def _agent_ok(i, tok):
    m = _meta(i)
    return bool(m and m.get('agent_on') and m.get('agent') and TOK_RE.match(tok)
                and hmac.compare_digest(_tok_hash(tok), m['agent']) and not _expired(m))


def _mcp_probe(i, tok):
    """The auth gate app.py puts in front of FastMCP. 404, never 401: a closed or
    nonexistent endpoint must be indistinguishable from a guess."""
    if not _agent_ok(i, tok):
        return _err(404, 'not_found', 'No such endpoint.')
    return _json(200, {'ok': True, 'session': i})


# --------------------------------------------------------------------------- relay
def _relay(method, i, op, fullpath, h, body):
    s = _st(i)
    if op == 'attach':
        if method != 'POST' or not _agent_ok(i, h.get('x-fcweb-agent', '')):
            return _err(404, 'not_found', 'No such endpoint.')
        t = secrets.token_hex(16)
        s['tabs'] = {t: {'seen': _now()}}      # one relay target at a time; the newest wins
        return _json(200, {'tab': t})
    tab = h.get('x-fcweb-tab', '')
    if tab not in s['tabs']:
        return _err(409, 'stale_tab', 'This tab is no longer the relay target; re-attach.')
    s['tabs'][tab]['seen'] = _now()
    if op == 'cmd' and method == 'GET':
        wait = min(float(_q(fullpath, 'wait', '0') or 0), 25.0)
        if s['queue'] is None and wait > 0:
            s['cmd_ev'].clear()
            LOCK.release()
            try:
                s['cmd_ev'].wait(wait)
            finally:
                LOCK.acquire()
        if s['queue'] is None:
            return 204, {}, b''
        cmd = s['queue']
        s['queue'] = None
        s['inflight'] = cmd['id']
        return _json(200, cmd)
    if op == 'result' and method == 'POST':
        try:
            b = json.loads(body)
        except Exception:
            return _fail(400, 'bad_request')
        if b.get('id') != s['inflight']:
            return _err(409, 'stale_result', 'That command is no longer in flight.')
        s['inflight'] = None
        s['result'] = b
        s['ev'].set()
        return _json(200, {'ok': True})
    return _err(405, 'method_not_allowed', 'This endpoint does not accept that method.')


def submit(i, tok, kind, args, timeout=30.0):
    """app.py's entry: run one tool in the attached tab and wait for its result.
    Returns the result dict, or an {ok:false, code, hint} dict. Never raises."""
    with LOCK:
        if not _agent_ok(i, tok):
            return {'ok': False, 'code': 'not_found', 'hint': HINTS['no_session']}
        s = _st(i)
        live = [t for t, v in s['tabs'].items() if _now() - v['seen'] <= HOLDER_SILENCE_S]
        if not live:
            return {'ok': False, 'code': 'no_tab', 'hint': HINTS['no_tab']}
        if s['queue'] is not None or s['inflight'] is not None:
            return {'ok': False, 'code': 'busy', 'hint': HINTS['busy']}
        cid = secrets.token_hex(4)
        s['queue'] = {'id': cid, 'kind': kind, 'args': args}
        s['result'] = None
        s['ev'].clear()
        s['cmd_ev'].set()
    ok = s['ev'].wait(min(timeout, 120.0))
    with LOCK:
        if not ok:
            s['queue'] = None
            s['inflight'] = None
            return {'ok': False, 'code': 'timeout',
                    'hint': 'The tab did not answer in %ds -- it may be busy in a long operation '
                            '(document restore, recompute). Try fc_status, then again.' % int(timeout)}
        r = s['result']
        s['result'] = None
        return r


# --------------------------------------------------------------------------- selftest
def selftest():
    import tempfile
    global _now
    clock = [1_700_000_000.0]
    _now = lambda: clock[0]
    CFG.update(_cfg())
    CFG.update(dir=tempfile.mkdtemp(), max_bytes=1024, quota=4096, public_url='https://x.test')
    STATE.clear()

    def call(method, path, body=b'', **hdr):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        st, hh, bb = handle(method, path, {k.replace('_', '-'): v for k, v in hdr.items()}, body)
        try:
            j = json.loads(bb) if bb else None
        except Exception:
            j = None
        assert 'X-Fcweb-Req' in hh, 'every response carries a request id'
        if st >= 400 and path.startswith('/share/'):
            assert j and j.get('code') and j.get('hint'), 'error without code/hint: %s %s' % (st, bb)
        return st, j, hh, bb

    key = 'a' * 64
    sid = hashlib.sha256(key.encode()).hexdigest()[:32]

    assert call('GET', '/share/health')[1]['ok'] is True
    assert call('GET', '/share/')[0] == 400                      # not enumerable
    assert call('GET', '/share/' + sid + '/v')[0] == 404          # unknown id
    assert call('POST', '/share/' + sid + '/join', {'name': 'Eve'}, X_Fcweb_Key='b' * 64)[0] == 404

    # owner creates by joining with the admin key; holds control by default
    st, j, _, _ = call('POST', '/share/' + sid + '/join', {'name': 'Alice'}, X_Fcweb_Key=key)
    assert st == 200 and j['role'] == 'admin' and j['edit'], j
    owner, oedit = j['client'], j['edit']
    st, j, _, _ = call('GET', '/share/%s/v' % sid, X_Fcweb_Client=owner)
    assert j['holder']['name'] == 'Alice' and j['you']['holder'] is True

    # document publish: wrong/no edit token, then holder
    assert call('PUT', '/share/' + sid, b'ONE', X_Fcweb_Client=owner)[0] == 403
    assert call('PUT', '/share/' + sid, b'ONE', X_Fcweb_Edit='zz')[0] == 401   # not joined at all
    st, j, _, _ = call('PUT', '/share/' + sid, b'ONE', X_Fcweb_Edit=oedit, X_Fcweb_Name='Box.FCStd')
    assert st == 200 and j['v'] == 1
    assert call('PUT', '/share/' + sid, b'x' * 2048, X_Fcweb_Edit=oedit)[0] == 413
    assert call('GET', '/share/' + sid, X_Fcweb_Client=owner)[3] == b'ONE'
    assert call('GET', '/share/' + sid, X_Fcweb_Client=owner, If_None_Match='"1"')[0] == 304

    # env: admin only; env_v advances only on change
    env = {'cfg': '<x/>', 'addons': [{'repo': 'o/r', 'ref': 'main'}]}
    assert call('PUT', '/share/%s/env' % sid, env, X_Fcweb_Edit=oedit)[0] == 403
    assert call('PUT', '/share/%s/env' % sid, env, X_Fcweb_Key=key)[1]['env_v'] == 1
    assert call('PUT', '/share/%s/env' % sid, env, X_Fcweb_Key=key)[1]['env_v'] == 1
    assert call('PUT', '/share/%s/env' % sid, {'cfg': '<y/>'}, X_Fcweb_Key=key)[1]['env_v'] == 2

    # passwords: viewer gates join (and so /v, body, /env); editor gates the edit token
    assert call('PUT', '/share/%s/passwords' % sid, {'viewer': 'v1', 'editor': 'e1'}, X_Fcweb_Edit=oedit)[0] == 403
    assert call('PUT', '/share/%s/passwords' % sid, {'viewer': 'v1', 'editor': 'e1'}, X_Fcweb_Key=key)[0] == 200
    assert call('POST', '/share/%s/join' % sid, {'name': 'Bob'})[0] == 401
    assert call('POST', '/share/%s/join' % sid, {'name': 'Bob', 'viewer_pw': 'wrong'})[0] == 401
    st, j, _, _ = call('POST', '/share/%s/join' % sid, {'name': 'Bob', 'viewer_pw': 'v1'})
    assert st == 200 and j['role'] == 'viewer' and j['edit'] is None, 'viewer pw must never yield an edit token'
    bob = j['client']
    assert call('GET', '/share/%s/v' % sid)[0] == 401              # not joined -> no read
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=bob)[0] == 200
    assert call('GET', '/share/%s/env' % sid, X_Fcweb_Client=bob)[3] == b'{"cfg": "<y/>"}'
    st, j, _, _ = call('POST', '/share/%s/join' % sid, {'name': 'Cy', 'viewer_pw': 'v1', 'editor_pw': 'e1'})
    assert st == 200 and j['role'] == 'editor' and j['edit']
    cy, cedit = j['client'], j['edit']
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=owner)[1]['watching'] == 3

    # control: viewer cannot request or force; editor queues; holder grants
    assert call('POST', '/share/%s/control/request' % sid, {'force': True}, X_Fcweb_Client=bob)[0] == 403
    st, j, _, _ = call('POST', '/share/%s/control/request' % sid, {}, X_Fcweb_Edit=cedit)
    assert st == 202 and j['granted'] is False
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=owner)[1]['pending']['name'] == 'Cy'
    assert call('PUT', '/share/' + sid, b'TWO', X_Fcweb_Edit=cedit)[0] == 409    # not holder
    assert call('GET', '/share/' + sid, X_Fcweb_Client=bob)[3] == b'ONE'         # bytes unchanged
    assert call('POST', '/share/%s/control/grant' % sid, {}, X_Fcweb_Edit=cedit)[0] == 409
    assert call('POST', '/share/%s/control/grant' % sid, {}, X_Fcweb_Edit=oedit)[1]['holder'] == 'Cy'
    assert call('PUT', '/share/' + sid, b'TWO', X_Fcweb_Edit=cedit)[1]['v'] == 2
    assert call('PUT', '/share/' + sid, b'LATE', X_Fcweb_Edit=oedit)[0] == 409  # displaced -> refused
    assert call('GET', '/share/' + sid, X_Fcweb_Client=bob)[3] == b'TWO'
    # force: editor seizes from an active holder immediately
    assert call('PUT', '/share/%s/live' % sid, {'cam': 'c1'}, X_Fcweb_Edit=cedit)[0] == 200
    st, j, _, _ = call('POST', '/share/%s/control/request' % sid, {'force': True}, X_Fcweb_Edit=oedit)
    assert st == 200 and j['forced'] is True
    assert call('PUT', '/share/%s/live' % sid, {'cam': 'c2'}, X_Fcweb_Edit=cedit)[0] == 409
    # release, then auto-grant after silence
    assert call('POST', '/share/%s/control/release' % sid, {}, X_Fcweb_Edit=cedit)[0] == 409
    assert call('POST', '/share/%s/control/release' % sid, {}, X_Fcweb_Edit=oedit)[0] == 200
    assert call('POST', '/share/%s/control/request' % sid, {}, X_Fcweb_Edit=cedit)[1]['granted'] is True
    clock[0] += HOLDER_SILENCE_S + 1
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=owner)[1]['holder']['silent'] is True
    assert call('POST', '/share/%s/control/request' % sid, {}, X_Fcweb_Edit=oedit)[1]['granted'] is True
    # admin force-release without holding
    call('POST', '/share/%s/control/request' % sid, {'force': True}, X_Fcweb_Edit=cedit)
    assert call('POST', '/share/%s/control/release' % sid, {}, X_Fcweb_Key=key)[0] == 200

    # activity: bounded, no IP, counts joins
    st, j, _, _ = call('GET', '/share/%s/activity' % sid, X_Fcweb_Key=key)
    assert j['views'] == 3 and all(set(a) == {'t', 'name', 'event'} for a in j['activity'])
    assert call('GET', '/share/%s/activity' % sid, X_Fcweb_Edit=cedit)[0] == 403

    # MCP token: closed until minted; wrong token / other session / off all 404
    assert call('POST', '/mcp/%s/%s' % (sid, 'c' * 32))[0] == 404
    assert call('POST', '/share/%s/agent' % sid, X_Fcweb_Edit=oedit)[0] == 403
    st, j, _, _ = call('POST', '/share/%s/agent' % sid, X_Fcweb_Key=key)
    tok = j['url'].rsplit('/', 1)[1]
    assert j['url'].startswith('https://x.test/mcp/' + sid + '/') and len(tok) == 32
    assert call('POST', '/mcp/%s/%s' % (sid, tok))[0] == 200
    assert call('POST', '/mcp/%s/%s' % (sid, 'e' * 32))[0] == 404
    assert call('POST', '/mcp/%s/%s' % ('0' * 32, tok))[0] == 404
    assert call('POST', '/mcp/%s/%s' % (sid, 'e1'))[0] == 404          # editor password as token
    st, j2, _, _ = call('POST', '/share/%s/agent' % sid, X_Fcweb_Key=key)
    tok2 = j2['url'].rsplit('/', 1)[1]
    assert call('POST', '/mcp/%s/%s' % (sid, tok))[0] == 404          # regenerate kills the old
    assert call('POST', '/mcp/%s/%s' % (sid, tok2))[0] == 200
    # relay: attach needs the MCP token; submit needs a live tab; one at a time
    assert call('POST', '/api/s/%s/attach' % sid, X_Fcweb_Agent='x' * 32)[0] == 404
    assert submit(sid, tok2, 'eval', {'code': '1'})['code'] == 'no_tab'
    st, j, _, _ = call('POST', '/api/s/%s/attach' % sid, X_Fcweb_Agent=tok2)
    tab = j['tab']
    assert call('GET', '/api/s/%s/cmd' % sid, X_Fcweb_Tab='nope')[0] == 409
    assert call('GET', '/api/s/%s/cmd?wait=0' % sid, X_Fcweb_Tab=tab)[0] == 204
    done = {}

    def tab_side():
        for _ in range(200):
            st, j, _, _ = call('GET', '/api/s/%s/cmd?wait=0.05' % sid, X_Fcweb_Tab=tab)
            if st == 200:
                done['cmd'] = j
                call('POST', '/api/s/%s/result' % sid, {'id': j['id'], 'ok': True, 'out': '42'}, X_Fcweb_Tab=tab)
                return
            time.sleep(0.01)
    th = threading.Thread(target=tab_side)
    th.start()
    r = submit(sid, tok2, 'eval', {'code': 'print(6*7)'}, timeout=5)
    th.join()
    assert r == {'id': done['cmd']['id'], 'ok': True, 'out': '42'} and done['cmd']['kind'] == 'eval', r
    assert call('DELETE', '/share/%s/agent' % sid, X_Fcweb_Key=key)[0] == 200
    assert call('POST', '/mcp/%s/%s' % (sid, tok2))[0] == 404             # AllowAgent off

    # durability: no expiry -> served 30 simulated days later; expiry -> 404 after it
    clock[0] += 30 * 86400
    assert call('GET', '/share/' + sid, X_Fcweb_Client=bob)[3] == b'TWO'
    assert call('PUT', '/share/%s/expiry' % sid, {'expires': clock[0] + 10}, X_Fcweb_Key=key)[0] == 200
    clock[0] += 11
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=bob)[1]['code'] == 'expired'
    st, j, _, _ = call('POST', '/share/%s/join' % sid, {'name': 'Alice'}, X_Fcweb_Key=key)   # owner re-creates
    assert st == 200
    assert call('PUT', '/share/' + sid, b'w' * 900, X_Fcweb_Edit=j['edit'])[1]['v'] == 1     # expiry wiped the bytes
    bob = call('POST', '/share/%s/join' % sid, {'name': 'Bob'})[1]['client']              # passwords were wiped too
    clock[0] += 5                                                                          # sid is now strictly the oldest-viewed

    # quota: least recently viewed no-expiry session evicted; dated ones spared; owner told
    def mk(k, size):
        s_ = hashlib.sha256(k.encode()).hexdigest()[:32]
        st, j, _, _ = call('POST', '/share/%s/join' % s_, {'name': 'O'}, X_Fcweb_Key=k)
        assert call('PUT', '/share/' + s_, b'z' * size, X_Fcweb_Edit=j['edit'])[0] == 200, s_
        return s_, j
    CFG['quota'] = 10 ** 7
    sa, ja = mk('1' * 64, 900)
    clock[0] += 5
    sb, jb = mk('2' * 64, 900)
    call('PUT', '/share/%s/expiry' % sb, {'expires': clock[0] + 99999}, X_Fcweb_Key='2' * 64)
    # room for exactly sa+sb+one more like them, NOT sid: the third write must evict one
    CFG['quota'] = _size(sa) + _size(sb) + _size(sa) + 400
    clock[0] += 5
    call('GET', '/share/' + sa, X_Fcweb_Client=ja['client'])          # sa viewed now: newer than sid
    clock[0] += 5
    sc, jc = mk('3' * 64, 900)                                          # forces an eviction
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=bob)[1]['code'] == 'evicted', 'oldest no-expiry goes'
    assert call('GET', '/share/%s/v' % sb, X_Fcweb_Client=jb['client'])[0] == 200, 'dated session spared'
    assert call('GET', '/share/%s/v' % sa, X_Fcweb_Client=ja['client'])[0] == 200

    # stop
    assert call('DELETE', '/share/' + sc, X_Fcweb_Edit=jc['edit'])[0] == 403
    assert call('DELETE', '/share/' + sc, X_Fcweb_Key='3' * 64)[0] == 204
    assert call('GET', '/share/%s/v' % sc, X_Fcweb_Client=jc['client'])[0] == 404
    assert call('POST', '/share/' + sa, b'', X_Fcweb_Key='1' * 64)[0] == 405

    _now = time.time
    print('share.py selftest OK')


# --------------------------------------------------------------------------- cli
class _Handler(__import__('http.server').server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _go(self, method):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b''
        st, h, b = handle(method, self.path, dict(self.headers), body)
        self.send_response(st)
        for k, v in h.items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        if method != 'HEAD':
            self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self): self._go('GET')
    def do_POST(self): self._go('POST')
    def do_PUT(self): self._go('PUT')
    def do_DELETE(self): self._go('DELETE')


def main(argv):
    CFG.update(_cfg())
    if argv[1:2] == ['--selftest']:
        selftest()
        return 0
    os.makedirs(CFG['dir'], exist_ok=True)
    if argv[1:2] == ['--stats']:
        used = _gc()
        print('sessions=%d used=%.1fMB quota=%.1fGB evicted=%d' % (
            len(_sessions()), used / 1048576, CFG['quota'] / 1073741824, len(_evicted())))
        return 0
    if argv[1:2] == ['--list']:
        for i in _sessions():
            m = _meta(i) or {}
            print(i, m.get('n', ''), 'v%d' % m.get('v', 0), '%.1fMB' % (_size(i) / 1048576),
                  'expires=%s' % m.get('expires'))
        return 0
    if argv[1:2] == ['--purge-expired']:
        _gc()
        return 0
    if argv[1:2] == ['--serve']:
        import socketserver
        port = int(argv[2]) if len(argv) > 2 else 8000
        srv = socketserver.ThreadingTCPServer(('0.0.0.0', port), _Handler)
        srv.daemon_threads = True
        sys.stderr.write('[share] listening on :%d dir=%s max=%dMB quota=%.1fGB sessions=%d\n' % (
            port, CFG['dir'], CFG['max_bytes'] // 1048576, CFG['quota'] / 1073741824, len(_sessions())))
        srv.serve_forever()
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
