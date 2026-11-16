"""The MCP tools (vl_tools.py) on a live graph, and the HTTP server."""

import json

import pytest

from vl_tools import ToolError, VlTools


@pytest.fixture
def tools(graph, project):
    from builder import Builder
    return VlTools(graph, project, Builder(), lambda: None)


def call(tools, name, **args):
    result = tools.tools[name].handler(args)
    return json.loads(result.content[0]["text"])


def test_edit_graph_with_refs(tools, graph):
    out = call(tools, "edit_graph", ops=[
        {"op": "add_node", "type": "constant_int", "ref": "c", "values": {"number": 7}},
        {"op": "add_node", "type": "add", "ref": "sum"},
        {"op": "connect", "source_node": "c", "source_socket": "value", "target_node": "sum", "target_socket": "a"},
    ])
    assert len(out["new_nodes"]) == 2
    assert graph.connectionCount == 1
    sum_id = out["refs"]["sum"]
    assert graph.find_node(out["refs"]["c"]).values["number"] == 7
    assert graph.find_node(sum_id) is not None
    graph.undo()
    assert graph.rowCount() == 0  # one undo step


def test_edit_graph_is_all_or_nothing(tools, graph):
    with pytest.raises(ToolError, match="Nothing was changed"):
        call(tools, "edit_graph", ops=[
            {"op": "add_node", "type": "add"},
            {"op": "connect", "source_node": "nope", "source_socket": "x",
             "target_node": "nope", "target_socket": "y"},
        ])
    assert graph.rowCount() == 0


def test_get_graph_and_types(tools, graph):
    graph.addNode("add", 0, 0)
    out = call(tools, "get_graph")
    assert out["nodes"][0]["type"] == "add"
    types = call(tools, "list_node_types")
    assert any(t["id"] == "add" for t in (types if isinstance(types, list) else types["node_types"]))


def test_server_definitions(tools):
    from mcp_server import McpServer
    server = McpServer(tools, "test")
    response = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in response["result"]["tools"]}
    assert {"edit_graph", "build", "commit"} <= names
