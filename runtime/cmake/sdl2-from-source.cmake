# Builds SDL2 from source into the program, for targets that have no SDL2
# development files on this machine (the Zig toolchains).
#
# On Linux, SDL loads its display backends (KMS/DRM without a desktop,
# Wayland, X11) at run time, so building it only needs their headers. They
# are the same for every CPU and come with VL (linux-headers.tar.xz, see
# tools/update_linux_headers.py), unpacked into a small fake root together
# with empty stand-ins for the libraries: SDL only reads their names. The
# program then needs nothing besides the system's own graphics libraries.

set(VL_SDL2_VERSION 2.32.10)

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(_host_root ${CMAKE_BINARY_DIR}/vl-linux-headers)
    set(_include ${_host_root}/usr/include)
    set(_lib ${_host_root}/usr/lib)
    if(NOT EXISTS ${_include}/X11/Xlib.h)
        file(ARCHIVE_EXTRACT INPUT ${CMAKE_CURRENT_LIST_DIR}/linux-headers.tar.xz
             DESTINATION ${_host_root}/usr)
    endif()
    file(MAKE_DIRECTORY ${_lib}/pkgconfig)

    # Library name -> the file name SDL will load on the target.
    set(_sonames
        X11=libX11.so.6 Xext=libXext.so.6 Xcursor=libXcursor.so.1 Xi=libXi.so.6
        Xfixes=libXfixes.so.3 Xrandr=libXrandr.so.2 Xrender=libXrender.so.1 Xss=libXss.so.1
        wayland-client=libwayland-client.so.0 wayland-egl=libwayland-egl.so.1
        wayland-cursor=libwayland-cursor.so.0 xkbcommon=libxkbcommon.so.0
        drm=libdrm.so.2 gbm=libgbm.so.1 udev=libudev.so.1)
    foreach(_pair IN LISTS _sonames)
        string(REPLACE "=" ";" _pair ${_pair})
        list(GET _pair 0 _name)
        list(GET _pair 1 _soname)
        file(TOUCH ${_lib}/${_soname})
        # A copy rather than a symlink: Windows may not allow creating links.
        # SDL takes the name from the file a symlink points to, else this one,
        # so the stand-in is named after the loaded file in both cases.
        file(TOUCH ${_lib}/lib${_name}.so)
        set(_soname_${_name} ${_soname})
    endforeach()

    # pkg-config files for the libraries SDL looks up that way.
    foreach(_module wayland-client wayland-egl wayland-cursor egl xkbcommon libdrm gbm)
        set(_cflags "-I${_include}")
        if(_module STREQUAL "libdrm")
            set(_cflags "${_cflags} -I${_include}/libdrm")
        endif()
        file(WRITE ${_lib}/pkgconfig/${_module}.pc
            "Name: ${_module}\nDescription: headers only\nVersion: 99\nCflags: ${_cflags}\nLibs:\n")
    endforeach()
    set(ENV{PKG_CONFIG_LIBDIR} ${_lib}/pkgconfig)
    set(ENV{PKG_CONFIG_PATH} "")
    list(APPEND CMAKE_FIND_ROOT_PATH ${_host_root})

    # These checks link against libX11, which the stand-ins can't do. Every
    # libX11 since 2009 has both.
    set(HAVE_XGENERICEVENT 1 CACHE INTERNAL "")
    set(SDL_VIDEO_DRIVER_X11_HAS_XKBKEYCODETOKEYSYM 1 CACHE INTERNAL "")

    # Wayland needs wayland-scanner on this machine. Without it, desktops
    # running Wayland still show the window through XWayland.
    find_program(VL_WAYLAND_SCANNER wayland-scanner)
    if(NOT VL_WAYLAND_SCANNER)
        message(STATUS "wayland-scanner not found: building SDL2 without Wayland (X11 is used instead)")
        set(SDL_WAYLAND OFF CACHE BOOL "" FORCE)
    endif()
endif()

set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)
set(SDL_TEST OFF CACHE BOOL "" FORCE)
set(SDL_AUDIO OFF CACHE BOOL "" FORCE)
set(SDL_OPENGL OFF CACHE BOOL "" FORCE)
set(SDL_VULKAN OFF CACHE BOOL "" FORCE)
set(SDL_WAYLAND_LIBDECOR OFF CACHE BOOL "" FORCE)
set(SDL_HIDAPI OFF CACHE BOOL "" FORCE)

FetchContent_Declare(SDL2
    URL https://github.com/libsdl-org/SDL/releases/download/release-${VL_SDL2_VERSION}/SDL2-${VL_SDL2_VERSION}.tar.gz)
FetchContent_MakeAvailable(SDL2)

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    foreach(_backend KMSDRM X11)
        get_directory_property(_have DIRECTORY ${sdl2_SOURCE_DIR} DEFINITION HAVE_${_backend})
        if(NOT _have)
            message(WARNING "SDL2 was built without its ${_backend} video backend.")
        endif()
    endforeach()
    # SDL_syswm.h includes the X11 headers, so code using SDL needs them too.
    target_include_directories(SDL2-static SYSTEM INTERFACE ${_include})
endif()
