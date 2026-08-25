# PySide6 package for the FreeCAD wasm monolith.
# The binding modules (QtCore/QtGui/QtWidgets) are compiled INTO the executable
# and registered in the inittab under underscore names (dotted inittab names
# break CPython's importlib bootstrap). Import them here and alias them into
# sys.modules under their canonical dotted names so both
# `from PySide6 import QtCore` and `import PySide6.QtCore` work, and so
# Shiboken's internal cross-module imports ("PySide6.QtCore") resolve.
import sys
import importlib

__version__ = "6.9.0"
__version_info__ = (6, 9, 0, "", "")
__all__ = ["QtCore", "QtGui", "QtWidgets", "QtNetwork"]
__path__ = []  # mark as package

# Order matters: QtGui pulls in QtCore, QtWidgets pulls in both.
QtCore = importlib.import_module("QtCore_fcweb")
sys.modules["PySide6.QtCore"] = QtCore
QtGui = importlib.import_module("QtGui_fcweb")
sys.modules["PySide6.QtGui"] = QtGui
QtWidgets = importlib.import_module("QtWidgets_fcweb")
sys.modules["PySide6.QtWidgets"] = QtWidgets

# QtNetwork last: it needs QtCore, and nothing above needs it. The Addon Manager is
# the reason it is here -- NetworkManager.py imports it before doing anything else,
# so without this the workbench installs and then cannot fetch a thing.
QtNetwork = importlib.import_module("QtNetwork_fcweb")
sys.modules["PySide6.QtNetwork"] = QtNetwork
