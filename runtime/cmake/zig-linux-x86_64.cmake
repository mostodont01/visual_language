# 64-bit x86 Linux, for machines without a system compiler or SDL2.
# glibc 2.36 = Debian 12 / Ubuntu 23.04 and newer.
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(VL_ZIG_TARGET x86_64-linux-gnu.2.36)
include(${CMAKE_CURRENT_LIST_DIR}/zig.cmake)
