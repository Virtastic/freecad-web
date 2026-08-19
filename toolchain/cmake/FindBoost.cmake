# FindBoost for the wasm cross-build, because CMake 4 no longer ships one.
#
# CMake deprecated FindBoost in 3.30 and REMOVED it in 4.0. From then on
# `find_package(Boost ... COMPONENTS ...)` is config-mode only and needs a BoostConfig.cmake
# shipped by Boost's own install. build-boost-weh.sh runs `b2 ... stage` and copies the
# staged archives into deps/wasm/lib -- it never runs `b2 install`, so no CMake package
# config exists anywhere in the tree. With cmake 4.2 on the runner, FreeCAD's SetupBoost
# therefore fails with:
#
#     By not providing "FindBoost.cmake" in CMAKE_MODULE_PATH this project has asked CMake
#     to find a package configuration file provided by "Boost", but CMake did not find one.
#
# Note the earlier "-- Found Boost: .../deps/wasm/include (found version 1.86.0)" in the same
# log is a different call, from a dependency that was handed Boost_INCLUDE_DIR directly. It
# does not mean this one can succeed.
#
# Providing this module puts the call back into MODULE mode, where the staged layout is
# perfectly usable: headers in ${FCWEB_DW}/include, static archives named libboost_<c>.a in
# ${FCWEB_DW}/lib. Generating a real BoostConfig.cmake from b2 would be the other fix, but it
# means rebuilding Boost to get a file that describes what is already on disk.

if(NOT BOOST_ROOT)
    if(FCWEB_DW)
        set(BOOST_ROOT "${FCWEB_DW}")
    elseif(DEFINED ENV{DW})
        set(BOOST_ROOT "$ENV{DW}")
    endif()
endif()

find_path(Boost_INCLUDE_DIR
    NAMES boost/version.hpp
    HINTS "${BOOST_ROOT}/include"
    NO_CMAKE_FIND_ROOT_PATH
)

# BOOST_VERSION is the packed integer form: 108600 -> 1.86.0
if(Boost_INCLUDE_DIR AND EXISTS "${Boost_INCLUDE_DIR}/boost/version.hpp")
    file(STRINGS "${Boost_INCLUDE_DIR}/boost/version.hpp" _boost_ver_line
         REGEX "^#define[ \t]+BOOST_VERSION[ \t]+[0-9]+")
    string(REGEX REPLACE "^.*BOOST_VERSION[ \t]+([0-9]+).*$" "\\1" _boost_ver_num "${_boost_ver_line}")
    if(_boost_ver_num)
        math(EXPR Boost_MAJOR_VERSION "${_boost_ver_num} / 100000")
        math(EXPR Boost_MINOR_VERSION "${_boost_ver_num} / 100 % 1000")
        math(EXPR Boost_SUBMINOR_VERSION "${_boost_ver_num} % 100")
        set(Boost_VERSION "${Boost_MAJOR_VERSION}.${Boost_MINOR_VERSION}.${Boost_SUBMINOR_VERSION}")
        set(Boost_VERSION_STRING "${Boost_VERSION}")
    endif()
endif()

message(STATUS "FindBoost: BOOST_ROOT=${BOOST_ROOT}")

set(Boost_LIBRARIES "")
set(_boost_missing "")

foreach(_comp IN LISTS Boost_FIND_COMPONENTS)
    string(TOUPPER "${_comp}" _COMP)
    # Direct existence check rather than find_library. The emscripten toolchain sets
    # CMAKE_FIND_ROOT_PATH_MODE_LIBRARY to ONLY, and even with NO_CMAKE_FIND_ROOT_PATH the
    # search came back empty for archives that are demonstrably there and named exactly
    # what was searched for (libboost_program_options.a and friends, staged by
    # build-boost-weh.sh). There is nothing to search for in a cross-build with a known
    # layout, so do not search.
    set(_boost_candidate "${BOOST_ROOT}/lib/libboost_${_comp}.a")
    if(EXISTS "${_boost_candidate}")
        set(Boost_${_COMP}_LIBRARY "${_boost_candidate}" CACHE FILEPATH "boost_${_comp}")
    else()
        find_library(Boost_${_COMP}_LIBRARY
            NAMES boost_${_comp}
            HINTS "${BOOST_ROOT}/lib"
            NO_CMAKE_FIND_ROOT_PATH
        )
    endif()
    if(Boost_${_COMP}_LIBRARY)
        # BOTH spellings. find_package_handle_standard_args(HANDLE_COMPONENTS) looks up
        # Boost_<component>_FOUND with the component name EXACTLY as the caller wrote it --
        # Boost_program_options_FOUND -- while the rest of FindBoost's interface, and every
        # consumer, uses the upper-case Boost_PROGRAM_OPTIONS_FOUND. Setting only the latter
        # produced the perfectly contradictory "Could NOT find Boost (missing:
        # program_options regex thread date_time) (found suitable version 1.86.0)" with all
        # four archives located and no diagnostic printed.
        set(Boost_${_COMP}_FOUND TRUE)
        set(Boost_${_comp}_FOUND TRUE)
        list(APPEND Boost_LIBRARIES "${Boost_${_COMP}_LIBRARY}")
        if(NOT TARGET Boost::${_comp})
            add_library(Boost::${_comp} UNKNOWN IMPORTED)
            set_target_properties(Boost::${_comp} PROPERTIES
                IMPORTED_LOCATION "${Boost_${_COMP}_LIBRARY}"
                INTERFACE_INCLUDE_DIRECTORIES "${Boost_INCLUDE_DIR}"
            )
        endif()
    else()
        set(Boost_${_COMP}_FOUND FALSE)
        set(Boost_${_comp}_FOUND FALSE)
        list(APPEND _boost_missing "${_comp}")
    endif()
endforeach()

# Header-only consumers ask for these by name.
foreach(_hdr_target boost headers)
    if(Boost_INCLUDE_DIR AND NOT TARGET Boost::${_hdr_target})
        add_library(Boost::${_hdr_target} INTERFACE IMPORTED)
        set_target_properties(Boost::${_hdr_target} PROPERTIES
            INTERFACE_INCLUDE_DIRECTORIES "${Boost_INCLUDE_DIR}")
    endif()
endforeach()

set(Boost_INCLUDE_DIRS "${Boost_INCLUDE_DIR}")
set(Boost_LIBRARY_DIRS "${BOOST_ROOT}/lib")

if(_boost_missing)
    message(STATUS "FindBoost: looked under ${BOOST_ROOT}")
    foreach(_m IN LISTS _boost_missing)
        message(STATUS "FindBoost: no ${BOOST_ROOT}/lib/libboost_${_m}.a")
    endforeach()
endif()

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(Boost
    REQUIRED_VARS Boost_INCLUDE_DIR
    VERSION_VAR Boost_VERSION
    HANDLE_COMPONENTS
)

mark_as_advanced(Boost_INCLUDE_DIR)
