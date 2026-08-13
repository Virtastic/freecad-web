# Where are the Model/Tasks tabs, the tree items, and the property rows? Published as
# screen coordinates so the harness can click them like a person.
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui, FreeCAD as App

def say(m):
    sys.__stderr__.write("GP " + str(m) + "\n"); sys.__stderr__.flush()

mw = Gui.getMainWindow()
for tb in mw.findChildren(QtWidgets.QTabBar):
    if not tb.isVisible():
        continue
    labels = [tb.tabText(i) for i in range(tb.count())]
    if any(l in ('Model', 'Tasks') for l in labels):
        for i, l in enumerate(labels):
            r = tb.tabRect(i)
            c = tb.mapToGlobal(r.center())
            say("TAB %s|%d|%d|current=%s" % (l, c.x(), c.y(), i == tb.currentIndex()))

for t in mw.findChildren(QtWidgets.QTreeWidget):
    if not t.isVisible() or t.topLevelItemCount() == 0:
        continue
    vis = t.viewport().rect()
    def walk(it, depth):
        if depth > 2:
            return
        r = t.visualItemRect(it)
        if r.isValid() and vis.intersects(r):
            p = t.viewport().mapToGlobal(r.center())
            if p.x() > 0 and p.y() > 0:
                say("TREEITEM %s|%d|%d" % (it.text(0)[:28], p.x(), p.y()))
        for i in range(it.childCount()):
            walk(it.child(i), depth + 1)
    for i in range(t.topLevelItemCount()):
        walk(t.topLevelItem(i), 0)
    break

pe = [v for v in mw.findChildren(QtWidgets.QTreeView)
      if v.isVisible() and 'propertyEditor' in (v.objectName() or '')]
for v in pe:
    m = v.model()
    say("PROPROWS %s=%d" % (v.objectName(), m.rowCount() if m else -1))
