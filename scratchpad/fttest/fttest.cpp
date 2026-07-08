// Standalone reproducer: load a glyph with the autohinter (af_autofitter path).
#include <cstdio>
#include <ft2build.h>
#include FT_FREETYPE_H
int main(int argc, char** argv) {
    const char* font = argc>1 ? argv[1] : "DejaVuSans.ttf";
    FT_Library lib; 
    printf("[T] init\n"); fflush(stdout);
    if (FT_Init_FreeType(&lib)) { printf("init fail\n"); return 1; }
    FT_Face face;
    printf("[T] new_face %s\n", font); fflush(stdout);
    if (FT_New_Face(lib, font, 0, &face)) { printf("new_face fail\n"); return 1; }
    FT_Set_Char_Size(face, 0, 12*64, 100, 100);
    printf("[T] load_char with autohint\n"); fflush(stdout);
    // FT_LOAD_FORCE_AUTOHINT forces the af_autofitter path
    FT_Error e = FT_Load_Char(face, 'A', FT_LOAD_RENDER | FT_LOAD_FORCE_AUTOHINT);
    printf("[T] load_char err=%d glyph w=%d h=%d\n", e,
           (int)face->glyph->bitmap.width, (int)face->glyph->bitmap.rows); fflush(stdout);
    printf("[T] OK\n");
    return 0;
}
