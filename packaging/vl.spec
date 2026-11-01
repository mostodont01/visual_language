# PyInstaller recipe for the packaged VL: a folder with the VL program, its
# QML/node/runtime files and the build tools (CMake, Ninja, Zig), so graphs
# can be compiled without installing anything.
#
#   pip install -r requirements.txt pyinstaller
#   pyinstaller packaging/vl.spec        -> dist/VL/
#
# packaging/build_appimage.sh and packaging/vl.iss turn dist/VL into the
# Linux AppImage and the Windows installer (see .github/workflows/package.yml).

import sys
from pathlib import Path

import cmake
import ninja
import ziglang

ROOT = Path(SPECPATH).parent
SUFFIX = ".exe" if sys.platform == "win32" else ""
cmake_data = Path(cmake.CMAKE_DATA)
zig_dir = Path(ziglang.__file__).parent

# builder.py looks for the tools in <bundle>/tools.
tools = [
    (str(cmake_data / "bin" / ("cmake" + SUFFIX)), "tools/cmake/bin"),
    (str(Path(ninja.BIN_DIR) / ("ninja" + SUFFIX)), "tools/ninja"),
    (str(zig_dir / ("zig" + SUFFIX)), "tools/zig"),
]
data = [
    (str(ROOT / "ui"), "ui"),
    (str(ROOT / "nodes"), "nodes"),
    (str(ROOT / "runtime"), "runtime"),
    (str(ROOT / "examples" / "robocars"), "examples/robocars"),
    (str(ROOT / "palette.json"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "packaging" / "vl.png"), "packaging"),   # window icon
    (str(cmake_data / "share"), "tools/cmake/share"),   # CMake's own modules
    (str(zig_dir / "lib"), "tools/zig/lib"),            # Zig's C/C++ libraries
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=tools,
    datas=data,
    # Qt modules VL doesn't use; PySide6 would otherwise pull some of them in.
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtQuick3D",
              "PySide6.QtWidgets", "tkinter"],
)

# Leave out what VL never loads: Qt modules it doesn't use (Qt's QML hook
# collects all of them, WebEngine alone is ~200 MB), other control styles,
# and Zig's C libraries for systems VL doesn't build for.
UNUSED_QT = ("WebEngine", "WebView", "WebChannel", "WebSockets", "Quick3D", "Qt3D", "Pdf",
             "Charts", "Graphs", "DataVisualization", "Multimedia", "SpatialAudio", "Location",
             "Positioning", "Scxml", "StateMachine", "RemoteObjects", "Sensors", "VirtualKeyboard",
             "TextToSpeech", "Qt5Compat", "QuickTimeline", "Lottie", "ShaderTools",
             "FluentWinUI3", "Imagine", "Material", "Universal", "designer", "assistant", "linguist")
UNUSED_LIBC = ("freebsd", "netbsd", "openbsd", "darwin", "macos", "wasi", "wasm", "musl", "haiku")
ZIG_ARCHES = ("any-", "generic-", "aarch64-", "x86-", "x86_64-")


def needed(entry) -> bool:
    dest = entry[0].replace("\\", "/")
    if dest.startswith("PySide6/"):
        return not any(name in dest for name in UNUSED_QT)
    if dest.startswith("tools/zig/lib/libc/"):
        parts = dest.split("/")[4:]   # e.g. ["include", "aarch64-linux-gnu", ...] or ["musl", ...]
        if parts[0] == "include" and len(parts) > 2:
            return parts[1].startswith(ZIG_ARCHES) and not any(n in parts[1] for n in UNUSED_LIBC)
        return not any(name in parts[0] for name in UNUSED_LIBC)
    return not dest.startswith("tools/zig/lib/docs/")


a.binaries = [e for e in a.binaries if needed(e)]
a.datas = [e for e in a.datas if needed(e)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="VL",
    console=False,
    icon=str(ROOT / "packaging" / "vl.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="VL", upx=False)
