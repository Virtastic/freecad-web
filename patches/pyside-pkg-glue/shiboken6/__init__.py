# shiboken6 package for the FreeCAD wasm monolith.
# The Shiboken C extension is compiled into the executable and registered in
# the inittab as "Shiboken_fcweb"; alias it under the canonical dotted name and
# re-export its symbols like the upstream package does.
import sys
import types
import importlib

__version__ = "6.11.2"
__version_info__ = (6, 11, 2, "", "")
# Consumed by shibokensupport.signature.parser._get_flag_enum_option; keep
# minimum < (3, 10) to avoid its "can now be simplified" dev warnings.
__minimum_python_version__ = (3, 9)
__maximum_python_version__ = (3, 13)
__path__ = []  # mark as package

# libshiboken creates its enums during PyInit_Shiboken_fcweb, and the first enum item
# runs sbkenum.cpp's _init_enum(), which is exactly
#     AutoDecRef shibo(PyImport_ImportModule("shiboken6.Shiboken"));
#     return !shibo.isNull();
# -- it never uses the module, it only requires the import to succeed. That import
# happens while THIS file is still executing, so the dotted name cannot resolve yet,
# _init_enum returns false and shiboken calls Py_FatalError("could not init enum").
# On wasm that abort unwinds the whole stack: the import machinery never releases its
# locks, PySide6 and shiboken6 stay half-initialised forever, and every workbench that
# imports PySide fails for the rest of the session (the wasm64 boot gate's
# "engine trapped while waiting for FCMADE", link 34008891984).
# A placeholder under the dotted name is enough to satisfy it; the real module replaces
# it as soon as the import returns.
sys.modules.setdefault("shiboken6.Shiboken", types.ModuleType("shiboken6.Shiboken"))
Shiboken = importlib.import_module("Shiboken_fcweb")
sys.modules["shiboken6.Shiboken"] = Shiboken

from shiboken6.Shiboken import *  # noqa: E402,F401,F403
