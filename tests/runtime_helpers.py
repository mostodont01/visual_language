"""Generate, build and run small graphs for the runtime tests.

Graphs are written compactly:

    nodes = {"tick": ("t_tick", {"count": 2}), "out": ("t_print", {"label": "x"})}
    wires = ["tick.value -> out.value"]
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from compiler import generate_project
from node_catalog import load_node_package

from conftest import NODES_DIR, TEST_NODES_DIR

HAVE_TOOLS = bool(shutil.which("cmake")) and bool(shutil.which("c++") or shutil.which("g++"))
needs_compiler = pytest.mark.skipif(not HAVE_TOOLS, reason="needs cmake and a C++ compiler")


def all_packages():
    packages = {}
    for folder in (NODES_DIR, TEST_NODES_DIR):
        for path in sorted(folder.glob("*.json")):
            p = load_node_package(path)
            packages[p.definition.type_id] = p
    return packages


def make_graph(nodes: dict, wires: list[str]) -> dict:
    graph = {"nodes": [], "connections": []}
    for i, (nid, (type_id, values)) in enumerate(nodes.items()):
        graph["nodes"].append({"id": nid, "type": type_id, "x": i * 250, "y": 0, "values": dict(values)})
    for w in wires:
        src, dst = (part.strip() for part in w.split("->"))
        sn, ss = src.split(".")
        tn, ts = dst.split(".")
        graph["connections"].append({"source_node": sn, "source_socket": ss,
                                     "target_node": tn, "target_socket": ts})
    return graph


def generate(graph: dict, out_dir: Path, name: str = "app", settings: dict | None = None):
    packages = all_packages()
    catalog = {k: p.definition for k, p in packages.items()}
    used = {n["type"] for n in graph["nodes"]}
    result = generate_project(graph, catalog, {k: v for k, v in packages.items() if k in used}, [],
                              {"fullscreen": False, **(settings or {})}, out_dir, name)
    assert result.ok, result.messages
    return result


def cmake_build(project_dir: Path, build_dir: Path | None = None) -> str:
    build_dir = build_dir or project_dir / "build"
    configure = ["cmake", "-S", str(project_dir), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Debug"]
    if shutil.which("ninja") and not (build_dir / "Makefile").exists():
        configure += ["-G", "Ninja"]
    log = ""
    for cmd in (configure, ["cmake", "--build", str(build_dir), "--parallel"]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        log += r.stdout + r.stderr
        assert r.returncode == 0, log[-6000:]
    return log


def run(exe: Path, seconds: float = 10, env: dict | None = None, timeout: float = 60) -> str:
    environment = dict(os.environ, VL_FAST="1", VL_STOP_AFTER=str(seconds), **(env or {}))
    r = subprocess.run([str(exe)], capture_output=True, text=True, env=environment, timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def build_and_run(tmp_path: Path, nodes: dict, wires: list[str], seconds: float = 10) -> list[str]:
    graph = make_graph(nodes, wires)
    generate(graph, tmp_path / "project")
    cmake_build(tmp_path / "project")
    return run(tmp_path / "project" / "app", seconds).splitlines()
