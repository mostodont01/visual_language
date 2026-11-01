# Shared part of the Zig toolchains (zig-<target>.cmake). Zig ships the C and
# C++ libraries for every target, so one download builds for all of them.
# VL passes the path of its Zig as VL_ZIG; otherwise `zig` from PATH is used.

if(NOT VL_ZIG)
    set(VL_ZIG "$ENV{VL_ZIG}")
endif()
if(NOT VL_ZIG)
    find_program(VL_ZIG zig REQUIRED)
endif()
# Try-compile projects re-read this file; they need the same values.
list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES VL_ZIG)

# UBSan is on by default in Zig debug builds; SDL trips it on purpose.
set(CMAKE_C_COMPILER "${VL_ZIG}" cc -target ${VL_ZIG_TARGET} -fno-sanitize=undefined)
set(CMAKE_CXX_COMPILER "${VL_ZIG}" c++ -target ${VL_ZIG_TARGET} -fno-sanitize=undefined)
set(CMAKE_RC_COMPILER "${VL_ZIG}")   # Windows resources; `zig rc`, see zig-rules.cmake
set(CMAKE_AR "${VL_ZIG}" CACHE FILEPATH "")
set(CMAKE_RANLIB "${VL_ZIG}" CACHE FILEPATH "")
set(CMAKE_USER_MAKE_RULES_OVERRIDE ${CMAKE_CURRENT_LIST_DIR}/zig-rules.cmake)

# Zig keeps debug info even in release builds; strip it there.
set(CMAKE_EXE_LINKER_FLAGS_RELEASE_INIT "-s")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# There's no SDL2 for the target here; build it into the program.
set(VL_SDL2_FROM_SOURCE ON)
