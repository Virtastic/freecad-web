#!/usr/bin/env bash
# Make the vendored ifcopenshell usable in the browser build (BIM workbench).
#   1. shapely needs native GEOS (not in wasm) but ifcopenshell.util.shape imports
#      it at module top -> importing the whole ifcopenshell.util chain crashes,
#      which breaks BIM's nativeifc observer on every document change. Make the
#      import optional (it is used by a single polygon-union helper).
#   2. lark (pure-python) is absent, so ifcopenshell prints "No stream support"
#      and the IFC selector language is unavailable. Vendor it into pyside-pkg.
# Idempotent. Run before the browser relink (from repo root).
set -euo pipefail
cd "$(dirname "$0")/.."
PKG="deps/wasm/pyside-pkg"
SHAPE="$PKG/ifcopenshell/util/shape.py"

# 1. shapely optional
if [ -f "$SHAPE" ] && ! grep -q "shapely = None" "$SHAPE"; then
  python3 - "$SHAPE" <<'PY'
import sys
f=sys.argv[1]; s=open(f).read()
old="import shapely\nimport shapely.ops\n"
new=("try:\n"
     "    import shapely\n"
     "    import shapely.ops\n"
     "except ImportError:  # wasm: no native GEOS; used by one helper only\n"
     "    shapely = None\n")
if old in s:
    open(f,'w').write(s.replace(old,new,1)); print("[ifc-deps] shapely made optional")
else:
    print("[ifc-deps] shapely import pattern not found (skipped)")
PY
else
  echo "[ifc-deps] shapely already optional"
fi

# 2. vendor lark (pure python) if missing
if [ ! -f "$PKG/lark/__init__.py" ]; then
  TMP=$(mktemp -d)
  if python3 -m pip download lark --no-deps --no-binary :all: -d "$TMP" >/dev/null 2>&1; then
    tar xzf "$TMP"/lark-*.tar.gz -C "$TMP"
    LARK=$(find "$TMP" -maxdepth 2 -type d -name lark | head -1)
    [ -n "$LARK" ] && cp -R "$LARK" "$PKG/" && echo "[ifc-deps] vendored lark into pyside-pkg"
  else
    echo "[ifc-deps] WARN: could not download lark (IFC streaming/selector stays off)"
  fi
  rm -rf "$TMP"
else
  echo "[ifc-deps] lark already present"
fi
