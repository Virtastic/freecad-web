# FindOpenGL for the wasm cross-build.
#
# Coin3D's installed coin-config.cmake does find_dependency(OpenGL). On a normal target
# CMake's own FindOpenGL locates libGL and an X11 or EGL provider; under emscripten there is
# no system OpenGL to find, so it fails and takes Coin down with it:
#
#     Found package configuration file: .../deps/wasm/lib/cmake/Coin-4.0.3/coin-config.cmake
#     but it set Coin_FOUND to FALSE ... Reason given by package:
#     Coin could not be found because dependency OpenGL could not be found.
#
# which reads as "Coin is missing" when Coin is present and fine.
#
# For this target the GL implementation is supplied by emscripten AT LINK TIME -- emcc adds
# its WebGL-backed GL library itself, and the legacy fixed-function entry points come from
# gl_legacy_stubs.c plus gl_compat.h. So the correct answer here is "found, and there is
# nothing extra to link", not a path to a library file.
#
# Put the directory containing this file on CMAKE_MODULE_PATH ahead of CMake's own Modules.

set(OPENGL_FOUND TRUE)
set(OpenGL_FOUND TRUE)
set(OPENGL_GLU_FOUND TRUE)
set(OPENGL_opengl_FOUND TRUE)
set(OPENGL_glx_FOUND FALSE)
set(OPENGL_egl_FOUND TRUE)

# emscripten's GL headers live in the sysroot; find them if we can, so consumers that add
# ${OPENGL_INCLUDE_DIR} get something real rather than an empty string.
if(NOT OPENGL_INCLUDE_DIR)
    execute_process(COMMAND em-config CACHE
                    OUTPUT_VARIABLE _gl_cache OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    if(_gl_cache AND EXISTS "${_gl_cache}/sysroot/include/GL/gl.h")
        set(OPENGL_INCLUDE_DIR "${_gl_cache}/sysroot/include")
    endif()
endif()
set(OPENGL_INCLUDE_DIRS "${OPENGL_INCLUDE_DIR}")

# Deliberately empty: emcc links its own GL. Naming a library here would either not exist
# or shadow the emulation.
set(OPENGL_LIBRARIES "")
set(OPENGL_gl_LIBRARY "")
set(OPENGL_glu_LIBRARY "")
set(OPENGL_opengl_LIBRARY "")
set(OPENGL_egl_LIBRARY "")

foreach(_t OpenGL::GL OpenGL::GLU OpenGL::OpenGL OpenGL::EGL)
    if(NOT TARGET ${_t})
        add_library(${_t} INTERFACE IMPORTED)
        if(OPENGL_INCLUDE_DIR)
            set_target_properties(${_t} PROPERTIES
                INTERFACE_INCLUDE_DIRECTORIES "${OPENGL_INCLUDE_DIR}")
        endif()
    endif()
endforeach()

mark_as_advanced(OPENGL_INCLUDE_DIR)
