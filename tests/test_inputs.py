"""Optional and non-triggering inputs: catalog, issues, generated code and runtime."""

import pytest

from compiler import plan_wires
from node_catalog import CatalogError, parse_node_definition
from runtime_helpers import all_packages, build_and_run, make_graph, needs_compiler


def _node(**inp):
    return {"id": "n", "class": "N", "inputs": [{"id": "x", "type": "int32", **inp}]}


def test_parse_flags():
    s = parse_node_definition(_node(optional=True, default=4, triggers=False), "t").inputs[0]
    assert (s.optional, s.default, s.triggers) == (True, 4, False)
    s = parse_node_definition(_node(), "t").inputs[0]
    assert (s.optional, s.default, s.triggers) == (False, None, True)


@pytest.mark.parametrize("bad", [
    {"optional": "yes"},
    {"triggers": 0},
    {"default": "four"},
    {"default": 1.5},
    {"default": 1, "widget": "number"},
])
def test_bad_flags(bad):
    with pytest.raises(CatalogError):
        parse_node_definition(_node(**bad), "t")


def test_default_needs_builtin_type():
    raw = {"id": "n", "class": "N", "inputs": [{"id": "x", "type": "Scan", "default": 1}]}
    with pytest.raises(CatalogError, match="only possible"):
        parse_node_definition(raw, "t")


def test_outputs_cant_be_optional():
    with pytest.raises(CatalogError):
        parse_node_definition({"id": "n", "outputs": [{"id": "x", "type": "int32", "optional": True}]}, "t")


def test_optional_inputs_are_no_issue(qapp):
    from graph_model import GraphModel
    catalog = {k: p.definition for k, p in all_packages().items()}
    graph = GraphModel(catalog)
    nid = graph.addNode("t_inputs", 0, 0)
    messages = [i["message"] for i in graph.issues if i["nodeId"] == nid and i["severity"] == "error"]
    # a and c are required and have no field; b, d, e are optional.
    assert len(messages) == 2
    assert all("'a'" in m or "'c'" in m for m in messages)


def test_non_triggering_wires_break_loops():
    catalog = {k: p.definition for k, p in all_packages().items()}
    graph = make_graph({"t": ("t_tick", {}), "i": ("t_inputs", {})},
                       ["t.value -> i.a", "i.sum -> i.c"])
    plan = plan_wires(graph["nodes"], graph["connections"], catalog)
    assert plan.feedback == set()
    assert plan.non_triggering == {1}
    assert plan.loop_holds == {1}
    assert plan.triggers(0) and not plan.triggers(1)


@needs_compiler
def test_optional_unconnected_and_non_triggering(tmp_path):
    lines = build_and_run(tmp_path, {
        "t": ("t_tick", {"count": 2}),
        "k": ("constant_int", {"number": 100}),
        "i": ("t_inputs", {}),
    }, ["t.value -> i.a", "k.value -> i.c"], seconds=5)
    assert lines == [
        "in a=1 b=5 c=100 d=0 e=9 b.connected=0 b.has=0 c.connected=1",
        "in a=2 b=5 c=100 d=0 e=9 b.connected=0 b.has=0 c.connected=1",
    ]


@needs_compiler
def test_non_triggering_input_only_updates(tmp_path):
    lines = build_and_run(tmp_path, {
        "slow": ("t_tick", {"count": 3, "interval": 1}),
        "fast": ("t_tick", {"count": 3, "start": 10, "interval": 0.25}),
        "i": ("t_inputs", {"e": 0}),
    }, ["slow.value -> i.a", "fast.value -> i.c"], seconds=5)
    assert [line.split(" b=")[0] + " c=" + line.split(" c=")[1].split()[0] for line in lines] == [
        "in a=1 c=10", "in a=2 c=12", "in a=3 c=12"]


@needs_compiler
def test_connected_optional_holds_default(tmp_path):
    lines = build_and_run(tmp_path, {
        "ta": ("t_tick", {"count": 2}),
        "tb": ("t_tick", {"count": 1, "start": 50, "skip": 1}),
        "k": ("constant_int", {"number": 0}),
        "i": ("t_inputs", {}),
    }, ["ta.value -> i.a", "tb.value -> i.b", "k.value -> i.c"], seconds=5)
    assert len(lines) == 2
    assert "a=1 b=5 " in lines[0] and "b.connected=1 b.has=0" in lines[0]
    assert "a=2 b=50 " in lines[1] and "b.connected=1 b.has=1" in lines[1]


@needs_compiler
def test_non_triggering_loop_starts(tmp_path):
    lines = build_and_run(tmp_path, {
        "t": ("t_tick", {"count": 2}),
        "i": ("t_inputs", {}),
    }, ["t.value -> i.a", "i.sum -> i.c"], seconds=5)
    assert [line.split(" d=")[0] for line in lines] == ["in a=1 b=5 c=0", "in a=2 b=5 c=15"]
