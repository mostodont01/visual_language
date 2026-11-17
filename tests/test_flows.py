"""Flows: exec sockets, the flow plan, and running start-up / event flows."""

import os
import signal
import subprocess
import time

import pytest

from compiler import GROUP_ALWAYS, GROUP_MAIN, plan_flows
from node_catalog import CatalogError, parse_node_definition
from runtime_helpers import all_packages, build_and_run, cmake_build, generate, make_graph, needs_compiler


def catalog():
    return {k: p.definition for k, p in all_packages().items()}


# -- Catalog and graph rules ---------------------------------------------------------

def test_exec_sockets_parse():
    d = catalog()["flow_branch"]
    assert d.is_flow and not d.is_flow_entry
    assert catalog()["flow_on_event"].is_flow_entry
    assert not catalog()["add"].is_flow


def test_exec_sockets_cant_have_widgets():
    raw = {"id": "x", "inputs": [{"id": "run", "type": "exec", "widget": "number"}]}
    with pytest.raises(CatalogError, match="exec"):
        parse_node_definition(raw, "t")


def test_exec_wires_one_per_output_many_per_input(qapp):
    from graph_model import GraphModel
    g = GraphModel(catalog())
    start = g.addNode("flow_on_start", 0, 0)
    a = g.addNode("flow_log", 200, 0)
    b = g.addNode("flow_log", 400, 0)
    assert g.addConnection(start, "then", a, "run")
    assert g.addConnection(a, "then", b, "run")
    assert g.addConnection(b, "then", a, "run")   # a.run has two wires now
    assert g.connectionCount == 3
    assert g.addConnection(start, "then", b, "run")  # replaces start -> a
    targets = sorted((c.source_node, c.target_node) for c in g.connections_dict.values())
    assert (start, a) not in targets and (start, b) in targets
    assert g.connectionCount == 3
    # Exec and data don't mix.
    k = g.addNode("constant_int", 0, 200)
    assert not g.addConnection(k, "value", a, "run")


def test_flow_issues(qapp):
    from graph_model import GraphModel
    g = GraphModel(catalog())
    g.addNode("flow_on_start", 0, 0)
    g.addNode("flow_on_start", 0, 100)
    lone = g.addNode("flow_wait", 0, 200)
    messages = [(i["severity"], i["nodeId"], i["message"]) for i in g.issues]
    assert any(s == "error" and "only have one On Start" in m for s, _, m in messages)
    assert any(n == lone and "No flow reaches" in m for _, n, m in messages)
    assert any("flow ends" in m for _, _, m in messages)


def test_flow_plan_groups():
    graph = make_graph({
        "start": ("flow_on_start", {}),
        "ready": ("t_signal", {}),
        "until": ("flow_wait_until", {}),
        "main": ("t_counter", {}),
        "go": ("flow_start_main", {}),
        "switch": ("t_signal", {}),
        "event": ("flow_on_event", {}),
        "stop": ("flow_stop_program", {}),
    }, ["start.then -> until.run", "ready.high -> until.condition", "until.then -> go.run",
        "switch.high -> event.trigger", "event.then -> stop.run"])
    plan = plan_flows(graph["nodes"], graph["connections"], catalog())
    assert plan.entries == ["start", "event"]
    assert plan.groups["ready"] == GROUP_MAIN | (1 << 2)
    assert plan.groups["main"] == GROUP_MAIN
    assert plan.groups["switch"] == GROUP_MAIN | GROUP_ALWAYS
    assert plan.groups["event"] == GROUP_ALWAYS
    assert ("start", 0, "until") in plan.exec_wires


def test_graph_without_flows_has_no_flow_code(tmp_path):
    generate(make_graph({"t": ("t_tick", {}), "p": ("t_print", {})}, ["t.value -> p.value"]), tmp_path / "p")
    main = (tmp_path / "p" / "generated" / "main.cpp").read_text()
    assert "Flows" not in main and "connectExec" not in main


# -- Running -----------------------------------------------------------------------------

STARTUP = {
    "start": ("flow_on_start", {}),
    "hello": ("flow_log", {"message": "startup"}),
    "ready": ("t_signal", {"on_at": 1.0}),
    "until": ("flow_wait_until", {}),
    "wait": ("flow_wait", {"seconds": 0.5}),
    "go_log": ("flow_log", {"message": "go"}),
    "go": ("flow_start_main", {}),
    "main": ("t_counter", {"label": "main", "interval": 0.5}),
}
STARTUP_WIRES = ["start.then -> hello.run", "hello.then -> until.run", "ready.high -> until.condition",
                 "until.then -> wait.run", "wait.then -> go_log.run", "go_log.then -> go.run"]


@needs_compiler
def test_start_up_flow_then_main(tmp_path):
    lines = build_and_run(tmp_path, STARTUP, STARTUP_WIRES, seconds=2.6)
    assert lines[:3] == ["startup", "go", "main 1 t=1.50"]
    assert lines[3:6] == ["main 2 t=2.00", "main 3 t=2.50", "main stop t=2.50"]


EVENTS = {
    "main": ("t_counter", {"label": "main", "interval": 1}),
    "switch": ("t_signal", {"on_at": 2.2, "off_at": 3.0}),
    "event": ("flow_on_event", {"priority": 1}),
    "log": ("flow_log", {"message": "event"}),
    "until": ("flow_wait_until", {}),
    "clear": ("flow_log", {"message": "clear"}),
    "resume": ("flow_resume_main", {}),
}
EVENT_WIRES = ["switch.high -> event.trigger", "event.then -> log.run", "log.then -> until.run",
               "switch.low -> until.condition", "until.then -> clear.run", "clear.then -> resume.run"]


@needs_compiler
def test_event_stops_main_and_resumes(tmp_path):
    lines = build_and_run(tmp_path, EVENTS, EVENT_WIRES, seconds=4.5)
    assert lines == [
        "main 1 t=0.00", "main 2 t=1.00", "main 3 t=2.00",
        "main stop t=2.20", "event", "clear",
        "main 4 t=3.00", "main 5 t=4.00",
        "main stop t=4.00",   # program end
    ]


@needs_compiler
def test_restart_runs_start_up_again(tmp_path):
    nodes = {
        "start": ("flow_on_start", {}),
        "boot": ("flow_log", {"message": "boot"}),
        "wait": ("flow_wait", {"seconds": 1}),
        "go": ("flow_start_main", {}),
        "main": ("t_counter", {"label": "main", "interval": 0.5}),
        "switch": ("t_signal", {"on_at": 1.6, "off_at": 1.8}),
        "event": ("flow_on_event", {}),
        "until": ("flow_wait_until", {}),
        "restart": ("flow_restart", {}),
    }
    wires = ["start.then -> boot.run", "boot.then -> wait.run", "wait.then -> go.run",
             "switch.high -> event.trigger", "event.then -> until.run", "switch.low -> until.condition",
             "until.then -> restart.run"]
    lines = build_and_run(tmp_path, nodes, wires, seconds=3.3)
    assert lines == [
        "boot", "main 1 t=1.00", "main 2 t=1.50", "main stop t=1.60",
        "main reset", "boot", "main 1 t=2.80", "main 2 t=3.30", "main stop t=3.30",
    ]


@needs_compiler
def test_stop_program(tmp_path):
    nodes = {
        "main": ("t_counter", {"label": "main", "interval": 1}),
        "switch": ("t_signal", {"on_at": 1.5}),
        "event": ("flow_on_event", {}),
        "bye": ("flow_log", {"message": "bye"}),
        "stop": ("flow_stop_program", {}),
    }
    wires = ["switch.high -> event.trigger", "event.then -> bye.run", "bye.then -> stop.run"]
    lines = build_and_run(tmp_path, nodes, wires, seconds=100)
    assert lines == ["main 1 t=0.00", "main 2 t=1.00", "main stop t=1.50", "bye", "main stop t=1.50"]


@needs_compiler
def test_branch_and_loop(tmp_path):
    nodes = {
        "start": ("flow_on_start", {}),
        "tick": ("flow_log", {"message": "tick"}),
        "wait": ("flow_wait", {"seconds": 0.5}),
        "branch": ("flow_branch", {}),
        "done": ("t_signal", {"on_at": 1.2}),
        "yes": ("flow_log", {"message": "done"}),
        "go": ("flow_start_main", {}),
        "main": ("t_counter", {"label": "main", "interval": 10}),
    }
    wires = ["start.then -> tick.run", "tick.then -> wait.run", "wait.then -> branch.run",
             "done.high -> branch.condition", "branch.if_true -> yes.run", "branch.if_false -> tick.run",
             "yes.then -> go.run"]
    lines = build_and_run(tmp_path, nodes, wires, seconds=2)
    assert lines == ["tick", "tick", "tick", "done", "main 1 t=1.50", "main stop t=1.50"]


@needs_compiler
def test_branch_sees_first_values(tmp_path):
    nodes = {
        "start": ("flow_on_start", {}),
        "branch": ("flow_branch", {}),
        "now": ("t_signal", {"on_at": 0}),
        "yes": ("flow_log", {"message": "yes"}),
        "no": ("flow_log", {"message": "no"}),
    }
    wires = ["start.then -> branch.run", "now.high -> branch.condition",
             "branch.if_true -> yes.run", "branch.if_false -> no.run"]
    assert build_and_run(tmp_path, nodes, wires, seconds=1) == ["yes"]


@needs_compiler
def test_priorities(tmp_path):
    nodes = {
        "main": ("t_counter", {"label": "main", "interval": 10}),
        "s1": ("t_signal", {"on_at": 1.0}),
        "e1": ("flow_on_event", {"priority": 1}),
        "l1": ("flow_log", {"message": "e1"}),
        "w1": ("flow_wait", {"seconds": 2}),
        "l1b": ("flow_log", {"message": "e1 done"}),
        "r1": ("flow_resume_main", {}),
        "s0": ("t_signal", {"on_at": 1.2}),
        "e0": ("flow_on_event", {"priority": 0}),
        "l0": ("flow_log", {"message": "e0"}),
        "s2": ("t_signal", {"on_at": 1.5}),
        "e2": ("flow_on_event", {"priority": 5}),
        "l2": ("flow_log", {"message": "e2"}),
        "r2": ("flow_resume_main", {}),
    }
    wires = ["s1.high -> e1.trigger", "e1.then -> l1.run", "l1.then -> w1.run", "w1.then -> l1b.run",
             "l1b.then -> r1.run",
             "s0.high -> e0.trigger", "e0.then -> l0.run",
             "s2.high -> e2.trigger", "e2.then -> l2.run", "l2.then -> r2.run"]
    lines = build_and_run(tmp_path, nodes, wires, seconds=5)
    assert lines == ["main 1 t=0.00", "main stop t=1.00", "e1", "e2", "main 2 t=1.50", "main stop t=1.50"]


@needs_compiler
def test_event_during_start_up_restarts_it_on_resume(tmp_path):
    nodes = dict(STARTUP, **{
        "switch": ("t_signal", {"on_at": 0.5}),
        "event": ("flow_on_event", {}),
        "log": ("flow_log", {"message": "event"}),
        "resume": ("flow_resume_main", {}),
    })
    wires = STARTUP_WIRES + ["switch.high -> event.trigger", "event.then -> log.run", "log.then -> resume.run"]
    lines = build_and_run(tmp_path, nodes, wires, seconds=2.6)
    # Interrupted at 0.5, the start-up flow starts over; LiDAR-ready (1.0) + 0.5 s -> main at 1.5.
    assert lines[:5] == ["startup", "event", "startup", "go", "main 1 t=1.50"]


@needs_compiler
def test_sigterm_calls_stop(tmp_path):
    graph = make_graph({"main": ("t_counter", {"label": "main", "interval": 0.05})}, [])
    generate(graph, tmp_path / "p")
    cmake_build(tmp_path / "p")
    env = {k: v for k, v in os.environ.items() if k not in ("VL_FAST", "VL_STOP_AFTER")}
    proc = subprocess.Popen([str(tmp_path / "p" / "app")], stdout=subprocess.PIPE, text=True, env=env)
    assert proc.stdout.readline().startswith("main 1")
    time.sleep(0.2)
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0
    assert "main stop" in out.splitlines()[-1]


@needs_compiler
def test_robocars_example(tmp_path):
    """The example from PLAN-flows-inputs-builds.md:

    On Start -> Wait Until [LiDAR ready] -> Wait Until [start place chosen] -> Wait Until [start button]
             -> Start Main
    On Event [emergency switch or battery low or motor stalled] (priority 10)
             -> Log "stopped: ..." -> Wait Until [all clear] -> Restart
    """
    nodes = {
        "start": ("flow_on_start", {}),
        "lidar": ("t_signal", {"on_at": 0.5}),
        "place": ("t_signal", {"on_at": 1.0}),
        "button": ("t_signal", {"on_at": 1.5}),
        "w_lidar": ("flow_wait_until", {}),
        "w_place": ("flow_wait_until", {}),
        "w_button": ("flow_wait_until", {}),
        "go": ("flow_start_main", {}),
        "drive": ("t_counter", {"label": "drive", "interval": 0.5}),
        "emergency": ("t_signal", {"on_at": 3.2, "off_at": 3.5}),
        "battery": ("t_signal", {"on_at": 100}),
        "stall": ("t_signal", {"on_at": 100}),
        "problem": ("t_any", {}),
        "event": ("flow_on_event", {"priority": 10}),
        "log": ("flow_log", {"message": "stopped: emergency, battery or stall"}),
        "clear": ("flow_wait_until", {}),
        "restart": ("flow_restart", {}),
    }
    wires = [
        "start.then -> w_lidar.run", "lidar.high -> w_lidar.condition",
        "w_lidar.then -> w_place.run", "place.high -> w_place.condition",
        "w_place.then -> w_button.run", "button.high -> w_button.condition",
        "w_button.then -> go.run",
        "emergency.high -> problem.a", "battery.high -> problem.b", "stall.high -> problem.c",
        "problem.any -> event.trigger", "event.then -> log.run",
        "log.then -> clear.run", "problem.none -> clear.condition", "clear.then -> restart.run",
    ]
    lines = build_and_run(tmp_path, nodes, wires, seconds=4.2)
    assert lines == [
        "drive 1 t=1.50", "drive 2 t=2.00", "drive 3 t=2.50", "drive 4 t=3.00",
        "drive stop t=3.20", "stopped: emergency, battery or stall",
        "drive reset", "drive 1 t=3.50", "drive 2 t=4.00", "drive stop t=4.00",
    ]
