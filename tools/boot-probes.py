# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Emit probe URLs for the boot harness -- statement-level bisection of frozen _setup.

    python tools/boot-probes.py            # list the probes
    python tools/boot-probes.py 3          # print the URL for probe 3

Each probe is Python source handed to the port's FCWEB_PROBE hook, which compiles and
runs it at the exact point where _PyImport_InitCore failed, with builtins/sys/_imp/
_bootstrap in scope, and prints OUT (or the exception plus frames).

WHY these: every ingredient _setup consumes verified clean from C -- the inittab, the
builtin_module_names tuple, sys.modules, and _imp.is_frozen when CALLED from C. The
failure therefore lives in what the eval loop does with them, so each probe isolates
one bytecode construct _setup uses, in the order _setup uses them. The first probe
that raises 'null argument to internal routine' names the construct.
"""
import sys
import urllib.parse

BASE = 'http://localhost:8792/probe.html'

PROBES = [
    ('sanity: does any bytecode run at all',
     "OUT = 1 + 1"),

    ('LOAD_ATTR on the sys module',
     "m = sys.modules\nOUT = type(m).__name__"),

    ('dict.items() + iteration -- _setup line 1512',
     "r = []\nfor name, module in sys.modules.items():\n    r.append(name)\nOUT = r"),

    ('type(sys) then isinstance -- _setup lines 1511/1513',
     "mt = type(sys)\nOUT = [n for n, m in sys.modules.items() if isinstance(m, mt)]"),

    ('PySequence_Contains against builtin_module_names -- _setup line 1514',
     "OUT = [n for n in sys.modules if n in sys.builtin_module_names]"),

    ('_imp.is_frozen from BYTECODE (it works from C) -- _setup line 1516',
     "OUT = _imp.is_frozen('_frozen_importlib')"),

    ('_imp.is_frozen over every module name, as _setup does',
     "r = {}\nfor n in list(sys.modules):\n    r[n] = _imp.is_frozen(n)\nOUT = r"),

    ('sys.modules[__name__] subscript -- _setup line 1526',
     "OUT = type(sys.modules['_frozen_importlib']).__name__"),

    ('_builtin_from_name for the three bootstrap modules -- _setup line 1529',
     "r = {}\nfor b in ('_thread', '_warnings', '_weakref'):\n"
     "    r[b] = 'present' if b in sys.modules else type(_imp.create_builtin(\n"
     "        _bootstrap.ModuleSpec(b, _bootstrap.BuiltinImporter))).__name__\nOUT = r"),

    ('setattr on the module object -- _setup line 1532',
     "sm = sys.modules['_frozen_importlib']\nsetattr(sm, '_fcweb_probe', 1)\n"
     "OUT = sm._fcweb_probe"),

    ('_spec_from_module + _init_module_attrs, the real work of the loop',
     "mt = type(sys)\nsp = _bootstrap._spec_from_module(sys, _bootstrap.BuiltinImporter)\n"
     "_bootstrap._init_module_attrs(sp, sys)\nOUT = repr(sp)"),

    ('the whole thing: call frozen _setup directly',
     "_bootstrap._setup(sys, _imp)\nOUT = 'setup returned'"),

    ('_weakref.ref -- _WeakValueDictionary instantiation, _setup line 1535',
     "import _weakref\nOUT = type(_weakref.ref(sys)).__name__"),
]


def main():
    if len(sys.argv) > 1:
        i = int(sys.argv[1])
        name, src = PROBES[i]
        print('# %d. %s' % (i, name))
        print('%s?probe=%s' % (BASE, urllib.parse.quote(src, safe='')))
        return
    for i, (name, src) in enumerate(PROBES):
        print('%2d. %s' % (i, name))
        print('    %s' % src.replace('\n', ' ; '))


if __name__ == '__main__':
    main()
