# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Shared sessions: the half that runs inside FreeCAD.

Loaded as an overlay from /fcweb-am at boot (see the AM_MODULES loader in freecad-gui.html).
Nothing here talks to the network -- that is the page's job. This module:

  * registers the "Sharing" preferences page and three Edit-menu commands,
  * pins ONE document and publishes it through the session's own save path
    (saveCopy into /tmp, never the autosave dir, never save()/saveAs()),
  * snapshots the environment (user.cfg, macros, add-on manifest) with the sharing group
    REDACTED, so the admin key and MCP URL never ride in the bundle every viewer downloads,
  * enforces read-only for non-holders with property statuses it can restore exactly,
  * runs the typed MCP tools when the page hands it a command file.

Talking to the page is by files under /tmp (MEMFS, never persisted): the page polls
STATE with FS.readFile on a 2 s interval and writes CTL back. Never a stdout marker for
anything secret -- stdout feeds the page's log ring.

Every entry point the page calls is wrapped: an exception here must never propagate into
fcweb_run_python, where it would look like a hang.
"""
import json
import os
import sys
import time
import hashlib
import traceback

import FreeCAD as App

GROUP = 'User parameter:BaseApp/Preferences/FCWeb/Sharing'
STATE = '/tmp/fcweb_share.json'     # python -> page
CTL = '/tmp/fcweb_share_ctl.json'   # page -> python: {session, role, holder, name}
PWFILE = '/tmp/fcweb_share_pw'      # passwords, handed to the page once, mode 0600
REQ = '/tmp/fcweb_share_req'        # menu commands -> page: share|request|force|release
STAGE = '/tmp/_fcsession'           # the session's own save path
MCP = '/tmp/fcmcp'                  # relay command/result files
SETTLE_S = 2.0                      # publish only after edits have settled this long

_last_state = None
_obs = None
_pin = None
_last_pub_change = 0.0
_env_hash = None
_ro = {}          # doc name -> obj name -> prop name -> original status list
_actions = {}     # our QActions on the Edit menu
_tick_n = 0
_revert_t = 0.0      # advanced whenever a non-holder's edit is noticed; the page re-applies
_was_holder = None


def _log(msg):
    try:
        sys.__stderr__.write('[fcweb] share: %s\n' % msg)
        sys.__stderr__.flush()
    except Exception:
        pass


def _p():
    return App.ParamGet(GROUP)


def _ctl():
    try:
        return json.loads(open(CTL).read())
    except Exception:
        return {}


def _gui():
    try:
        import FreeCADGui as Gui
        return Gui if Gui.getMainWindow() else None
    except Exception:
        return None


# --------------------------------------------------------------------------- observer
class _Observer(object):
    """Notices edits to the pinned document; while guarding, records that a non-holder
    tried to change it. Never mutates the document from inside a callback -- that is
    re-entrant into the C++ document. tick() acts on `tripped` later."""

    def __init__(self):
        self.changed = 0.0
        self.guard = False
        self.tripped = False

    def _touch(self, doc):
        try:
            if _pin and doc is not None and doc.Name == _pin:
                self.changed = time.time()
                if self.guard:
                    self.tripped = True
        except Exception:
            pass

    def slotChangedObject(self, obj, prop=None):
        self._touch(getattr(obj, 'Document', None))

    def slotCreatedObject(self, obj):
        self._touch(getattr(obj, 'Document', None))

    def slotDeletedObject(self, obj):
        self._touch(getattr(obj, 'Document', None))

    def slotRecomputedDocument(self, doc):
        self._touch(doc)

    def slotUndoDocument(self, doc):
        self._touch(doc)

    def slotRedoDocument(self, doc):
        self._touch(doc)


# --------------------------------------------------------------------------- pin / publish
def pin(name):
    """Share exactly this document and no other."""
    global _pin
    if name and name in App.listDocuments():
        _pin = name
        _p().SetString('PinnedDocument', name)
        if _obs:
            _obs.changed = time.time()
        _log('session pinned to %s, own observer installed' % name)
        return True
    return False


def _doc():
    return App.listDocuments().get(_pin) if _pin else None


def publish(force=False):
    """Stage the pinned document for the page to upload. True when a new file was staged.
    saveCopy, never save(): the document's own FileName and dirty flag are untouched, so
    sharing never makes an unsaved document look saved nor redirects Ctrl+S."""
    global _last_pub_change
    d = _doc()
    if d is None or _obs is None:
        return False
    if not force:
        if _obs.changed <= _last_pub_change:
            return False
        if time.time() - _obs.changed < SETTLE_S:
            return False
    os.makedirs(STAGE, exist_ok=True)
    g = App.ParamGet('User parameter:BaseApp/Preferences/Document')
    lvl = g.GetInt('CompressionLevel', 3)
    g.SetInt('CompressionLevel', 0)          # same trade the autosaver makes: 3.5x less stall
    try:
        d.saveCopy(os.path.join(STAGE, 'doc.FCStd'))
    finally:
        g.SetInt('CompressionLevel', lvl)
    _last_pub_change = _obs.changed if _obs.changed else time.time()
    open(os.path.join(STAGE, 'doc.pending'), 'w').write(json.dumps(
        {'name': (d.Label or d.Name) + '.FCStd', 't': time.time()}))
    return True


# --------------------------------------------------------------------------- environment
def _redacted_cfg():
    """user.cfg as text, with the whole FCWeb group removed. The group holds the write
    key, the passwords and the MCP URL; publishing it would hand every viewer ownership."""
    import xml.etree.ElementTree as ET
    App.saveParameter()
    path = os.path.join(App.getUserConfigDir(), 'user.cfg')
    tree = ET.parse(path)
    root = tree.getroot()
    stripped = 0
    for parent in root.iter():
        for child in list(parent):
            if child.tag == 'FCParamGroup' and child.get('Name') == 'FCWeb':
                parent.remove(child)
                stripped += 1
    text = ET.tostring(root, encoding='unicode')
    assert 'WriteKey' not in text and 'AgentUrl' not in text, 'redaction failed'
    return text, stripped


def _addons():
    """Installed add-ons as owner/repo from their package.xml repository URL. Anything
    without one is listed by name with repo=None so the page can say it cannot travel."""
    import xml.etree.ElementTree as ET
    out = []
    mod = os.path.join(App.getUserAppDataDir(), 'Mod')
    if not os.path.isdir(mod):
        return out
    for name in sorted(os.listdir(mod)):
        d = os.path.join(mod, name)
        if not os.path.isdir(d):
            continue
        repo, ref = None, 'HEAD'
        try:
            r = ET.parse(os.path.join(d, 'package.xml')).getroot()
            for u in r.iter():
                if u.tag.endswith('url') and u.get('type') == 'repository' and u.text:
                    t = u.text.strip().rstrip('/')
                    if 'github.com/' in t:
                        repo = t.split('github.com/', 1)[1].removesuffix('.git')
                    if u.get('branch'):
                        ref = u.get('branch')
        except Exception:
            pass
        out.append({'name': name, 'repo': repo, 'ref': ref})
    return out


def snapshot_env():
    """Write /tmp/_fcsession/env.json when the environment changed. True when written."""
    global _env_hash
    if not _p().GetBool('IncludeEnv', True):
        env = {'cfg': '', 'macros': {}, 'addons': [], 'provenance': _prov()}
    else:
        cfg, stripped = _redacted_cfg()
        macros = {}
        md = App.getUserMacroDir(True)
        if os.path.isdir(md):
            for f in sorted(os.listdir(md)):
                if f.endswith(('.FCMacro', '.py')) and os.path.getsize(os.path.join(md, f)) < 262144:
                    try:
                        macros[f] = open(os.path.join(md, f), encoding='utf-8', errors='replace').read()
                    except Exception:
                        pass
        env = {'cfg': cfg, 'macros': macros, 'addons': _addons(), 'provenance': _prov()}
        env['provenance']['stripped'] = stripped
    raw = json.dumps(env)
    h = hashlib.sha256(raw.encode()).hexdigest()
    if h == _env_hash:
        return False
    os.makedirs(STAGE, exist_ok=True)
    open(os.path.join(STAGE, 'env.json'), 'w').write(raw)
    _env_hash = h
    _log('env published: FCWeb/Sharing stripped (%s), %d addons, %d macros' % (
        env['provenance'].get('stripped', 0), len(env['addons']), len(env['macros'])))
    return True


def _prov():
    v = App.Version()
    try:
        mdir = os.path.relpath(App.getUserMacroDir(True), os.path.expanduser('~')).replace(os.sep, '/')
    except Exception:
        mdir = '.FreeCAD/Macro'
    return {'freecad': '.'.join(str(x) for x in v[:3]), 'build': os.environ.get('FCWEB_BUILD', ''),
            'owner': _p().GetString('DisplayName', ''), 'macro_dir': mdir}


# --------------------------------------------------------------------------- read-only
def set_readonly(on):
    """Lock or unlock the pinned document. Statuses are SNAPSHOTTED per property before
    locking and restored exactly on unlock: Shape and every computed output are read-only
    by design and must stay that way."""
    d = _doc()
    if d is None or _obs is None:
        return 0
    saved = _ro.setdefault(d.Name, {})
    n = 0
    changed_before = _obs.changed      # status flips fire the observer; they are not edits
    for o in d.Objects:
        props = saved.setdefault(o.Name, {})
        for prop in o.PropertiesList:
            try:
                if on:
                    if prop not in props:
                        props[prop] = list(o.getPropertyStatus(prop))
                    o.setPropertyStatus(prop, 'ReadOnly')
                    n += 1
                elif prop in props:
                    if 'ReadOnly' not in props[prop]:
                        o.setPropertyStatus(prop, '-ReadOnly')
                    n += 1
            except Exception:
                pass
    if not on:
        _ro.pop(d.Name, None)
    _obs.changed = changed_before
    _obs.guard = bool(on)
    _obs.tripped = False
    try:
        base = d.Label.replace(' (read-only)', '')
        d.Label = base + (' (read-only)' if on else '')
    except Exception:
        pass
    _log('read-only: %d properties %s, guard observer %s' % (
        n, 'locked, statuses snapshotted' if on else 'restored', 'on' if on else 'off'))
    return n


# --------------------------------------------------------------------------- menu + prefs
class _Cmd(object):
    def __init__(self, text, tip, req):
        self.text, self.tip, self.req = text, tip, req

    def GetResources(self):
        return {'MenuText': self.text, 'ToolTip': self.tip}

    def IsActive(self):
        c = _ctl()
        if self.req == 'share':
            return True
        if not c.get('session'):
            return False
        if self.req == 'release':
            return bool(c.get('holder'))
        return c.get('role') in ('editor', 'admin') and not c.get('holder')

    def Activated(self):
        if self.req == 'share':
            try:
                import FreeCADGui as Gui
                Gui.showPreferences('Sharing', 0)
            except Exception as e:
                _log('showPreferences failed: %r' % (e,))
            return
        try:
            open(REQ, 'w').write(self.req)
        except Exception:
            pass


COMMANDS = (
    ('Fcweb_ShareSession', _Cmd('Share Session...', 'Share this document as a live, durable link', 'share')),
    ('Fcweb_RequestControl', _Cmd('Request Control', 'Ask the current editor for control of the shared session', 'request')),
    ('Fcweb_ReleaseControl', _Cmd('Release Control', 'Hand control of the shared session back', 'release')),
)

_ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
             '<circle cx="18" cy="32" r="9" fill="#5b8def"/><circle cx="46" cy="16" r="9" fill="#5b8def"/>'
             '<circle cx="46" cy="48" r="9" fill="#5b8def"/>'
             '<path d="M25 28 L39 20 M25 36 L39 44" stroke="#5b8def" stroke-width="5" fill="none"/></svg>')


def ensure_menu():
    """Put our three entries on the Edit menu, and put them BACK after a workbench switch,
    which rebuilds the menu bar. Called from tick()."""
    Gui = _gui()
    if Gui is None:
        return False
    try:
        from PySide6 import QtWidgets, QtGui
    except ImportError:
        return False
    mw = Gui.getMainWindow()
    edit = None
    for a in mw.menuBar().actions():
        m = a.menu()
        if m is None:
            continue
        if m.objectName() == 'Edit' or a.text().replace('&', '').strip() == 'Edit':
            edit = m
            break
    if edit is None:
        return False
    present = set(x.objectName() for x in edit.actions())
    if 'Fcweb_ShareSession' in present:
        for name, _ in COMMANDS:
            act = _actions.get(name)
            if act is not None:
                act.setEnabled(dict(COMMANDS)[name].IsActive())
        return True
    sep = edit.addSeparator()
    sep.setObjectName('Fcweb_Sep')
    for name, cmd in COMMANDS:
        act = QtGui.QAction(cmd.text, mw)
        act.setObjectName(name)
        act.setToolTip(cmd.tip)
        act.triggered.connect(lambda checked=False, n=name: Gui.runCommand(n))
        act.setEnabled(cmd.IsActive())
        edit.addAction(act)
        _actions[name] = act
    _log('Edit menu: Share Session, Request Control, Release Control installed')
    return True


def install():
    """Register the page, the icon and the commands. Idempotent."""
    global _obs
    if _obs is not None:
        return
    Gui = _gui()
    _obs = _Observer()
    App.addDocumentObserver(_obs)
    if Gui is None:
        _log('no GUI; observer only')
        return
    try:
        Gui.addIcon('preferences-sharing', _ICON_SVG, 'SVG')
    except Exception as e:
        _log('addIcon failed: %r' % (e,))
    try:
        Gui.addPreferencePage('/fcweb-am/fcweb_share.ui', 'Sharing')
        _log('sharing preference page registered')
    except Exception as e:
        _log('sharing page FAILED: %r' % (e,))
    for name, cmd in COMMANDS:
        try:
            Gui.addCommand(name, cmd)
        except Exception as e:
            _log('addCommand %s failed: %r' % (name, e))
    pinned = _p().GetString('PinnedDocument', '')
    if pinned:
        pin(pinned)


# --------------------------------------------------------------------------- tick
def _camera():
    Gui = _gui()
    try:
        return Gui.ActiveDocument.ActiveView.getCamera() if Gui and Gui.ActiveDocument else ''
    except Exception:
        return ''


def tick():
    """Called from the page's 1.5 s autosave tick. Everything the page needs to know goes
    into STATE, written only when it changes. Passwords are moved out of the parameter
    tree the moment they appear: Gui::PrefLineEdit persists them as plaintext into
    user.cfg, which is now a file we publish."""
    global _last_state, _tick_n, _pin
    _tick_n += 1
    try:
        p = _p()
        pw = {}
        for k in ('ViewerPassword', 'EditorPassword'):
            v = p.GetString(k, '')
            if v:
                pw[k] = v
                p.SetString(k, '')
        if pw:
            fd = os.open(PWFILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.write(fd, json.dumps(pw).encode())
            os.close(fd)
            App.saveParameter()
        c = _ctl()
        enabled = p.GetBool('Enabled', False)
        if (enabled or c.get('session')) and not _pin:
            d = App.ActiveDocument
            if d is not None and not (d.FileName or '').startswith('/freecad/'):
                pin(d.Name)
        # Read-only is reconciled HERE, every tick, from what the page says about control.
        # A page-initiated set_readonly() can be dropped while the interpreter is busy; a
        # state the interpreter re-derives itself cannot stay wrong for more than one tick.
        if _pin and _obs is not None and (enabled or c.get('session')):
            want = not bool(c.get('holder'))
            if _obs.guard != want:
                set_readonly(want)
        if _tick_n % 2 == 0:
            ensure_menu()
        staged = False
        # A joiner who took control publishes too: their ephemeral home has the sharing group
        # stripped (redaction), so 'Enabled' is false there; the page's CTL says it is a session.
        if (enabled or c.get('session')) and _pin and c.get('holder'):
            staged = publish()
            if c.get('role') == 'admin' and (_env_hash is None or _tick_n % 20 == 0):
                snapshot_env()          # right away on first enable, then every ~30 s
        global _revert_t, _was_holder
        if _obs is not None and _obs.tripped and not c.get('holder'):
            _obs.tripped = False
            _revert_t = time.time()
        # Losing control with unpublished work: keep it as a separate document, here, where
        # it cannot be dropped by a busy interpreter. The page only tells the person.
        holder_now = bool(c.get('holder'))
        if _was_holder and not holder_now and _pin and unpublished():
            d = _doc()
            if d is not None:
                try:
                    d.Label = d.Label.replace(' (read-only)', '') + ' (my changes)'
                    App._fcweb_shared_doc = None
                    _log('detached as "%s"' % d.Label)
                except Exception as e:
                    _log('detach failed: %r' % (e,))
                _pin = None
        _was_holder = holder_now
        st = {
            'enabled': enabled, 'pinned': _pin, 'name': p.GetString('DisplayName', ''),
            'include_env': p.GetBool('IncludeEnv', True), 'agent': p.GetBool('AllowAgent', False),
            'regen_agent': p.GetBool('RegenerateAgent', False),
            'expiry_days': p.GetInt('ExpiryDays', 0), 'session': p.GetString('SessionId', ''),
            'key': p.GetString('WriteKey', ''), 'agent_url': p.GetString('AgentUrl', ''),
            'pw_pending': bool(pw), 'staged': staged, 'revert_t': _revert_t,
            'cam': _camera(), 'docs': sorted(App.listDocuments().keys()),
            'active': App.ActiveDocument.Name if App.ActiveDocument else None,
            'obs_changed': _obs.changed if _obs else None, 'last_pub': _last_pub_change,
            'guard': bool(_obs and _obs.guard), 'tick': _tick_n,
            'last_published': p.GetInt('LastPublished', 0),
        }
        if st != _last_state:
            _last_state = dict(st)
            open(STATE, 'w').write(json.dumps(st))
        if st['regen_agent']:
            p.SetBool('RegenerateAgent', False)
    except Exception:
        _log('tick failed: ' + traceback.format_exc().splitlines()[-1])


def set_param(key, value):
    """The page writes back ids and links so the preferences page can show them."""
    p = _p()
    if isinstance(value, bool):
        p.SetBool(key, value)
    elif isinstance(value, int):
        p.SetInt(key, value)
    else:
        p.SetString(key, str(value))
    try:
        App.saveParameter()
    except Exception:
        pass


# --------------------------------------------------------------------------- MCP tools
def _o(d, name):
    o = d.getObject(name)
    if o is None:
        hits = d.getObjectsByLabel(name)
        o = hits[0] if hits else None
    if o is None:
        raise KeyError('no object named or labelled %r' % (name,))
    return o


def _pval(o, prop):
    v = getattr(o, prop)
    try:
        json.dumps(v)
        return v
    except Exception:
        return str(v)


def _shape_info(o):
    s = getattr(o, 'Shape', None)
    if s is None or s.isNull():
        return {'has_shape': False}
    bb = s.BoundBox
    return {'has_shape': True, 'valid': s.isValid(), 'volume': s.Volume, 'area': s.Area,
            'bbox': [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
            'center_of_mass': list(s.CenterOfMass) if hasattr(s, 'CenterOfMass') else None,
            'faces': len(s.Faces), 'edges': len(s.Edges), 'vertexes': len(s.Vertexes),
            'type': s.ShapeType}


def unpublished():
    """True when the pinned document changed after its last publish."""
    return bool(_obs and _obs.changed > _last_pub_change)


def _tool(kind, a):
    Gui = _gui()
    d = App.ActiveDocument
    if kind == 'eval':
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(a.get('code', ''), '<agent>', 'exec'), {'__name__': '__agent__'})
        return {'out': buf.getvalue()[-16000:]}
    if kind == 'document_info':
        if d is None:
            return {'document': None}
        return {'document': d.Name, 'label': d.Label, 'file': d.FileName,
                'unpublished': bool(_obs and _obs.changed > _last_pub_change),
                'objects': len(d.Objects), 'undo': d.UndoCount, 'redo': d.RedoCount,
                'active_workbench': Gui.activeWorkbench().name() if Gui else None,
                'pinned': _pin}
    if kind == 'env_info':
        p = App.ParamGet('User parameter:BaseApp/Preferences/Units')
        return {'addons': _addons(), 'unit_schema': p.GetInt('UserSchema', 0),
                'decimals': p.GetInt('Decimals', 2), 'provenance': _prov(),
                'workbenches': sorted(Gui.listWorkbenches().keys()) if Gui else []}
    if kind == 'tree':
        if d is None:
            return {'objects': []}
        return {'document': d.Name, 'objects': [
            {'name': o.Name, 'label': o.Label, 'type': o.TypeId,
             'parents': [x.Name for x in o.InList], 'children': [x.Name for x in o.OutList],
             'visible': bool(getattr(o, 'Visibility', True)), 'touched': ('Touched' in o.State),
             'valid': 'Invalid' not in o.State} for o in d.Objects]}
    if kind == 'list_objects':
        if d is None:
            return {'objects': []}
        f = (a.get('filter') or '').lower()
        return {'objects': [{'name': o.Name, 'label': o.Label, 'type': o.TypeId} for o in d.Objects
                            if not f or f in o.Name.lower() or f in o.Label.lower() or f in o.TypeId.lower()]}
    if kind == 'get_object':
        o = _o(d, a['name'])
        props = {}
        for pr in o.PropertiesList:
            props[pr] = {'type': o.getTypeIdOfProperty(pr), 'value': _pval(o, pr),
                         'status': list(o.getPropertyStatus(pr))}
            try:
                e = o.getEnumerationsOfProperty(pr)
                if e:
                    props[pr]['choices'] = list(e)
            except Exception:
                pass
        ex = {}
        try:
            ex = {k: v for k, v in o.ExpressionEngine}
        except Exception:
            pass
        return {'name': o.Name, 'label': o.Label, 'type': o.TypeId, 'properties': props,
                'expressions': ex, 'shape': _shape_info(o)}
    if kind == 'find':
        return {'objects': [{'name': o.Name, 'label': o.Label} for o in d.getObjectsByLabel(a['label'])]}
    if kind == 'shape_info':
        return _shape_info(_o(d, a['name']))
    if kind == 'add_object':
        o = d.addObject(a['type'], a.get('name') or a['type'].split('::')[-1])
        return {'name': o.Name, 'label': o.Label}
    if kind == 'set_property':
        o = _o(d, a['name'])
        prop = a['prop']
        if prop not in o.PropertiesList:
            raise KeyError('%s has no property %r' % (o.Name, prop))
        if 'ReadOnly' in o.getPropertyStatus(prop):
            raise PermissionError('%s.%s is read-only' % (o.Name, prop))
        setattr(o, prop, a['value'])
        return {'name': o.Name, 'prop': prop, 'value': _pval(o, prop)}
    if kind == 'set_expression':
        o = _o(d, a['name'])
        o.setExpression(a['prop'], a.get('expr') or None)
        return {'name': o.Name, 'prop': a['prop'], 'expr': a.get('expr')}
    if kind == 'call':
        o = _o(d, a['name'])
        r = getattr(o, a['method'])(*a.get('args', []))
        return {'result': _pval_any(r)}
    if kind == 'delete_object':
        o = _o(d, a['name'])
        n = o.Name
        d.removeObject(n)
        return {'deleted': n}
    if kind == 'recompute':
        n = d.recompute() if d else 0
        errs = [{'name': o.Name, 'error': o.getStatusString()} for o in (d.Objects if d else []) if 'Invalid' in o.State]
        return {'recomputed': n, 'errors': errs}
    if kind == 'undo':
        d.undo()
        return {'undo': d.UndoCount}
    if kind == 'redo':
        d.redo()
        return {'redo': d.RedoCount}
    if kind == 'selection_get':
        out = []
        for so in Gui.Selection.getSelectionEx():
            out.append({'name': so.ObjectName, 'label': so.Object.Label,
                        'sub': list(so.SubElementNames)})
        return {'selection': out}
    if kind == 'selection_set':
        Gui.Selection.clearSelection()
        for it in a.get('items', []):
            o = _o(d, it['name'])
            for sub in it.get('sub') or ['']:
                Gui.Selection.addSelection(o, sub) if sub else Gui.Selection.addSelection(o)
        return {'selected': len(a.get('items', []))}
    if kind == 'selection_clear':
        Gui.Selection.clearSelection()
        return {'selected': 0}
    if kind == 'list_workbenches':
        return {'workbenches': sorted(Gui.listWorkbenches().keys()),
                'active': Gui.activeWorkbench().name()}
    if kind == 'activate_workbench':
        ok = Gui.activateWorkbench(a['name'])
        if not ok:
            raise RuntimeError('activateWorkbench returned False for %r' % a['name'])
        return {'active': Gui.activeWorkbench().name()}
    if kind == 'list_commands':
        names = Gui.listCommands()
        out = []
        for n in names:
            info = {}
            try:
                info = Gui.Command.get(n).getInfo()
            except Exception:
                pass
            out.append({'name': n, 'menu': info.get('menuText', ''), 'tip': info.get('toolTip', '')})
        return {'commands': out, 'count': len(out)}
    if kind == 'run_command':
        Gui.runCommand(a['name'], int(a.get('item', 0)))
        return {'ran': a['name']}
    if kind == 'view_set':
        v = Gui.ActiveDocument.ActiveView
        std = a.get('standard')
        if std:
            getattr(v, 'view' + std.capitalize())()
        elif a.get('camera'):
            v.setCamera(a['camera'])
        return {'camera': v.getCamera()}
    if kind == 'fit_all':
        Gui.SendMsgToActiveView('ViewFit')
        return {'ok': True}
    if kind == 'fit_selection':
        Gui.SendMsgToActiveView('ViewSelection')
        return {'ok': True}
    if kind == 'console_tail':
        from PySide6 import QtWidgets
        w = Gui.getMainWindow().findChild(QtWidgets.QTextEdit, 'Report view')
        lines = (w.toPlainText() if w else '').splitlines()
        n = int(a.get('n', 50))
        return {'lines': lines[-n:]}
    if kind == 'export':
        import importlib
        fmt = a.get('format', 'step').lower()
        objs = [_o(d, n) for n in a.get('objects', [])] or list(d.Objects)
        out = os.path.join(MCP, a['id'] + '.out')
        mod = {'step': 'ImportGui', 'stp': 'ImportGui', 'iges': 'ImportGui', 'stl': 'Mesh',
               'obj': 'Mesh', 'brep': 'Part', 'fcstd': None}.get(fmt)
        if fmt == 'fcstd':
            d.saveCopy(out)
        elif mod == 'Mesh':
            import Mesh
            Mesh.export(objs, out + '.' + fmt)
            os.replace(out + '.' + fmt, out)
        elif mod:
            m = importlib.import_module(mod)
            m.export(objs, out + '.' + fmt)
            os.replace(out + '.' + fmt, out)
        else:
            raise ValueError('unsupported format %r' % fmt)
        return {'file': out, 'bytes': os.path.getsize(out), 'format': fmt}
    if kind in ('import_bytes', 'open_bytes'):
        src = os.path.join(MCP, a['id'] + '.in')
        name = a.get('name', 'import.' + a.get('format', 'step'))
        dst = os.path.join(MCP, name)
        os.replace(src, dst)
        if kind == 'open_bytes' or name.lower().endswith('.fcstd'):
            nd = App.openDocument(dst)
            return {'document': nd.Name}
        import importlib
        importlib.import_module('ImportGui' if name.lower().endswith(('.step', '.stp', '.iges', '.igs')) else 'Mesh').insert(dst, d.Name)
        return {'imported': name, 'objects': len(d.Objects)}
    if kind == 'screenshot':
        return {'screenshot': a.get('region', 'viewport'), 'max_px': int(a.get('max_px', 1280))}
    raise KeyError('unknown tool %r' % kind)


def _pval_any(v):
    try:
        json.dumps(v)
        return v
    except Exception:
        return str(v)


MUTATING = {'eval', 'add_object', 'set_property', 'set_expression', 'call', 'delete_object',
            'recompute', 'undo', 'redo', 'run_command', 'import_bytes', 'open_bytes'}


def run_agent(cid):
    """Run one relay command from /tmp/fcmcp/<cid>.json; write <cid>.result.json.
    Output is captured, never printed: stdout feeds the page's log ring."""
    res = {'id': cid, 'ok': False}
    try:
        cmd = json.loads(open(os.path.join(MCP, cid + '.json')).read())
        kind, args = cmd.get('kind'), dict(cmd.get('args') or {})
        args['id'] = cid
        c = _ctl()
        if kind in MUTATING and not c.get('holder'):
            res.update(code='not_holder',
                       hint='Request control first: fc_control_request(), then retry.')
        else:
            if _obs is not None and kind in MUTATING:
                _obs.guard = False       # the holder's own agent is not an intruder
            out = _tool(kind, args)
            res.update(ok=True, result=out, mutating=kind in MUTATING)
            if kind in MUTATING and _obs is not None:
                _obs.changed = time.time()
    except Exception as e:
        tb = traceback.format_exc()
        res.update(code=res.get('code', 'tool_error'), error=str(e)[:2000], trace=tb[-4000:],
                   hint=res.get('hint', 'Read the error; fc_console_tail() shows FreeCAD\'s own report.'))
    try:
        open(os.path.join(MCP, cid + '.result.json'), 'w').write(json.dumps(res))
    except Exception:
        pass
    return res
