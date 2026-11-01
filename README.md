# Visual Language (VL)

Visual Language (VL) is a visual dataflow programming language. Programs are built as node
graphs, similar to Blender's node editor: nodes have typed inputs and outputs
connected by wires, and incompatible types (e.g. `LidarScan` to `int32`)
can't be connected.

![A VL graph: Input Number → Add (+5) → Show Number](docs/screenshot.png)

VL is a visual front end for a compiler, not a runtime: the goal is to
translate the graph into C++ (or another compiled language) that runs on the
target hardware.

VL started as a way to program a RoboCars competition robot, so its first
nodes are robotics-oriented, but the language isn't tied to it.

Built with Python, PySide6 and Qt Quick (QML). Runs on Linux and Windows.

## Install

### Ready-made packages

The [Releases](https://github.com/mostodont01/vl/releases) page has:

- **Windows:** `VL-Setup-x86_64.exe`. Run it and VL appears in the Start
  menu. No admin rights are needed. Windows may warn that the app is from an
  unknown publisher: choose *More info → Run anyway*.
- **Linux:** `VL-x86_64.AppImage`. Make it executable
  (`chmod +x VL-x86_64.AppImage`) and run it. To add VL to the app menu
  (so you can search for it), run `./VL-x86_64.AppImage --install` once.
  The downloaded file can then be deleted; `~/.local/bin/VL.AppImage
  --uninstall` removes VL again.

Both include everything needed to compile graphs: nothing else to install.

### From source: Linux (Ubuntu)

```bash
sudo apt update
sudo apt install python3 python3-venv git
git clone https://github.com/mostodont01/vl.git
cd vl
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

To add VL to the app menu, run `packaging/install_linux.sh` (again after
changing the icon). `packaging/install_linux.sh --uninstall` removes it.

### From source: Windows

1. Install Python 3.12 or newer from [python.org](https://www.python.org/downloads/).
   In the installer, tick *Add python.exe to PATH*.
2. Download VL: *Code → Download ZIP* on GitHub (and unzip it), or
   `git clone https://github.com/mostodont01/vl.git`.
3. In the VL folder, open PowerShell (*Shift + right-click → Open PowerShell
   window here*) and run:

   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   .venv\Scripts\python main.py
   ```

   Next time only the last line is needed.

`requirements.txt` also installs the build tools (Zig, CMake, Ninja), about
300 MB.

### Making the packages

`.github/workflows/package.yml` builds both packages on GitHub: push a tag
like `v0.1.0` to publish a release, or start it by hand under *Actions →
Package → Run workflow* (the files are then under *Artifacts*). Locally:
`pyinstaller packaging/vl.spec` makes `dist/VL/` for the current system.

## Compiling graphs

**Compile** (Ctrl+B) turns the graph into a C++ project (CMake) in the output
folder and builds it into a program for the chosen target:

| Target | Runs on |
| --- | --- |
| Linux x86-64 | Ubuntu 23.04 / Debian 12 and newer |
| Linux ARM64 | 64-bit Raspberry Pi OS (Bookworm or newer), other ARM64 Linux |
| Windows x86-64 | Windows 10 and 11 |

Every target can be built from both Linux and Windows. VL builds with
[Zig](https://ziglang.org), a C++ compiler that brings the system libraries
of every target, and builds SDL2 (for the widget window) from source into
the program. The first build for a target takes a few minutes; Dear ImGui
and SDL2 are downloaded then. On Linux, native builds use the system compiler
instead when it's installed:

```bash
sudo apt install build-essential cmake libsdl2-dev
```

The built program doesn't need VL or any of these tools. On Raspberry Pi
OS, copy it over (e.g. `scp`) and run it. With the desktop it opens a
fullscreen window; without one (Raspberry Pi OS Lite) it draws straight to
the screen, which needs:

```bash
sudo apt install libgbm1 libegl1 libgles2
```

## Current state

Early node editor front end.

- Typed nodes and sockets; only wires between matching types are allowed.
  Feedback loops (including a node feeding itself) are allowed.
- Nodes are defined by JSON files (see `nodes/README.md`), including inline
  fields shown on unconnected inputs and node settings. General nodes are
  built in (`nodes/`); your own nodes are imported into a project with
  File → Import Nodes… (Ctrl+I) (try `examples/robocars/`)
- Projects are saved as `.vl` files (a zip with the graph, settings and
  imported nodes); startup screen with recent projects
- Settings tab: group and socket type colours, imported nodes
- Issues pill: click an issue to jump to its node
- Undo/redo for adding, deleting, moving, connecting and editing values
- Nodes with an app widget have an eye toggle in their header: whether the
  widget is shown in the compiled app (which lays widgets out automatically)
- Shift+A menu grouped by node group

### Controls

| Action | Input |
|---|---|
| Add node | Shift+A (↑/↓ to move, Enter to open a group or add a node) |
| Select / move | Click / drag a node |
| Toggle in selection | Ctrl+click |
| Box select | Shift+drag on empty canvas |
| Deselect all | Click empty canvas |
| Delete selected | Delete / Backspace |
| Copy / paste / duplicate | Ctrl+C / Ctrl+V / Ctrl+D |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z or Ctrl+Y (also in the Edit menu) |
| New / open / save / save as | Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S |
| Connect | Drag from any socket to a compatible one |
| Move or delete a wire | Drag it off its input; drop on empty canvas to delete |
| Disconnect input | Right-click the input |
| Pan / zoom | Right-drag / mouse wheel |
| Frame all | Home, or the Frame All button |
| Compile options | Ctrl+B, or the Compile button (Enter compiles) |

## Structure

- `main.py` — starts the app: loads the node catalog and QML
- `node_catalog.py` — loads and validates the node JSON files
- `graph_model.py` — nodes, values, typed connections, undo/redo, clipboard
- `project.py` — project files (zip), unsaved changes, recent projects, compile settings, palette, imported nodes
- `palette.json` — default group and socket type colours for new projects
- `examples/robocars/` — importable RoboCars nodes (JSON + C++; LiDAR simulated for now)
- `compiler.py` — compile options, graph checks and C++/CMake code generation
- `builder.py` — runs CMake in the background and collects the build log
- `runtime/vl/` — C++ runtime every compiled program uses (nodes, scheduler, widget window)
- `runtime/cmake/` — Zig toolchains for each target, SDL2-from-source build, Linux display headers
- `packaging/` — PyInstaller recipe, AppImage and Windows installer scripts, Linux app-menu installer, app icon
- `tools/update_linux_headers.py` — rebuilds the bundled Linux display headers
- `nodes/` — built-in node types, one JSON file each
- `ui/Main.qml` — application window: toolbar, File menu, inspector, startup popup, dialogs
- `ui/components/NodeCanvas.qml` — canvas: navigation, wires, selection, clipboard, add-node popup
- `ui/components/Node.qml` — a single node and its rows
- `ui/components/ValueWidget.qml` — inline value editors (number, string, select, checkbox)
- `ui/components/CompilePopup.qml` — compile options popup
- `ui/components/BuildPopup.qml` — build log
- `ui/components/MessageBox.qml` — themed message / confirmation dialog
- `ui/components/SettingsPage.qml` — Settings tab
- `ui/components/ColorPicker.qml` — colour chooser
- `ui/components/Toast.qml` — short fading messages
- `ui/components/ShortcutMenuItem.qml` — menu item with a shortcut hint
- `requirements.txt` — Python dependencies (PySide6) and build tools (Zig, CMake, Ninja)

## License

MIT — see [LICENSE](LICENSE).
