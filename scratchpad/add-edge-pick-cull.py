"""Per-edge culling for ray picks in SoBrepEdgeSet (wasm only) -- the edge half of
add-pick-cull.py. Coin's SoIndexedLineSet::generatePrimitives hands every segment of every
edge to SoRayPickAction::intersect(line) (closest points + two matrix multiplies each):
~15% of a preselection pick on 900a_GA3DtechProject before the face culling, the floor
after it. For a pick, walk the edges (one -1-terminated run of coordIndex each), test each
edge's cached bounding box against the pick cone, and feed only the survivors to Coin --
same picked points and the same SoLineDetail line indices.

Rewrites the SoBrepEdgeSet.cpp section of patches/freecad.patch (pristine 1.1.3 + existing
section + these edits, diff -ruNp) and appends a SoBrepEdgeSet.h section. LF files."""
import io, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, 'patches', 'freecad.patch')
T = os.path.join(ROOT, 'scratchpad', 'tree113')
WORK = os.path.join(ROOT, 'scratchpad', 'edgecull-work')


def apply_section(src, sec):
    lines = src.split(b'\n')
    out, pos = [], 0
    for h in sec.split(b'\n@@ ')[1:]:
        head, body = h.split(b'\n', 1)
        start = int(head.split()[0].split(b',')[0][1:])
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


H_EDITS = [
    (b'    void getBoundingBox(SoGetBoundingBoxAction* action) override;\n',
     b'''    void getBoundingBox(SoGetBoundingBoxAction* action) override;
#if defined(__EMSCRIPTEN__)
    // FCWEB: ray picks skip edges whose bounding box misses the pick cone (see the .cpp).
    void rayPick(SoRayPickAction* action) override;
#endif
''', 1),
    (b'''    // backreference to viewprovider that owns this node
    ViewProviderPartExt* viewProvider = nullptr;
};
''', b'''    // backreference to viewprovider that owns this node
    ViewProviderPartExt* viewProvider = nullptr;
#if defined(__EMSCRIPTEN__)
    // FCWEB: per-edge bounding boxes for ray picks, keyed on this node's id
    // (coordIndex) and the coordinate node's id.
    SbUniqueId pickBoxesNode = 0;
    SbUniqueId pickBoxesCoord = 0;
    std::vector<SbBox3f> pickBoxes;
    SbBox3f pickBoxesAll;
#endif
};
''', 1),
]

GEN = b'''
#if defined(__EMSCRIPTEN__)
// FCWEB: per-edge culling for ray picks. Coin tests this node's bounding box once
// (SoShape::rayPick) and SoIndexedLineSet::generatePrimitives then hands every segment of
// every edge to SoRayPickAction::intersect(line) -- closest points plus two matrix
// multiplies per segment -- which was ~15% of a preselection pick on a large assembly and
// the whole of it once faces are culled (2026-09-15, 900a_GA3DtechProject). Each edge is one
// -1-terminated run of coordIndex; an edge whose bounding box misses the pick cone has no
// segment that can hit, so only the survivors are generated. Same structure as
// SoShape::rayPick (pick style, object-space ray, shape box, primitives), with the shape box
// being the union of the cached edge boxes. The picked points and their SoLineDetail line
// indices are the same as Coin's; the material/normal/texture indices on a picked point are
// not, and nothing reads those for an edge (getElementPicked uses getLineIndex()).
// SoIndexedLineSet::generatePrimitives is private, hence the override one level up.
void SoBrepEdgeSet::rayPick(SoRayPickAction* action)
{
    if (this->coordIndex.getNum() < 2 || this->vertexProperty.getValue()) {
        inherited::rayPick(action);
        return;
    }
    if (!this->shouldRayPick(action)) {
        return;
    }
    this->computeObjectSpaceRay(action);

    SoState* state = action->getState();
    const SoCoordinateElement* coords = SoCoordinateElement::getInstance(state);
    const int32_t* cindices = this->coordIndex.getValues(0);
    const int32_t* const end = cindices + this->coordIndex.getNum();

    const SbUniqueId nid = this->getNodeId();
    const SbUniqueId cid = coords->getNodeId();
    if (pickBoxesNode != nid || pickBoxesCoord != cid) {
        pickBoxes.clear();
        pickBoxesAll.makeEmpty();
        for (const int32_t* ip = cindices; ip + 1 < end;) {
            SbBox3f bb;
            while (ip < end && *ip >= 0) {
                bb.extendBy(coords->get3(*ip));
                ++ip;
            }
            if (ip < end) {
                ++ip;
            }
            pickBoxes.push_back(bb);
            pickBoxesAll.extendBy(bb);
        }
        pickBoxesNode = nid;
        pickBoxesCoord = cid;
    }
    if (pickBoxesAll.isEmpty() || !action->intersect(pickBoxesAll, TRUE)) {
        return;
    }

    SoPrimitiveVertex vertex;
    SoPointDetail pointDetail;
    SoLineDetail lineDetail;
    vertex.setDetail(&pointDetail);
    size_t edge = 0;
    while (cindices + 1 < end) {
        const bool skip = edge < pickBoxes.size()
            && (pickBoxes[edge].isEmpty() || !action->intersect(pickBoxes[edge], TRUE));
        if (!skip) {
            this->beginShape(action, LINE_STRIP, &lineDetail);
        }
        int32_t i = 0;
        bool first = true;
        while (cindices < end && (i = *cindices++) >= 0) {
            if (!skip) {
                pointDetail.setCoordinateIndex(i);
                vertex.setPoint(coords->get3(i));
                this->shapeVertex(&vertex);
                if (!first) {
                    lineDetail.incPartIndex();
                }
            }
            first = false;
        }
        if (!skip) {
            this->endShape();
        }
        lineDetail.incLineIndex();
        ++edge;
    }
}
#endif
'''

CPP_EDITS = [
    (b'#include <Inventor/actions/SoGLRenderAction.h>\n',
     b'#include <Inventor/actions/SoGLRenderAction.h>\n#include <Inventor/actions/SoRayPickAction.h>\n#include <Inventor/details/SoPointDetail.h>\n', 1),
]


def section(rel, mod_fn):
    src = io.open(os.path.join(T, rel), 'rb').read()
    assert b'\r\n' not in src
    raw = io.open(P, 'rb').read()
    hdr = b'diff -ruNp a/' + rel.encode() + b' b/' + rel.encode() + b'\n'
    if hdr in raw:
        i = raw.index(hdr); j = raw.index(b'\ndiff -ruNp ', i + 10) + 1
        cur = apply_section(src, raw[i:j])
    else:
        i = j = None; cur = src
    mod = mod_fn(cur)
    a = os.path.join(WORK, 'a', rel); b = os.path.join(WORK, 'b', rel)
    os.makedirs(os.path.dirname(a), exist_ok=True); os.makedirs(os.path.dirname(b), exist_ok=True)
    io.open(a, 'wb').write(src); io.open(b, 'wb').write(mod)
    r = subprocess.run(['diff', '-ruNp', 'a/' + rel, 'b/' + rel], cwd=WORK, capture_output=True)
    assert r.returncode == 1, r.stderr
    body = r.stdout.split(b'\n', 2)[2]
    sec = hdr + b'--- a/' + rel.encode() + b'\n+++ b/' + rel.encode() + b'\n' + body
    if i is None:
        if not raw.endswith(b'\n'):
            raw += b'\n'
        raw = raw + sec
    else:
        raw = raw[:i] + sec + raw[j:]
    io.open(P, 'wb').write(raw)
    return sec


def edit(edits, tail=b''):
    def fn(cur):
        mod = cur
        for old, new, n in edits:
            assert mod.count(old) == n, (old[:50], mod.count(old))
            mod = mod.replace(old, new)
        return mod + tail
    return fn


secs = section('src/Mod/Part/Gui/SoBrepEdgeSet.cpp', edit(CPP_EDITS, GEN))
secs += section('src/Mod/Part/Gui/SoBrepEdgeSet.h', edit(H_EDITS))
io.open(os.path.join(WORK, 'sec.diff'), 'wb').write(secs)
r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'check-patch-applies.py'), os.path.join(WORK, 'sec.diff'), os.path.join(WORK, 'a')], capture_output=True, text=True)
print(r.stdout.strip()[-300:], r.stderr.strip()[-300:])
sys.exit(r.returncode)
