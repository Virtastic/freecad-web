# Injected via CMAKE_PROJECT_INCLUDE_BEFORE. Coerce real SHARED/MODULE libraries
# to STATIC so the wasm monolith links third-party archives (fmt, Qt, OCCT, boost)
# once in the final executable rather than embedding them into each "-shared" object.
#
# Guard: CMAKE_PROJECT_INCLUDE_BEFORE runs once per project() call, so define the
# override only the first time (otherwise _add_library chains into infinite recursion).
get_property(_fc_force_static_done GLOBAL PROPERTY _FC_FORCE_STATIC_DONE)
if(NOT _fc_force_static_done)
    set_property(GLOBAL PROPERTY _FC_FORCE_STATIC_DONE TRUE)
    function(add_library name)
        set(_args ${ARGN})
        foreach(_kw INTERFACE ALIAS IMPORTED OBJECT UNKNOWN STATIC)
            if("${ARGV1}" STREQUAL "${_kw}")
                _add_library(${name} ${ARGN})
                return()
            endif()
        endforeach()
        if("IMPORTED" IN_LIST _args)
            _add_library(${name} ${ARGN})
            return()
        endif()
        list(REMOVE_ITEM _args SHARED MODULE)
        _add_library(${name} STATIC ${_args})
    endfunction()
endif()
