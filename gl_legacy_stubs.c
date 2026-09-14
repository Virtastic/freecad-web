/* External-linkage definitions for fixed-function GL calls that Coin3D's viewport makes but
 * emscripten's LEGACY_GL_EMULATION does not provide. Without them the FreeCAD GUI does not
 * link at all.
 *
 * They are NOT all no-ops, and the distinction matters: an empty body here is not
 * "unimplemented", it is a draw, a state change or a query silently discarded at run time.
 * Where the emulation provides an equivalent, these forward to it rather than drop the call
 * -- the immediate-mode doubles to their float forms, glRect to the quad the spec defines it
 * as, and the scalar material/light setters to the vector forms the JS glue implements.
 *
 * `tools/gl-noop-inventory.py` classifies every entry point below as EMPTY, CONSTANT or
 * FORWARDING, and the ci.yml `shims` job prints it on every push. The empty count should
 * only ever fall.
 *
 * What remains empty is mostly genuinely absent from WebGL -- stipple patterns, the
 * accumulation buffer, colour-index mode, pixel transfer -- plus two groups that are real
 * work rather than impossible: the GL_SELECT name stack, and display lists (see glGenLists
 * below, and ROADMAP item 5). A full Coin->WebGL viewport port would replace all of it. */
#include <emscripten/em_js.h>
#include <emscripten/emscripten.h>
#include <stdint.h>
typedef unsigned int   GLenum;
typedef unsigned int   GLbitfield;
typedef int            GLint;
typedef int            GLsizei;
typedef unsigned char  GLubyte;
typedef float          GLfloat;
typedef double         GLdouble;
typedef short          GLshort;
typedef unsigned short GLushort;

/* The float entry points LEGACY_GL_EMULATION really does implement. This file is compiled
 * WITHOUT the gl_compat.h force-include (see fcwasm_draw_text_tris below), so naming them
 * here binds to the emulation rather than to the shims Coin's sources see. */
extern void glNormal3f(GLfloat, GLfloat, GLfloat);
extern void glVertex2f(GLfloat, GLfloat);
extern void glVertex3f(GLfloat, GLfloat, GLfloat);
extern void glColor3f(GLfloat, GLfloat, GLfloat);
extern void glColor4f(GLfloat, GLfloat, GLfloat, GLfloat);
extern void glTexCoord2f(GLfloat, GLfloat);
extern void glBegin(GLenum);
extern void glEnd(void);
extern void glMaterialfv(GLenum, GLenum, const GLfloat*);
extern void glLightfv(GLenum, GLenum, const GLfloat*);
extern void glLightModelfv(GLenum, const GLfloat*);
extern void glTexCoord3f(GLfloat, GLfloat, GLfloat);
extern void glTexCoord4f(GLfloat, GLfloat, GLfloat, GLfloat);

/* glPushAttrib/glPopAttrib keep only what this file itself models: the pixel zoom. The
 * axis cross sets glPixelZoom(1/3) inside a glPushAttrib(GL_ALL_ATTRIB_BITS) pair and never
 * resets it; with no-op push/pop every later glDrawPixels -- Coin's SoText2 labels -- drew at
 * a third of their size (dots where the colour bar's numbers should be, 2026-09-14). */
static int fc_dl_note(int kind, double a, double b, double c, double d, double e, double f, const void* p, int bytes);
static void fc_push_attrib(void);
static void fc_pop_attrib(void);
static float fc_zoom[2] = { 1.0f, 1.0f };   /* glPixelZoom: scales glDrawPixels only, as the spec says */
static float fc_zoom_stack[16][2];
static int fc_zoom_depth = 0;
static void fc_push_attrib(void) { if (fc_zoom_depth < 16) { fc_zoom_stack[fc_zoom_depth][0] = fc_zoom[0]; fc_zoom_stack[fc_zoom_depth][1] = fc_zoom[1]; } fc_zoom_depth++; }
static void fc_pop_attrib(void) { if (fc_zoom_depth > 0) { fc_zoom_depth--; if (fc_zoom_depth < 16) { fc_zoom[0] = fc_zoom_stack[fc_zoom_depth][0]; fc_zoom[1] = fc_zoom_stack[fc_zoom_depth][1]; } } }
void glPushAttrib(GLbitfield m) { (void)m; if (fc_dl_note(5, 0, 0, 0, 0, 0, 0, 0, 0)) fc_push_attrib(); }
void glPopAttrib(void) { if (fc_dl_note(6, 0, 0, 0, 0, 0, 0, 0, 0)) fc_pop_attrib(); }
void glPushClientAttrib(GLbitfield m) { (void)m; }
void glPopClientAttrib(void) {}
/* glRect(x1,y1,x2,y2) is defined by the GL spec as exactly this quad, in this winding.
 * Emitting it through glBegin/glEnd -- which the emulation does provide -- turns two more
 * silently-dropped draws into real ones. */
static void fcwasm_rect(GLfloat x1, GLfloat y1, GLfloat x2, GLfloat y2) {
    const GLenum GL_TRIANGLE_FAN_ = 0x0006;
    glBegin(GL_TRIANGLE_FAN_);
    glVertex2f(x1, y1); glVertex2f(x2, y1); glVertex2f(x2, y2); glVertex2f(x1, y2);
    glEnd();
}
void glRecti(GLint a, GLint b, GLint c, GLint d) { fcwasm_rect((GLfloat)a,(GLfloat)b,(GLfloat)c,(GLfloat)d); }
void glRectf(GLfloat a, GLfloat b, GLfloat c, GLfloat d) { fcwasm_rect(a,b,c,d); }
void glVertex2d(GLdouble x, GLdouble y) { glVertex2f((GLfloat)x,(GLfloat)y); }
void glVertex3d(GLdouble x, GLdouble y, GLdouble z) { glVertex3f((GLfloat)x,(GLfloat)y,(GLfloat)z); }
void glVertex3dv(const GLdouble* v) { if (v) glVertex3f((GLfloat)v[0],(GLfloat)v[1],(GLfloat)v[2]); }
void glColor3d(GLdouble r, GLdouble g, GLdouble b) { glColor3f((GLfloat)r,(GLfloat)g,(GLfloat)b); }
void glColor4d(GLdouble r, GLdouble g, GLdouble b, GLdouble a) { glColor4f((GLfloat)r,(GLfloat)g,(GLfloat)b,(GLfloat)a); }
void glNormal3d(GLdouble x, GLdouble y, GLdouble z) { glNormal3f((GLfloat)x,(GLfloat)y,(GLfloat)z); }
void glTexCoord2d(GLdouble s, GLdouble t) { glTexCoord2f((GLfloat)s,(GLfloat)t); }
/* GLushort, not GLshort: the GL spec has always had the stipple pattern unsigned, and
 * emscripten's own <GL/gl.h> declares it that way. This file is compiled without that
 * header, so the mismatch stayed invisible until gl_compat.h -- generated from these
 * signatures -- was included alongside it and the two declarations collided. Harmless
 * in wasm (both pass as i32) but wrong, and it broke every unit that sees both. */
void glLineStipple(GLint f, GLushort p) { (void)f;(void)p; }
void glPolygonStipple(const GLubyte* m) { (void)m; }

/* second batch */
void glAccum(GLenum op, GLfloat v) { (void)op;(void)v; }
void glColorMaterial(GLenum f, GLenum m) { (void)f;(void)m; }
void glGetDoublev(GLenum pn, GLdouble* p) { (void)pn; if (p) { for (int i=0;i<16;++i) p[i]=(i%5==0)?1.0:0.0; } }
/* glPixelZoom scales glDrawPixels only (never glBitmap), as the spec says; see the raster ops at the end. */
static void fc_pixel_zoom(float x, float y) { fc_zoom[0] = x; fc_zoom[1] = y; }
void glPixelZoom(GLfloat x, GLfloat y) { if (fc_dl_note(4, x, y, 0, 0, 0, 0, 0, 0)) fc_pixel_zoom(x, y); }
void glTexCoord4fv(const GLfloat* v) { if (v) glTexCoord4f(v[0],v[1],v[2],v[3]); }
// Returns GLint (hit count in GL_SELECT/GL_FEEDBACK exit) — a void definition
// is a wasm signature mismatch vs callers expecting the count (mesh picking).
GLint glRenderMode(GLenum m) { (void)m; return 0; }
void glSelectBuffer(GLsizei n, unsigned int* b) { (void)n;(void)b; }
void glInitNames(void) {}
void glPushName(unsigned int n) { (void)n; }
void glPopName(void) {}
void glLoadName(unsigned int n) { (void)n; }
void glClipPlane(GLenum p, const GLdouble* e) { (void)p;(void)e; }
void glGetClipPlane(GLenum p, GLdouble* e) { (void)p;(void)e; }
void glReadBuffer(GLenum m) { (void)m; }
void glCopyPixels(GLint x, GLint y, GLsizei w, GLsizei h, GLenum t) { (void)x;(void)y;(void)w;(void)h;(void)t; }

/* third batch — the exact 17 fixed-function GL funcs LEGACY_GL_EMULATION lacks
 * that Coin references. glGenLists returns 0 so Coin falls back to immediate
 * mode (which LEGACY_GL emulates), giving a chance at real rendering. */
typedef unsigned int GLuint;
/* Display lists are Coin's render caches: the desktop is fast on big static scenes because
 * each separator is compiled once and replayed. They live in the JS glue (__fcDL, put there
 * by tools/patch-freecad-js.py): every GL import called between glNewList and glEndList is
 * recorded, pointer arguments are copied, and glCallList replays the list. Without the glue
 * object glGenLists answers 0 and Coin renders uncached, as it did before 2026-09-14. */
EM_JS(unsigned int, fcweb_dl_gen, (int range), { return (typeof __fcDL !== "undefined") ? __fcDL.gen(range) : 0; });
EM_JS(void, fcweb_dl_begin, (unsigned int list, unsigned int mode), { if (typeof __fcDL !== "undefined") __fcDL.begin(list, mode); });
EM_JS(void, fcweb_dl_end, (void), { if (typeof __fcDL !== "undefined") __fcDL.end(); });
EM_JS(void, fcweb_dl_call, (unsigned int list), { if (typeof __fcDL !== "undefined") __fcDL.call(list); });
EM_JS(void, fcweb_dl_del, (unsigned int list, int range), { if (typeof __fcDL !== "undefined") __fcDL.del(list, range); });
/* This file's own raster ops are not GL imports, so the recorder cannot see them. They ask
 * whether a list is being recorded (0 no, 1 GL_COMPILE, 2 GL_COMPILE_AND_EXECUTE), push
 * themselves as an op that calls back into fcweb_dl_exec() at replay -- with the pixel data
 * copied -- and run now only when the mode says so. Evaluated at replay, as GL specifies
 * for glRasterPos: the list's own matrix loads have executed by then. */
EM_JS(int, fcweb_dl_rec_state, (void), { return (typeof __fcDL !== "undefined" && __fcDL.rec && !__fcDL.replaying) ? (__fcDL.rec.exec ? 2 : 1) : 0; });
EM_JS(void, fcweb_dl_push, (int kind, double a, double b, double c, double d, double e, double f, double p, int bytes), { if (typeof __fcDL !== "undefined") __fcDL.pushC(kind, a, b, c, d, e, f, p, bytes); });
static int fc_dl_note(int kind, double a, double b, double c, double d, double e, double f, const void* p, int bytes) {
    int st = fcweb_dl_rec_state();
    if (!st) return 1;                                   /* not recording: run normally */
    fcweb_dl_push(kind, a, b, c, d, e, f, (double)(uintptr_t)p, bytes);
    return st == 2;                                      /* COMPILE_AND_EXECUTE runs it now as well */
}
GLuint glGenLists(GLsizei range) { return fcweb_dl_gen(range); }
void glNewList(GLuint list, GLenum mode) { fcweb_dl_begin(list, mode); }
void glEndList(void) { fcweb_dl_end(); }
void glCallList(GLuint list) { fcweb_dl_call(list); }
void glDeleteLists(GLuint list, GLsizei range) { fcweb_dl_del(list, range); }
void glClearIndex(GLfloat c) { (void)c; }
void glIndexi(GLint c) { (void)c; }
void glLightModeli(GLenum pn, GLint p) { GLfloat f = (GLfloat)p; glLightModelfv(pn, &f); }
void glLightf(GLenum light, GLenum pn, GLfloat p) { glLightfv(light, pn, &p); }
/* The scalar forms are defined by the GL spec as the 1-element vector call, and the vector
 * forms are the ones the JS glue actually implements -- glMaterialfv in particular, which
 * BUILD-WEH.md records as handling the cases Coin uses (EMISSION, AMBIENT_AND_DIFFUSE).
 * glMaterialf carries GL_SHININESS, so dropping it silently flattens specular highlights. */
void glMaterialf(GLenum face, GLenum pn, GLfloat p) { glMaterialfv(face, pn, &p); }
void glPixelMapfv(GLenum m, GLsizei n, const GLfloat* v) { (void)m;(void)n;(void)v; }
void glPixelMapuiv(GLenum m, GLsizei n, const GLuint* v) { (void)m;(void)n;(void)v; }
void glPixelTransferf(GLenum pn, GLfloat p) { (void)pn;(void)p; }
void glPixelTransferi(GLenum pn, GLint p) { (void)pn;(void)p; }
void glTexCoord3fv(const GLfloat* v) { if (v) glTexCoord3f(v[0],v[1],v[2]); }
void glTexGenf(GLenum coord, GLenum pn, GLfloat p) { (void)coord;(void)pn;(void)p; }
void glVertex2s(GLshort x, GLshort y) { glVertex2f((GLfloat)x,(GLfloat)y); }

/* glInterleavedArrays: MeshGui's SoFCMeshObject/SoFCIndexedFaceSet feed
 * interleaved vertex/normal/color/texcoord arrays. LEGACY_GL_EMULATION lacks
 * it, but it decomposes exactly into the client-state calls the emulation DOES
 * provide, so implement it per the classic GL spec (component order T,C,N,V). */
extern void glEnableClientState(GLenum);
extern void glDisableClientState(GLenum);
extern void glVertexPointer(GLint, GLenum, GLsizei, const void*);
extern void glNormalPointer(GLenum, GLsizei, const void*);
extern void glColorPointer(GLint, GLenum, GLsizei, const void*);
extern void glTexCoordPointer(GLint, GLenum, GLsizei, const void*);
void glInterleavedArrays(GLenum format, GLsizei stride, const void* pointer) {
    const GLenum GL_VERTEX_ARRAY_=0x8074, GL_NORMAL_ARRAY_=0x8075,
                 GL_COLOR_ARRAY_=0x8076, GL_TEXTURE_COORD_ARRAY_=0x8078;
    const GLenum GL_FLOAT_=0x1406, GL_UNSIGNED_BYTE_=0x1401;
    const int F = (int)sizeof(GLfloat);
    int tc=0, cc=0, ct=(int)GL_FLOAT_, nrm=0, vc=3;
    switch (format) {
        case 0x2A20: vc=2; break;                                   /* V2F */
        case 0x2A21: vc=3; break;                                   /* V3F */
        case 0x2A22: cc=4; ct=(int)GL_UNSIGNED_BYTE_; vc=2; break;   /* C4UB_V2F */
        case 0x2A23: cc=4; ct=(int)GL_UNSIGNED_BYTE_; vc=3; break;   /* C4UB_V3F */
        case 0x2A24: cc=3; vc=3; break;                             /* C3F_V3F */
        case 0x2A25: nrm=1; vc=3; break;                            /* N3F_V3F */
        case 0x2A26: cc=4; nrm=1; vc=3; break;                      /* C4F_N3F_V3F */
        case 0x2A27: tc=2; vc=3; break;                             /* T2F_V3F */
        case 0x2A28: tc=4; vc=4; break;                             /* T4F_V4F */
        case 0x2A29: tc=2; cc=4; ct=(int)GL_UNSIGNED_BYTE_; vc=3; break; /* T2F_C4UB_V3F */
        case 0x2A2A: tc=2; cc=3; vc=3; break;                       /* T2F_C3F_V3F */
        case 0x2A2B: tc=2; nrm=1; vc=3; break;                      /* T2F_N3F_V3F */
        case 0x2A2C: tc=2; cc=4; nrm=1; vc=3; break;                /* T2F_C4F_N3F_V3F */
        case 0x2A2D: tc=4; cc=4; nrm=1; vc=4; break;                /* T4F_C4F_N3F_V4F */
        default: return;
    }
    int off = 0;
    int toff=off; if (tc) off += tc*F;
    int coff=off; if (cc) off += (ct==(int)GL_UNSIGNED_BYTE_) ? 4 : cc*F;
    int noff=off; if (nrm) off += 3*F;
    int voff=off; off += vc*F;
    GLsizei str = stride ? stride : (GLsizei)off;
    const char* base = (const char*)pointer;
    if (tc) { glEnableClientState(GL_TEXTURE_COORD_ARRAY_); glTexCoordPointer(tc, GL_FLOAT_, str, base+toff); }
    else glDisableClientState(GL_TEXTURE_COORD_ARRAY_);
    if (cc) { glEnableClientState(GL_COLOR_ARRAY_); glColorPointer(cc, (GLenum)ct, str, base+coff); }
    else glDisableClientState(GL_COLOR_ARRAY_);
    if (nrm) { glEnableClientState(GL_NORMAL_ARRAY_); glNormalPointer(GL_FLOAT_, str, base+noff); }
    else glDisableClientState(GL_NORMAL_ARRAY_);
    glEnableClientState(GL_VERTEX_ARRAY_); glVertexPointer(vc, GL_FLOAT_, str, base+voff);
}

/* fcwasm_draw_text_tris: draw SoAsciiText glyph triangles through the GL
 * emulation's CLIENT-ARRAY path instead of glBegin/glEnd. The immediate-mode
 * assembly of Coin's per-glyph text batches comes out corrupt under
 * LEGACY_GL_EMULATION (glyph triangles paint as a screen-spanning fan), while
 * client-side vertex arrays render correctly. This file is compiled WITHOUT
 * the gl_compat.h force-include, so the calls below bind to the real
 * emulation entry points (Coin sources see no-op shims for these). */
extern void glDrawArrays(GLenum, GLint, GLsizei);
void fcwasm_draw_text_tris(const float* verts, int nverts) {
    const GLenum GL_VERTEX_ARRAY_ = 0x8074, GL_NORMAL_ARRAY_ = 0x8075,
                 GL_COLOR_ARRAY_ = 0x8076, GL_TEXTURE_COORD_ARRAY_ = 0x8078;
    const GLenum GL_FLOAT_ = 0x1406, GL_TRIANGLES_ = 0x0004;
    if (!verts || nverts < 3) return;
    glDisableClientState(GL_NORMAL_ARRAY_);
    glDisableClientState(GL_COLOR_ARRAY_);
    glDisableClientState(GL_TEXTURE_COORD_ARRAY_);
    glEnableClientState(GL_VERTEX_ARRAY_);
    glVertexPointer(3, GL_FLOAT_, 0, verts);
    glNormal3f(0.0f, 0.0f, 1.0f);
    glDrawArrays(GL_TRIANGLES_, 0, nverts);
    glDisableClientState(GL_VERTEX_ARRAY_);
}

/* ARB VBO suffix aliases used by PartGui's Coin SoBrepFaceSet (map to core). */
#include <GLES2/gl2.h>
#include <stdlib.h>
void glBindBufferARB(GLenum target, GLuint buffer) { glBindBuffer(target, buffer); }
void glGenBuffersARB(GLsizei n, GLuint* buffers) { glGenBuffers(n, buffers); }
void glDeleteBuffersARB(GLsizei n, const GLuint* buffers) { glDeleteBuffers(n, buffers); }
void glBufferDataARB(GLenum target, long size, const void* data, GLenum usage) { glBufferData(target, size, data, usage); }

/* Raster operations: glRasterPos + glBitmap / glDrawPixels, the way Coin's SoText2 uses
 * them (every 2D label: the FEM colour bar's numbers, axis and dimension text). SoText2 sets
 * an ortho projection in window pixels, positions each string with glRasterPos3f and hands
 * over either one RGBA image of the whole string (FreeType, antialiased: glDrawPixels) or a
 * 1-bit mask per glyph (the built-in font: glBitmap, coloured with the raster colour).
 * These were empty until 2026-09-13, so no 2D text ever reached the screen.
 *
 * The raster position is projected through the current matrices to a window position, as
 * the spec says; the image is then drawn as one textured quad under a window-pixel ortho of
 * our own, at the raster depth, and every piece of state touched is put back. A texture per
 * call is the price of not caching: a colour bar is a dozen small images a frame. */
extern void glMatrixMode(GLenum);
extern void glPushMatrix(void);
extern void glPopMatrix(void);
extern void glLoadIdentity(void);
extern void glOrtho(GLdouble, GLdouble, GLdouble, GLdouble, GLdouble, GLdouble);

static struct { float x, y, z; float color[4]; int valid; } fc_raster = { 0, 0, 0, {1, 1, 1, 1}, 0 };

static void fc_mat_mul_vec(const float* m, const float* v, float* out) {   /* column-major, as GL stores it */
    for (int r = 0; r < 4; r++) out[r] = m[r] * v[0] + m[4 + r] * v[1] + m[8 + r] * v[2] + m[12 + r] * v[3];
}

static void fc_raster_pos(float x, float y, float z) {
    float mv[16], pr[16], obj[4] = { x, y, z, 1.0f }, eye[4], clip[4];
    GLint vp[4];
    glGetFloatv(0x0BA6 /* GL_MODELVIEW_MATRIX */, mv);
    glGetFloatv(0x0BA7 /* GL_PROJECTION_MATRIX */, pr);
    glGetIntegerv(0x0BA2 /* GL_VIEWPORT */, vp);
    fc_mat_mul_vec(mv, obj, eye);
    fc_mat_mul_vec(pr, eye, clip);
    if (clip[3] == 0.0f) { fc_raster.valid = 0; return; }
    fc_raster.x = (float)vp[0] + (clip[0] / clip[3] + 1.0f) * 0.5f * (float)vp[2];
    fc_raster.y = (float)vp[1] + (clip[1] / clip[3] + 1.0f) * 0.5f * (float)vp[3];
    fc_raster.z = clip[2] / clip[3];
    fc_raster.color[0] = fc_raster.color[1] = fc_raster.color[2] = fc_raster.color[3] = 1.0f;
    glGetFloatv(0x0B00 /* GL_CURRENT_COLOR */, fc_raster.color);
    fc_raster.valid = 1;
}

/* One RGBA image at window position (x, y), bottom-left origin, rows bottom-up. */
/* The images repeat: a glyph of the built-in font is the same 32x14 bitmap every frame, and a
 * string's RGBA buffer changes only when the string does. A colour bar is ~160 glyphs a frame,
 * so uploading each one every time is 160 texture creations per paint. Cache by content hash
 * and size, per GL context (a texture belongs to the context that made it; Coin has one per
 * view), least-recently-used out. */
extern long emscripten_webgl_get_current_context(void);
#define FC_TEXCACHE 256
static struct { long ctx; GLsizei w, h; unsigned hash; GLuint tex; unsigned stamp; } fc_texcache[FC_TEXCACHE];
static unsigned fc_texstamp = 0;

static GLuint fc_cached_texture(GLsizei w, GLsizei h, const GLubyte* rgba) {
    const GLenum GL_TEXTURE_2D_ = 0x0DE1, GL_RGBA_ = 0x1908, GL_UNSIGNED_BYTE_ = 0x1401;
    const long ctx = emscripten_webgl_get_current_context();
    const size_t n = (size_t)w * (size_t)h * 4;
    unsigned hash = 2166136261u;                       /* FNV-1a over the pixels */
    for (size_t i = 0; i < n; i++) { hash ^= rgba[i]; hash *= 16777619u; }
    int victim = 0;
    for (int i = 0; i < FC_TEXCACHE; i++) {
        if (fc_texcache[i].tex && fc_texcache[i].ctx == ctx && fc_texcache[i].w == w && fc_texcache[i].h == h && fc_texcache[i].hash == hash) {
            fc_texcache[i].stamp = ++fc_texstamp;
            glBindTexture(GL_TEXTURE_2D_, fc_texcache[i].tex);
            return fc_texcache[i].tex;
        }
        if (!fc_texcache[i].tex) { victim = i; break; }
        if (fc_texcache[i].stamp < fc_texcache[victim].stamp) victim = i;
    }
    if (fc_texcache[victim].tex) {
        /* A texture from another context cannot be deleted here; let it leak with its view. */
        if (fc_texcache[victim].ctx == ctx) glDeleteTextures(1, &fc_texcache[victim].tex);
        fc_texcache[victim].tex = 0;
    }
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D_, tex);
    glTexParameteri(GL_TEXTURE_2D_, 0x2801 /* MIN_FILTER */, 0x2601 /* LINEAR */);
    glTexParameteri(GL_TEXTURE_2D_, 0x2800 /* MAG_FILTER */, 0x2601);
    glTexParameteri(GL_TEXTURE_2D_, 0x2802 /* WRAP_S */, 0x812F /* CLAMP_TO_EDGE */);
    glTexParameteri(GL_TEXTURE_2D_, 0x2803 /* WRAP_T */, 0x812F);
    glTexImage2D(GL_TEXTURE_2D_, 0, GL_RGBA_, w, h, 0, GL_RGBA_, GL_UNSIGNED_BYTE_, rgba);
    fc_texcache[victim].ctx = ctx; fc_texcache[victim].w = w; fc_texcache[victim].h = h;
    fc_texcache[victim].hash = hash; fc_texcache[victim].tex = tex; fc_texcache[victim].stamp = ++fc_texstamp;
    return tex;
}

static void fc_draw_rgba(float x, float y, GLsizei w, GLsizei h, const GLubyte* rgba, float zx, float zy) {
    const GLenum GL_TEXTURE_2D_ = 0x0DE1;
    const GLenum GL_MODELVIEW_ = 0x1700, GL_PROJECTION_ = 0x1701, GL_TRIANGLE_FAN_ = 0x0006;
    const GLenum GL_BLEND_ = 0x0BE2, GL_LIGHTING_ = 0x0B50;
    GLint vp[4], oldtex = 0, blendsrc = 0, blenddst = 0;
    GLubyte blendWas, lightWas, texWas;
    if (w <= 0 || h <= 0 || !rgba) return;
    glGetIntegerv(0x0BA2 /* GL_VIEWPORT */, vp);
    glGetIntegerv(0x8069 /* GL_TEXTURE_BINDING_2D */, &oldtex);
    /* The WebGL names: the classic GL_BLEND_SRC and GL_BLEND_DST are invalid enums there. */
    glGetIntegerv(0x80C9 /* GL_BLEND_SRC_RGB */, &blendsrc);
    glGetIntegerv(0x80C8 /* GL_BLEND_DST_RGB */, &blenddst);
    blendWas = glIsEnabled(GL_BLEND_);
    lightWas = glIsEnabled(GL_LIGHTING_);
    texWas = glIsEnabled(GL_TEXTURE_2D_);   /* answered by the glue from the fixed-function state */

    fc_cached_texture(w, h, rgba);   /* binds it */

    glMatrixMode(GL_PROJECTION_); glPushMatrix(); glLoadIdentity();
    glOrtho(vp[0], vp[0] + vp[2], vp[1], vp[1] + vp[3], -1.0, 1.0);
    glMatrixMode(GL_MODELVIEW_); glPushMatrix(); glLoadIdentity();
    glDisable(GL_LIGHTING_);
    glEnable(GL_TEXTURE_2D_);   /* the emulation's shader samples only an ENABLED unit; a bound texture alone draws white */
    glEnable(GL_BLEND_);
    glBlendFunc(0x0302 /* SRC_ALPHA */, 0x0303 /* ONE_MINUS_SRC_ALPHA */);
    glColor4f(1.0f, 1.0f, 1.0f, 1.0f);           /* the image carries its own colour */
    /* glOrtho(-1, 1) maps z_eye to -z_eye, so -z_ndc lands at the raster depth. */
    const float zq = -fc_raster.z;
    glBegin(GL_TRIANGLE_FAN_);
    glTexCoord2f(0.0f, 0.0f); glVertex3f(x, y, zq);
    glTexCoord2f(1.0f, 0.0f); glVertex3f(x + (float)w * zx, y, zq);
    glTexCoord2f(1.0f, 1.0f); glVertex3f(x + (float)w * zx, y + (float)h * zy, zq);
    glTexCoord2f(0.0f, 1.0f); glVertex3f(x, y + (float)h * zy, zq);
    glEnd();

    glColor4f(fc_raster.color[0], fc_raster.color[1], fc_raster.color[2], fc_raster.color[3]);
    glMatrixMode(GL_MODELVIEW_); glPopMatrix();
    glMatrixMode(GL_PROJECTION_); glPopMatrix();
    /* GL_MATRIX_MODE cannot be queried through the emulation; MODELVIEW is the GL default and
     * what every Coin caller leaves selected. */
    if (!blendWas) glDisable(GL_BLEND_);
    glBlendFunc((GLenum)blendsrc, (GLenum)blenddst);
    if (lightWas) glEnable(GL_LIGHTING_);
    if (!texWas) glDisable(GL_TEXTURE_2D_);
    glBindTexture(GL_TEXTURE_2D_, (GLuint)oldtex);
}

static void fc_draw_pixels(GLsizei w, GLsizei h, GLenum format, GLenum type, const void* pixels) {
    if (!fc_raster.valid) return;
    if (format == 0x1908 /* GL_RGBA */ && type == 0x1401 /* GL_UNSIGNED_BYTE */) {
        fc_draw_rgba(fc_raster.x, fc_raster.y, w, h, (const GLubyte*)pixels, fc_zoom[0], fc_zoom[1]);
    }
    /* Other formats (depth, stencil, colour index) are not what any caller here sends. */
}

static void fc_bitmap(GLsizei w, GLsizei h, float xorig, float yorig, float xmove, float ymove, const GLubyte* bits) {
    if (!fc_raster.valid) return;
    if (w > 0 && h > 0 && bits) {
        /* 1 bit per pixel, MSB first, rows padded to a byte (SoText2 sets UNPACK_ALIGNMENT 1). */
        const int rowbytes = (w + 7) / 8;
        GLubyte* rgba = (GLubyte*)malloc((size_t)w * (size_t)h * 4);
        if (rgba) {
            const GLubyte r = (GLubyte)(fc_raster.color[0] * 255.0f), g = (GLubyte)(fc_raster.color[1] * 255.0f),
                          b = (GLubyte)(fc_raster.color[2] * 255.0f), a = (GLubyte)(fc_raster.color[3] * 255.0f);
            for (int y = 0; y < h; y++) {
                const GLubyte* row = bits + (size_t)y * rowbytes;
                GLubyte* dst = rgba + (size_t)y * w * 4;
                for (int x = 0; x < w; x++, dst += 4) {
                    const int on = (row[x >> 3] >> (7 - (x & 7))) & 1;
                    dst[0] = r; dst[1] = g; dst[2] = b; dst[3] = on ? a : 0;
                }
            }
            fc_draw_rgba(fc_raster.x - xorig, fc_raster.y - yorig, w, h, rgba, 1.0f, 1.0f);
            free(rgba);
        }
    }
    fc_raster.x += xmove;
    fc_raster.y += ymove;
}

/* The public raster entry points: recorded into an open display list, executed per mode. */
void glRasterPos3f(GLfloat x, GLfloat y, GLfloat z) { if (fc_dl_note(1, x, y, z, 0, 0, 0, 0, 0)) fc_raster_pos(x, y, z); }
void glRasterPos2f(GLfloat x, GLfloat y) { glRasterPos3f(x, y, 0.0f); }
void glRasterPos2i(GLint x, GLint y) { glRasterPos3f((GLfloat)x, (GLfloat)y, 0.0f); }
void glRasterPos2d(GLdouble x, GLdouble y) { glRasterPos3f((GLfloat)x, (GLfloat)y, 0.0f); }
void glDrawPixels(GLsizei w, GLsizei h, GLenum format, GLenum type, const void* pixels) {
    int bytes = (format == 0x1908 && type == 0x1401 && w > 0 && h > 0) ? w * h * 4 : 0;
    if (fc_dl_note(3, w, h, format, type, 0, 0, pixels, bytes)) fc_draw_pixels(w, h, format, type, pixels);
}
void glBitmap(GLsizei w, GLsizei h, GLfloat xorig, GLfloat yorig, GLfloat xmove, GLfloat ymove, const GLubyte* bits) {
    int bytes = (w > 0 && h > 0 && bits) ? ((w + 7) / 8) * h : 0;
    if (fc_dl_note(2, w, h, xorig, yorig, xmove, ymove, bits, bytes)) fc_bitmap(w, h, xorig, yorig, xmove, ymove, bits);
}
/* Replay entry, called from the glue for a recorded raster op. */
EMSCRIPTEN_KEEPALIVE void fcweb_dl_exec(int kind, double a, double b, double c, double d, double e, double f, double p) {
    const void* ptr = (const void*)(uintptr_t)p;
    switch (kind) {
    case 1: fc_raster_pos((float)a, (float)b, (float)c); break;
    case 2: fc_bitmap((GLsizei)a, (GLsizei)b, (float)c, (float)d, (float)e, (float)f, (const GLubyte*)ptr); break;
    case 3: fc_draw_pixels((GLsizei)a, (GLsizei)b, (GLenum)c, (GLenum)d, ptr); break;
    case 4: fc_pixel_zoom((float)a, (float)b); break;
    case 5: fc_push_attrib(); break;
    case 6: fc_pop_attrib(); break;
    default: break;
    }
}
