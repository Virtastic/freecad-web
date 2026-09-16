"""Per-face culling for ray picks in SoBrepFaceSet::generatePrimitives (wasm only).

Coin's SoShape::rayPick tests one bounding box per shape, then feeds EVERY triangle of every
face through shapeVertex()/intersect(). A preselection pick over 900a_GA3DtechProject cost
120-330 ms per mouse move of exactly that (2026-09-15 zoom-profile.py). A face whose bounding
box misses the pick cone cannot contain a hit, so its triangles are walked (the index
bookkeeping must stay exact) but not handed to Coin.

Rebuilds the SoBrepFaceSet.cpp section of patches/freecad.patch: pristine 1.1.3 file
(scratchpad/tree113) + the existing section -> current, + these edits -> new, diff -ruNp,
section replaced byte for byte, checked with tools/check-patch-applies.py. LF file."""
import io, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = 'src/Mod/Part/Gui/SoBrepFaceSet.cpp'
PRISTINE = os.path.join(ROOT, 'scratchpad', 'tree113', REL)
WORK = os.path.join(ROOT, 'scratchpad', 'pickcull-work')
P = os.path.join(ROOT, 'patches', 'freecad.patch')


def apply_section(src, sec):
    """Apply one file's unified-diff hunks (exact context) to src; both bytes, LF."""
    lines = src.split(b'\n')
    out, pos = [], 0
    hunks = sec.split(b'\n@@ ')[1:]
    for h in hunks:
        head, body = h.split(b'\n', 1)
        start = int(head.split()[0].split(b',')[0][1:])  # -start
        body = body.split(b'\n')
        if body and body[-1] == b'':
            body = body[:-1]
        out.extend(lines[pos:start - 1]); pos = start - 1
        for b in body:
            if b.startswith(b'-') or b.startswith(b' '):
                assert lines[pos] == b[1:], (pos + 1, lines[pos][:60], b[:60])
                if b.startswith(b' '):
                    out.append(lines[pos])
                pos += 1
            elif b.startswith(b'+'):
                out.append(b[1:])
            elif b.startswith(b'\\'):
                pass
            else:
                raise AssertionError(b[:60])
    out.extend(lines[pos:])
    return b'\n'.join(out)


COMMENT = b'''#if defined(__EMSCRIPTEN__)
    // FCWEB: per-face culling for ray picks. Coin tests one bounding box per shape
    // (SoShape::rayPick) and then feeds every triangle of every face below through
    // shapeVertex()/intersect(); a preselection pick over a large assembly spent 120-330 ms
    // per mouse move in exactly that (2026-09-15, 900a_GA3DtechProject). A face whose
    // bounding box misses the pick cone has no triangle that can hit it, so its triangles are
    // still walked (the index bookkeeping below must stay exact) but not handed to Coin. Same
    // picked points, fewer triangles. The boxes are cached per node until coordIndex/partIndex
    // or the coordinate node change.
    SoRayPickAction* pickAction = action->isOfType(SoRayPickAction::getClassTypeId())
        ? static_cast<SoRayPickAction*>(action)
        : nullptr;
    const int32_t* pibegin = this->partIndex.getValues(0);
    bool skipPart = false;
    if (pickAction) {
        VBO* p = PRIVATE(this).get();
        const SbUniqueId nid = this->getNodeId();
        const SbUniqueId cid = coords->getNodeId();
        if (p->pickBoxesNode != nid || p->pickBoxesCoord != cid
            || p->pickBoxes.size() != static_cast<size_t>(num_partindices)) {
            p->pickBoxes.assign(num_partindices, SbBox3f());
            const int32_t* ip = cindices;
            const int32_t* iend = cindices + numindices;
            const int32_t* pp = pibegin;
            int ppi = pp < piendptr ? *pp++ : -1;
            while (ppi == 0) {
                ppi = pp < piendptr ? *pp++ : -1;
            }
            int tri = 0;
            while (ip < iend && ppi > 0) {
                SbBox3f& bb = p->pickBoxes[static_cast<int>(pp - pibegin) - 1];
                while (ip < iend && *ip >= 0) {
                    bb.extendBy(coords->get3(*ip));
                    ++ip;
                }
                if (ip < iend) {
                    ++ip;
                }
                if (++tri == ppi) {
                    ppi = pp < piendptr ? *pp++ : -1;
                    while (ppi == 0) {
                        ppi = pp < piendptr ? *pp++ : -1;
                    }
                    tri = 0;
                }
            }
            p->pickBoxesNode = nid;
            p->pickBoxesCoord = cid;
        }
    }
    // Ray-vs-box slab test in object space. Coin's SoRayPickAction::intersect(box) walks six
    // planes in double precision plus the cone check; it was 15 ms of a 40 ms pick on the
    // a2plus assembly once the triangles were culled (2026-09-15). Triangles have no pick
    // radius, so a face whose box the RAY misses contributes nothing whatever the cone says
    // -- the plain slab test decides the same set, a hair more generously (the epsilon).
    // Near/far clipping is left to Coin's per-triangle isBetweenPlanes(), as before.
    const SbLine& fcwebRay = pickAction->getLine();
    auto rayHitsBox = [&](const SbBox3f& bb) {
        const SbVec3f& o = fcwebRay.getPosition();
        const SbVec3f& d = fcwebRay.getDirection();
        const SbVec3f& lo = bb.getMin();
        const SbVec3f& hi = bb.getMax();
        float sx, sy, sz;
        bb.getSize(sx, sy, sz);
        const float e = 1e-4f * std::max(sx, std::max(sy, sz)) + 1e-6f;
        float tmin = -std::numeric_limits<float>::max(), tmax = std::numeric_limits<float>::max();
        for (int k = 0; k < 3; ++k) {
            if (std::fabs(d[k]) < 1e-12f) {
                if (o[k] < lo[k] - e || o[k] > hi[k] + e) {
                    return false;
                }
                continue;
            }
            const float inv = 1.0f / d[k];
            float t1 = (lo[k] - e - o[k]) * inv, t2 = (hi[k] + e - o[k]) * inv;
            if (t1 > t2) {
                std::swap(t1, t2);
            }
            tmin = std::max(tmin, t1);
            tmax = std::min(tmax, t2);
            if (tmin > tmax) {
                return false;
            }
        }
        return true;
    };
    auto cullPart = [&]() {
        skipPart = false;
        if (!pickAction || pi < 0) {
            return;
        }
        int partno = static_cast<int>(piptr - pibegin) - 1;
        if (partno >= 0 && partno < static_cast<int>(PRIVATE(this)->pickBoxes.size())) {
            const SbBox3f& bb = PRIVATE(this)->pickBoxes[partno];
            skipPart = bb.isEmpty() || !rayHitsBox(bb);
        }
    };
    cullPart();
#endif
'''

FIELDS = b'''#if defined(__EMSCRIPTEN__)
    // FCWEB: per-face bounding boxes for ray picks, see generatePrimitives(). Keyed on this
    // node's id (coordIndex/partIndex) and the coordinate node's id.
    SbUniqueId pickBoxesNode = 0;
    SbUniqueId pickBoxesCoord = 0;
    std::vector<SbBox3f> pickBoxes;
#endif
'''

EMIT = b'''#if defined(__EMSCRIPTEN__)
// FCWEB: a triangle of a face whose bounding box misses the pick cone is walked but not
// handed to Coin (skipPart, generatePrimitives()). Whole triangles only, so the TRIANGLES
// primitive stream stays aligned.
#define FCWEB_SHAPE_VERTEX(v) \\
    if (!(skipPart && mode == TRIANGLES)) { \\
        this->shapeVertex(v); \\
    }
#else
#define FCWEB_SHAPE_VERTEX(v) this->shapeVertex(v)
#endif

'''

SKIP = b'''#if defined(__EMSCRIPTEN__)
        // FCWEB: a culled face whose triangles are laid out the way ViewProviderPartExt writes
        // them (v1 v2 v3 -1, pi times) is jumped over, with every index pointer and counter
        // advanced exactly as the walk below would have advanced it (v1 site + DO_VERTEX x2 +
        // the per-triangle tail). Walking it was still 40 ms a pick on the a2plus assembly
        // after the culling (2026-09-15). Anything not in that layout takes the walk.
        if (skipPart && trinr == 0 && pi > 0 && viptr + 4 * pi <= viendptr) {
            bool plain = true;
            for (int k = 0; k < pi && plain; ++k) {
                const int32_t* t = viptr + 4 * k;
                plain = t[0] >= 0 && t[1] >= 0 && t[2] >= 0 && t[3] < 0;
            }
            if (plain) {
                viptr += 4 * pi;
                if (mbind == PER_PART) {
                    matnr++;
                }
                else if (mbind == PER_PART_INDEXED) {
                    mindices++;
                }
                else if (mbind == PER_VERTEX) {
                    matnr += 3 * pi;
                }
                else if (mbind == PER_FACE) {
                    matnr += pi;
                }
                else if (mbind == PER_VERTEX_INDEXED) {
                    mindices += 4 * pi;
                }
                else if (mbind == PER_FACE_INDEXED) {
                    mindices += pi;
                }
                if (nbind == PER_VERTEX) {
                    normnr += 3 * pi;
                }
                else if (nbind == PER_FACE) {
                    normnr += pi;
                }
                else if (nbind == PER_VERTEX_INDEXED) {
                    nindices += 4 * pi;
                }
                else if (nbind == PER_FACE_INDEXED) {
                    nindices += pi;
                }
                if ((tb.isFunction() && tb.needIndices()) || (!tb.isFunction() && tbind != NONE)) {
                    if (tindices) {
                        tindices += 3 * pi;
                    }
                    else {
                        texidx += 3 * pi;
                    }
                }
                if (tindices) {
                    tindices += pi;
                }
                faceDetail.setFaceIndex(faceDetail.getFaceIndex() + pi);
                pi = piptr < piendptr ? *piptr++ : -1;
                while (pi == 0) {
                    pi = piptr < piendptr ? *piptr++ : -1;
                    if (mbind == PER_PART) {
                        matnr++;
                    }
                    else if (mbind == PER_PART_INDEXED) {
                        mindices++;
                    }
                }
                cullPart();
                continue;
            }
        }
#endif
'''

EDITS = [
    (b'#include <Inventor/actions/SoGLRenderAction.h>\n',
     b'#include <Inventor/actions/SoGLRenderAction.h>\n#include <Inventor/actions/SoRayPickAction.h>\n#include <Inventor/SbLine.h>\n#include <cmath>\n', 1),
    (b'    std::map<uint32_t, Buffer> vbomap;\n', b'    std::map<uint32_t, Buffer> vbomap;\n' + FIELDS, 1),
    (b'#define DO_VERTEX(idx) \\\n', EMIT + b'#define DO_VERTEX(idx) \\\n', 1),
    (b'    pointDetail.setCoordinateIndex(idx); \\\n    this->shapeVertex(&vertex);\n',
     b'    pointDetail.setCoordinateIndex(idx); \\\n    FCWEB_SHAPE_VERTEX(&vertex);\n', 1),
    (b'        pointDetail.setCoordinateIndex(v1);\n        vertex.setPoint(coords->get3(v1));\n        this->shapeVertex(&vertex);\n',
     b'        pointDetail.setCoordinateIndex(v1);\n        vertex.setPoint(coords->get3(v1));\n        FCWEB_SHAPE_VERTEX(&vertex);\n', 1),
    # after the leading "skip empty parts" loop, before the triangle walk
    (b'            mindices++;\n        }\n    }\n\n    while (viptr + 2 < viendptr) {\n',
     b'            mindices++;\n        }\n    }\n\n' + COMMENT + b'\n    while (viptr + 2 < viendptr) {\n', 1),
    (b'    while (viptr + 2 < viendptr) {\n        v1 = *viptr++;\n        v2 = *viptr++;\n        v3 = *viptr++;\n        if (v1 < 0 || v2 < 0 || v3 < 0) {\n',
     b'    while (viptr + 2 < viendptr) {\n' + SKIP + b'        v1 = *viptr++;\n        v2 = *viptr++;\n        v3 = *viptr++;\n        if (v1 < 0 || v2 < 0 || v3 < 0) {\n', 1),
    (b'            trinr = 0;\n        }\n    }\n    if (mode != POLYGON) {\n',
     b'            trinr = 0;\n#if defined(__EMSCRIPTEN__)\n            cullPart();\n#endif\n        }\n    }\n    if (mode != POLYGON) {\n', 1),
    (b'#undef DO_VERTEX\n', b'#undef DO_VERTEX\n#undef FCWEB_SHAPE_VERTEX\n', 1),
]

src = io.open(PRISTINE, 'rb').read()
assert b'\r\n' not in src
raw = io.open(P, 'rb').read()
hdr = b'diff -ruNp a/' + REL.encode() + b' b/' + REL.encode() + b'\n'
i = raw.index(hdr)
j = raw.index(b'\ndiff -ruNp ', i + 10) + 1
old_sec = raw[i:j]
# The edits anchor on the section as it was BEFORE any culling (67781cb); the current file's
# section is replaced wholesale, so the script can be re-run to regenerate it.
base_raw = subprocess.check_output(['git', 'show', '67781cb:patches/freecad.patch'], cwd=ROOT)
bi = base_raw.index(hdr); bj = base_raw.index(b'\ndiff -ruNp ', bi + 10) + 1
cur = apply_section(src, base_raw[bi:bj])
if len(sys.argv) > 1 and sys.argv[1] == '--check-cur':
    io.open(os.path.join(ROOT, 'scratchpad', '_bfs_cur.cpp'), 'wb').write(cur); print('wrote _bfs_cur.cpp'); sys.exit(0)
mod = cur
for old, new, n in EDITS:
    assert mod.count(old) == n, (old[:50], mod.count(old))
    mod = mod.replace(old, new)
a = os.path.join(WORK, 'a', REL); b = os.path.join(WORK, 'b', REL)
os.makedirs(os.path.dirname(a), exist_ok=True); os.makedirs(os.path.dirname(b), exist_ok=True)
io.open(a, 'wb').write(src); io.open(b, 'wb').write(mod)
r = subprocess.run(['diff', '-ruNp', 'a/' + REL, 'b/' + REL], cwd=WORK, capture_output=True)
assert r.returncode == 1, r.stderr
body = r.stdout.split(b'\n', 2)[2]   # drop the timestamped ---/+++ lines
new_sec = hdr + b'--- a/' + REL.encode() + b'\n+++ b/' + REL.encode() + b'\n' + body
io.open(P, 'wb').write(raw[:i] + new_sec + raw[j:])
io.open(os.path.join(WORK, 'sec.diff'), 'wb').write(new_sec)
print('section %d -> %d bytes' % (len(old_sec), len(new_sec)))
r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'check-patch-applies.py'), os.path.join(WORK, 'sec.diff'), os.path.join(WORK, 'a')], capture_output=True, text=True)
print(r.stdout.strip()[-300:], r.stderr.strip()[-300:])
sys.exit(r.returncode)
