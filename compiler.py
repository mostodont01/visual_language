"""Compiling a VL graph into a C++ project.

generate_project() writes a self-contained CMake project into the output
folder:

    CMakeLists.txt
    runtime/vl/                 the VL runtime (copied from this repo)
    runtime/cmake/              toolchain files for cross-compiling
    nodes/<type id>/...         the code of every node type used in the graph
    generated/node_<type>.cpp   one per node type: describes it for the runtime
    generated/main.cpp          creates the nodes and connects the wires
    <program>.values.json       settings and input values, read at start-up

The folder is kept between compiles and only files whose content changed
are rewritten, so the build (in build/ inside it) only recompiles what
changed: a value change compiles nothing, a node's code recompiles that
node's files, a new wire only main.cpp.

builder.py then runs CMake on it. The execution model is described in
runtime/vl/runtime.hpp.
"""

import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from node_catalog import EXEC_TYPE, NodeDef, NodePackage, is_integer_type

# Choices offered in the Compile popup: (id, label). The first one is the default.
LANGUAGES = [
    ("cpp", "C++"),
]

TARGETS = [
    ("linux-x86_64", "Linux x86-64"),
    ("linux-arm64", "Linux ARM64 (Raspberry Pi OS 64-bit, Jetson…)"),
    ("windows-x86_64", "Windows x86-64 (.exe)"),
]


def host_target() -> str:
    """The target VL itself runs on, or "" for systems VL can't build for."""
    machine = platform.machine().lower()
    if platform.system() == "Linux":
        return "linux-arm64" if machine in ("aarch64", "arm64") else "linux-x86_64"
    if platform.system() == "Windows":
        return "windows-x86_64"
    return ""


BUILD_TYPES = [
    ("release", "Release (optimized)"),
    ("debug", "Debug (debug symbols, no optimization)"),
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": LANGUAGES[0][0],
    "target": host_target() or TARGETS[0][0],
    "build_type": BUILD_TYPES[0][0],
    "output_dir": "",        # "" = <project folder>/build
    "executable_name": "",   # "" = project name
    "fullscreen": True,
}

_CHOICES = {
    "language": {i for i, _ in LANGUAGES},
    "target": {i for i, _ in TARGETS},
    "build_type": {i for i, _ in BUILD_TYPES},
}

RUNTIME_DIR = Path(__file__).parent / "runtime"
# Marks an output folder as written by VL, so it may be cleaned on the next build.
MARKER_FILE = ".vl-build"
IMGUI_VERSION = "v1.91.5"

# Socket/setting types every project knows, and their C++ names.
BUILTIN_CPP_TYPES = {
    "int32": "int32_t",
    "float32": "float",
    "bool": "bool",
    "string": "std::string",
}


def coerce_setting(key: str, value: Any) -> Any:
    """Validate one compile setting. Raises ValueError for unknown keys or bad values."""
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"unknown compile setting {key!r}")
    if key in _CHOICES:
        if value not in _CHOICES[key]:
            raise ValueError(f"invalid {key}: {value!r}")
        return value
    if key == "fullscreen":
        if not isinstance(value, bool):
            raise ValueError("fullscreen must be true or false")
        return value
    return str(value).strip()


def load_settings(raw: Any) -> dict[str, Any]:
    """Settings from a project file, falling back to defaults for anything invalid."""
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                settings[key] = coerce_setting(key, value)
            except ValueError:
                pass
    return settings


def executable_file_name(name: str, target: str) -> str:
    return name + ".exe" if target.startswith("windows") else name


# ---------------------------------------------------------------------------
# Graph analysis
# ---------------------------------------------------------------------------

def _input_def(catalog, nodes_by_id, node_id, socket_id):
    node_def = catalog.get(nodes_by_id[node_id]["type"]) if node_id in nodes_by_id else None
    return next((s for s in node_def.inputs if s.id == socket_id), None) if node_def else None


def non_triggering_connections(nodes: list[dict], connections: list[dict], catalog) -> set[int]:
    """Indices of wires into inputs marked "triggers": false."""
    by_id = {n["id"]: n for n in nodes}
    result = set()
    for i, c in enumerate(connections):
        s = _input_def(catalog, by_id, c["target_node"], c["target_socket"])
        if s is not None and not s.triggers:
            result.add(i)
    return result


def feedback_connections(nodes: list[dict], connections: list[dict],
                         skip: set[int] = frozenset()) -> set[int]:
    """Indices of connections that close a feedback loop.

    A depth-first walk along the wires marks every wire that leads back to a
    node still being walked (including a node feeding itself). Removing those
    wires leaves no cycles, so if they don't trigger a run, nothing can run
    forever. The walk starts from nodes without incoming wires, in a fixed
    order, so the result is the same on every compile.

    Wires in `skip` (non-triggering ones) are left out of the walk: they
    can't make anything run, so they already break every loop they are in.
    """
    outgoing: dict[str, list[tuple[int, str]]] = {n["id"]: [] for n in nodes}
    has_incoming = set()
    for i, c in enumerate(connections):
        if i in skip:
            continue
        outgoing[c["source_node"]].append((i, c["target_node"]))
        has_incoming.add(c["target_node"])

    order = sorted(outgoing, key=lambda nid: (nid in has_incoming, nid))
    state: dict[str, int] = {}  # 1 = being walked, 2 = done
    feedback: set[int] = set()

    for start in order:
        if start in state:
            continue
        # Iterative DFS: (node, iterator over its outgoing wires)
        stack = [(start, iter(outgoing[start]))]
        state[start] = 1
        while stack:
            node, wires = stack[-1]
            for index, target in wires:
                if state.get(target) == 1:
                    feedback.add(index)
                elif target not in state:
                    state[target] = 1
                    stack.append((target, iter(outgoing[target])))
                    break
            else:
                state[node] = 2
                stack.pop()
    return feedback


def wires_in_loops(nodes: list[dict], connections: list[dict], indices: set[int]) -> set[int]:
    """The wires among `indices` that are part of a loop (their target can
    reach their source along the wires)."""
    outgoing: dict[str, set[str]] = {n["id"]: set() for n in nodes}
    for c in connections:
        outgoing.setdefault(c["source_node"], set()).add(c["target_node"])
    result = set()
    for i in indices:
        source, start = connections[i]["source_node"], connections[i]["target_node"]
        seen, todo = {start}, [start]
        while todo:
            node = todo.pop()
            if node == source:
                result.add(i)
                break
            for nxt in outgoing.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
    return result


@dataclass
class WirePlan:
    """How each wire behaves in the generated program."""
    feedback: set[int]        # picked to break a loop: doesn't trigger, target starts with a value
    non_triggering: set[int]  # into a "triggers": false input
    loop_holds: set[int]      # non-triggering wires in a loop: target starts with a value too

    def triggers(self, index: int) -> bool:
        return index not in self.feedback and index not in self.non_triggering

    def starts_with_value(self, index: int) -> bool:
        return index in self.feedback or index in self.loop_holds


def plan_wires(nodes: list[dict], connections: list[dict], catalog) -> WirePlan:
    quiet = non_triggering_connections(nodes, connections, catalog)
    return WirePlan(feedback=feedback_connections(nodes, connections, quiet),
                    non_triggering=quiet,
                    loop_holds=wires_in_loops(nodes, connections, quiet))


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------

MAX_FLOWS = 60   # Group bits: 0 = main tree, 1 = always, 2.. = one per flow.
GROUP_MAIN = 1 << 0
GROUP_ALWAYS = 1 << 1


@dataclass
class FlowPlan:
    """Which nodes run when (see runtime/vl/flow.hpp)."""
    entries: list[str]               # entry node ids (no exec input), in graph order
    groups: dict[str, int]           # node id -> group bits (data nodes and entries)
    exec_wires: list[tuple[str, int, str]]   # (source node, exec output number, target node)
    errors: list[str]

    @property
    def has_flows(self) -> bool:
        return bool(self.entries)


def plan_flows(nodes: list[dict], connections: list[dict], catalog) -> FlowPlan:
    by_id = {n["id"]: n for n in nodes}
    defs = {n["id"]: catalog[n["type"]] for n in nodes}
    flow_ids = {nid for nid, d in defs.items() if d.is_flow}
    errors: list[str] = []

    exec_out: dict[str, list[str]] = {}       # node -> its exec output ids in order
    for nid in flow_ids:
        exec_out[nid] = [s.id for s in defs[nid].outputs if s.type == EXEC_TYPE]

    exec_next: dict[str, set[str]] = {nid: set() for nid in flow_ids}
    exec_wires = []
    data_in: dict[str, list[str]] = {nid: [] for nid in by_id}    # node -> data sources
    data_out: dict[str, list[str]] = {nid: [] for nid in by_id}   # node -> data targets
    for c in connections:
        sn, tn = c["source_node"], c["target_node"]
        if sn not in by_id or tn not in by_id:
            continue
        sock = next((s for s in defs[sn].outputs if s.id == c["source_socket"]), None)
        if sock is not None and sock.type == EXEC_TYPE:
            exec_next[sn].add(tn)
            exec_wires.append((sn, exec_out[sn].index(sock.id), tn))
        else:
            data_in[tn].append(sn)
            data_out[sn].append(tn)

    entries = [n["id"] for n in nodes if n["id"] in flow_ids
               and not any(s.type == EXEC_TYPE for s in defs[n["id"]].inputs)]
    if len(entries) > MAX_FLOWS:
        errors.append(f"At most {MAX_FLOWS} flows (On Start / On Event nodes) are supported.")
        entries = entries[:MAX_FLOWS]

    groups: dict[str, int] = {nid: GROUP_MAIN for nid in by_id if nid not in flow_ids}

    def upstream(starts):
        seen, todo = set(), list(starts)
        while todo:
            nid = todo.pop()
            if nid in seen or nid in flow_ids:
                continue
            seen.add(nid)
            todo.extend(data_in[nid])
        return seen

    def downstream(starts):
        seen, todo = set(), list(starts)
        while todo:
            nid = todo.pop()
            if nid in seen or nid in flow_ids:
                continue
            seen.add(nid)
            todo.extend(data_out[nid])
        return seen

    for k, entry in enumerate(entries):
        bit = 1 << (2 + k)
        members, todo = set(), [entry]
        while todo:
            nid = todo.pop()
            if nid in members:
                continue
            members.add(nid)
            todo.extend(exec_next[nid])
        # (The entry's own inputs are watched in every phase, see below.)
        sources = [src for m in members if m != entry for src in data_in[m]]
        targets = [t for m in members for t in data_out[m]]
        for nid in upstream(sources) | downstream(targets):
            groups[nid] |= bit
        # Entry nodes run as data nodes in every phase (they watch triggers),
        # and so does everything feeding them.
        groups[entry] = GROUP_ALWAYS
        for nid in upstream(data_in[entry]):
            groups[nid] |= GROUP_ALWAYS

    return FlowPlan(entries, groups, exec_wires, errors)


def split_exec_wires(connections: list[dict], nodes: list[dict], catalog) -> tuple[list[dict], list[dict]]:
    """(data wires, exec wires)."""
    by_id = {n["id"]: n for n in nodes}
    data, exec_ = [], []
    for c in connections:
        node = by_id.get(c["source_node"])
        sock = next((s for s in catalog[node["type"]].outputs if s.id == c["source_socket"]), None) if node else None
        (exec_ if sock is not None and sock.type == EXEC_TYPE else data).append(c)
    return data, exec_


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

@dataclass
class GenerateResult:
    ok: bool
    messages: list[str]
    gui: bool = False


def _cpp_string(text: str) -> str:
    # JSON string escapes (\", \\, \n, \uXXXX) are valid in C++ literals too.
    return json.dumps(text, ensure_ascii=False)


def generate_project(
    graph: dict[str, Any],
    catalog: dict[str, NodeDef],
    packages: dict[str, NodePackage],
    graph_errors: list[str],
    settings: dict[str, Any],
    output_dir: Path,
    name: str,
) -> GenerateResult:
    """Validate the graph and write the C++ project. Nothing is written if invalid.

    packages has the code of every node type used (built-in and imported).
    graph_errors are the graph's own issues (e.g. unconnected inputs).
    """
    errors = list(graph_errors)
    nodes = graph["nodes"]
    connections = graph["connections"]
    used_types = sorted({n["type"] for n in nodes})

    if not nodes:
        errors.append("The graph is empty.")

    # Every used node type needs a C++ class and its code.
    for type_id in used_types:
        node_def = catalog[type_id]
        if not node_def.cpp_class:
            errors.append(f"Node type '{node_def.title}' has no \"class\" in its JSON.")
        if type_id not in packages:
            errors.append(f"The code of node type '{node_def.title}' is missing.")

    # Every socket type needs a C++ type; custom types must be defined once.
    type_owner: dict[str, str] = {}   # type name -> type id of the node whose header defines it
    for type_id in used_types:
        for type_name, type_def in catalog[type_id].types.items():
            if type_name in BUILTIN_CPP_TYPES:
                continue
            other = type_owner.get(type_name)
            if other is None:
                type_owner[type_name] = type_id
            elif type_id in packages and other in packages:
                mine = packages[type_id].files.get(type_def.header)
                theirs = packages[other].files.get(catalog[other].types[type_name].header)
                if mine != theirs or type_def.cpp != catalog[other].types[type_name].cpp:
                    errors.append(f"Type '{type_name}' is defined differently by "
                                  f"'{catalog[other].title}' and '{catalog[type_id].title}'.")

    def cpp_type(data_type: str) -> str | None:
        if data_type in BUILTIN_CPP_TYPES:
            return BUILTIN_CPP_TYPES[data_type]
        owner = type_owner.get(data_type)
        return catalog[owner].types[data_type].cpp if owner else None

    for type_id in used_types:
        node_def = catalog[type_id]
        for s in node_def.inputs + node_def.outputs + node_def.settings:
            if s.type != EXEC_TYPE and cpp_type(s.type) is None:
                errors.append(f"Type '{s.type}' (used by '{node_def.title}') has no C++ definition. "
                              "Declare it in a node's \"types\".")

    flows = plan_flows(nodes, connections, catalog)
    errors += flows.errors
    starts = [n for n in nodes if n["type"] == "flow_on_start"]
    if len(starts) > 1:
        errors.append("A program can only have one On Start.")

    # Only clean folders VL wrote itself.
    if output_dir.exists() and any(output_dir.iterdir()) and not (output_dir / MARKER_FILE).exists():
        errors.append(f"The output folder {output_dir} is not empty and wasn't created by VL. "
                      "Choose an empty or new folder.")

    if errors:
        return GenerateResult(False, errors)

    gui = any(catalog[n["type"]].app_widget is not None and n.get("widget_visible", True) for n in nodes)
    target = cmake_target_name(name)

    # Function names of the node type descriptions must not collide.
    functions: dict[str, str] = {}
    for type_id in used_types:
        fn = _type_function(type_id)
        if fn in functions:
            return GenerateResult(False, [f"Node types '{functions[fn]}' and '{type_id}' are too similar "
                                          "(their ids only differ in punctuation)."])
        functions[fn] = type_id

    # -- Write files (only those whose content changed, so the build only
    # recompiles what's needed) and remove the ones from earlier compiles
    # that aren't used any more.
    files: dict[str, bytes] = {}
    for path in sorted(RUNTIME_DIR.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files["runtime/" + path.relative_to(RUNTIME_DIR).as_posix()] = path.read_bytes()

    for type_id in used_types:
        # Header file -> custom type it defines, for this node.
        type_headers = {t.header: name for name, t in catalog[type_id].types.items()
                        if name not in BUILTIN_CPP_TYPES}
        for rel, content in packages[type_id].files.items():
            type_name = type_headers.get(rel)
            if type_name:
                # Several nodes may ship the same type header; a guard named
                # after the type makes it count only once.
                macro = "VL_TYPE_" + "".join(c if c.isalnum() else "_" for c in type_name)
                content = (f"#ifndef {macro}\n#define {macro}\n".encode()
                           + content + f"\n#endif  // {macro}\n".encode())
            files[f"nodes/{type_id}/{rel}"] = content
        files[f"generated/{_type_file(type_id)}"] = _node_type_cpp(
            type_id, catalog, type_owner).encode("utf-8")

    data_wires, _ = split_exec_wires(connections, nodes, catalog)
    plan = plan_wires(nodes, data_wires, catalog)
    files["generated/main.cpp"] = _main_cpp(nodes, data_wires, plan, gui, flows).encode("utf-8")
    files[values_file_name(name)] = (json.dumps(
        _values(nodes, data_wires, plan, catalog, settings, name), indent=1, ensure_ascii=False)
        + "\n").encode("utf-8")

    cpp_files = sorted(
        f"nodes/{type_id}/{rel}"
        for type_id in used_types
        for rel in packages[type_id].files
        if rel.endswith((".cpp", ".cc", ".cxx"))
    )
    type_files = [f"generated/{_type_file(t)}" for t in used_types]
    files["CMakeLists.txt"] = _cmake_lists(target, type_files + cpp_files, gui).encode("utf-8")

    try:
        changed = _write_tree(output_dir, files)
    except OSError as e:
        return GenerateResult(False, [f"Could not write the project to {output_dir}: {e.strerror}"])

    feedback = len(plan.feedback)
    if flows.has_flows:
        count = len(flows.entries)
    messages = [
        f"Generated C++ project in {output_dir}"
        + (f" ({changed} file{'s' if changed != 1 else ''} changed)" if changed else " (nothing changed)"),
        f"{len(nodes)} nodes, {len(connections)} wires"
        + (f" ({feedback} feedback)" if feedback else "")
        + (f", {count} flow{'s' if count != 1 else ''}" if flows.has_flows else "")
        + (", with app widgets" if gui else ", no window (no visible app widgets)"),
    ]
    return GenerateResult(True, messages, gui)


def cmake_target_name(name: str) -> str:
    """The executable's name (without .exe): the project name made safe for CMake."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in name) or "app"


def values_file_name(name: str) -> str:
    """The values file the program reads at start-up, next to the executable."""
    return cmake_target_name(name) + ".values.json"


def _type_function(type_id: str) -> str:
    return "vl_type_" + "".join(c if c.isalnum() else "_" for c in type_id)


def _type_file(type_id: str) -> str:
    return "node_" + "".join(c if c.isalnum() or c in "_-" else "_" for c in type_id) + ".cpp"


def _write_tree(output_dir: Path, files: dict[str, bytes]) -> int:
    """Write files (relative path -> content) into output_dir, skipping files
    that already have that content, so their modification time stays and the
    build skips them. Files listed in the marker by an earlier compile and not
    written now are removed. Returns how many files were written or removed."""
    output_dir.mkdir(parents=True, exist_ok=True)
    marker = output_dir / MARKER_FILE
    previous: list[str] = []
    try:
        previous = json.loads(marker.read_text(encoding="utf-8")).get("files", [])
    except (OSError, ValueError, AttributeError):
        # First compile, or a folder from an older VL that wiped these on
        # every compile: start them over.
        for sub in ("runtime", "nodes", "generated", "cmake"):
            shutil.rmtree(output_dir / sub, ignore_errors=True)

    changed = 0
    for rel, content in files.items():
        path = output_dir / rel
        try:
            if path.read_bytes() == content:
                continue
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".vl-tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)
        changed += 1

    for rel in previous:
        if rel not in files and not rel.startswith(("/", "..")):
            path = output_dir / rel
            if path.is_file():
                path.unlink()
                changed += 1
                # Remove folders that became empty.
                parent = path.parent
                while parent != output_dir and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent

    manifest = json.dumps({
        "note": "Written by VL. The files listed here are rewritten on every compile.",
        "files": sorted(files),
    }, indent=1) + "\n"
    try:
        same = marker.read_text(encoding="utf-8") == manifest
    except OSError:
        same = False
    if not same:
        marker.write_text(manifest, encoding="utf-8")
    return changed


def _node_type_cpp(type_id: str, catalog, type_owner: dict[str, str]) -> str:
    """generated/node_<type>.cpp: the vl::NodeType describing one node type."""
    node_def = catalog[type_id]
    cls = node_def.cpp_class
    includes = []
    # Custom types this node uses but another node defines.
    for s in node_def.inputs + node_def.outputs + node_def.settings:
        owner = type_owner.get(s.type) if s.type != EXEC_TYPE else None
        if owner and owner != type_id:
            include = f"nodes/{owner}/{catalog[owner].types[s.type].header}"
            if include not in includes:
                includes.append(include)
    includes += [f"nodes/{type_id}/{rel}" for rel in node_def.code
                 if rel.endswith((".hpp", ".h", ".hh", ".hxx"))]

    out = [
        f"// Generated by VL: the node type {_cpp_string(type_id)} for the runtime.",
        "// Do not edit: this file is rewritten on every compile.",
        '#include "vl/runtime.hpp"',
        *[f'#include "{inc}"' for inc in includes],
        "",
        f"const vl::NodeType& {_type_function(type_id)}() {{",
        f"    using N = {cls};",
        "    static const vl::NodeType type = [] {",
        "        vl::NodeType t;",
        f"        t.id = {_cpp_string(type_id)};",
        f"        t.title = {_cpp_string(node_def.title)};",
        "        t.create = [] { return std::unique_ptr<vl::Node>(new N()); };",
    ]
    for s in (s for s in node_def.inputs if s.type != EXEC_TYPE):
        out.append(f"        t.inputs.push_back(vl::inputPort({_cpp_string(s.id)}, {_cpp_string(s.type)}, "
                   f"{'true' if s.optional else 'false'}, &N::{s.id}));")
    for s in (s for s in node_def.outputs if s.type != EXEC_TYPE):
        out.append(f"        t.outputs.push_back(vl::outputPort({_cpp_string(s.id)}, {_cpp_string(s.type)}, "
                   f"&N::{s.id}));")
    for s in node_def.settings:
        out.append(f"        t.settings.push_back(vl::settingPort({_cpp_string(s.id)}, &N::{s.id}));")
    if node_def.app_widget is not None:
        out.append("        t.hasWidget = true;")
    out += [
        "        return t;",
        "    }();",
        "    return type;",
        "}",
        "",
    ]
    return "\n".join(out)


def _main_cpp(nodes, connections, plan: WirePlan, gui: bool, flows: FlowPlan) -> str:
    """generated/main.cpp: creates the nodes and wires them. Only depends on
    which nodes there are and how they are wired, not on any value."""
    used_types = sorted({n["type"] for n in nodes})
    out = [
        "// Generated by VL. Do not edit: this file is rewritten on every compile.",
        "// Values (settings, input fields) are in the .values.json file next to the program.",
        '#include "vl/runtime.hpp"',
        "",
        *[f"const vl::NodeType& {_type_function(t)}();" for t in used_types],
        "",
        "int main(int argc, char** argv) {",
        f"    vl::App app({'true' if gui else 'false'});",
        "",
        "    // Nodes",
    ]
    # Variables are numbered: ids like "a-1" and "a_1" would clash as identifiers.
    var = {n["id"]: f"n{i}" for i, n in enumerate(nodes)}
    for n in nodes:
        out.append(f"    auto& {var[n['id']]} = app.create({_type_function(n['type'])}(), "
                   f"{_cpp_string(n['id'])});")
    out += ["", "    // Wires (feedback wires and wires into non-triggering inputs don't trigger a run)"]
    for i, c in enumerate(connections):
        out.append(f"    app.connect({var[c['source_node']]}, {_cpp_string(c['source_socket'])}, "
                   f"{var[c['target_node']]}, {_cpp_string(c['target_socket'])}, "
                   f"{'true' if plan.triggers(i) else 'false'});")
    if flows.has_flows:
        out += ["", "    // Flows: exec wires, entries (On Start / On Event) and which data nodes",
                "    // run during which flow (group bits: 1 main tree, 2 always, 4.. one per flow)"]
        for source, index, target in flows.exec_wires:
            out.append(f"    app.connectExec({var[source]}, {index}, {var[target]});")
        for k, entry in enumerate(flows.entries):
            out.append(f"    app.addFlowEntry({var[entry]}, {2 + k});")
        for n in nodes:
            groups = flows.groups.get(n["id"])
            if groups is not None and groups != GROUP_MAIN and n["id"] not in flows.entries:
                out.append(f"    app.setGroups({var[n['id']]}, {groups:#x});")
    out += [
        "",
        "    if (!app.loadValues(argc, argv))",
        "        return 1;",
        "    return app.run();",
        "}",
        "",
    ]
    return "\n".join(out)


def _json_value(value: Any, data_type: str) -> Any:
    """A value as the runtime reads it (numbers rounded for integer types)."""
    if isinstance(value, bool) or data_type == "bool":
        return bool(value)
    if isinstance(value, (int, float)):
        return int(round(value)) if is_integer_type(data_type) else float(value)
    return value


def _values(nodes, connections, plan: WirePlan, catalog, settings, name) -> dict[str, Any]:
    """The values file: everything about the graph that can change without
    compiling (settings, starting values of inputs, widget options)."""
    connected_inputs = {(c["target_node"], c["target_socket"]) for c in connections}
    held_inputs = {(connections[i]["target_node"], connections[i]["target_socket"])
                   for i in range(len(connections)) if plan.starts_with_value(i)}
    result: dict[str, Any] = {
        "app": {"name": name, "fullscreen": bool(settings.get("fullscreen", True))},
        "nodes": {},
    }
    for n in nodes:
        node_def = catalog[n["type"]]
        values = n.get("values", {})
        entry: dict[str, Any] = {}

        node_settings = {s.id: _json_value(values[s.id], s.type) for s in node_def.settings if s.id in values}
        if node_settings:
            entry["settings"] = node_settings

        inputs: dict[str, Any] = {}
        for s in node_def.inputs:
            key = (n["id"], s.id)
            field = values.get(s.id, s.widget.default) if s.widget is not None else None
            if key not in connected_inputs:
                # Unconnected input: its field value, or an optional input's default.
                if s.widget is not None:
                    inputs[s.id] = {"init" if s.optional else "receive": _json_value(field, s.type)}
                elif s.optional and s.default is not None:
                    inputs[s.id] = {"init": _json_value(s.default, s.type)}
            else:
                start = field if s.widget is not None else s.default
                if s.optional:
                    if start is not None:
                        inputs[s.id] = {"init": _json_value(start, s.type)}  # until a value arrives
                elif key in held_inputs:
                    # Fed by a wire in a loop that doesn't trigger: start from the
                    # field value (or T{}), so the loop can start.
                    inputs[s.id] = {"receive": _json_value(start, s.type) if start is not None else None}
        if inputs:
            entry["inputs"] = inputs

        if node_def.app_widget is not None:
            title_setting = node_def.app_widget.title_setting
            title = str(values.get(title_setting, "")) if title_setting else ""
            entry["widget"] = {"visible": bool(n.get("widget_visible", True)), "title": title or node_def.title}
        if entry:
            result["nodes"][n["id"]] = entry
    return result


def _cmake_lists(target: str, cpp_files: list[str], gui: bool) -> str:
    sources = "\n    ".join(["generated/main.cpp", "runtime/vl/app.cpp", *cpp_files])
    return f"""# Generated by VL. Do not edit: this file is rewritten on every compile.
cmake_minimum_required(VERSION 3.16)
if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)  # Downloaded files get the extraction time.
endif()
project({target} CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Put the executable directly in this folder.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${{CMAKE_SOURCE_DIR}})

option(VL_GUI "Build the app widget window (Dear ImGui + SDL2)" {"ON" if gui else "OFF"})

# ccache, when installed, makes rebuilds of unchanged files almost free.
if(NOT VL_ZIG AND NOT CMAKE_CXX_COMPILER_LAUNCHER)
    find_program(VL_CCACHE ccache)
    if(VL_CCACHE)
        set(CMAKE_CXX_COMPILER_LAUNCHER ${{VL_CCACHE}})
    endif()
endif()

add_executable({target}
    {sources}
)
target_include_directories({target} PRIVATE ${{CMAKE_SOURCE_DIR}} ${{CMAKE_SOURCE_DIR}}/runtime)

if(VL_GUI)
    include(FetchContent)
    if(VL_SDL2_FROM_SOURCE)
        include(runtime/cmake/sdl2-from-source.cmake)
    else()
        find_package(SDL2 REQUIRED)
    endif()
    FetchContent_Declare(imgui
        URL https://github.com/ocornut/imgui/archive/refs/tags/{IMGUI_VERSION}.tar.gz)
    FetchContent_MakeAvailable(imgui)

    target_sources({target} PRIVATE
        ${{imgui_SOURCE_DIR}}/imgui.cpp
        ${{imgui_SOURCE_DIR}}/imgui_draw.cpp
        ${{imgui_SOURCE_DIR}}/imgui_tables.cpp
        ${{imgui_SOURCE_DIR}}/imgui_widgets.cpp
        ${{imgui_SOURCE_DIR}}/backends/imgui_impl_sdl2.cpp
        ${{imgui_SOURCE_DIR}}/backends/imgui_impl_sdlrenderer2.cpp)
    target_include_directories({target} PRIVATE ${{imgui_SOURCE_DIR}} ${{imgui_SOURCE_DIR}}/backends)
    target_compile_definitions({target} PRIVATE VL_GUI)
    if(TARGET SDL2::SDL2)
        target_link_libraries({target} PRIVATE SDL2::SDL2)
    else()
        target_link_libraries({target} PRIVATE SDL2::SDL2-static)
    endif()
endif()
"""


TOOLCHAIN_FILES = {
    "linux-x86_64": "runtime/cmake/zig-linux-x86_64.cmake",
    "linux-arm64": "runtime/cmake/zig-linux-arm64.cmake",
    "windows-x86_64": "runtime/cmake/zig-windows-x86_64.cmake",
}
