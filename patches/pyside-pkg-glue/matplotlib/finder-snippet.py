if _sys.platform == "emscripten":
    # matplotlib's C extensions are statically linked into the FreeCAD wasm
    # monolith and registered in the CPython inittab under their full dotted
    # names. BuiltinImporter.find_spec refuses to resolve submodules, so install
    # a meta-path finder mapping those dotted names to BuiltinImporter (same
    # approach as numpy in this build). Must run before cbook/_api import the
    # extensions below.
    import _imp as _imp_mod
    from importlib.machinery import BuiltinImporter as _BI, ModuleSpec as _MS

    _MPL_BUILTINS = frozenset((
        "matplotlib.backends._backend_agg",
        "matplotlib.ft2font",
        "matplotlib._image",
        "matplotlib._path",
        "matplotlib._qhull",
        "matplotlib._tri",
        "matplotlib._c_internal_utils",
        "matplotlib._ttconv",
    ))

    class _MplBuiltinFinder:
        def find_spec(self, name, path=None, target=None):
            if name in _MPL_BUILTINS and _imp_mod.is_builtin(name):
                return _MS(name, _BI, is_package=False)
            return None

    if not any(f.__class__.__name__ == "_MplBuiltinFinder" for f in _sys.meta_path):
        _sys.meta_path.insert(0, _MplBuiltinFinder())
