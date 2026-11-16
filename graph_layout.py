"""Placing nodes on the canvas automatically.

Used when nodes are added without a position (by the MCP server) and for
"arrange": a layered layout where wires run left to right, like a hand-made
graph. Works on plain data (GraphModel.to_dict() shapes), so it has no Qt
dependency. Sizes mirror ui/components/Node.qml.
"""

from typing import Any

from compiler import feedback_connections
from node_catalog import NodeDef

NODE_WIDTH = 230
HEADER_HEIGHT = 34
ROW_PITCH = 26
ROW_PADDING = 8 + 10        # rowsTopPadding + rowsBottomPadding
COLUMN_GAP = 90             # Horizontal space between columns (for the wires).
ROW_GAP = 40                # Vertical space between nodes in a column.


def node_height(node_def: NodeDef, widget_visible: bool = True) -> int:
    settings = [s for s in node_def.settings if widget_visible or not s.app_widget_only]
    rows = len(node_def.outputs) + len(settings) + len(node_def.inputs)
    return HEADER_HEIGHT + ROW_PADDING + rows * ROW_PITCH


def _boxes(nodes: list[dict], catalog: dict[str, NodeDef]) -> dict[str, tuple[float, float, float, float]]:
    """{node id: (x, y, width, height)}"""
    return {n["id"]: (n["x"], n["y"], NODE_WIDTH, node_height(catalog[n["type"]], n.get("widget_visible", True)))
            for n in nodes}


def _overlaps(box, others) -> bool:
    x, y, w, h = box
    return any(x < ox + ow + ROW_GAP / 2 and ox < x + w + ROW_GAP / 2
               and y < oy + oh + ROW_GAP / 2 and oy < y + h + ROW_GAP / 2
               for ox, oy, ow, oh in others)


def place_new_nodes(graph: dict[str, Any], catalog: dict[str, NodeDef], new_ids: list[str]) -> dict[str, tuple[float, float]]:
    """Positions for nodes that were added without one.

    A node goes one column to the right of the nodes feeding it (or left of
    the nodes it feeds), level with them, then moves down until it doesn't
    cover another node. Nodes with no placed neighbour go below the graph.
    Returns {node id: (x, y)}.
    """
    by_id = {n["id"]: dict(n) for n in graph["nodes"]}
    pending = [i for i in new_ids if i in by_id]
    placed = {i for i in by_id if i not in pending}
    boxes = _boxes([by_id[i] for i in placed], catalog)
    result: dict[str, tuple[float, float]] = {}
    step = NODE_WIDTH + COLUMN_GAP

    def put(node_id: str, x: float, y: float):
        node = by_id[node_id]
        h = node_height(catalog[node["type"]], node.get("widget_visible", True))
        while _overlaps((x, y, NODE_WIDTH, h), boxes.values()):
            y += ROW_PITCH
        node["x"], node["y"] = x, y
        boxes[node_id] = (x, y, NODE_WIDTH, h)
        placed.add(node_id)
        result[node_id] = (x, y)

    while pending:
        progress = False
        for node_id in list(pending):
            sources = [by_id[c["source_node"]] for c in graph["connections"]
                       if c["target_node"] == node_id and c["source_node"] in placed]
            targets = [by_id[c["target_node"]] for c in graph["connections"]
                       if c["source_node"] == node_id and c["target_node"] in placed]
            if sources:
                put(node_id, max(n["x"] for n in sources) + step, min(n["y"] for n in sources))
            elif targets:
                put(node_id, min(n["x"] for n in targets) - step, min(n["y"] for n in targets))
            else:
                continue
            pending.remove(node_id)
            progress = True

        if not progress:
            # Nothing connects to the placed nodes: start below the graph.
            node_id = pending.pop(0)
            if boxes:
                left = min(b[0] for b in boxes.values())
                bottom = max(b[1] + b[3] for b in boxes.values())
                put(node_id, left, bottom + ROW_GAP * 2)
            else:
                put(node_id, 0, 0)
    return result


def arrange(graph: dict[str, Any], catalog: dict[str, NodeDef], node_ids: set[str] | None = None) -> dict[str, tuple[float, float]]:
    """A layered layout of the given nodes (default: all), keeping their top-left corner.

    Each node goes in the column after the latest node feeding it (wires
    that close a feedback loop are ignored), so wires run left to right.
    Within a column, nodes are ordered by where their inputs come from, to
    keep wires short and uncrossed. Returns {node id: (x, y)}.
    """
    nodes = [n for n in graph["nodes"] if node_ids is None or n["id"] in node_ids]
    if not nodes:
        return {}
    ids = {n["id"] for n in nodes}
    connections = [c for c in graph["connections"] if c["source_node"] in ids and c["target_node"] in ids]
    feedback = feedback_connections(nodes, connections)
    edges = [c for i, c in enumerate(connections) if i not in feedback]

    # Column = longest path from a node with no inputs (the graph is acyclic without feedback wires).
    column = {n["id"]: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for c in edges:
            if column[c["target_node"]] < column[c["source_node"]] + 1:
                column[c["target_node"]] = column[c["source_node"]] + 1
                changed = True
        if not changed:
            break

    # Order inside each column: first by the average row of the nodes feeding it
    # (barycentre), then by the old vertical position.
    by_id = {n["id"]: n for n in nodes}
    order: dict[str, float] = {}
    columns: dict[int, list[str]] = {}
    for node_id in sorted(ids, key=lambda i: (column[i], by_id[i]["y"], by_id[i]["x"], i)):
        columns.setdefault(column[node_id], []).append(node_id)
    for col in sorted(columns):
        def key(node_id):
            rows = [order[c["source_node"]] for c in edges
                    if c["target_node"] == node_id and c["source_node"] in order]
            return (sum(rows) / len(rows) if rows else float("inf"), by_id[node_id]["y"])
        columns[col].sort(key=key)
        for row, node_id in enumerate(columns[col]):
            order[node_id] = row

    left = min(n["x"] for n in nodes)
    top = min(n["y"] for n in nodes)
    result = {}
    for col, members in columns.items():
        y = top
        for node_id in members:
            node = by_id[node_id]
            result[node_id] = (left + col * (NODE_WIDTH + COLUMN_GAP), y)
            y += node_height(catalog[node["type"]], node.get("widget_visible", True)) + ROW_GAP
    return result
