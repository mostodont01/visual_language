# 64-bit ARM Linux: Raspberry Pi OS, Jetson... glibc 2.36 = Debian 12 /
# Raspberry Pi OS Bookworm, so programs also run on every newer system.
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(VL_ZIG_TARGET aarch64-linux-gnu.2.36)
include(${CMAKE_CURRENT_LIST_DIR}/zig.cmake)
