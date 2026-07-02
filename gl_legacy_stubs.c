/* External-linkage no-op stubs for fixed-function GL calls that Coin3D's
 * viewport makes but emscripten's LEGACY_GL_EMULATION does not provide. These
 * let the FreeCAD GUI link in wasm; the affected viewport bits (attrib stack,
 * raster text, immediate-mode rects/doubles) simply do nothing for now.
 * A full Coin->WebGL viewport port would replace these. */
typedef unsigned int   GLenum;
typedef unsigned int   GLbitfield;
typedef int            GLint;
typedef int            GLsizei;
typedef unsigned char  GLubyte;
typedef float          GLfloat;
typedef double         GLdouble;
typedef short          GLshort;

void glPushAttrib(GLbitfield m) { (void)m; }
void glPopAttrib(void) {}
void glPushClientAttrib(GLbitfield m) { (void)m; }
void glPopClientAttrib(void) {}
void glRasterPos2f(GLfloat x, GLfloat y) { (void)x;(void)y; }
void glRasterPos2i(GLint x, GLint y) { (void)x;(void)y; }
void glRasterPos3f(GLfloat x, GLfloat y, GLfloat z) { (void)x;(void)y;(void)z; }
void glBitmap(GLsizei w, GLsizei h, GLfloat x0, GLfloat y0, GLfloat xi, GLfloat yi, const GLubyte* b)
{ (void)w;(void)h;(void)x0;(void)y0;(void)xi;(void)yi;(void)b; }
void glRecti(GLint a, GLint b, GLint c, GLint d) { (void)a;(void)b;(void)c;(void)d; }
void glRectf(GLfloat a, GLfloat b, GLfloat c, GLfloat d) { (void)a;(void)b;(void)c;(void)d; }
void glVertex2d(GLdouble x, GLdouble y) { (void)x;(void)y; }
void glVertex3d(GLdouble x, GLdouble y, GLdouble z) { (void)x;(void)y;(void)z; }
void glVertex3dv(const GLdouble* v) { (void)v; }
void glColor3d(GLdouble r, GLdouble g, GLdouble b) { (void)r;(void)g;(void)b; }
void glColor4d(GLdouble r, GLdouble g, GLdouble b, GLdouble a) { (void)r;(void)g;(void)b;(void)a; }
void glNormal3d(GLdouble x, GLdouble y, GLdouble z) { (void)x;(void)y;(void)z; }
void glTexCoord2d(GLdouble s, GLdouble t) { (void)s;(void)t; }
void glLineStipple(GLint f, GLshort p) { (void)f;(void)p; }
void glPolygonStipple(const GLubyte* m) { (void)m; }

/* second batch */
void glAccum(GLenum op, GLfloat v) { (void)op;(void)v; }
void glColorMaterial(GLenum f, GLenum m) { (void)f;(void)m; }
void glDrawPixels(GLsizei w, GLsizei h, GLenum f, GLenum t, const void* p) { (void)w;(void)h;(void)f;(void)t;(void)p; }
void glGetDoublev(GLenum pn, GLdouble* p) { (void)pn; if (p) { for (int i=0;i<16;++i) p[i]=(i%5==0)?1.0:0.0; } }
void glPixelZoom(GLfloat x, GLfloat y) { (void)x;(void)y; }
void glRasterPos2d(GLdouble x, GLdouble y) { (void)x;(void)y; }
void glTexCoord4fv(const GLfloat* v) { (void)v; }
void glRenderMode(GLenum m) { (void)m; }
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
GLuint glGenLists(GLsizei range) { (void)range; return 0; }   /* 0 => no display lists => immediate mode */
void glNewList(GLuint list, GLenum mode) { (void)list;(void)mode; }
void glEndList(void) {}
void glCallList(GLuint list) { (void)list; }
void glDeleteLists(GLuint list, GLsizei range) { (void)list;(void)range; }
void glClearIndex(GLfloat c) { (void)c; }
void glIndexi(GLint c) { (void)c; }
void glLightModeli(GLenum pn, GLint p) { (void)pn;(void)p; }
void glLightf(GLenum light, GLenum pn, GLfloat p) { (void)light;(void)pn;(void)p; }
void glMaterialf(GLenum face, GLenum pn, GLfloat p) { (void)face;(void)pn;(void)p; }
void glPixelMapfv(GLenum m, GLsizei n, const GLfloat* v) { (void)m;(void)n;(void)v; }
void glPixelMapuiv(GLenum m, GLsizei n, const GLuint* v) { (void)m;(void)n;(void)v; }
void glPixelTransferf(GLenum pn, GLfloat p) { (void)pn;(void)p; }
void glPixelTransferi(GLenum pn, GLint p) { (void)pn;(void)p; }
void glTexCoord3fv(const GLfloat* v) { (void)v; }
void glTexGenf(GLenum coord, GLenum pn, GLfloat p) { (void)coord;(void)pn;(void)p; }
void glVertex2s(GLshort x, GLshort y) { (void)x;(void)y; }

/* ARB VBO suffix aliases used by PartGui's Coin SoBrepFaceSet (map to core). */
#include <GLES2/gl2.h>
void glBindBufferARB(GLenum target, GLuint buffer) { glBindBuffer(target, buffer); }
void glGenBuffersARB(GLsizei n, GLuint* buffers) { glGenBuffers(n, buffers); }
void glDeleteBuffersARB(GLsizei n, const GLuint* buffers) { glDeleteBuffers(n, buffers); }
void glBufferDataARB(GLenum target, long size, const void* data, GLenum usage) { glBufferData(target, size, data, usage); }
