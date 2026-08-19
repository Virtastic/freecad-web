# FindICU for the emscripten ICU port.
#
# FreeCAD 1.1 added `find_package(ICU REQUIRED COMPONENTS uc i18n)` to its top-level
# CMakeLists and links ICU into Base. FreeCAD 1.0 had no ICU dependency, so this is new
# work for the 1.1 upgrade rather than something that was already handled.
#
# emscripten does ship an ICU port (`embuilder build icu`, `--use-port=icu`), but it names
# the libraries after ICU's *source directories* rather than ICU's usual output names:
#
#     upstream ICU        emscripten port
#     libicuuc.a      ->  libicu_common.a
#     libicui18n.a    ->  libicu_i18n.a
#     libicudata.a    ->  libicu_stubdata.a
#     libicuio.a      ->  libicu_io.a
#
# CMake's own FindICU searches for the upstream names, so it finds the headers (it reported
# "found version 68.2") and then fails with "missing: ICU_LIBRARY uc i18n". Pointing
# ICU_UC_LIBRARY at the port by hand does not help either, because FindICU resolves through
# ICU_<C>_LIBRARY_RELEASE internally.
#
# So this module replaces it. Put the directory containing this file on CMAKE_MODULE_PATH
# ahead of CMake's own Modules directory -- FreeCAD only ever APPENDS its own cMake/ dir,
# so a value passed in on the command line stays first.
#
# Note the data library: the port builds *stubdata*, which contains no locale data. That is
# the right choice for a browser build (full ICU data is tens of megabytes) and it is what
# FreeCAD's use of ICU -- Base/Tools string handling -- needs. Anything that requires real
# collation or locale data would need the data package staged separately.

set(_icu_sysroot "${ICU_EM_SYSROOT}")
if(NOT _icu_sysroot)
    # Fall back to asking the compiler, so the module is usable outside the CI workflow.
    execute_process(COMMAND em-config CACHE
                    OUTPUT_VARIABLE _icu_cache OUTPUT_STRIP_TRAILING_WHITESPACE
                    ERROR_QUIET)
    if(_icu_cache)
        set(_icu_sysroot "${_icu_cache}/sysroot")
    endif()
endif()

find_path(ICU_INCLUDE_DIR
    NAMES unicode/uversion.h
    HINTS "${_icu_sysroot}/include"
    NO_CMAKE_FIND_ROOT_PATH
)

# component name -> the port's library name
set(_icu_lib_uc      icu_common)
set(_icu_lib_i18n    icu_i18n)
set(_icu_lib_data    icu_stubdata)
set(_icu_lib_io      icu_io)

set(ICU_LIBRARIES "")
set(_icu_missing "")

foreach(_comp IN LISTS ICU_FIND_COMPONENTS)
    if(NOT DEFINED _icu_lib_${_comp})
        list(APPEND _icu_missing "${_comp} (no emscripten port equivalent)")
        continue()
    endif()
    string(TOUPPER "${_comp}" _COMP)
    find_library(ICU_${_COMP}_LIBRARY
        NAMES ${_icu_lib_${_comp}}
        HINTS "${_icu_sysroot}/lib/wasm32-emscripten"
        NO_CMAKE_FIND_ROOT_PATH
    )
    if(ICU_${_COMP}_LIBRARY)
        list(APPEND ICU_LIBRARIES "${ICU_${_COMP}_LIBRARY}")
        if(NOT TARGET ICU::${_comp})
            add_library(ICU::${_comp} UNKNOWN IMPORTED)
            set_target_properties(ICU::${_comp} PROPERTIES
                IMPORTED_LOCATION "${ICU_${_COMP}_LIBRARY}"
                INTERFACE_INCLUDE_DIRECTORIES "${ICU_INCLUDE_DIR}"
            )
        endif()
    else()
        list(APPEND _icu_missing "${_comp}")
    endif()
endforeach()

# The stub data library is not a component anyone asks for, but every ICU link needs it or
# u_init_* comes out undefined. Append it whenever it exists.
find_library(ICU_DATA_LIBRARY
    NAMES ${_icu_lib_data}
    HINTS "${_icu_sysroot}/lib/wasm32-emscripten"
    NO_CMAKE_FIND_ROOT_PATH
)
if(ICU_DATA_LIBRARY)
    list(APPEND ICU_LIBRARIES "${ICU_DATA_LIBRARY}")
endif()

if(ICU_INCLUDE_DIR AND EXISTS "${ICU_INCLUDE_DIR}/unicode/uvernum.h")
    file(STRINGS "${ICU_INCLUDE_DIR}/unicode/uvernum.h" _icu_ver
         REGEX "^#define[ \t]+U_ICU_VERSION[ \t]+\"[^\"]+\"")
    string(REGEX REPLACE "^.*\"([^\"]+)\".*$" "\\1" ICU_VERSION "${_icu_ver}")
endif()

set(ICU_INCLUDE_DIRS "${ICU_INCLUDE_DIR}")

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(ICU
    REQUIRED_VARS ICU_INCLUDE_DIR ICU_LIBRARIES
    VERSION_VAR ICU_VERSION
    FAIL_MESSAGE "emscripten ICU port not usable (sysroot: ${_icu_sysroot}; missing: ${_icu_missing})"
)

mark_as_advanced(ICU_INCLUDE_DIR ICU_DATA_LIBRARY)
