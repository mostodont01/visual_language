#!/bin/sh
# Adds VL to the Linux app menu for the current user, so it can be found by
# searching for "Visual Language" or "VL". Run it again after changing the icon.
#
#   packaging/install_linux.sh               VL from this source folder (.venv)
#   ./VL-x86_64.AppImage --install           the AppImage (copied to ~/.local/bin)
#   ... --uninstall                          removes the menu entry again
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
DESKTOP_FILE=$DATA/applications/vl.desktop   # main.py names the window "vl"
ICON_FILE=$DATA/icons/hicolor/256x256/apps/vl.png
APPIMAGE_COPY=$HOME/.local/bin/VL.AppImage

refresh() {
    command -v update-desktop-database >/dev/null && update-desktop-database "$DATA/applications" || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" || true
}

if [ "$1" = "--uninstall" ]; then
    rm -f "$DESKTOP_FILE" "$ICON_FILE" "$APPIMAGE_COPY"
    refresh
    echo "Removed Visual Language from the app menu."
    exit 0
fi

# The AppImage runtime sets APPIMAGE (the .AppImage file) when it runs this.
if [ -n "$APPIMAGE" ]; then
    mkdir -p "$(dirname "$APPIMAGE_COPY")"
    if [ "$(readlink -f "$APPIMAGE")" != "$(readlink -f "$APPIMAGE_COPY")" ]; then
        cp "$APPIMAGE" "$APPIMAGE_COPY"
    fi
    chmod +x "$APPIMAGE_COPY"
    EXEC="\"$APPIMAGE_COPY\""
    WORKDIR=$HOME
else
    ROOT=$(dirname "$HERE")
    PYTHON=$ROOT/.venv/bin/python
    if [ ! -x "$PYTHON" ]; then
        echo "No .venv in $ROOT: set it up first (see README.md, Install)." >&2
        exit 1
    fi
    EXEC="\"$PYTHON\" \"$ROOT/main.py\""
    WORKDIR=$ROOT
fi

mkdir -p "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON_FILE")"
cp "$HERE/vl.png" "$ICON_FILE"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Visual Language
GenericName=Visual programming
Comment=Visual dataflow language that compiles to C++
Exec=$EXEC
Path=$WORKDIR
Icon=vl
Terminal=false
Categories=Development;IDE;
Keywords=VL;Visual Language;Visual Studio;visual programming;dataflow;node;graph;compiler;robot;
StartupWMClass=VL
DESKTOP
refresh
echo "Added Visual Language to the app menu ($DESKTOP_FILE)."
