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
folder and builds it into a program for the chosen target. Next to the
program VL writes `<program>.values.json` with every setting and input value;
the program reads it at start-up, so **copy both** to the robot.

Builds are incremental: the output folder is kept, only changed files are
rewritten and each node type is compiled on its own. Changing a value
compiles nothing, changing one node's code recompiles that node, adding a
wire recompiles one small file. `VL_VALUES=other.values.json ./program` runs
the program with other values. [ccache](https://ccache.dev) is used when
installed.

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

## Versions and branches

Every project has a git-like history, stored inside the `.vl` file (no git
needed, the one file is still the whole project).

- **Commit** (Ctrl+K, or the Commit button) saves the current version (graph,
  compile settings, colours and imported nodes) with a message, and saves the
  file.
- **Branches** are separate versions of the program, e.g. `main` and
  `pi-motor-test`. The branch button in the toolbar (`⎇ main •`) switches
  between them and creates new ones. The dot means uncommitted changes.
- **Uncommitted changes stay with their branch.** Switching never asks and
  never loses work. Come back to a branch and its changes are still there.
- A **new branch** from the toolbar starts from what you have now and takes the
  uncommitted changes with it, while the old branch goes back to its last
  commit (like `git switch -c`).
- The **History** tab lists the branches and each branch's commits with
  what changed (“+2 nodes, −1 wire”). Hover a commit to *Restore* it (its
  version replaces the current one; commit to keep it) or to start a *New
  Branch Here*. Branches can be renamed and deleted there.

Compile settings are part of each version, so a branch can build for another
target (e.g. Raspberry Pi) with its own output folder. Switching branches or
restoring a commit clears Ctrl+Z, like opening a file. Merging branches isn't
supported yet.

## Working with Claude (MCP)

VL has a built-in [MCP](https://modelcontextprotocol.io) server, so Claude
Code (or another MCP client on the same computer) can build graphs in the
open window: add nodes, wire them, set values, import node files, compile
and read the build log. You see every change live, and Ctrl+Z undoes it.

1. In VL: **Settings → Claude (MCP server) → Allow MCP connections**
   (or start VL with `--mcp` to turn it on for one run).
2. Once, in a terminal: `claude mcp add --transport http vl http://127.0.0.1:7357/mcp`
   (the Copy button next to the command in Settings copies it).
3. In Claude Code, reconnect with `/mcp` (or restart it), then just ask,
   e.g. "add a threshold that turns the motor off below 30 cm".

Tools: `list_node_types`, `get_graph`, `edit_graph` (a batch of edits that
applies all or nothing as one undo step), `arrange_nodes`, `import_nodes`,
`get_project`, `set_compile_settings`, `build`, `get_build_log`,
`save_project`, `get_history`, `commit`, `switch_branch`, `create_branch`,
`screenshot`.

The server only listens on 127.0.0.1 and refuses requests from web pages.
It is off by default.

## Current state

Usable: RoboCars is programmed with it.

- Node editor: typed nodes and sockets (only matching types connect),
  feedback loops, inline value fields, settings, app-widget eye toggle,
  Shift+A menu, undo/redo, copy/paste, box select, issues list
- Nodes defined by JSON + C++ (`nodes/README.md`, `tutorial.md`); built-in
  nodes in `nodes/`, your own imported into a project (Ctrl+I)
- Inputs can be optional (diamond) or non-triggering (italic label)
- **Flows** (group Flow): start-up and event sequences on white exec wires
  (On Start → … → Start Main before the main tree; On Event for
  emergencies), with Wait, Wait Until, Branch, Log, Restart, Stop Program
- Projects are `.vl` files (zip) with commits and branches; History tab
- Compiler to C++ with incremental builds, cross-compiling for Raspberry Pi
  and Windows, fast simulated time for tests (`VL_FAST=1`)
- MCP server so Claude can build graphs in the open window
- Tests: `python -m pytest tests` (headless; builds and runs small graphs)

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
| Commit | Ctrl+K, or the Commit button (Enter commits) |
| Switch / new branch | The `⎇ branch` button in the toolbar; History tab |

## Structure

- `main.py` — starts the app: loads the node catalog and QML
- `node_catalog.py` — loads and validates the node JSON files
- `graph_model.py` — nodes, values, typed connections, undo/redo, clipboard
- `project.py` — project files (zip), unsaved changes, recent projects, compile settings, palette, imported nodes, commits and branches
- `history.py` — version history: snapshots, commits and branches, stored under `history/` in the project file
- `palette.json` — default group and socket type colours for new projects
- `tests/` — pytest suite; `tests/nodes/` are small C++ nodes the runtime tests build
- `examples/robocars/` — importable RoboCars nodes (JSON + C++; LiDAR simulated for now)
- `compiler.py` — compile options, graph checks and C++/CMake code generation
- `builder.py` — runs CMake in the background and collects the build log
- `mcp_server.py` — the MCP server (HTTP on 127.0.0.1, JSON-RPC) Claude connects to
- `vl_tools.py` — the MCP tools: reading and editing the graph, import, build, screenshot
- `graph_layout.py` — automatic node placement and the layered "arrange" layout
- `runtime/vl/` — C++ runtime every compiled program uses (nodes, scheduler, flows, values file, widget window)
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
- `ui/components/HistoryPage.qml` — History tab: branches and commits
- `ui/components/CommitPopup.qml` — commit message popup
- `ui/components/NamePopup.qml` — asks for a name (new / renamed branch)
- `ui/components/ColorPicker.qml` — colour chooser
- `ui/components/Toast.qml` — short fading messages
- `ui/components/ShortcutMenuItem.qml` — menu item with a shortcut hint
- `requirements.txt` — Python dependencies (PySide6) and build tools (Zig, CMake, Ninja)

## License

MIT — see [LICENSE](LICENSE).
