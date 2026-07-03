# Injected via CMAKE_PROJECT_INCLUDE for the pivy wasm build.
# 1) Coerce SHARED/MODULE libs to STATIC (wasm monolith).
# 2) Provide the prebuilt wasm Coin as a `Coin` target so pivy's CMakeLists
#    takes its "else" branch instead of find_package(Coin CONFIG), whose
#    find_dependency chain (OpenGL/EXPAT/superglu/...) fails under the
#    emscripten find root.
include("${CMAKE_CURRENT_LIST_DIR}/force-static.cmake")

set(FCWEB_DW "$ENV{FCWEB_DW}")
if(NOT FCWEB_DW)
    set(FCWEB_DW "${CMAKE_CURRENT_LIST_DIR}/deps/wasm")
endif()

if(NOT TARGET Coin)
    add_library(Coin STATIC IMPORTED GLOBAL)
    set_target_properties(Coin PROPERTIES
        IMPORTED_LOCATION "${FCWEB_DW}/lib/libCoin.a"
        INTERFACE_INCLUDE_DIRECTORIES "${FCWEB_DW}/include"
        INTERFACE_COMPILE_DEFINITIONS "COIN_NOT_DLL")
    # Variables pivy's else-branch derives include dirs from:
    set(Coin_SOURCE_DIR "${FCWEB_DW}")
    set(Coin_BINARY_DIR "${FCWEB_DW}")
endif()
