# Stub FindX11 for the wasm cross-build.
#
# Coin 4.0.3's CMakeLists.txt:210 does:
#
#     if(UNIX AND NOT APPLE)
#       find_package(X11 REQUIRED)
#
# Under emscripten CMake sets UNIX=1 and APPLE=0, so that branch is taken even though the
# target is WebAssembly and there is no X server anywhere in the picture. Coin only uses the
# result to append ${X11_INCLUDE_DIR} and ${X11_LIBRARIES}, which for this target must be
# empty.
#
# configure-coin-weh.sh previously passed -DCMAKE_DISABLE_FIND_PACKAGE_X11=ON, which cannot
# work: CMake refuses it for a REQUIRED package and stops with
#
#     find_package for module X11 called with REQUIRED, but CMAKE_DISABLE_FIND_PACKAGE_X11
#     is enabled. A REQUIRED package cannot be disabled.
#
# CI run 32093796201. Installing libx11-dev on the runner would also satisfy it -- and is
# probably what makes this succeed on the macOS build machine, where XQuartz supplies X11 --
# but that drags host headers into a wasm configure and makes the result depend on what
# happens to be installed. A stub on CMAKE_MODULE_PATH is deterministic and identical on
# every machine, which is the property this build has been short of.
#
# Nothing else in the tree overrides a find module, so this directory contains only this file
# and only affects find_package(X11).

set(X11_FOUND TRUE)
set(X11_INCLUDE_DIR "")
set(X11_LIBRARIES "")
set(X11_X11_INCLUDE_PATH "")
set(X11_X11_LIB "")

if(NOT X11_FIND_QUIETLY)
  message(STATUS "X11: stubbed for the wasm cross-build (toolchain/cmake/FindX11.cmake)")
endif()
