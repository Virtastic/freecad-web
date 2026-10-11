#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Shared sessions for freecad-web: the transport-agnostic core.

    python share.py --selftest            # the check: asserts the whole protocol, no sockets
    python share.py --serve [port]        # stdlib http.server, for tools/serve-artifact.py
    python share.py --stats | --list | --files | --purge-expired

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

SERVER FILES (/files/*, opt-in). A separate, much smaller store for documents a user
chooses to keep on the server, so they can be reopened later or from another machine --
the thing a browser-only IDBFS home cannot do. It is OFF unless FCWEB_FILES=1, because it
is the one part of this service that moves a user's model off their machine and the site
otherwise promises that nothing leaves the browser.

Namespaced, not per-user: the browser invents a 32-hex namespace key and keeps it in
localStorage, presenting it as X-Fcweb-Ns. So there are no accounts and no login, one
browser is one folder, and a second browser on the same box gets its own. Like a session
id it is the only key to anything, so a wrong or absent one is 404, never 403 -- a folder
cannot be probed by guessing. No IP, no name, no document metadata beyond name, size and
time.

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
import unicodedata
from urllib.parse import quote, unquote

ID_RE = re.compile(r'[0-9a-f]{32}\Z')
TOK_RE = re.compile(r'[0-9a-f]{32,64}\Z')
# A document name: letters and digits in any script, plus space, dot, dash and underscore.
# Unicode on purpose -- people name files after what they are building. No path separator,
# no leading dot, nothing over 64 characters. The name is HASHED, never used as a path, so
# this is about keeping the listing honest rather than about safety.
NAME_RE = re.compile(r'[\w .-]+\Z', re.UNICODE)
PBKDF_ROUNDS = 200_000
V0_TTL_S = 3600.0                  # a session that never published anything
KEEP_S = 86400.0                   # viewed this recently: quota pressure must not evict it
HOLDER_SILENCE_S = 60      # a holder unseen this long can be auto-granted away
WATCHER_TTL_S = 20         # /v polls keep a watcher alive this long
ACTIVITY_MAX = 100         # bounded ring per session; no IPs, ever
LOCK = threading.RLock()   # ponytail: one global lock; per-id locks if this ever serves a crowd

CFG = {}
_now = time.time            # monkeypatched by the selftest to simulate days passing


def _cfg():
    d = os.environ.get('FCWEB_SHARE_DIR', '/data')
    return dict(
        dir=d,
        max_bytes=int(os.environ.get('FCWEB_SHARE_MAX_MB', '25')) * 1048576,
        quota=int(float(os.environ.get('FCWEB_SHARE_MAX_GB', '5')) * 1073741824),
        public_url=os.environ.get('FCWEB_PUBLIC_URL', ''),   # e.g. https://fc.example.com
        # Server files: a separate opt-in store. Off by default -- see the module docstring.
        files_on=os.environ.get('FCWEB_FILES', '0').strip().lower() in ('1', 'on', 'true', 'yes'),
        files_dir=os.environ.get('FCWEB_FILES_DIR', os.path.join(d, 'files')),
        files_quota=int(float(os.environ.get('FCWEB_FILES_MAX_GB', '2')) * 1073741824),
        # A ceiling on the store as a whole. The per-folder quota above cannot do this job:
        # anyone can mint a namespace, so N visitors with a 2 GB folder each is unbounded
        # disk. This is the operator's backstop and nothing is ever evicted to stay under
        # it -- a write is refused instead, same rule as a full folder.
        files_total=int(float(os.environ.get('FCWEB_FILES_TOTAL_GB', '20')) * 1073741824),
        # An optional SHARED folder key. Set it and every browser that presents it reaches
        # the same folder, which is what makes "open it on another machine" possible at all:
        # a per-browser key cannot cross a machine by construction, and there is no way to
        # copy one across. Unset, each browser is its own folder as before.
        #
        # The folder NAME is derived from the key with sha256, never the key itself, so a
        # secret pasted into a chat or a screenshot never becomes a directory name on disk.
        # The comparison is constant-time. A browser presenting nothing or the wrong key is
        # refused as if the folder did not exist, same rule as a session id.
        files_key=os.environ.get('FCWEB_FILES_KEY', '').strip(),
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
        # ponytail: O(n) scandir per GC pass; an index file if the volume ever holds thousands
        if n.endswith('.json') and not n.endswith('.env.json') and n != 'evicted.json':
            i = n[:-5]
            if ID_RE.match(i):
                out.append(i)
    return out


def _expired(m):
    return bool(m.get('expires')) and _now() > m['expires']


_HEALTH_GC = [0.0, 0]          # when we last swept for /share/health, and what it found


def _gc(incoming=0):
    """Expiry on touch, then quota: evict least-recently-viewed sessions WITHOUT an expiry
    until the incoming write fits. Never evicts a session whose owner set a date -- they
    made a decision, and quota pressure is not a reason to override it silently.

    Nor a session someone is still looking at. On a public origin anyone can create one, so
    an unbounded upload would otherwise delete a stranger's model to make room; refusing the
    write is the honest failure. A session still at v0 an hour on never published anything --
    the page publishes within seconds of Start sharing -- so it is an abandoned one."""
    total = 0
    rows = []
    for i in _sessions():
        m = _meta(i)
        if m is None:
            continue
        if _expired(m):
            _remove(i, 'expired')
            continue
        if not m.get('v') and _now() - m.get('created', 0) > V0_TTL_S:
            _remove(i, 'expired')
            continue
        s = _size(i)
        total += s
        rows.append((m.get('last_viewed', m.get('created', 0)), i, s, bool(m.get('expires'))))
    rows.sort()
    for lv, i, s, dated in rows:
        if total + incoming <= CFG['quota']:
            break
        if dated or _now() - lv < KEEP_S:
            continue          # dated, or someone opened it today: not ours to delete
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
            kicked={},       # client id -> when, so their tab can be told why
            queue=None,      # {id, code, kind, args}
            inflight=None,
            result=None,
            ev=threading.Event(),
            cmd_ev=threading.Event(),
            turn=threading.Lock(),   # submit() callers take turns instead of being refused
        )
    return s


def _people(s):
    """Everyone currently in the session: the list the panel shows and acts on.

    The client id travels because the actions need something to name a person BY --
    display names are self-declared and two people can pick the same one. It is only
    ever handed to people already in the session."""
    t = _now()
    out = []
    for cid, c in s['clients'].items():
        if t - c['seen'] > WATCHER_TTL_S:
            continue
        out.append({'id': cid, 'name': c['name'], 'role': c['role'],
                    'holder': cid == s['holder'], 'asking': cid == s['pending'],
                    'idle': int(t - c['seen'])})
    # One row per person, not per page load. Every reload mints a new client id, so
    # someone who refreshed a few times filled the list with copies of their own name
    # until each aged out. Keep the freshest, and let it carry the holder mark.
    best = {}
    for x in out:
        k = (x['name'] or '').strip().lower()
        cur = best.get(k)
        if cur is None:
            best[k] = x
        elif x['idle'] < cur['idle']:
            x['holder'] = x['holder'] or cur['holder']
            x['asking'] = x['asking'] or cur['asking']
            best[k] = x
        else:
            cur['holder'] = cur['holder'] or x['holder']
            cur['asking'] = cur['asking'] or x['asking']
    out = list(best.values())
    out.sort(key=lambda x: (not x['holder'], x['name'].lower()))
    return out


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
    # Holding control IS the right to publish, so a client granted it gets an edit token
    # even if they never presented the editor password: a human decided to hand it over.
    c = s['clients'].get(cid)
    if c is not None and not c.get('edit'):
        tok = secrets.token_hex(16)
        s['edits'][tok] = cid
        c['edit'] = tok
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
    'files_off': 'This server does not keep documents. Everything stays in this browser; ask the operator to start it with FCWEB_FILES=1.',
    'no_namespace': 'No folder was named. If this server uses a shared folder key, paste it into '
                    'Edit > Server Files...; otherwise clear the site\'s data to start a fresh folder.',
    'no_file': 'That file is not in this folder any more. Refresh the list.',
    'no_session': 'This session does not exist or has ended. Ask the sender for a fresh link.',
    'evicted': 'This session was removed to free space on the server. Ask the sender to share it again.',
    'expired': 'This link has expired. Ask the sender to extend or re-share it.',
    'password_required': 'Enter the password the sender gave you.',
    'not_joined': 'Join the session first (this happens automatically when the page loads).',
    'not_editor': 'Only editors can do this. Ask the sender for the editor password.',
    'not_holder': 'Request control from the Edit menu, or fc_control_request() over MCP.',
    'not_admin': 'Only the person who shared this session can do this.',
    'removed': 'The owner removed you from this session. Ask them for a new link.',
    'no_client': 'That person is no longer in the session.',
    'too_big': 'The document is over the size limit for this server.',
    'quota': 'The server is out of space; the operator can raise FCWEB_SHARE_MAX_GB.',
    'already_pending': 'Someone else is already asking for control. Try again in a moment.',
    'no_holder_to_grant': 'Nobody is holding control right now, so there is no one to grant it. The editor password lets you take it yourself.',
    'no_tab': 'No browser tab is attached. The OWNER\'s FreeCAD tab -- the one that ticked "Allow an AI assistant" in Edit > Share Session -- must be open; a joined viewer\'s tab does not relay.',
    'busy': 'Another command was still running when yours timed out waiting its turn. Retry.',
    'bad_request': 'The request body was not what this endpoint expects.',
}


def _fail(status, code, **kw):
    return _err(status, code, HINTS[code], **kw)


# --------------------------------------------------------------------------- server files
# A folder per browser, addressed by a namespace key the browser invents and keeps. The key
# is the only thing standing between a stranger's guess and someone else's models, so it is
# checked for shape and a wrong one is indistinguishable from a missing folder.
def _ns_dir(ns):
    return os.path.join(CFG['files_dir'], ns)


def _shared_ns():
    """The folder name for a shared-key install: sha256 of the key, never the key."""
    return hashlib.sha256(CFG['files_key'].encode()).hexdigest()[:32]


def _ns_ok(h):
    """Which folder this request addresses, or None if it names none.

    With FCWEB_FILES_KEY set, ONLY X-Fcweb-Key counts and the browser's own namespace is
    ignored entirely -- so a client cannot address a folder it was not given, and every client
    with the key gets the same one. Constant-time because it is a secret comparison.

    Deliberately not "X-Fcweb-Key or X-Fcweb-Ns": falling back to the namespace would let a
    namespace value grant access whenever it happened to equal the key, which is confusing to
    reason about and impossible to audit. One header, one meaning."""
    if CFG.get('files_key'):
        given = h.get('x-fcweb-key', '')
        if given and hmac.compare_digest(str(given), CFG['files_key']):
            return _shared_ns()
        return None
    ns = h.get('x-fcweb-ns', '')
    return ns if ID_RE.match(ns) else None


def _fkey(name):
    """The on-disk stem for one document. The visible name is kept in the sidecar, because
    it may hold spaces and accents and must never become a path."""
    return hashlib.sha256(name.encode('utf-8')).hexdigest()[:32]


def _f_ok(name):
    if not name or len(name) > 64 or name[0] == '.' or not NAME_RE.match(name):
        return None
    return name


def _f_norm(name):
    """NFC, so a name typed on macOS (which hands out NFD) and the same name typed on
    Windows resolve to ONE document instead of two that look identical in the list."""
    try:
        return unicodedata.normalize('NFC', name)
    except Exception:
        return name


def _f_meta(ns, name):
    try:
        with open(os.path.join(_ns_dir(ns), _fkey(name) + '.json'), 'rb') as f:
            m = json.load(f)
        m['name'] = name
        return m
    except Exception:
        return None


def _f_files(ns):
    """Every document in one folder: name, bytes, saved time. Scandir of a single folder --
    a browser holds tens, not thousands, so an index file would be a second thing to keep
    consistent."""
    out = []
    d = _ns_dir(ns)
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for k in names:
        if not k.endswith('.json'):
            continue
        try:
            with open(os.path.join(d, k), 'rb') as f:
                m = json.load(f)
            nm = m.get('n', '')
            if m.get('d') and os.path.exists(os.path.join(d, m['d'])):
                out.append({'name': nm, 'bytes': int(m.get('b', 0)), 'saved': int(m.get('t', 0))})
        except Exception:
            continue          # a half-written or foreign file is not listed, not fatal
    out.sort(key=lambda x: (-x['saved'], x['name']))
    return out


def _f_used():
    total = 0
    for root, _dirs, files in os.walk(CFG['files_dir']):
        for n in files:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return total


_f_used_cache = [0.0, -1]      # when we last walked the tree, and the answer


def _f_used_now():
    """_f_used() with a short cache. It walks the whole store, which is fine once in a while
    and wasteful on every write; the store only changes through this process, so a stale
    read for a few seconds can only ever be stale in the direction of refusing a write that
    would just fit -- never of letting the volume grow past the ceiling.

    Invalidated on every write and delete, so the answer is exact immediately after a change
    and only the idle case pays for the walk."""
    if _now() - _f_used_cache[0] > 10.0:
        _f_used_cache[0], _f_used_cache[1] = _now(), _f_used()
    return _f_used_cache[1]


def _f_used_dirty():
    """Force the next _f_used_now() to re-walk: a write or delete just changed the total."""
    _f_used_cache[0] = 0.0


def _f_delete(ns, name):
    d = _ns_dir(ns)
    k = _fkey(name)
    for ext in ('.bin', '.json'):
        try:
            os.remove(os.path.join(d, k + ext))
        except OSError:
            pass
    _f_used_dirty()


def _sz(n):
    """A size a person can act on. The hint and --files quote this, so it must never round a
    real file down to "0": under a kilobyte it says bytes."""
    n = float(n)
    if n >= 1073741824:
        return '%.1f GB' % (n / 1073741824)
    if n >= 1048576:
        return '%.1f MB' % (n / 1048576)
    if n >= 1024:
        return '%.1f kB' % (n / 1024.0)
    return '%d B' % int(n)


def _files_route(method, path, fullpath, h, body):
    if not CFG['files_on']:
        return _fail(404, 'files_off')
    ns = _ns_ok(h)
    if not ns:
        return _fail(404, 'no_namespace')
    d = _ns_dir(ns)

    if path == '/files':
        if method != 'GET':
            return _err(405, 'method_not_allowed', 'This endpoint does not accept that method.')
        files = _f_files(ns)
        return _json(200, {'files': files, 'used': _f_used_now(), 'quota': CFG['files_quota'],
                           'total_quota': CFG['files_total'], 'max_mb': CFG['max_bytes'] // 1048576})

    m = re.match(r'/files/(.+)\Z', path)
    if not m:
        return _fail(400, 'bad_request')
    name = _f_norm(unquote(m.group(1)))
    if not _f_ok(name):
        # A traversal attempt and an over-long name are the same refusal: the name is never
        # used to build a path, it is hashed, so this only keeps the listing honest.
        return _fail(400, 'bad_request')
    key = _fkey(name)

    if method == 'GET':
        meta = _f_meta(ns, name)
        if not meta or not meta.get('d'):
            return _fail(404, 'no_file')
        try:
            data = open(os.path.join(d, meta['d']), 'rb').read()
        except OSError:
            return _fail(404, 'no_file')
        if h.get('if-none-match') == '"%d"' % meta.get('t', 0):
            return 304, {'ETag': '"%d"' % meta.get('t', 0)}, b''
        return 200, {'Content-Type': 'application/octet-stream', 'ETag': '"%d"' % meta.get('t', 0),
                     'Content-Disposition': 'attachment; filename*=UTF-8\'\'%s' % quote(name, safe=''),
                     'Cache-Control': 'no-store'}, data

    if method == 'PUT':
        if len(body) == 0 or len(body) > CFG['max_bytes']:
            return _fail(413, 'too_big')
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return _fail(507, 'quota')
        old = 0
        meta = _f_meta(ns, name)
        if meta and meta.get('d'):
            try:
                old = os.path.getsize(os.path.join(d, meta['d']))
            except OSError:
                old = 0
        # Re-saving the same document frees its own previous bytes first.
        used = _f_used_now()
        if used - old + len(body) > CFG['files_quota']:
            # No eviction here, and deliberately. A session is disposable and a public box
            # must not grow without bound; this folder is the user's own saved work, so a
            # full disk is answered by refusing the write and naming the limit, never by
            # deleting a document they did not ask us to delete. Same rule as the session
            # store's "refused rather than evicting somebody's model".
            return _err(507, 'quota', 'This folder is full: %s of %s are in use. Delete a '
                        'document to make room, or the operator can raise FCWEB_FILES_MAX_GB.'
                        % (_sz(used), _sz(CFG['files_quota'])))
        if used - old + len(body) > CFG['files_total']:
            # The backstop for the whole store, not this folder: anyone can mint a namespace,
            # so per-folder limits alone do not bound the volume. Refused, never evicted.
            return _err(507, 'quota', 'The server has no room for more documents right now: '
                        '%s of %s are in use. Try again later, or the operator can raise '
                        'FCWEB_FILES_TOTAL_GB.' % (_sz(used), _sz(CFG['files_total'])))
        try:
            _write_atomic(os.path.join(d, key + '.bin'), body)
            _write_atomic(os.path.join(d, key + '.json'),
                          json.dumps({'n': name, 'b': len(body), 't': int(_now()),
                                      'd': key + '.bin'}).encode())
        except OSError:
            return _fail(507, 'quota')
        _f_used_dirty()
        return _json(200, {'ok': True, 'name': name, 'bytes': len(body), 'used': _f_used_now()})

    if method == 'DELETE':
        if not _f_meta(ns, name):
            return _fail(404, 'no_file')
        _f_delete(ns, name)
        return _json(200, {'ok': True, 'name': name})

    return _err(405, 'method_not_allowed', 'This endpoint does not accept that method.')


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
        # Unauthenticated, so it must not be a lever: a real _gc() scandirs the volume,
        # parses every metadata file and can delete sessions, all under the global lock.
        # The 30 s docker healthcheck keeps calling this, which is what runs expiry.
        if _now() - _HEALTH_GC[0] > 60:
            _HEALTH_GC[0], _HEALTH_GC[1] = _now(), _gc()
        used = _HEALTH_GC[1]
        return _json(200, {'ok': True, 'v': 1, 'n': len(_sessions()), 'used': used,
                           'quota': CFG['quota'], 'max_mb': CFG['max_bytes'] // 1048576})

    m_share = re.match(r'/share/([0-9a-f]{32})(/[a-z/]+)?\Z', path)
    m_api = re.match(r'/api/s/([0-9a-f]{32})/(attach|cmd|result)\Z', path)
    m_mcp = re.match(r'/mcp/([0-9a-f]{32})/([0-9a-f]{32,64})\Z', path)

    # Server files: its own tree, gated on the opt-in and the namespace key. Handled before
    # the share routes so a document name can never be read as a session id.
    if path == '/files' or path.startswith('/files/'):
        if len(body) > CFG['max_bytes']:
            return _fail(413, 'too_big')     # the same ceiling as a session document
        return _files_route(method, path, fullpath, h, body)

    if path.startswith('/share/') and not m_share:
        return _fail(400, 'bad_id')
    # Size BEFORE parse. Every handler below json.loads its body while holding the global
    # lock, and nginx allows 32m so that this limit, not nginx's, is what answers with a
    # code and a hint. /api/ is deliberately not covered: it carries screenshots and has
    # its own 4m ceiling in nginx.
    if path.startswith('/share/') and len(body) > CFG['max_bytes']:
        return _fail(413, 'too_big')
    if m_mcp:
        return _mcp_probe(m_mcp.group(1), m_mcp.group(2))
    if m_api:
        return _relay(method, m_api.group(1), m_api.group(2), fullpath, h, body)
    if not m_share:
        return _err(404, 'not_found', 'No such endpoint.')

    i, sub = m_share.group(1), (m_share.group(2) or '')
    admin = _is_admin(i, h.get('x-fcweb-key', ''))
    m = _meta(i)

    # ---- creation: the owner's own /join with the admin key ------------------------
    if m is None and method == 'POST' and sub == '/join' and admin:
        m = {'v': 0, 'env_v': 0, 'n': '', 't': 0, 'seen': 0, 'cam': '', 'note': '',
             'acting_as': 'human', 'salt': secrets.token_hex(16), 'pw_view': '',
             'pw_edit': '', 'agent': '', 'agent_on': False, 'expires': None,
             'created': int(_now()), 'last_viewed': int(_now()), 'activity': [],
             'owner': ''}
        why = _evicted().get(i)
        if why:
            # the owner is re-sharing a session the server threw away: say so once
            m['recreated_after'] = why['why']
            ev = _evicted(); ev.pop(i, None)
            _write_atomic(os.path.join(CFG['dir'], 'evicted.json'), json.dumps(ev).encode())
        _save_meta(i, m)
    if m is None:
        why = _evicted().get(i)
        if why:
            return _fail(404, 'evicted' if why['why'] == 'quota' else 'expired')
        return _fail(404, 'no_session')
    if _expired(m):
        _remove(i, 'expired')
        return _fail(404, 'expired')
    # Only now, for a session that demonstrably EXISTS. _st() allocates a dict, two Events
    # and a Lock and nothing ever frees it, so creating it above meant any caller could mint
    # permanent memory with a 32-hex guess that answers 404 -- 5/s per IP, forever.
    s = _st(i)

    # ---- who is calling -------------------------------------------------------------
    cid = h.get('x-fcweb-client', '')
    client = s['clients'].get(cid)
    if client is None and cid and cid in s.get('kicked', {}):
        return _fail(403, 'removed')
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
                           'env_v': m['env_v'], 'holder': _name(s, s['holder']),
                           'recreated_after': m.pop('recreated_after', None)})

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
            'watching': _watching(s), 'people': _people(s),
            'expires': m['expires'], 'owner': m.get('owner', ''),
            # whether a password is in force, for the owner's Sharing page: the page never
            # sees the passwords themselves after they are set
            'has_pw': {'viewer': bool(m.get('pw_view')), 'editor': bool(m.get('pw_edit'))} if admin else None,
            'you': {'holder': client is not None and cid == s['holder'],
                    'role': client['role'] if client else 'admin',
                    # their own capability, returned only to them: granted control
                    # mints a token, and this is how the tab picks it up
                    'edit': client.get('edit') if client else None}})

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
        # the document's name is fixed by its first publish (or by the admin); a joiner who
        # holds control does not rename it -- their copy's label may carry a suffix
        nm = re.sub(r'[^\w .\-]', '', h.get('x-fcweb-name', ''))[:64]
        if nm and (not m['n'] or admin):
            m['n'] = nm
        m['n'] = m['n'] or 'shared.FCStd'
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
        # ANYONE in the session may ask -- the current holder decides. The editor
        # password is what lets you TAKE control instead of asking: immediately when
        # control is free, and over a live holder's head with force.
        if not client:
            return _fail(401, 'not_joined')
        try:
            b = json.loads(body or b'{}')
        except Exception:
            return _fail(400, 'bad_request')
        force = bool(b.get('force'))
        if s['holder'] == cid:
            return _json(200, {'granted': True, 'already': True, 'edit': client.get('edit')})
        free = s['holder'] is None or s['holder'] not in s['clients'] \
            or _now() - s['holder_seen'] > HOLDER_SILENCE_S
        if force and editor_cid is None:
            return _fail(403, 'not_editor')
        if force or (free and editor_cid is not None):
            _grant(s, cid, m, 'took control' if force and not free else 'granted control')
            _save_meta(i, m)
            return _json(200, {'granted': True, 'forced': force and not free,
                               'edit': s['clients'][cid].get('edit')})
        if free:
            # no live holder, so no one can answer: the editor password is the way in
            return _fail(409, 'no_holder_to_grant')
        if s['pending'] and s['pending'] != cid and s['pending'] in s['clients']:
            return _fail(409, 'already_pending')
        s['pending'] = cid
        _activity(m, s, cid, 'asked for control')
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

    if method == 'POST' and sub == '/kick':
        # The owner's session, the owner's call. Removing the client drops their edit
        # token with it, so a kicked editor cannot publish on the way out; their tab
        # discovers it on the next poll and says so.
        if not admin:
            return _fail(403, 'not_admin')
        try:
            b = json.loads(body or b'{}')
        except Exception:
            return _fail(400, 'bad_request')
        who = str(b.get('client', ''))
        c = s['clients'].pop(who, None)
        if c is None:
            return _fail(404, 'no_client')
        for tok, owner_cid in list(s['edits'].items()):
            if owner_cid == who:
                s['edits'].pop(tok, None)
        if s['holder'] == who:
            s['holder'] = None
        if s['pending'] == who:
            s['pending'] = None
        s['kicked'][who] = _now()
        _activity(m, s, None, 'removed %s from the session' % c['name'])
        _save_meta(i, m)
        return _json(200, {'ok': True, 'removed': c['name']})

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
    if op == 'attach':
        if method != 'POST' or not _agent_ok(i, h.get('x-fcweb-agent', '')):
            return _err(404, 'not_found', 'No such endpoint.')
        s = _st(i)          # only once the capability checked out; see _route
        t = secrets.token_hex(16)
        # one relay target at a time; the newest wins. The client id is what fc_session_info
        # compares with the holder -- identity, not a display name.
        s['tabs'] = {t: {'seen': _now(), 'client': h.get('x-fcweb-client', '')}}
        return _json(200, {'tab': t})
    tab = h.get('x-fcweb-tab', '')
    s = STATE.get(i)
    # No state means no attach has ever succeeded here, so no tab token can be valid.
    if s is None or tab not in s['tabs']:
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
    timeout = min(float(timeout), 120.0)
    # One command runs in the tab at a time (one interpreter), but callers QUEUE for it
    # rather than being refused: an AI client that issues two tool calls in parallel gets
    # both answered, in order, instead of one 'busy'.
    # ponytail: fairness is the lock's; a real deque if ordering ever matters.
    if not s['turn'].acquire(timeout=timeout):
        return {'ok': False, 'code': 'busy', 'hint': HINTS['busy']}
    try:
        with LOCK:
            cid = secrets.token_hex(4)
            # the tab bounds its own wait to this, so a stuck interpreter answers 'timeout'
            # instead of leaving the relay wedged
            s['queue'] = {'id': cid, 'kind': kind, 'args': args, 'timeout': timeout}
            s['result'] = None
            s['ev'].clear()
            s['cmd_ev'].set()
        ok = s['ev'].wait(timeout)
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
    finally:
        s['turn'].release()


# --------------------------------------------------------------------------- selftest
def selftest():
    import tempfile
    global _now
    clock = [1_700_000_000.0]
    _now = lambda: clock[0]
    CFG.update(_cfg())
    CFG.update(dir=tempfile.mkdtemp(), max_bytes=1024, quota=4096, public_url='https://x.test')
    # Server files live in their own tree, off by default, and the selftest turns them on:
    # the store is the build gate, so an untested one would ship exactly like an untested
    # session protocol. max_bytes/quota are the session's small test values, so a document
    # is 1 KB here and the folder's ceiling is asserted in the same units.
    CFG.update(files_dir=tempfile.mkdtemp(), files_on=True, files_quota=8192,
               files_total=10 ** 7)
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
    assert j['has_pw'] is None, 'has_pw must be admin-only'
    assert [x['name'] for x in j['people']] == ['Alice'] and j['people'][0]['holder'], j['people']
    jo = call('GET', '/share/%s/v' % sid, X_Fcweb_Key=key)[1]
    assert jo['has_pw'] == {'viewer': False, 'editor': False}, jo['has_pw']

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

    # control: ANYONE in the session may ask -- the holder decides. Only the editor
    # password TAKES: force over a live holder, or straight through when control is free.
    assert call('POST', '/share/%s/control/request' % sid, {'force': True}, X_Fcweb_Client=bob)[0] == 403
    st, j, _, _ = call('POST', '/share/%s/control/request' % sid, {}, X_Fcweb_Client=bob)
    assert st == 202 and j['granted'] is False, j          # a plain viewer CAN ask
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=owner)[1]['pending']['name'] == 'Bob'
    assert call('POST', '/share/%s/control/grant' % sid, {}, X_Fcweb_Edit=oedit)[1]['holder'] == 'Bob'
    you = call('GET', '/share/%s/v' % sid, X_Fcweb_Client=bob)[1]['you']
    ppl = {x['name']: x for x in call('GET', '/share/%s/v' % sid, X_Fcweb_Client=bob)[1]['people']}
    assert set(ppl) >= {'Alice', 'Bob'} and ppl['Bob']['id'] == bob, ppl
    assert ppl['Bob']['holder'] and not ppl['Alice']['holder'], ppl      # Bob was just granted control
    assert you['holder'] is True and you['edit'], 'a granted viewer must receive an edit token'
    assert call('PUT', '/share/' + sid, b'BOB', X_Fcweb_Edit=you['edit'])[1]['v'] == 2
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=cy)[1]['you']['edit'] != you['edit']
    # hand it back to the owner and carry on with the editor paths
    assert call('POST', '/share/%s/control/request' % sid, {'force': True}, X_Fcweb_Edit=oedit)[1]['granted'] is True
    assert call('PUT', '/share/' + sid, b'ONE', X_Fcweb_Edit=oedit)[1]['v'] == 3
    st, j, _, _ = call('POST', '/share/%s/control/request' % sid, {}, X_Fcweb_Edit=cedit)
    assert st == 202 and j['granted'] is False
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=owner)[1]['pending']['name'] == 'Cy'
    assert call('PUT', '/share/' + sid, b'TWO', X_Fcweb_Edit=cedit)[0] == 409    # not holder
    assert call('GET', '/share/' + sid, X_Fcweb_Client=bob)[3] == b'ONE'         # bytes unchanged
    assert call('POST', '/share/%s/control/grant' % sid, {}, X_Fcweb_Edit=cedit)[0] == 409
    assert call('POST', '/share/%s/control/grant' % sid, {}, X_Fcweb_Edit=oedit)[1]['holder'] == 'Cy'
    assert call('PUT', '/share/' + sid, b'TWO', X_Fcweb_Edit=cedit)[1]['v'] == 4
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
    st, j, _, _ = call('POST', '/share/%s/control/request' % sid, {}, X_Fcweb_Client=bob)
    assert st == 409 and j['code'] == 'no_holder_to_grant', j   # nobody to answer a viewer
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
    st, j, _, _ = call('POST', '/api/s/%s/attach' % sid, X_Fcweb_Agent=tok2, X_Fcweb_Client=owner)
    tab = j['tab']
    assert _st(sid)['tabs'][tab]['client'] == owner, 'attach must record the tab\'s client id'
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
    assert done['cmd']['timeout'] == 5.0, 'the tab must learn the caller\'s timeout'
    # two callers at once: both are answered, in order, none refused
    seen = []

    def tab_loop():
        for _ in range(400):
            st, j, _, _ = call('GET', '/api/s/%s/cmd?wait=0.05' % sid, X_Fcweb_Tab=tab)
            if st == 200:
                seen.append(j['args']['code'])
                call('POST', '/api/s/%s/result' % sid, {'id': j['id'], 'ok': True, 'out': j['args']['code']}, X_Fcweb_Tab=tab)
                if len(seen) == 2:
                    return
            time.sleep(0.01)
    th = threading.Thread(target=tab_loop)
    th.start()
    outs = {}
    ths = [threading.Thread(target=lambda c=c: outs.__setitem__(c, submit(sid, tok2, 'eval', {'code': c}, timeout=5))) for c in ('A', 'B')]
    [t.start() for t in ths]; [t.join() for t in ths]; th.join()
    assert outs['A']['ok'] and outs['B']['ok'] and sorted(seen) == ['A', 'B'], (outs, seen)
    assert call('DELETE', '/share/%s/agent' % sid, X_Fcweb_Key=key)[0] == 200
    assert call('POST', '/mcp/%s/%s' % (sid, tok2))[0] == 404             # AllowAgent off

    # kick: the owner removes a client; their token dies with them and they are told
    st, j, _, _ = call('POST', '/share/%s/join' % sid, {'name': 'Mallory', 'viewer_pw': 'v1'})
    mal = j['client']
    assert call('GET', '/share/%s/v' % sid, X_Fcweb_Client=mal)[0] == 200
    assert call('POST', '/share/%s/kick' % sid, {'client': mal}, X_Fcweb_Client=mal)[0] == 403   # not the owner
    assert call('POST', '/share/%s/kick' % sid, {'client': mal}, X_Fcweb_Key=key)[1]['removed'] == 'Mallory'
    st, j, _, _ = call('GET', '/share/%s/v' % sid, X_Fcweb_Client=mal)
    assert st == 403 and j['code'] == 'removed' and j['hint'], j
    assert call('POST', '/share/%s/kick' % sid, {'client': 'nope'}, X_Fcweb_Key=key)[0] == 404

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
    clock[0] += KEEP_S + 5        # sid is the oldest-viewed AND now idle long enough to evict

    # quota: least recently viewed no-expiry session evicted; dated ones spared; owner told
    def mk(k, size):
        s_ = hashlib.sha256(k.encode()).hexdigest()[:32]
        st, j, _, _ = call('POST', '/share/%s/join' % s_, {'name': 'O'}, X_Fcweb_Key=k)
        _r = call('PUT', '/share/' + s_, b'z' * size, X_Fcweb_Edit=j['edit'])
        assert _r[0] == 200, (s_, _r[0], _r[1])
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

    # ...and a stranger cannot make room by uploading. Everything left was viewed moments
    # ago, so the write is refused instead of deleting somebody's model.
    for _s, _j in ((sa, ja), (sb, jb), (sc, jc)):
        call('GET', '/share/' + _s, X_Fcweb_Client=_j['client'])
    CFG['quota'] = _size(sa) + _size(sb) + _size(sc) + 100
    n_before = len(_sessions())
    assert call('PUT', '/share/' + sa, b'q' * 900, X_Fcweb_Edit=ja['edit'])[1]['code'] == 'quota'
    assert len(_sessions()) == n_before, 'quota pressure must not evict a session in use'
    CFG['quota'] = 10 ** 7

    # a session that never published anything is an abandoned one
    kv = '4' * 64
    sv = hashlib.sha256(kv.encode()).hexdigest()[:32]
    call('POST', '/share/%s/join' % sv, {'name': 'O'}, X_Fcweb_Key=kv)
    assert call('GET', '/share/%s/v' % sv, X_Fcweb_Key=kv)[0] == 200
    clock[0] += V0_TTL_S + 1
    _gc()
    assert call('GET', '/share/%s/v' % sv, X_Fcweb_Key=kv)[0] == 404, 'a v0 session ages out'

    # an id nobody has proved exists must not leave anything behind: _st() allocates a dict,
    # two Events and a Lock, and nothing ever frees them
    zid = 'f' * 32
    assert call('GET', '/share/%s/v' % zid)[0] == 404
    assert call('POST', '/api/s/%s/attach' % zid, {}, X_Fcweb_Agent='0' * 32)[0] == 404
    assert call('GET', '/api/s/%s/cmd' % zid, X_Fcweb_Tab='0' * 32)[0] == 409
    assert STATE.get(zid) is None, 'an unauthenticated id must not allocate session state'

    # size is checked BEFORE the body is parsed: oversized junk is 413, never 400
    st_, j_, _, _ = call('PUT', '/share/%s/env' % sa, b'not json ' + b'x' * 2000, X_Fcweb_Key='1' * 64)
    assert st_ == 413, 'the size guard must run before json.loads (got %s)' % st_

    # health is unauthenticated, so its sweep is rate limited rather than on demand
    gc_calls = [0]
    real_gc = _gc
    globals()['_gc'] = lambda incoming=0: (gc_calls.__setitem__(0, gc_calls[0] + 1), real_gc(incoming))[1]
    _HEALTH_GC[0] = 0.0
    for _ in range(3):
        assert call('GET', '/share/health')[0] == 200
    assert gc_calls[0] == 1, 'health swept %d times in a minute' % gc_calls[0]
    clock[0] += 61
    call('GET', '/share/health')
    assert gc_calls[0] == 2, 'health must sweep again once the minute is up'
    globals()['_gc'] = real_gc

    # ---- server files ----------------------------------------------------------------
    # Off by default, and the refusal must look like nothing exists rather than "disabled":
    # a page that probes /files on a site that does not run it should just find no source.
    CFG['files_on'] = False
    assert call('GET', '/files', X_Fcweb_Ns='a' * 32)[0] == 404
    CFG['files_on'] = True

    ns = 'b1' * 16
    # No key, or a key of the wrong shape, is the same answer as an empty folder: the
    # namespace is the only thing addressing someone's models, so it is never guessable.
    assert call('GET', '/files')[1]['code'] == 'no_namespace'
    assert call('GET', '/files', X_Fcweb_Ns='nope')[1]['code'] == 'no_namespace'
    assert call('GET', '/files', X_Fcweb_Ns='a' * 32)[1]['files'] == []

    # put / get / list
    st, j, _, _ = call('PUT', '/files/Box.FCStd', b'FCStd-bytes', X_Fcweb_Ns=ns)
    assert st == 200 and j['name'] == 'Box.FCStd' and j['bytes'] == 11, j
    st, j, _, _ = call('GET', '/files', X_Fcweb_Ns=ns)
    assert [(f['name'], f['bytes']) for f in j['files']] == [('Box.FCStd', 11)], j['files']
    st, j, hh, bb = call('GET', '/files/Box.FCStd', X_Fcweb_Ns=ns)
    assert st == 200 and bb == b'FCStd-bytes', bb
    # a re-fetch of what we just saved is a 304, so an unchanged document costs nothing
    assert call('GET', '/files/Box.FCStd', X_Fcweb_Ns=ns, If_None_Match=hh['ETag'])[0] == 304

    # names with spaces and accents round-trip, and are never used as a path
    call('PUT', '/files/' + quote('Ünter Rad 2.FCStd'), b'b', X_Fcweb_Ns=ns)
    st, j, _, bb = call('GET', '/files/' + quote('Ünter Rad 2.FCStd'), X_Fcweb_Ns=ns)
    assert st == 200 and bb == b'b'
    assert any(f['name'] == 'Ünter Rad 2.FCStd' for f in call('GET', '/files', X_Fcweb_Ns=ns)[1]['files'])
    assert call('PUT', '/files/' + quote('../../etc/passwd'), b'x', X_Fcweb_Ns=ns)[0] == 400
    assert call('GET', '/files/' + quote('../../etc/passwd'), X_Fcweb_Ns=ns)[0] == 400
    assert call('PUT', '/files/' + quote('.hidden'), b'x', X_Fcweb_Ns=ns)[0] == 400
    assert call('PUT', '/files/' + quote('n' * 65), b'x', X_Fcweb_Ns=ns)[0] == 400
    # macOS hands out NFD; the same name typed on Windows is NFC. One document, not two
    # that look identical in the list.
    assert call('PUT', '/files/' + quote('café.FCStd'), b'nfc', X_Fcweb_Ns=ns)[0] == 200
    assert call('PUT', '/files/' + quote('café.FCStd'), b'nfd', X_Fcweb_Ns=ns)[0] == 200
    assert call('GET', '/files/' + quote('café.FCStd'), X_Fcweb_Ns=ns)[3] == b'nfd'
    assert len([f for f in call('GET', '/files', X_Fcweb_Ns=ns)[1]['files']
                if f['name'].startswith('caf')]) == 1, 'NFC and NFD must be one document'

    # a namespace is a folder: two browsers do not see each other
    assert call('GET', '/files/Box.FCStd', X_Fcweb_Ns='c2' * 16)[0] == 404
    assert call('GET', '/files', X_Fcweb_Ns='c2' * 16)[1]['files'] == []

    # re-saving replaces, and the size ceiling is the session's own
    assert call('PUT', '/files/Box.FCStd', b'x' * 2048, X_Fcweb_Ns=ns)[0] == 413
    st, j, _, _ = call('PUT', '/files/Box.FCStd', b'new', X_Fcweb_Ns=ns)
    assert st == 200 and j['bytes'] == 3
    assert call('GET', '/files/Box.FCStd', X_Fcweb_Ns=ns)[3] == b'new'
    assert len([f for f in call('GET', '/files', X_Fcweb_Ns=ns)[1]['files']
                if f['name'] == 'Box.FCStd']) == 1, 'a re-save is not a second entry'

    # delete, then a second delete is a miss
    assert call('DELETE', '/files/Box.FCStd', X_Fcweb_Ns=ns)[0] == 200
    assert call('DELETE', '/files/Box.FCStd', X_Fcweb_Ns=ns)[1]['code'] == 'no_file'
    assert call('GET', '/files/Box.FCStd', X_Fcweb_Ns=ns)[1]['code'] == 'no_file'

    # quota: a folder that cannot fit the write REFUSES it. Nothing is evicted here, unlike
    # the session store -- these are the user's own documents, so the server never deletes
    # one it was not asked to delete.
    CFG['files_quota'] = _f_used() + 400
    clock[0] += 5
    assert call('PUT', '/files/Old.FCStd', b'old', X_Fcweb_Ns=ns)[0] == 200
    clock[0] += 5
    n_before = len(_f_files(ns))
    assert call('PUT', '/files/Big.FCStd', b'q' * 300, X_Fcweb_Ns=ns)[0] == 200
    assert len(_f_files(ns)) == n_before + 1, 'a fit write must not evict anything'
    CFG['files_quota'] = 8
    assert call('PUT', '/files/Huge.FCStd', b'q' * 900, X_Fcweb_Ns=ns)[1]['code'] == 'quota'
    assert len(_f_files(ns)) == n_before + 1, 'a refused write must leave the folder alone'
    # re-saving an existing document still works when the folder is nearly full: it frees its
    # own bytes first, so "save" fails only when the NEW file genuinely does not fit. Here
    # the folder holds N bytes and 'old' is 3 of them, so a quota of N+1 is exactly enough
    # for 'tiny' (4) and nothing more.
    CFG['files_quota'] = _f_used() - 3 + 4
    assert call('PUT', '/files/Old.FCStd', b'tiny', X_Fcweb_Ns=ns)[0] == 200
    assert call('GET', '/files/Old.FCStd', X_Fcweb_Ns=ns)[3] == b'tiny'
    assert call('PUT', '/files/Also.FCStd', b'q', X_Fcweb_Ns=ns)[1]['code'] == 'quota'
    CFG['files_quota'] = 10 ** 7
    assert call('POST', '/files', X_Fcweb_Ns=ns)[0] == 405

    # The whole-store ceiling. Anyone can mint a namespace, so a per-folder limit alone
    # does not bound the volume: a second browser with a roomy folder must still hit the
    # operator's backstop, and hitting it must cost nobody a document.
    CFG['files_total'] = _f_used() + 200
    assert call('PUT', '/files/Backstop.FCStd', b'q' * 150, X_Fcweb_Ns=ns)[0] == 200
    keep = len(_f_files(ns))
    CFG['files_total'] = _f_used()          # nothing left for anyone
    assert call('PUT', '/files/Nope.FCStd', b'q' * 100, X_Fcweb_Ns='d4' * 16)[1]['code'] == 'quota'
    assert len(_f_files(ns)) == keep, 'hitting the store ceiling must delete nothing'
    assert 'FCWEB_FILES_TOTAL_GB' in call('PUT', '/files/Nope.FCStd', b'q', X_Fcweb_Ns=ns)[1]['hint'], 'the hint names the knob the operator can turn'
    CFG['files_total'] = 10 ** 7
    assert call('POST', '/files', X_Fcweb_Ns=ns)[0] == 405

    # A shared folder key: every browser that presents it reaches ONE folder, which is the
    # only arrangement in which "open it on another machine" is possible at all -- a
    # per-browser namespace cannot cross a machine and there is no way to copy one across.
    KEY = 'shared-folder-secret'
    CFG['files_key'] = KEY
    assert call('PUT', '/files/Shared.FCStd', b'shared', X_Fcweb_Key=KEY)[0] == 200
    # Two browsers: different namespaces, same key -> the same folder, so one sees the
    # other's file. This is the entire point of the feature.
    assert call('GET', '/files/Shared.FCStd', X_Fcweb_Key=KEY, X_Fcweb_Ns='a' * 32)[3] == b'shared'
    assert call('GET', '/files/Shared.FCStd', X_Fcweb_Key=KEY, X_Fcweb_Ns='b' * 32)[3] == b'shared'
    assert [f['name'] for f in call('GET', '/files', X_Fcweb_Key=KEY, X_Fcweb_Ns='c' * 32)[1]['files']] \
        == ['Shared.FCStd'], 'every holder of the key sees the whole folder'
    # The namespace is IGNORED, not accepted as a fallback: with a key configured only the
    # key addresses anything. Otherwise a namespace that happened to equal the key would
    # grant access, which is unauditable.
    assert call('GET', '/files', X_Fcweb_Ns=ns)[1]['code'] == 'no_namespace'
    assert call('GET', '/files', X_Fcweb_Ns=KEY)[1]['code'] == 'no_namespace'
    assert call('GET', '/files')[1]['code'] == 'no_namespace'
    assert call('GET', '/files', X_Fcweb_Key='wrong')[1]['code'] == 'no_namespace'
    assert call('GET', '/files', X_Fcweb_Key=KEY.upper())[1]['code'] == 'no_namespace', \
        'the key is compared exactly'
    # The key is never a directory name: sha256 of it, so a pasted secret never lands on disk
    listing = os.listdir(CFG['files_dir'])
    assert KEY not in listing, 'the key itself must never become a folder name'
    assert _shared_ns() in listing, 'and the folder is named by its hash'
    # The per-browser folder it would otherwise have used is untouched and still separate.
    assert call('GET', '/files', X_Fcweb_Ns=ns)[1]['code'] == 'no_namespace'
    CFG['files_key'] = ''
    assert call('GET', '/files/Shared.FCStd', X_Fcweb_Key=KEY)[0] == 404, \
        'with no key configured a key header addresses nothing'
    assert call('GET', '/files/Shared.FCStd', X_Fcweb_Ns=ns)[0] == 404, \
        'and the shared folder is unreachable without the key'

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
    if argv[1:2] == ['--files']:
        # The operator's view of the opt-in store. Same shape as --list so the two can be
        # compared line for line when checking what the page is showing.
        if not CFG['files_on']:
            print('server files are OFF (set FCWEB_FILES=1 on the session container)')
            return 0
        print('files=on used=%s quota=%s' % (_sz(_f_used()), _sz(CFG['files_quota'])))
        for ns in sorted(os.listdir(CFG['files_dir'])) if os.path.isdir(CFG['files_dir']) else []:
            if not ID_RE.match(ns):
                continue
            rows = _f_files(ns)
            print('  %s  %d document(s)' % (ns, len(rows)))
            for r in rows:
                print('    %s  %s  %s' % (r['name'], _sz(r['bytes']),
                                          time.strftime('%Y-%m-%d %H:%M', time.localtime(r['saved']))))
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
