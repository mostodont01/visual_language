#!/bin/sh
# Turns the PyInstaller folder (dist/VL) into a single-file Linux AppImage.
#   packaging/build_appimage.sh [dist/VL] [VL-x86_64.AppImage]
set -e
DIST=${1:-dist/VL}
OUT=${2:-VL-x86_64.AppImage}
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
APPDIR=$WORK/VL.AppDir

mkdir -p "$APPDIR/usr/lib"
cp -a "$DIST" "$APPDIR/usr/lib/vl"
cp "$HERE/vl.png" "$APPDIR/vl.png"
cp "$HERE/install_linux.sh" "$APPDIR/install_linux.sh"
cat > "$APPDIR/vl.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Visual Language
Comment=Visual dataflow language that compiles to C++
Exec=VL %f
Icon=vl
Categories=Development;IDE;
Keywords=VL;Visual Language;Visual Studio;visual programming;dataflow;node;graph;compiler;robot;
DESKTOP
# `VL-x86_64.AppImage --install` adds VL to the app menu (see install_linux.sh).
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
case "$1" in
    --install) exec "$HERE/install_linux.sh" ;;
    --uninstall) exec "$HERE/install_linux.sh" --uninstall ;;
esac
exec "$HERE/usr/lib/vl/VL" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# appimagetool 1.9 builds AppImages that don't need libfuse2.
TOOL=$WORK/appimagetool
curl -sSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage
chmod +x "$TOOL"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"
rm -rf "$WORK"
