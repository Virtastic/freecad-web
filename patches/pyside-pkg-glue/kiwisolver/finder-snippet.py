if _sys.platform == "emscripten":
    # kiwisolver._cext is statically linked into the FreeCAD wasm monolith and
    # registered in the inittab under its dotted name; map it to BuiltinImporter.
    import _imp as _imp_mod
    from importlib.machinery import BuiltinImporter as _BI, ModuleSpec as _MS

    class _KiwiBuiltinFinder:
        def find_spec(self, name, path=None, target=None):
            if name == "kiwisolver._cext" and _imp_mod.is_builtin(name):
                return _MS(name, _BI, is_package=False)
            return None

    if not any(f.__class__.__name__ == "_KiwiBuiltinFinder" for f in _sys.meta_path):
        _sys.meta_path.insert(0, _KiwiBuiltinFinder())
