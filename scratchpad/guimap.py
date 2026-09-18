# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
# Where the menus and the toolbar buttons ARE, in page coordinates, so guidrive.js can put
# a real mouse click on them. Qt-for-wasm draws the whole window into the canvas, so a
# widget's global position is its position on the page, which is what puppeteer clicks.
#
# guidrive.js reads this file, rewrites "GUI " to its own marker, and waits for the last
# line. Keep the prefix and the line shapes exactly as they are -- it parses them with:
#     /MAP(\d+)\s+MENU '([^']*)' (\d+) (\d+)/
#     /MAP(\d+)\s+TOOL '[^']*' '([^']*)' (\d+) (\d+)/
#
# This lived in /tmp on one machine, so guidrive.js died with ENOENT everywhere else and
# the production gate never ran at all. It is tracked now.
import re
import sys

from PySide6 import QtCore, QtWidgets

import FreeCADGui as Gui


def _centre(widget, rect):
    """Page coordinates of the middle of a widget rectangle."""
    p = widget.mapToGlobal(QtCore.QPoint(rect.x() + rect.width() // 2,
                                         rect.y() + rect.height() // 2))
    return p.x(), p.y()


def _plain(html):
    """The first line of a tooltip, with the markup taken out."""
    if not html:
        return ''
    txt = re.sub(r'<[^>]+>', chr(10), html)
    for line in txt.split(chr(10)):
        line = line.strip()
        if line:
            return line
    return ''


def _names(action):
    """Every name one button answers to, most specific first.

    The caller looks up exact strings -- 'New', 'Undo', 'Fit all' -- while a Qt action
    carries several: a menu text of '&New', a tooltip of 'New Document', a command name of
    'Std_New'. Publishing one guess meant the lookup quietly found nothing and the check
    reported 'unchanged', which reads exactly like a button that does nothing.
    """
    out = []
    for raw in (action.text(), _plain(action.toolTip()), action.objectName()):
        name = (raw or '').replace('&', '').split('(')[0].strip().replace("'", '')
        if not name or name in out:
            continue
        out.append(name)
    return out
    # No first-word aliases. 'New Document', 'New Part', 'New Group' and 'New Body' would
    # all publish 'New', the last one would win the caller's map, and the click would land
    # on New Body -- which does nothing without an active document, so the check read as
    # "the New button is broken". The caller matches on a prefix instead.


mw = Gui.getMainWindow()
menus = tools = 0

bar = mw.menuBar() if mw is not None else None
if bar is not None:
    for a in bar.actions():
        # A menu with no geometry is one Qt has not laid out: clicking it hits nothing.
        if not a.isVisible():
            continue
        r = bar.actionGeometry(a)
        if r.isEmpty():
            continue
        x, y = _centre(bar, r)
        sys.__stderr__.write("GUI MENU '%s' %d %d\n" % (a.text().replace('&', ''), x, y))
        menus += 1

for tb in (mw.findChildren(QtWidgets.QToolBar) if mw is not None else []):
    if not tb.isVisible():
        continue
    name = (tb.windowTitle() or tb.objectName() or '').replace("'", '')
    for a in tb.actions():
        if a.isSeparator() or not a.isVisible():
            continue
        w = tb.widgetForAction(a)
        if w is None or not w.isVisible():
            continue
        r = w.rect()
        if r.isEmpty():
            continue
        x, y = _centre(w, r)
        for label in _names(a):
            sys.__stderr__.write("GUI TOOL '%s' '%s' %d %d\n" % (name, label, x, y))
        tools += 1

sys.__stderr__.write('GUI MAPPED menus=%d tools=%d\n' % (menus, tools))
sys.__stderr__.flush()
