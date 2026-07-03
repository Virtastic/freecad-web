# shiboken6 package for the FreeCAD wasm monolith.
# The Shiboken C extension is compiled into the executable and registered in
# the inittab as "Shiboken_fcweb"; alias it under the canonical dotted name and
# re-export its symbols like the upstream package does.
import sys
import importlib

__version__ = "6.9.0"
__version_info__ = (6, 9, 0, "", "")
# Consumed by shibokensupport.signature.parser._get_flag_enum_option; keep
# minimum < (3, 10) to avoid its "can now be simplified" dev warnings.
__minimum_python_version__ = (3, 9)
__maximum_python_version__ = (3, 13)
__path__ = []  # mark as package

Shiboken = importlib.import_module("Shiboken_fcweb")
sys.modules["shiboken6.Shiboken"] = Shiboken

from shiboken6.Shiboken import *  # noqa: E402,F401,F403
