# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Apply the glMaterialfv ambient/diffuse/emission patch to a linked FreeCAD.js.

stage-jspi.sh does this, but its regex only matches an else-branch of `{0}`. This link
emitted `{throw"glMaterialfv: TODO: "+pname}` instead, so the patch silently missed --
mat:MISS -- and the staged artifact came out without a fix the shipping one has. A silent
MISS is the dangerous shape: the link succeeds, the size looks right, and materials are
wrong at runtime.

Matches either else-branch, and either heap accessor form (growth on or off).

    python3 apply_mat_patch.py play-gui/FreeCAD.js
"""
import re
import sys

# GLEmulation.materialShininess[0] = <heap>[param<shift>]  ... then the else branch we replace
PATTERN = re.compile(
    r"else if\(pname==5633\)\{GLEmulation\.materialShininess\[0\]="
    r"(?P<heap>HEAPF32|GROWABLE_HEAP_F32\(\))"
    r"\[param(?P<shift>>>>2>>>0|>>2)\]\}"
    r"else\{(?:0|throw\"glMaterialfv: TODO: \"\+pname)\}\}"
    r"(?P<semi>;?)var _emscripten_glMaterialfv"
)


def build(heap, shift, semi):
    def f(off):
        return "%s[param%s%s]" % (heap, ("+%d" % off) if off else "", shift)

    return (
        "else if(pname==5633){GLEmulation.materialShininess[0]=%s}" % f(0)
        + "else if(pname==5632){"
        + ";".join("GLEmulation.materialEmission[%d]=%s" % (i, f(i * 4)) for i in range(4))
        + "}"
        + "else if(pname==5634){"
        + "var _r=%s,_g=%s,_b=%s,_a=%s;" % (f(0), f(4), f(8), f(12))
        + ";".join("GLEmulation.materialAmbient[%d]=%s" % (i, v)
                   for i, v in enumerate(("_r", "_g", "_b", "_a")))
        + ";"
        + ";".join("GLEmulation.materialDiffuse[%d]=%s" % (i, v)
                   for i, v in enumerate(("_r", "_g", "_b", "_a")))
        + "}"
        + "else{0}}" + semi + "var _emscripten_glMaterialfv"
    )


def main(argv):
    path = argv[1] if len(argv) > 1 else "play-gui/FreeCAD.js"
    with open(path, "r", encoding="utf-8", newline="") as f:
        s = f.read()

    if "pname==5634" in s:
        print("mat: already applied")
        return 0

    m = PATTERN.search(s)
    if not m:
        print("mat: MISS -- the glMaterialfv site did not match; do not ship this artifact",
              file=sys.stderr)
        return 1

    s = s.replace(m.group(0),
                  build(m.group("heap"), m.group("shift"), m.group("semi")), 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)

    with open(path, "r", encoding="utf-8", newline="") as f:
        check = f.read()
    ok = check.count("pname==5634") == 1 and check.count("pname==5632") >= 1
    print("mat: applied (5634=%d, 5632=%d)"
          % (check.count("pname==5634"), check.count("pname==5632")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
