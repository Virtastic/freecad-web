# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""The shared-session edge paths, each one a thing a real person hits: a dead link, a
viewer password, stopping a share, the diagnostics panel with its secrets redacted, and
the collapsible session bar. Registered by tools/boot-gate.py as scenario `edges`."""
import time

import gate_session as gs


def scenario_edges(ctx, url, args, fail):
    S = gs._Session()
    # 1. a link to a session that does not exist: FreeCAD boots normally, one honest toast
    dead = S(ctx, url + ('&' if '?' in url else '?') + 's=' + 'd' * 32, args.timeout)
    gs._dialogs(dead.page)
    if not dead.load():
        fail('a dead link stopped FreeCAD from booting (%s)' % dead.phase())
    else:
        time.sleep(4)
        st = dead.page.evaluate('({err: !!window.__fcSessionJoinError, mode: !!window.__fcSession && window.__fcSession.mode, toasts: Array.from(document.querySelectorAll("#fcweb-toasts div")).map(e => e.textContent).filter(t => t.length > 30)})')
        if not st['err'] or not any('Could not join' in t for t in st['toasts']):
            fail('a dead link did not produce the join-failure toast: %r' % st)
        else:
            print('==> dead link: booted normally with the toast')
        # and their own home is mounted: an autosave dir is what proves it
        home = dead.page.evaluate('(() => { try { return window.fcInstance.FS.analyzePath("/home/web_user/.config").exists; } catch (e) { return false; } })()')
        if not home:
            fail('after a dead link the normal home was not there')
    dead.page.close()

    # 2. owner shares with a VIEWER password; a viewer must give it (real prompt), and a
    #    wrong one is refused with a hint
    s1, sid = gs._owner_up(ctx, url, args, fail, extra="p.SetString('ViewerPassword', 'v1')")
    if not sid:
        return s1
    if not gs._wait(s1, 'share: passwords updated', 40):
        fail('the viewer password never reached the server')
    bad = gs._viewer(ctx, url, sid, args, name='Eve', vpw='wrong')
    ok = bad.load()
    time.sleep(3)
    st = bad.page.evaluate('({err: !!window.__fcSessionJoinError, code: window.__fcSessionJoinError && window.__fcSessionJoinError.code})')
    if not st['err'] or st['code'] != 'password_required':
        fail('a wrong viewer password was not refused as password_required: %r' % st)
    else:
        print('==> wrong viewer password: refused (%s), FreeCAD still booted=%s' % (st['code'], ok))
    bad.page.close()
    good = gs._viewer(ctx, url, sid, args, name='Bob', vpw='v1')
    if not good.load() or not gs._wait(good, 'share applied v', 90, 'console'):
        fail('the right viewer password did not open the session')
    else:
        print('==> right viewer password: session opened')

    # 3. the session bar collapses to a tab and comes back (real clicks on DOM buttons)
    g0 = good.page.evaluate('(() => { const b = document.getElementById("fcweb-session-bar"); const r = b.getBoundingClientRect(); return [Math.round(r.height), Math.round(r.top)]; })()')
    good.page.click('#fcweb-session-bar button[title^="Hide the session bar"]')
    time.sleep(0.5)
    g1 = good.page.evaluate('(() => { const b = document.getElementById("fcweb-session-bar"); const r = b.getBoundingClientRect(); return [Math.round(r.height), Math.round(r.top), getComputedStyle(b.querySelector("span:nth-child(3)")).display]; })()')
    good.page.click('#fcweb-session-bar')
    time.sleep(0.5)
    g2 = good.page.evaluate('(() => { const b = document.getElementById("fcweb-session-bar"); const r = b.getBoundingClientRect(); return [Math.round(r.height), Math.round(r.top)]; })()')
    if not (g1[0] < g0[0] and g1[1] == 0 and g1[2] == 'none' and g2 == g0):
        fail('the session bar did not collapse and restore: %r %r %r' % (g0, g1, g2))
    else:
        print('==> session bar: %dpx -> %dpx tab at the top edge -> %dpx' % (g0[0], g1[0], g2[0]))

    # 4. diagnostics: opens, and the bug-report copy contains no secret. The owner has an
    #    MCP URL in play, so the ring has something to redact.
    s1.run_python("import FreeCAD as A\nA.ParamGet(%r).SetBool('AllowAgent', True)" % gs.GROUP)
    if not gs._wait_state(s1, lambda x: x.get('agentUrl'), 40):
        fail('no MCP URL minted for the diagnostics check')
    s1.page.click('#fcweb-session-bar button:has-text("Diagnostics")')
    time.sleep(1)
    d = s1.page.evaluate('(() => { const h = document.getElementById("fcweb-diag"); return h ? h.textContent : null; })()')
    if not d or 'Session diagnostics' not in d:
        fail('the diagnostics panel did not open')
    else:
        tok = s1.page.evaluate('window.__fcSession.agentUrl.split("/").pop()')
        if tok and tok in d:
            fail('the diagnostics panel shows the MCP token in clear')
        else:
            print('==> diagnostics panel open, token not shown')

    # 5. stop sharing: the viewer sees "ended" and keeps a usable tab
    s1.run_python("import FreeCAD as A\nA.ParamGet(%r).SetBool('Enabled', False)" % gs.GROUP)
    if not gs._wait(s1, 'share: stopped sharing', 40):
        fail('unticking Share did not stop the session')
    st = gs._wait_state(good, lambda x: x.get('ended'), 40)
    if not st:
        fail('the viewer never learned the session ended')
    else:
        v = gs._volumes(good, fail)
        print('==> stopped: viewer shows "ended", document still open=%s' % bool(v))
        if not v:
            fail('after the session ended the viewer lost the document')
    return s1
