"""Incremental builds: values out of the code, one file per node type, and
only changed files rewritten."""

import json
import re
import shutil
import subprocess

import pytest

from compiler import values_file_name
from runtime_helpers import cmake_build, generate, make_graph, needs_compiler, run

NODES = {
    "t": ("t_tick", {"count": 2, "start": 1}),
    "k": ("constant_int", {"number": 100}),
    "i": ("t_inputs", {}),
    "p": ("t_print", {"label": "sum"}),
}
WIRES = ["t.value -> i.a", "k.value -> i.c", "i.sum -> p.value"]

needs_ninja = pytest.mark.skipif(not shutil.which("ninja"), reason="needs ninja")


def compiled(log: str) -> list[str]:
    """The source files a Ninja build log says it compiled."""
    return sorted(re.findall(r"Building CXX object \S+?/([^/\s]+)\.o", log))


def sums(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("sum")]


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.stat().st_mtime_ns
            for p in folder.rglob("*") if p.is_file() and "build" not in p.relative_to(folder).parts}


def test_only_changed_files_are_rewritten(tmp_path):
    out = tmp_path / "project"
    generate(make_graph(NODES, WIRES), out)
    before = snapshot(out)
    nodes = dict(NODES, k=("constant_int", {"number": 5}))
    result = generate(make_graph(nodes, WIRES), out)
    after = snapshot(out)
    assert {k for k in after if after[k] != before[k]} == {"app.values.json"}
    assert "1 file changed" in result.messages[0]
    assert json.loads((out / "app.values.json").read_text())["nodes"]["k"]["settings"] == {"number": 5}


def test_unused_files_are_removed(tmp_path):
    out = tmp_path / "project"
    generate(make_graph(NODES, WIRES), out)
    assert (out / "generated" / "node_t_print.cpp").exists()
    nodes = {k: v for k, v in NODES.items() if k != "p"}
    generate(make_graph(nodes, WIRES[:2]), out)
    assert not (out / "generated" / "node_t_print.cpp").exists()
    assert not (out / "nodes" / "t_print").exists()


def test_values_file_name():
    assert values_file_name("my robot") == "my_robot.values.json"


@needs_compiler
@needs_ninja
def test_rebuilds_only_what_changed(tmp_path):
    out = tmp_path / "project"
    exe = out / "app"
    generate(make_graph(NODES, WIRES), out)
    first = compiled(cmake_build(out))
    assert "main.cpp" in first and "node_t_inputs.cpp" in first and "app.cpp" in first
    assert sums(run(exe, 5))[0] == "sum 115"   # 1 + 5 + 100 + 0 + 9

    # A value: nothing to compile, the program reads the new value.
    nodes = dict(NODES, k=("constant_int", {"number": 200}))
    generate(make_graph(nodes, WIRES), out)
    assert compiled(cmake_build(out)) == []
    assert sums(run(exe, 5))[0] == "sum 215"

    # A new wire: only main.cpp.
    nodes = dict(nodes, t2=("t_tick", {"count": 1, "start": 1000}))
    wires = WIRES + ["t2.value -> i.d"]
    generate(make_graph(nodes, wires), out)
    assert compiled(cmake_build(out)) == ["main.cpp"]
    assert "sum 1215" in sums(run(exe, 5))


@needs_compiler
@needs_ninja
def test_changed_node_code_recompiles_that_node(tmp_path, monkeypatch):
    import runtime_helpers
    from conftest import TEST_NODES_DIR
    from node_catalog import load_node_package

    out = tmp_path / "project"
    generate(make_graph(NODES, WIRES), out)
    cmake_build(out)

    # Same node, different code.
    nodes_dir = tmp_path / "nodes"
    shutil.copytree(TEST_NODES_DIR, nodes_dir)
    header = nodes_dir / "src" / "t_print.hpp"
    header.write_text(header.read_text().replace('"%s %d\\n"', '"%s = %d\\n"'))
    original = runtime_helpers.all_packages

    def patched():
        packages = original()
        packages["t_print"] = load_node_package(nodes_dir / "t_print.json")
        return packages
    monkeypatch.setattr(runtime_helpers, "all_packages", patched)
    generate(make_graph(NODES, WIRES), out)
    assert compiled(cmake_build(out)) == ["node_t_print.cpp"]
    assert sums(run(out / "app", 5))[0] == "sum = 115"


@needs_compiler
def test_values_file_is_needed_and_can_be_overridden(tmp_path):
    out = tmp_path / "project"
    generate(make_graph(NODES, WIRES), out)
    cmake_build(out)
    values = json.loads((out / "app.values.json").read_text())
    values["nodes"]["k"]["settings"]["number"] = 1
    other = tmp_path / "other.values.json"
    other.write_text(json.dumps(values))
    assert sums(run(out / "app", 5, env={"VL_VALUES": str(other)}))[0] == "sum 16"

    (out / "app.values.json").unlink()
    r = subprocess.run([str(out / "app")], capture_output=True, text=True, env={"VL_FAST": "1"})
    assert r.returncode == 1
    assert "values file" in r.stderr
