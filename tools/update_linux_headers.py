"""Rebuilds runtime/cmake/linux-headers.tar.xz from Debian's -dev packages.

SDL2 is built from source when cross-compiling for Linux (see
runtime/cmake/sdl2-from-source.cmake). It loads its display backends (X11,
Wayland, KMS/DRM) at run time, so building it only needs their headers.
They are the same for every CPU and are bundled with VL, so building works
on any machine, Windows included.

Only needs running when the header set should change:
    python tools/update_linux_headers.py
"""

import io
import lzma
import sys
import tarfile
import urllib.request
from pathlib import Path

MIRROR = "https://deb.debian.org/debian"
SUITE = "bookworm"   # Raspberry Pi OS Bookworm is based on Debian 12.
PACKAGES = [
    "libx11-dev", "x11proto-dev", "libxext-dev", "libxcursor-dev", "libxi-dev",
    "libxfixes-dev", "libxrandr-dev", "libxrender-dev", "libxss-dev",
    "libxkbcommon-dev", "libwayland-dev", "libdrm-dev", "libgbm-dev", "libudev-dev",
]
OUTPUT = Path(__file__).resolve().parent.parent / "runtime" / "cmake" / "linux-headers.tar.xz"


def package_index() -> dict[str, str]:
    """Package name -> pool file name, for arm64 (headers don't depend on the CPU)."""
    url = f"{MIRROR}/dists/{SUITE}/main/binary-arm64/Packages.xz"
    text = lzma.decompress(urllib.request.urlopen(url).read()).decode()
    index = {}
    for entry in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in entry.splitlines() if ": " in line and not line[0].isspace())
        if "Package" in fields:
            index[fields["Package"]] = fields["Filename"]
    return index


def deb_data(deb: bytes) -> tarfile.TarFile:
    """The data.tar.* member of a .deb (an `ar` archive)."""
    pos = 8   # "!<arch>\n"
    while pos < len(deb):
        name = deb[pos:pos + 16].decode().strip().rstrip("/")
        size = int(deb[pos + 48:pos + 58].decode().strip())
        if name.startswith("data.tar"):
            return tarfile.open(fileobj=io.BytesIO(deb[pos + 60:pos + 60 + size]))
        pos += 60 + size + (size & 1)
    raise ValueError("no data.tar in package")


def main() -> int:
    index = package_index()
    files: dict[str, bytes] = {}
    copyrights: list[str] = []
    for package in PACKAGES:
        url = f"{MIRROR}/{index[package]}"
        print("Fetching", url)
        data = deb_data(urllib.request.urlopen(url).read())
        for member in data.getmembers():
            name = member.name.removeprefix("./")
            if member.isfile() and name.startswith("usr/include/") and "aarch64-linux-gnu" not in name:
                files[name.removeprefix("usr/")] = data.extractfile(member).read()
            elif member.isfile() and name == f"usr/share/doc/{package}/copyright":
                copyrights.append(f"===== {package} ({index[package].rsplit('/', 1)[-1]})\n"
                                  + data.extractfile(member).read().decode(errors="replace"))
    files["COPYRIGHT"] = "\n\n".join(copyrights).encode()

    with tarfile.open(OUTPUT, "w:xz") as tar:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size = len(files[name])
            info.mtime = 0
            tar.addfile(info, io.BytesIO(files[name]))
    print(f"Wrote {OUTPUT} ({len(files)} files, {OUTPUT.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
