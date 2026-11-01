# Loaded after CMake's platform files (CMAKE_USER_MAKE_RULES_OVERRIDE, set in
# zig.cmake). Their rules call a stand-alone `ar` and `ranlib`, which Zig only
# is as `zig ar` and `zig ranlib`; the same goes for `zig rc`.
set(CMAKE_RC_COMPILE_OBJECT "<CMAKE_RC_COMPILER> rc <DEFINES> <INCLUDES> <FLAGS> /fo <OBJECT> -- <SOURCE>")

foreach(lang C CXX)
    if(NOT DEFINED CMAKE_${lang}_ARCHIVE_CREATE)
        set(CMAKE_${lang}_ARCHIVE_CREATE "<CMAKE_AR> qc <TARGET> <LINK_FLAGS> <OBJECTS>")
    endif()
    if(NOT DEFINED CMAKE_${lang}_ARCHIVE_APPEND)
        set(CMAKE_${lang}_ARCHIVE_APPEND "<CMAKE_AR> q <TARGET> <LINK_FLAGS> <OBJECTS>")
    endif()
    if(NOT DEFINED CMAKE_${lang}_ARCHIVE_FINISH)
        set(CMAKE_${lang}_ARCHIVE_FINISH "<CMAKE_RANLIB> <TARGET>")
    endif()
    foreach(rule ARCHIVE_CREATE ARCHIVE_APPEND ARCHIVE_FINISH LINK_EXECUTABLE
                 CREATE_SHARED_LIBRARY CREATE_SHARED_MODULE)
        # This file runs once per language: don't add the subcommand twice.
        string(REGEX REPLACE "<CMAKE_AR> (ar )?" "<CMAKE_AR> ar " CMAKE_${lang}_${rule} "${CMAKE_${lang}_${rule}}")
        string(REGEX REPLACE "<CMAKE_RANLIB> (ranlib )?" "<CMAKE_RANLIB> ranlib " CMAKE_${lang}_${rule} "${CMAKE_${lang}_${rule}}")
    endforeach()
endforeach()
