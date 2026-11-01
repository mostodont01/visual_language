# 64-bit Windows. Everything is linked statically: the .exe runs on its own.
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(VL_ZIG_TARGET x86_64-windows-gnu)
include(${CMAKE_CURRENT_LIST_DIR}/zig.cmake)
