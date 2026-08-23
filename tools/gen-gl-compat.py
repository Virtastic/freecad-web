# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Generate toolchain/include/gl_compat.h from gl_legacy_stubs.c plus the legacy enum table.

gl_compat.h is force-included into Coin3D and every FreeCAD translation unit. It supplies
the two things a GLES2/WebGL2 target does not have but fixed-function code needs:

  1. DECLARATIONS for the entry points emscripten's LEGACY_GL_EMULATION omits. Those are
     exactly the ones gl_legacy_stubs.c defines, so they are read out of that file rather
     than written twice -- a stub with no declaration then fails at its call site, and a
     declaration with no stub fails at link, instead of the two drifting apart.

  2. The legacy ENUM CONSTANTS. GLES2/gl2.h carries only the subset GLES2 kept, so
     GL_ACCUM, GL_TEXTURE_GEN_S, GL_NORMALIZE, GL_LIGHT0 and the rest are simply absent.
     CI run 32224571660 is where this was established: Coin3D's SoGLRenderAction.cpp
     failed with "use of undeclared identifier 'GL_ACCUM'" and twelve more like it, having
     previously "built fine" only because it was building against an EMPTY gl_compat.h.

EVERY constant is emitted under #ifndef, so wherever a real GL header defines one, the real
definition wins and this table cannot override it. The values below are the fixed
OpenGL 1.1/1.2 assignments.

A wrong value would be worse than a missing one -- it compiles and then misbehaves at run
time -- so the generator also emits a verification translation unit (--check) that, for
every constant, asserts at PREPROCESS time that any real header agreeing to define it
agrees on the value. ci.yml compiles that against emscripten's own <GL/gl.h>.

    python tools/gen-gl-compat.py            > toolchain/include/gl_compat.h
    python tools/gen-gl-compat.py --check    > /tmp/gl_compat_check.c
"""
import re
import sys

SRC = 'gl_legacy_stubs.c'

# A definition in the stub file: starts at column 0, names a gl* symbol, is neither
# `extern` (those bind to the emulation) nor `static` (file-local helpers).
DEF = re.compile(r'^(?!extern|static)([A-Za-z_][A-Za-z0-9_ ]*?)\s+(gl[A-Za-z0-9_]+)\s*\(([^)]*)\)\s*\{', re.M)

# The fixed-function constants a GLES2 header does not carry. Grouped as the GL spec groups
# them, so a gap is visible as a gap.
ENUMS = [
    ("Primitives GLES2 dropped", [
        ("GL_QUADS", "0x0007"), ("GL_QUAD_STRIP", "0x0008"), ("GL_POLYGON", "0x0009"),
    ]),
    ("Accumulation buffer operations", [
        ("GL_ACCUM", "0x0100"), ("GL_LOAD", "0x0101"), ("GL_RETURN", "0x0102"),
        ("GL_MULT", "0x0103"), ("GL_ADD", "0x0104"),
    ]),
    ("glPushAttrib / glPopAttrib bits", [
        ("GL_CURRENT_BIT", "0x00000001"), ("GL_POINT_BIT", "0x00000002"),
        ("GL_LINE_BIT", "0x00000004"), ("GL_POLYGON_BIT", "0x00000008"),
        ("GL_POLYGON_STIPPLE_BIT", "0x00000010"), ("GL_PIXEL_MODE_BIT", "0x00000020"),
        ("GL_LIGHTING_BIT", "0x00000040"), ("GL_FOG_BIT", "0x00000080"),
        ("GL_ACCUM_BUFFER_BIT", "0x00000200"), ("GL_VIEWPORT_BIT", "0x00000800"),
        ("GL_TRANSFORM_BIT", "0x00001000"), ("GL_ENABLE_BIT", "0x00002000"),
        ("GL_HINT_BIT", "0x00008000"), ("GL_EVAL_BIT", "0x00010000"),
        ("GL_LIST_BIT", "0x00020000"), ("GL_TEXTURE_BIT", "0x00040000"),
        ("GL_SCISSOR_BIT", "0x00080000"), ("GL_ALL_ATTRIB_BITS", "0x000FFFFF"),
    ]),
    ("glPushClientAttrib / glPopClientAttrib bits", [
        ("GL_CLIENT_PIXEL_STORE_BIT", "0x00000001"),
        ("GL_CLIENT_VERTEX_ARRAY_BIT", "0x00000002"),
        ("GL_CLIENT_ALL_ATTRIB_BITS", "0xFFFFFFFF"),
    ]),
    ("Fog", [
        ("GL_EXP", "0x0800"), ("GL_EXP2", "0x0801"),
        ("GL_FOG", "0x0B60"), ("GL_FOG_INDEX", "0x0B61"), ("GL_FOG_DENSITY", "0x0B62"),
        ("GL_FOG_START", "0x0B63"), ("GL_FOG_END", "0x0B64"), ("GL_FOG_MODE", "0x0B65"),
        ("GL_FOG_COLOR", "0x0B66"),
    ]),
    ("Enable/disable capabilities the fixed-function pipeline owns", [
        ("GL_POINT_SMOOTH", "0x0B10"), ("GL_LINE_SMOOTH", "0x0B20"),
        ("GL_LINE_STIPPLE", "0x0B24"),
        ("GL_POLYGON_MODE", "0x0B40"), ("GL_POLYGON_SMOOTH", "0x0B41"),
        ("GL_POLYGON_STIPPLE", "0x0B42"),
        ("GL_LIGHTING", "0x0B50"), ("GL_COLOR_MATERIAL", "0x0B57"),
        ("GL_NORMALIZE", "0x0BA1"), ("GL_ALPHA_TEST", "0x0BC0"),
        ("GL_AUTO_NORMAL", "0x0D80"), ("GL_INDEX_LOGIC_OP", "0x0BF1"),
    ]),
    ("Alpha test state", [
        ("GL_ALPHA_TEST_FUNC", "0x0BC1"), ("GL_ALPHA_TEST_REF", "0x0BC2"),
    ]),
    ("Light model", [
        ("GL_LIGHT_MODEL_LOCAL_VIEWER", "0x0B51"), ("GL_LIGHT_MODEL_TWO_SIDE", "0x0B52"),
        ("GL_LIGHT_MODEL_AMBIENT", "0x0B53"),
        ("GL_SHADE_MODEL", "0x0B54"), ("GL_FLAT", "0x1D00"), ("GL_SMOOTH", "0x1D01"),
    ]),
    ("Matrix stacks", [
        ("GL_MODELVIEW", "0x1700"), ("GL_PROJECTION", "0x1701"), ("GL_TEXTURE", "0x1702"),
        ("GL_MATRIX_MODE", "0x0BA0"),
        ("GL_MODELVIEW_MATRIX", "0x0BA6"), ("GL_PROJECTION_MATRIX", "0x0BA7"),
        ("GL_TEXTURE_MATRIX", "0x0BA8"),
        ("GL_MODELVIEW_STACK_DEPTH", "0x0BA3"), ("GL_PROJECTION_STACK_DEPTH", "0x0BA4"),
        ("GL_TEXTURE_STACK_DEPTH", "0x0BA5"),
        ("GL_MAX_MODELVIEW_STACK_DEPTH", "0x0D36"),
        ("GL_MAX_PROJECTION_STACK_DEPTH", "0x0D38"),
        ("GL_MAX_TEXTURE_STACK_DEPTH", "0x0D39"),
    ]),
    ("Implementation limits", [
        ("GL_MAX_LIGHTS", "0x0D31"), ("GL_MAX_CLIP_PLANES", "0x0D32"),
        ("GL_MAX_ATTRIB_STACK_DEPTH", "0x0D35"),
        ("GL_MAX_CLIENT_ATTRIB_STACK_DEPTH", "0x0D3B"),
        ("GL_MAX_NAME_STACK_DEPTH", "0x0D37"), ("GL_MAX_LIST_NESTING", "0x0B31"),
        ("GL_MAX_EVAL_ORDER", "0x0D30"), ("GL_MAX_PIXEL_MAP_TABLE", "0x0D34"),
    ]),
    ("Accumulation buffer sizes", [
        ("GL_ACCUM_RED_BITS", "0x0D58"), ("GL_ACCUM_GREEN_BITS", "0x0D59"),
        ("GL_ACCUM_BLUE_BITS", "0x0D5A"), ("GL_ACCUM_ALPHA_BITS", "0x0D5B"),
        ("GL_INDEX_BITS", "0x0D51"),
    ]),
    ("Texture coordinate generation", [
        ("GL_TEXTURE_GEN_S", "0x0C60"), ("GL_TEXTURE_GEN_T", "0x0C61"),
        ("GL_TEXTURE_GEN_R", "0x0C62"), ("GL_TEXTURE_GEN_Q", "0x0C63"),
        ("GL_TEXTURE_GEN_MODE", "0x2500"),
        ("GL_OBJECT_PLANE", "0x2501"), ("GL_EYE_PLANE", "0x2502"),
        ("GL_EYE_LINEAR", "0x2400"), ("GL_OBJECT_LINEAR", "0x2401"),
        ("GL_SPHERE_MAP", "0x2402"),
        ("GL_S", "0x2000"), ("GL_T", "0x2001"), ("GL_R", "0x2002"), ("GL_Q", "0x2003"),
    ]),
    ("Material and light parameters", [
        ("GL_AMBIENT", "0x1200"), ("GL_DIFFUSE", "0x1201"), ("GL_SPECULAR", "0x1202"),
        ("GL_POSITION", "0x1203"), ("GL_SPOT_DIRECTION", "0x1204"),
        ("GL_SPOT_EXPONENT", "0x1205"), ("GL_SPOT_CUTOFF", "0x1206"),
        ("GL_CONSTANT_ATTENUATION", "0x1207"), ("GL_LINEAR_ATTENUATION", "0x1208"),
        ("GL_QUADRATIC_ATTENUATION", "0x1209"),
        ("GL_EMISSION", "0x1600"), ("GL_SHININESS", "0x1601"),
        ("GL_AMBIENT_AND_DIFFUSE", "0x1602"), ("GL_COLOR_INDEXES", "0x1603"),
    ]),
    ("Light names", [
        ("GL_LIGHT0", "0x4000"), ("GL_LIGHT1", "0x4001"), ("GL_LIGHT2", "0x4002"),
        ("GL_LIGHT3", "0x4003"), ("GL_LIGHT4", "0x4004"), ("GL_LIGHT5", "0x4005"),
        ("GL_LIGHT6", "0x4006"), ("GL_LIGHT7", "0x4007"),
    ]),
    ("Clip planes", [
        ("GL_CLIP_PLANE0", "0x3000"), ("GL_CLIP_PLANE1", "0x3001"),
        ("GL_CLIP_PLANE2", "0x3002"), ("GL_CLIP_PLANE3", "0x3003"),
        ("GL_CLIP_PLANE4", "0x3004"), ("GL_CLIP_PLANE5", "0x3005"),
    ]),
    ("Render modes (the GL_SELECT name stack)", [
        ("GL_RENDER", "0x1C00"), ("GL_FEEDBACK", "0x1C01"), ("GL_SELECT", "0x1C02"),
        ("GL_NAME_STACK_DEPTH", "0x0D70"),
    ]),
    ("Display lists", [
        ("GL_COMPILE", "0x1300"), ("GL_COMPILE_AND_EXECUTE", "0x1301"),
        ("GL_LIST_BASE", "0x0B32"), ("GL_LIST_INDEX", "0x0B33"), ("GL_LIST_MODE", "0x0B30"),
    ]),
    ("Polygon rasterization modes", [
        ("GL_POINT", "0x1B00"), ("GL_LINE", "0x1B01"), ("GL_FILL", "0x1B02"),
    ]),
    ("Client array state", [
        ("GL_VERTEX_ARRAY", "0x8074"), ("GL_NORMAL_ARRAY", "0x8075"),
        ("GL_COLOR_ARRAY", "0x8076"), ("GL_INDEX_ARRAY", "0x8077"),
        ("GL_TEXTURE_COORD_ARRAY", "0x8078"), ("GL_EDGE_FLAG_ARRAY", "0x8079"),
    ]),
    ("glInterleavedArrays formats", [
        ("GL_V2F", "0x2A20"), ("GL_V3F", "0x2A21"), ("GL_C4UB_V2F", "0x2A22"),
        ("GL_C4UB_V3F", "0x2A23"), ("GL_C3F_V3F", "0x2A24"), ("GL_N3F_V3F", "0x2A25"),
        ("GL_C4F_N3F_V3F", "0x2A26"), ("GL_T2F_V3F", "0x2A27"), ("GL_T4F_V4F", "0x2A28"),
        ("GL_T2F_C4UB_V3F", "0x2A29"), ("GL_T2F_C3F_V3F", "0x2A2A"),
        ("GL_T2F_N3F_V3F", "0x2A2B"), ("GL_T2F_C4F_N3F_V3F", "0x2A2C"),
        ("GL_T4F_C4F_N3F_V4F", "0x2A2D"),
    ]),
    ("Texture environment", [
        ("GL_TEXTURE_ENV", "0x2300"), ("GL_TEXTURE_ENV_MODE", "0x2200"),
        ("GL_TEXTURE_ENV_COLOR", "0x2201"),
        ("GL_MODULATE", "0x2100"), ("GL_DECAL", "0x2101"),
        ("GL_CLAMP", "0x2900"),
        ("GL_TEXTURE_BORDER_COLOR", "0x1004"), ("GL_TEXTURE_BORDER", "0x1005"),
        ("GL_TEXTURE_INTENSITY_SIZE", "0x8061"), ("GL_TEXTURE_LUMINANCE_SIZE", "0x8060"),
        ("GL_TEXTURE_COMPONENTS", "0x1003"),
    ]),
    ("Pixel formats and transfer", [
        ("GL_COLOR_INDEX", "0x1900"), ("GL_STENCIL_INDEX", "0x1901"),
        ("GL_RED", "0x1903"), ("GL_GREEN", "0x1904"), ("GL_BLUE", "0x1905"),
        ("GL_BGR", "0x80E0"), ("GL_BGRA", "0x80E1"),
        ("GL_INTENSITY", "0x8049"),
        ("GL_DOUBLE", "0x140A"),
        ("GL_UNPACK_SWAP_BYTES", "0x0CF0"), ("GL_UNPACK_LSB_FIRST", "0x0CF1"),
        ("GL_UNPACK_ROW_LENGTH", "0x0CF2"), ("GL_UNPACK_SKIP_ROWS", "0x0CF3"),
        ("GL_UNPACK_SKIP_PIXELS", "0x0CF4"),
        ("GL_PACK_SWAP_BYTES", "0x0D00"), ("GL_PACK_LSB_FIRST", "0x0D01"),
        ("GL_PACK_ROW_LENGTH", "0x0D02"), ("GL_PACK_SKIP_ROWS", "0x0D03"),
        ("GL_PACK_SKIP_PIXELS", "0x0D04"),
        ("GL_RED_SCALE", "0x0D14"), ("GL_RED_BIAS", "0x0D15"),
        ("GL_GREEN_SCALE", "0x0D18"), ("GL_GREEN_BIAS", "0x0D19"),
        ("GL_BLUE_SCALE", "0x0D1A"), ("GL_BLUE_BIAS", "0x0D1B"),
        ("GL_ALPHA_SCALE", "0x0D1C"), ("GL_ALPHA_BIAS", "0x0D1D"),
        ("GL_DEPTH_SCALE", "0x0D1E"), ("GL_DEPTH_BIAS", "0x0D1F"),
        ("GL_ZOOM_X", "0x0D16"), ("GL_ZOOM_Y", "0x0D17"),
        ("GL_MAP_COLOR", "0x0D10"), ("GL_MAP_STENCIL", "0x0D11"),
        ("GL_INDEX_SHIFT", "0x0D12"), ("GL_INDEX_OFFSET", "0x0D13"),
    ]),
    ("Pixel map names", [
        ("GL_PIXEL_MAP_I_TO_I", "0x0C70"), ("GL_PIXEL_MAP_S_TO_S", "0x0C71"),
        ("GL_PIXEL_MAP_I_TO_R", "0x0C72"), ("GL_PIXEL_MAP_I_TO_G", "0x0C73"),
        ("GL_PIXEL_MAP_I_TO_B", "0x0C74"), ("GL_PIXEL_MAP_I_TO_A", "0x0C75"),
        ("GL_PIXEL_MAP_R_TO_R", "0x0C76"), ("GL_PIXEL_MAP_G_TO_G", "0x0C77"),
        ("GL_PIXEL_MAP_B_TO_B", "0x0C78"), ("GL_PIXEL_MAP_A_TO_A", "0x0C79"),
    ]),
    ("Current raster / current state queries", [
        ("GL_CURRENT_COLOR", "0x0B00"), ("GL_CURRENT_INDEX", "0x0B01"),
        ("GL_CURRENT_NORMAL", "0x0B02"), ("GL_CURRENT_TEXTURE_COORDS", "0x0B03"),
        ("GL_CURRENT_RASTER_COLOR", "0x0B04"),
        ("GL_CURRENT_RASTER_POSITION", "0x0B07"),
        ("GL_CURRENT_RASTER_POSITION_VALID", "0x0B08"),
        ("GL_RASTER_POSITION_UNCLIPPED_IBM", "0x19262"),
    ]),
    ("Feedback buffer types", [
        ("GL_2D", "0x0600"), ("GL_3D", "0x0601"), ("GL_3D_COLOR", "0x0602"),
        ("GL_3D_COLOR_TEXTURE", "0x0603"), ("GL_4D_COLOR_TEXTURE", "0x0604"),
        ("GL_PASS_THROUGH_TOKEN", "0x0700"), ("GL_POINT_TOKEN", "0x0701"),
        ("GL_LINE_TOKEN", "0x0702"), ("GL_POLYGON_TOKEN", "0x0703"),
        ("GL_BITMAP_TOKEN", "0x0704"), ("GL_DRAW_PIXEL_TOKEN", "0x0705"),
        ("GL_COPY_PIXEL_TOKEN", "0x0706"), ("GL_LINE_RESET_TOKEN", "0x0707"),
    ]),
]


def check_table():
    """A name listed twice would emit two #defines -- the second silently ignored by its
    own #ifndef guard, so a wrong duplicate value would never be noticed."""
    seen = {}
    for title, items in ENUMS:
        for name, value in items:
            if name in seen and seen[name] != value:
                sys.exit('%s defined twice with different values: %s and %s'
                         % (name, seen[name], value))
            if name in seen:
                sys.exit('%s listed twice (in %r)' % (name, title))
            seen[name] = value
    return len(seen)


def parse_definitions(text):
    seen, decls = set(), []
    for m in DEF.finditer(text):
        ret, name, args = m.group(1).strip(), m.group(2), ' '.join(m.group(3).split())
        if name in seen:
            sys.exit('duplicate definition of %s in %s' % (name, SRC))
        seen.add(name)
        decls.append('%s %s(%s);' % (ret, name, args))
    if not decls:
        sys.exit('no definitions found in %s -- has the file moved?' % SRC)
    return decls


def emit_header(decls):
    n_enums = sum(len(v) for _, v in ENUMS)
    out = []
    w = out.append
    w('/* GENERATED by tools/gen-gl-compat.py from %s -- do not edit by hand.' % SRC)
    w(' *')
    w(' * What a GLES2/WebGL2 target lacks but fixed-function code needs:')
    w(' *')
    w(' *   %3d declarations -- the entry points emscripten\'s LEGACY_GL_EMULATION does not' % len(decls))
    w(' *       provide, which are exactly the ones %s defines.' % SRC)
    w(' *   %3d enum constants -- GLES2/gl2.h keeps only the subset GLES2 kept, so GL_ACCUM,' % n_enums)
    w(' *       GL_TEXTURE_GEN_S, GL_NORMALIZE, GL_LIGHT0 and the rest are simply absent.')
    w(' *')
    w(' * Force-included (-include) into Coin3D and every FreeCAD translation unit by the')
    w(' * configure scripts.')
    w(' *')
    w(' * Every constant is #ifndef-guarded, so a real GL header that defines one wins. The')
    w(' * values are the fixed OpenGL 1.1/1.2 assignments, and a wrong one would compile and')
    w(' * then misbehave -- so gen-gl-compat.py --check emits a translation unit asserting')
    w(' * that any header which also defines a constant agrees on its value. ci.yml compiles')
    w(' * that against emscripten\'s own <GL/gl.h>.')
    w(' *')
    w(' * Regenerate after changing %s:' % SRC)
    w(' *     python tools/gen-gl-compat.py > toolchain/include/gl_compat.h')
    w(' *')
    w(' * NOTE: this file is a RECONSTRUCTION. The build machine\'s original was never')
    w(' * committed; toolchain/stage-headers.sh prefers an existing copy over this one and')
    w(' * only diffs the two. See BUILD-WEH.md.')
    w(' */')
    w('#ifndef FCWEB_GL_COMPAT_H')
    w('#define FCWEB_GL_COMPAT_H')
    w('')
    w('/* Base GL types. GLES2/gl2.h is what emscripten actually provides; the desktop-only')
    w(' * scalar types the legacy API needs are added here if nothing defined them. */')
    w('#include <GLES2/gl2.h>')
    w('')
    w('#ifndef GL_COMPAT_HAVE_GLDOUBLE')
    w('#define GL_COMPAT_HAVE_GLDOUBLE 1')
    w('typedef double GLdouble;')
    w('#endif')
    w('')
    w('/* ---- legacy enum constants ------------------------------------------------------ */')
    for title, items in ENUMS:
        w('')
        w('/* %s */' % title)
        for name, value in items:
            w('#ifndef %s' % name)
            w('#define %s %s' % (name, value))
            w('#endif')
    w('')
    w('/* ---- entry points LEGACY_GL_EMULATION does not provide --------------------------- */')
    w('')
    w('#ifdef __cplusplus')
    w('extern "C" {')
    w('#endif')
    w('')
    for d in decls:
        w(d)
    w('')
    w('#ifdef __cplusplus')
    w('}  /* extern "C" */')
    w('#endif')
    w('')
    w('#endif /* FCWEB_GL_COMPAT_H */')
    return out


def emit_check():
    """A translation unit that fails to preprocess if any real GL header disagrees.

    The point is the direction of the test: `#if defined(X) && (X) != (value)` only fires
    where something ELSE has already defined the constant, so it checks this table against
    the authority wherever an authority exists, and stays silent where none does.
    """
    out = []
    w = out.append
    w('/* GENERATED by tools/gen-gl-compat.py --check -- do not edit, do not commit output.')
    w(' *')
    w(' * Compile this with the real GL headers included FIRST and gl_compat.h force-included')
    w(' * after. Every constant that both define is compared; a disagreement is a hard error')
    w(' * at preprocess time. Constants no real header defines are silently skipped, which is')
    w(' * the whole point -- those are the ones gl_compat.h exists to supply.')
    w(' */')
    w('#include <GL/gl.h>')
    w('#include <GLES2/gl2.h>')
    w('')
    for title, items in ENUMS:
        w('/* %s */' % title)
        for name, value in items:
            w('#if defined(%s) && ((%s) != (%s))' % (name, name, value))
            w('#error "gl_compat.h disagrees with the system header on %s"' % name)
            w('#endif')
    w('')
    w('int main(void) { return 0; }')
    return out


def main():
    check_table()
    check = '--check' in sys.argv[1:]
    if check:
        print('\n'.join(emit_check()))
        return
    text = open(SRC, encoding='utf-8').read()
    print('\n'.join(emit_header(parse_definitions(text))))


if __name__ == '__main__':
    main()
