"""The tools VL offers over MCP: reading and editing the open graph, importing
nodes, compiling, saving and taking a screenshot.

Every tool works on the live app state (the same GraphModel and Project the
window shows), on the Qt main thread, so changes appear in the window at
once and can be undone with Ctrl+Z like the user's own edits.

A tool handler takes the call's arguments and returns a ToolResult, or a
Deferred for tools that finish later (a build). ToolError becomes an error
result that the client shows to the model.
"""

import base64
import json
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
from PySide6.QtQuick import QQuickWindow

import compiler
import graph_layout
from builder import Builder
from graph_model import GraphModel
from history import HistoryError, describe_summary
from node_catalog import NodeDef
from project import Project

LOG_LINES = 120   # Build log lines returned by default (the end of the log).


class ToolError(Exception):
    """A problem to report to the model (bad arguments, a rejected edit...)."""


@dataclass
class ToolResult:
    content: list[dict[str, Any]]
    is_error: bool = False

    @staticmethod
    def json(data: Any) -> "ToolResult":
        return ToolResult([{"type": "text", "text": json.dumps(data, indent=1, ensure_ascii=False)}])

    @staticmethod
    def text(text: str, is_error: bool = False) -> "ToolResult":
        return ToolResult([{"type": "text", "text": text}], is_error)


class Deferred:
    """A result that arrives later. The server registers one callback."""

    def __init__(self):
        self._callback: Callable[[ToolResult], None] | None = None
        self._result: ToolResult | None = None

    def resolve(self, result: ToolResult):
        if self._result is not None:
            return
        self._result = result
        if self._callback:
            self._callback(result)

    def then(self, callback: Callable[[ToolResult], None]):
        self._callback = callback
        if self._result is not None:
            callback(self._result)


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[[dict[str, Any]], "ToolResult | Deferred"]
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    read_only: bool = False

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {"type": "object", "properties": self.properties, "required": self.required,
                            "additionalProperties": False},
            "annotations": {"readOnlyHint": self.read_only, "destructiveHint": False, "openWorldHint": False},
        }


INSTRUCTIONS = """\
VL is a visual dataflow language: programs are graphs of typed nodes, compiled to C++.
These tools edit the graph that is open in the user's VL window; they watch it change
live and can undo your edits with Ctrl+Z.

- Start with list_node_types (what exists, socket ids and types) and get_graph.
- Wires go from an output socket to an input socket of exactly the same type (no
  conversions). An input takes one wire; outputs can feed many inputs. Loops are allowed
  (feedback).
- Inputs with a widget have a value used while unconnected; settings are values with
  no socket. Set both with set_values.
- Make all related changes in one edit_graph call: it applies all or nothing and is one
  undo step. Leave x/y out and VL places new nodes next to the nodes they connect to.
- get_graph lists issues: an error is an input that needs a wire; a warning is an unused
  output. Fix errors before building.
- New node types: write a node JSON plus its C++ (see the project's nodes/README.md and
  tutorial.md), then import_nodes. build compiles and returns the log.
- The project has git-like branches and commits (get_history). For an experiment the
  user didn't ask to keep on the current branch, offer create_branch first; commit when
  a working step is done, with a short message saying what changed.
"""


def _widget(w) -> dict[str, Any] | None:
    if w is None:
        return None
    data: dict[str, Any] = {"kind": w.kind, "default": w.default}
    if w.kind == "number":
        if w.min is not None:
            data["min"] = w.min
        if w.max is not None:
            data["max"] = w.max
    if w.kind == "select":
        data["options"] = list(w.options)
    return data


def _socket(s) -> dict[str, Any]:
    data = {"id": s.id, "name": s.name, "type": s.type}
    if getattr(s, "widget", None) is not None:
        data["widget"] = _widget(s.widget)
    return data


def _node_type(d: NodeDef, imported: bool) -> dict[str, Any]:
    data: dict[str, Any] = {"id": d.type_id, "title": d.title, "group": d.group}
    if d.description:
        data["description"] = d.description
    if imported:
        data["imported"] = True
    data["inputs"] = [_socket(s) for s in d.inputs]
    data["outputs"] = [_socket(s) for s in d.outputs]
    if d.settings:
        data["settings"] = [{**_socket(s), **({"app_widget_only": True} if s.app_widget_only else {})}
                            for s in d.settings]
    if d.app_widget is not None:
        data["app_widget"] = True
    return data


class VlTools(QObject):
    # Asks the window to do something only QML can: "frame" (zoom to show the
    # whole graph) or "showBuildLog".
    viewRequested = Signal(str)

    def __init__(self, graph: GraphModel, project: Project, builder: Builder,
                 window: Callable[[], QQuickWindow | None]):
        super().__init__()
        self._graph = graph
        self._project = project
        self._builder = builder
        self._window = window
        node_ref = {"type": "string", "description": "A node id, or a ref given to add_node earlier in this call."}
        self.tools: dict[str, Tool] = {t.name: t for t in [
            Tool("list_node_types",
                 "All node types that can be added to the graph (built-in and imported), with their "
                 "input/output sockets (id, type), value widgets and settings.",
                 self._list_node_types,
                 {"group": {"type": "string", "description": "Only this group (case-insensitive)."}},
                 read_only=True),
            Tool("get_graph",
                 "The open graph: nodes (id, type, position, values), wires and issues "
                 "(errors block compiling). Also the project file and whether it has unsaved changes.",
                 self._get_graph, read_only=True),
            Tool("edit_graph",
                 "Apply a list of edits to the graph, in order, as ONE undo step. If any edit fails, "
                 "nothing is changed and the error says which one.\n"
                 "Ops (field 'op'):\n"
                 "- add_node: type, ref?, x?, y?, values? ({id: value}), widget_visible?. 'ref' is a "
                 "name later ops can use instead of the new node's id. Without x/y the node is placed "
                 "next to the nodes it gets connected to.\n"
                 "- remove_nodes: nodes (list), also removes their wires.\n"
                 "- move_node: node, x, y (canvas coordinates; nodes are 230 wide, y grows downwards).\n"
                 "- set_values: node, values ({input-or-setting id: value}).\n"
                 "- connect: source_node, source_socket (an output), target_node, target_socket (an input). "
                 "Replaces a wire already on that input.\n"
                 "- disconnect: target_node, target_socket.\n"
                 "- set_widget_visible: node, visible (show the node's widget in the compiled app).\n"
                 "Returns the ids of added nodes (by ref) and the graph's issues afterwards.",
                 self._edit_graph,
                 {"ops": {"type": "array", "items": {
                     "type": "object",
                     "properties": {
                         "op": {"type": "string", "enum": ["add_node", "remove_nodes", "move_node", "set_values",
                                                           "connect", "disconnect", "set_widget_visible"]},
                         "type": {"type": "string"}, "ref": {"type": "string"},
                         "x": {"type": "number"}, "y": {"type": "number"},
                         "values": {"type": "object"}, "widget_visible": {"type": "boolean"},
                         "node": node_ref, "nodes": {"type": "array", "items": node_ref},
                         "source_node": node_ref, "source_socket": {"type": "string"},
                         "target_node": node_ref, "target_socket": {"type": "string"},
                         "visible": {"type": "boolean"},
                     },
                     "required": ["op"],
                 }}},
                 ["ops"]),
            Tool("arrange_nodes",
                 "Lay out nodes in columns so wires run left to right (one undo step). "
                 "Defaults to the whole graph.",
                 self._arrange_nodes,
                 {"nodes": {"type": "array", "items": {"type": "string"},
                            "description": "Only these nodes (they keep their top-left corner)."},
                  "frame": {"type": "boolean", "description": "Also zoom the view to show the whole graph "
                                                              "(default true)."}}),
            Tool("import_nodes",
                 "Import node types from node JSON files (absolute paths); the code files each JSON lists "
                 "are imported too and stored in the project. Re-importing an id replaces the old version "
                 "(nodes in the graph are kept where their sockets still fit). Note: importing clears the "
                 "undo history.",
                 self._import_nodes,
                 {"paths": {"type": "array", "items": {"type": "string"}},
                  "replace": {"type": "boolean", "description": "Replace already imported ids (default true)."}},
                 ["paths"]),
            Tool("get_project",
                 "Project file, unsaved changes, compile settings (with allowed values), imported node "
                 "types and the last build's status.",
                 self._get_project, read_only=True),
            Tool("set_compile_settings",
                 "Change compile settings, e.g. {\"target\": \"linux-arm64\", \"build_type\": \"debug\"}. "
                 "Keys: language, target, build_type, output_dir (\"\" = <project folder>/build), "
                 "executable_name (\"\" = project name), fullscreen. See get_project for allowed values.",
                 self._set_compile_settings,
                 {"settings": {"type": "object"}}, ["settings"]),
            Tool("build",
                 "Compile the graph to C++ and build it (like the Compile button). The build log opens in "
                 "the window. By default waits for the build to finish and returns the result and the end "
                 "of the log.",
                 self._build,
                 {"wait": {"type": "boolean", "description": "Wait for the build to finish (default true)."}}),
            Tool("get_build_log",
                 "Status and log of the current or last build.",
                 self._get_build_log,
                 {"lines": {"type": "integer", "description": f"Lines from the end (default {LOG_LINES}, "
                                                             "0 = whole log)."}},
                 read_only=True),
            Tool("save_project",
                 "Save the project (to its file, or to 'path' — an absolute path; \".vl\" is added).",
                 self._save_project,
                 {"path": {"type": "string"}}),
            Tool("get_history",
                 "Version history: the branches (current one, uncommitted changes, last commit) and the "
                 "commits of one branch, newest first (id, message, time, what changed).",
                 self._get_history,
                 {"branch": {"type": "string", "description": "Whose commits to list (default: the current branch)."}},
                 read_only=True),
            Tool("commit",
                 "Commit the current state (graph, compile settings, colours, imported nodes) on the current "
                 "branch, like git commit, and save the project file. The project must have been saved once.",
                 self._commit,
                 {"message": {"type": "string", "description": "What changed, e.g. \"slow down near walls\"."}},
                 ["message"]),
            Tool("switch_branch",
                 "Switch to another branch. Uncommitted changes stay with the branch left (nothing is lost) "
                 "and the target's own uncommitted changes come back. Clears the undo history.",
                 self._switch_branch,
                 {"branch": {"type": "string"}}, ["branch"]),
            Tool("create_branch",
                 "Create a branch and switch to it. Without from_commit it starts from the current state and "
                 "takes the uncommitted changes along (the old branch goes back to its last commit), like "
                 "git switch -c. With from_commit (an id from get_history) it starts at that commit. Good "
                 "for trying out a change without touching the working version.",
                 self._create_branch,
                 {"name": {"type": "string"}, "from_commit": {"type": "string"}}, ["name"]),
            Tool("screenshot",
                 "A picture of the VL window as the user sees it, e.g. to check the layout.",
                 self._screenshot,
                 {"frame": {"type": "boolean", "description": "First zoom the view to show the whole graph "
                                                             "(default false)."}},
                 read_only=True),
        ]}

    # -- Helpers --------------------------------------------------------------

    def _issues(self) -> list[dict[str, str]]:
        return [{"severity": i["severity"], "node": i["nodeId"], "message": i["message"]}
                for i in self._graph.issues]

    def _frame_all(self):
        self.viewRequested.emit("frame")

    def _notice(self, text: str):
        self._project.notice.emit(text)

    # -- Reading --------------------------------------------------------------

    def _list_node_types(self, args: dict) -> ToolResult:
        group = str(args.get("group", "")).lower()
        imported = self._project.imported_ids
        types = [_node_type(d, d.type_id in imported)
                 for d in sorted(self._graph.catalog.values(), key=lambda d: (d.group.lower(), d.title.lower()))
                 if not group or d.group.lower() == group]
        return ToolResult.json(types)

    def _get_graph(self, args: dict) -> ToolResult:
        graph = self._graph.to_dict()
        for node in graph["nodes"]:
            node["title"] = self._graph.catalog[node["type"]].title
        return ToolResult.json({
            "project": self._project.filePath or None,
            "unsaved_changes": self._project.isDirty,
            "nodes": graph["nodes"],
            "connections": graph["connections"],
            "issues": self._issues(),
        })

    def _get_project(self, args: dict) -> ToolResult:
        return ToolResult.json({
            "project": self._project.filePath or None,
            "unsaved_changes": self._project.isDirty,
            "branch": self._project.currentBranch,
            "uncommitted_changes": self._project.hasUncommittedChanges,
            "compile_settings": self._project.compileSettings,
            "allowed_values": {key: [c["value"] for c in choices]
                               for key, choices in self._project.compileChoices.items()},
            "default_output_dir": self._project.defaultOutputDir or None,
            "imported_nodes": [{"id": n["id"], "title": n["title"], "files": n["files"],
                                "source": n["source"], "used": n["useCount"]}
                               for n in self._project.importedNodes],
            "build_status": self._builder.status,
        })

    # -- Editing --------------------------------------------------------------

    def _edit_graph(self, args: dict) -> ToolResult:
        ops = args.get("ops")
        if not isinstance(ops, list) or not ops:
            raise ToolError("'ops' must be a non-empty list of edits.")

        graph = self._graph
        refs: dict[str, str] = {}
        added: list[str] = []
        unplaced: list[str] = []
        counts = {"added": 0, "removed": 0, "wired": 0, "unwired": 0, "changed": 0}
        notes: list[str] = []

        def node_id(op: dict, key: str) -> str:
            value = op.get(key)
            if not isinstance(value, str) or not value:
                raise ToolError(f"'{key}' is missing.")
            value = refs.get(value, value)
            if graph.find_node(value) is None:
                raise ToolError(f"No node '{value}' (use a node id from get_graph, or a ref from add_node).")
            return value

        def coerce_values(nid: str, values: Any) -> dict[str, Any]:
            if not isinstance(values, dict):
                raise ToolError("'values' must be an object of {id: value}.")
            node = graph.find_node(nid)
            fields = graph.catalog[node.type].value_fields()
            result = {}
            for key, value in values.items():
                if key not in fields:
                    valid = ", ".join(fields) or "none"
                    raise ToolError(f"{node.type} has no input widget or setting '{key}' (valid: {valid}).")
                data_type, widget = fields[key]
                try:
                    result[key] = widget.coerce(value, data_type)
                except (TypeError, ValueError) as e:
                    raise ToolError(f"Invalid value for '{key}' on {nid}: {e}") from None
            return result

        def set_values(nid: str, values: dict[str, Any]):
            for key, value in coerce_values(nid, values).items():
                if graph.find_node(nid).values.get(key) != value:
                    graph.setNodeValue(nid, key, value)
                    counts["changed"] += 1

        def number(op: dict, key: str) -> float:
            value = op.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ToolError(f"'{key}' must be a number.")
            return float(value)

        try:
            with graph.single_undo_step():
                for index, op in enumerate(ops):
                    if not isinstance(op, dict):
                        raise ToolError(f"Edit {index}: must be an object.")
                    kind = op.get("op")
                    try:
                        if kind == "add_node":
                            type_id = op.get("type")
                            if type_id not in graph.catalog:
                                raise ToolError(f"Unknown node type '{type_id}' (see list_node_types).")
                            ref = op.get("ref")
                            if ref is not None and (not isinstance(ref, str) or not ref or ref in refs
                                                    or graph.find_node(ref)):
                                raise ToolError(f"ref '{ref}' must be a new name, not used by a node or ref.")
                            placed = "x" in op or "y" in op
                            x = number(op, "x") if "x" in op else 0.0
                            y = number(op, "y") if "y" in op else 0.0
                            nid = graph.addNode(type_id, x, y)
                            if ref:
                                refs[ref] = nid
                            added.append(nid)
                            if not placed:
                                unplaced.append(nid)
                            if "values" in op:
                                set_values(nid, op["values"])
                            if "widget_visible" in op:
                                graph.setWidgetVisible(nid, bool(op["widget_visible"]))
                            counts["added"] += 1

                        elif kind == "remove_nodes":
                            nodes = op.get("nodes")
                            if not isinstance(nodes, list) or not nodes:
                                raise ToolError("'nodes' must be a non-empty list.")
                            ids = [node_id({"n": n}, "n") for n in nodes]
                            graph.removeNodes(ids)
                            unplaced = [n for n in unplaced if n not in ids]
                            added = [n for n in added if n not in ids]
                            counts["removed"] += len(set(ids))

                        elif kind == "move_node":
                            nid = node_id(op, "node")
                            graph.moveNodes([{"id": nid, "x": number(op, "x"), "y": number(op, "y")}])
                            if nid in unplaced:
                                unplaced.remove(nid)

                        elif kind == "set_values":
                            set_values(node_id(op, "node"), op.get("values"))

                        elif kind == "connect":
                            sn, tn = node_id(op, "source_node"), node_id(op, "target_node")
                            sp, tp = str(op.get("source_socket", "")), str(op.get("target_socket", ""))
                            error = graph._validate_connection(sn, sp, tn, tp)
                            if error:
                                s_def, t_def = graph.catalog[graph.find_node(sn).type], graph.catalog[graph.find_node(tn).type]
                                if graph.find_socket(graph.find_node(sn), sp, True) is None:
                                    error += (f" Outputs of {op['source_node']}: "
                                              f"{', '.join(s.id for s in s_def.outputs) or 'none'}.")
                                if graph.find_socket(graph.find_node(tn), tp, False) is None:
                                    error += (f" Inputs of {op['target_node']}: "
                                              f"{', '.join(s.id for s in t_def.inputs) or 'none'}.")
                                raise ToolError(error)
                            replaced = next((c for c in graph.connections_dict.values()
                                             if c.target_node == tn and c.target_port == tp
                                             and (c.source_node, c.source_port) != (sn, sp)), None)
                            if replaced:
                                notes.append(f"{tn}.{tp} was fed by {replaced.source_node}."
                                             f"{replaced.source_port}; that wire was replaced.")
                            graph.addConnection(sn, sp, tn, tp)
                            counts["wired"] += 1

                        elif kind == "disconnect":
                            tn = node_id(op, "target_node")
                            tp = str(op.get("target_socket", ""))
                            if graph.disconnectInput(tn, tp):
                                counts["unwired"] += 1
                            else:
                                notes.append(f"{tn}.{tp} had no wire.")

                        elif kind == "set_widget_visible":
                            nid = node_id(op, "node")
                            if graph.catalog[graph.find_node(nid).type].app_widget is None:
                                raise ToolError(f"{nid} has no app widget.")
                            graph.setWidgetVisible(nid, bool(op.get("visible", True)))
                            counts["changed"] += 1

                        else:
                            raise ToolError(f"Unknown op '{kind}'.")
                    except ToolError as e:
                        raise ToolError(f"Edit {index} ({kind}) failed: {e}") from None

                if unplaced:
                    positions = graph_layout.place_new_nodes(graph.to_dict(), graph.catalog, unplaced)
                    graph.moveNodes([{"id": nid, "x": x, "y": y} for nid, (x, y) in positions.items()])
        except ToolError as e:
            raise ToolError(f"{e} Nothing was changed.") from None

        done = [f"{n} {word}" for word, n in (("node(s) added", counts["added"]),
                                              ("node(s) removed", counts["removed"]),
                                              ("wire(s) connected", counts["wired"]),
                                              ("wire(s) removed", counts["unwired"]),
                                              ("value(s) changed", counts["changed"])) if n]
        if done:
            self._notice("Claude: " + ", ".join(done))
        return ToolResult.json({
            "done": ", ".join(done) or "nothing changed",
            **({"new_nodes": added} if added else {}),
            **({"refs": refs} if refs else {}),
            **({"notes": notes} if notes else {}),
            "issues": self._issues(),
        })

    def _arrange_nodes(self, args: dict) -> ToolResult:
        nodes = args.get("nodes")
        if nodes is not None:
            missing = [n for n in nodes if self._graph.find_node(n) is None]
            if missing:
                raise ToolError(f"No such nodes: {', '.join(missing)}.")
        positions = graph_layout.arrange(self._graph.to_dict(), self._graph.catalog,
                                         set(nodes) if nodes is not None else None)
        self._graph.moveNodes([{"id": nid, "x": x, "y": y} for nid, (x, y) in positions.items()])
        if args.get("frame", True):
            self._frame_all()
        return ToolResult.text(f"Arranged {len(positions)} node(s).")

    def _import_nodes(self, args: dict) -> ToolResult:
        paths = args.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
            raise ToolError("'paths' must be a list of node JSON file paths.")
        relative = [p for p in paths if not Path(p).is_absolute()]
        if relative:
            raise ToolError(f"Use absolute paths (VL doesn't know your working directory): {', '.join(relative)}")
        result = self._project.import_node_files(paths, args.get("replace", True) is not False)
        data: dict[str, Any] = {k: v for k, v in result.items() if v}
        if result["existing"]:
            data["existing"] = [e["file"] for e in result["existing"]]
            data["hint"] = "Already imported; pass replace=true to replace them."
        result_obj = ToolResult.json(data or {"done": "nothing imported"})
        result_obj.is_error = not (result["added"] or result["updated"])
        return result_obj

    def _set_compile_settings(self, args: dict) -> ToolResult:
        settings = args.get("settings")
        if not isinstance(settings, dict) or not settings:
            raise ToolError("'settings' must be an object of {key: value}.")
        for key, value in settings.items():
            try:
                compiler.coerce_setting(key, value)
            except ValueError as e:
                raise ToolError(f"{e}. Nothing was changed.") from None
        for key, value in settings.items():
            self._project.setCompileSetting(key, value)
        return ToolResult.json(self._project.compileSettings)

    def _save_project(self, args: dict) -> ToolResult:
        path = args.get("path") or self._project.filePath
        if not path:
            raise ToolError("The project has never been saved: give a 'path' (absolute, e.g. ~/robot.vl).")
        path = str(Path(path).expanduser())
        if not Path(path).is_absolute():
            raise ToolError("'path' must be absolute.")
        error = self._project.save_to(path, show_errors=False)
        if error:
            raise ToolError(error)
        return ToolResult.text(f"Saved {self._project.filePath}")

    # -- Version history ------------------------------------------------------

    def _get_history(self, args: dict) -> ToolResult:
        project = self._project
        history = project.history
        branch = args.get("branch") or history.current
        if branch not in history.branches:
            raise ToolError(f"There is no branch '{branch}'. Branches: {', '.join(history.branches)}.")
        return ToolResult.json({
            "current_branch": history.current,
            "branches": [{"name": b["name"], "current": b["isCurrent"], "uncommitted_changes": b["hasDraft"],
                          "commits": b["commitCount"], "last_commit": b["message"] or None}
                         for b in project.branches],
            "uncommitted_summary": project.uncommittedSummary() or None,
            "branch": branch,
            "commits": [{"id": c["id"], "message": c["message"],
                         "time": datetime.fromtimestamp(c["time"]).isoformat(timespec="seconds"),
                         "changes": describe_summary(c.get("summary"))}
                        for c in history.log(branch)],
        })

    def _commit(self, args: dict) -> ToolResult:
        if not self._project.filePath:
            raise ToolError("The project has never been saved: save_project with a 'path' first.")
        try:
            error = self._project.commit_changes(str(args.get("message", "")), show_errors=False)
        except HistoryError as e:
            raise ToolError(str(e)) from None
        head = self._project.history.head()
        text = f"Committed {head} on {self._project.history.current}"
        return ToolResult.text(f"{text}, but saving failed: {error}" if error else f"{text} and saved.")

    def _switch_branch(self, args: dict) -> ToolResult:
        try:
            warnings = self._project.switch_branch(str(args.get("branch", "")))
        except HistoryError as e:
            raise ToolError(str(e)) from None
        self._frame_all()
        return ToolResult.json({"current_branch": self._project.history.current,
                                "warnings": warnings, "issues": self._issues()})

    def _create_branch(self, args: dict) -> ToolResult:
        try:
            name, warnings = self._project.create_branch(str(args.get("name", "")),
                                                         str(args.get("from_commit") or ""))
        except HistoryError as e:
            raise ToolError(str(e)) from None
        self._frame_all()
        return ToolResult.json({"current_branch": name, "warnings": warnings, "issues": self._issues()})

    # -- Building -------------------------------------------------------------

    def _build_report(self, lines: int = LOG_LINES) -> dict[str, Any]:
        log = self._builder.log.splitlines()
        if lines and len(log) > lines:
            log = [f"... ({len(log) - lines} earlier lines; get_build_log with lines=0 for all)"] + log[-lines:]
        report: dict[str, Any] = {"status": self._builder.status}
        if self._builder.executable and self._builder.status == "succeeded":
            report["executable"] = self._builder.executable
        report["log"] = "\n".join(log)
        return report

    def _build(self, args: dict) -> "ToolResult | Deferred":
        if self._builder.running:
            raise ToolError("A build is already running (get_build_log shows its progress).")
        self.viewRequested.emit("showBuildLog")

        if args.get("wait", True) is False:
            started = self._project.compileProject()
            report = self._build_report()
            if started:
                report["note"] = "Build started; get_build_log shows progress."
            return ToolResult([{"type": "text", "text": json.dumps(report, indent=1)}], is_error=not started)

        # finished is emitted later by the build, or at once if the graph can't be compiled.
        deferred = Deferred()

        def finished(success: bool, summary: str):
            self._builder.finished.disconnect(finished)
            report = self._build_report()
            report["summary"] = summary
            deferred.resolve(ToolResult([{"type": "text", "text": json.dumps(report, indent=1)}],
                                        is_error=not success))

        self._builder.finished.connect(finished)
        self._project.compileProject()
        return deferred

    def _get_build_log(self, args: dict) -> ToolResult:
        lines = args.get("lines", LOG_LINES)
        if isinstance(lines, bool) or not isinstance(lines, int) or lines < 0:
            raise ToolError("'lines' must be a whole number ≥ 0.")
        return ToolResult.json(self._build_report(lines))

    # -- Screenshot -----------------------------------------------------------

    def _screenshot(self, args: dict) -> ToolResult:
        window = self._window()
        if window is None:
            raise ToolError("The VL window isn't open.")
        if args.get("frame"):
            self._frame_all()
        image = window.grabWindow()
        if image.isNull():
            raise ToolError("Could not capture the window (is it minimised?).")
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return ToolResult([{"type": "image", "mimeType": "image/png",
                            "data": base64.b64encode(bytes(data)).decode("ascii")}])
