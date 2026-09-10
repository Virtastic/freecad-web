# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Compile and RUN the edge expansion that patches/freecad.patch adds to SoBrepEdgeSet.

    python3 tools/check-edge-expansion.py

The patch turns Coin's index list -- line strips separated by -1 -- into GL_LINES pairs and
caches the result on the node, which is what took the a2plus assembly from 431 ms/frame to
a frame with no per-vertex work in it at all. That expansion is the only non-trivial logic
in the patch, it lives where nothing else in this repository executes it, and getting it
wrong draws the WRONG LINES rather than crashing: connecting the last vertex of one strip
to the first of the next is a silent diagonal across the model.

So take the helper out of the patch itself -- not a copy of it, the bytes that ship --
compile it against stub GL and Coin types, run it, and assert what it produced.

Needs em++ and node. Both are present wherever the linked C shims are syntax-checked.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

PATCH = 'patches/freecad.patch'
MARK = 'diff -ruNp a/src/Mod/Part/Gui/SoBrepEdgeSet.cpp'

HARNESS = r'''
// Stubs: enough of GL and Coin for the helper to compile and run outside a browser.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

typedef unsigned int GLenum;
typedef float GLfloat;
typedef int GLsizei;
typedef int64_t SbUniqueId;
#define GL_NORMAL_ARRAY 0x8075
#define GL_VERTEX_ARRAY 0x8074
#define GL_V3F 0x2A16
#define GL_LINES 0x0001

static int g_drawCalls = 0;
static GLsizei g_lastCount = 0;
static const void* g_lastPtr = nullptr;
static GLenum g_lastFormat = 0;
static void glEnableClientState(GLenum) {}
static void glDisableClientState(GLenum) {}
static void glInterleavedArrays(GLenum f, GLsizei, const void* p)
{
    g_lastFormat = f;
    g_lastPtr = p;
}
static void glDrawArrays(GLenum mode, int, GLsizei count)
{
    assert(mode == GL_LINES);
    g_drawCalls++;
    g_lastCount = count;
}

struct SbVec3f
{
    float v[3];
    SbVec3f()
    {
        v[0] = v[1] = v[2] = 0.0F;
    }
    SbVec3f(float a, float b, float c)
    {
        v[0] = a;
        v[1] = b;
        v[2] = c;
    }
    float operator[](int i) const
    {
        return v[i];
    }
};

//// HELPER ////

int main()
{
    // Five points, two strips: 0-1-2 and 3-4, separated by -1. Three segments, so six
    // vertices, and the pairs must be (0,1) (1,2) (3,4) -- never (2,3), which would draw
    // a line between two strips that share nothing.
    SbVec3f pts[5];
    for (int i = 0; i < 5; ++i) {
        pts[i] = SbVec3f((float)i, 0.0F, 0.0F);
    }
    const int32_t idx[] = {0, 1, 2, -1, 3, 4, -1};
    bool ok = fcwebDrawEdgeArray((const void*)1, 7, pts, 5, idx, 7);
    assert(ok);
    assert(g_drawCalls == 1);
    assert(g_lastCount == 6);
    assert(g_lastFormat == GL_V3F);
    const GLfloat* v = (const GLfloat*)g_lastPtr;
    // GL_V3F: three position floats per vertex and nothing else. Coin sends line vertices
    // with no normal attribute, and adding one makes the emulation light them.
    const float wantX[6] = {0.0F, 1.0F, 1.0F, 2.0F, 3.0F, 4.0F};
    for (int i = 0; i < 6; ++i) {
        if (v[i * 3] != wantX[i]) {
            printf("FAIL vertex %d x=%f want %f\n", i, (double)v[i * 3], (double)wantX[i]);
            return 1;
        }
    }

    // Same node, same id: the cache is reused and the draw is identical.
    ok = fcwebDrawEdgeArray((const void*)1, 7, pts, 5, idx, 7);
    assert(ok && g_drawCalls == 2 && g_lastCount == 6);

    // An index past the end of the coordinate array is skipped, not dereferenced.
    const int32_t bad[] = {0, 99, 1, -1};
    ok = fcwebDrawEdgeArray((const void*)2, 1, pts, 5, bad, 4);
    assert(ok);
    assert(g_lastCount == 2);

    // A strip with a single point has no segment: draw nothing rather than an empty array.
    const int32_t lone[] = {2, -1};
    assert(!fcwebDrawEdgeArray((const void*)3, 1, pts, 5, lone, 2));

    printf("edge expansion OK: %d draws, last count %d\n", g_drawCalls, g_lastCount);
    return 0;
}
'''


def helper_from_patch():
    raw = io.open(PATCH, 'rb').read().decode('utf-8', 'replace')
    i = raw.find(MARK)
    if i < 0:
        raise SystemExit('%s: the SoBrepEdgeSet section is gone' % PATCH)
    seg = raw[i:]
    j = seg.find('\ndiff -ruNp ')
    if j > 0:
        seg = seg[:j]
    added = [l[1:] for l in seg.split('\n') if l.startswith('+') and not l.startswith('+++')]
    body = '\n'.join(added)
    start = body.find('namespace\n{')
    end = body.find('}  // namespace')
    if start < 0 or end < 0:
        raise SystemExit('%s: the helper namespace is not in the added lines' % PATCH)
    return body[start:end + len('}  // namespace')]


def tool(name, fallback):
    return shutil.which(name) or (fallback if os.path.exists(fallback) else None)


def main():
    em = tool('em++', 'C:/Users/Michael Stavridis/emsdk/upstream/emscripten/em++.exe')
    if not em:
        raise SystemExit('em++ is not on PATH')
    src = HARNESS.replace('//// HELPER ////', helper_from_patch())
    work = tempfile.mkdtemp(prefix='edgeexp')
    cpp = os.path.join(work, 'edge-expansion.cpp')
    js = os.path.join(work, 'edge-expansion.js')
    io.open(cpp, 'w', encoding='utf-8', newline='\n').write(src)
    r = subprocess.run([em, '-std=c++17', '-Wall', '-Wextra', '-sASSERTIONS=1', cpp,
                        '-o', js], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stdout.write(r.stdout[-3000:])
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit('the edge helper does not compile')
    node = tool('node', 'C:/Users/Michael Stavridis/emsdk/node/24.19.0_64bit/bin/node.exe')
    if not node:
        raise SystemExit('node is not on PATH')
    r = subprocess.run([node, js], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit('the edge expansion is wrong')


if __name__ == '__main__':
    main()
