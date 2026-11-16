"""Project files, commits and branches through the Project object (no UI)."""

import json
import zipfile


def _build_graph(graph):
    a = graph.addNode("constant_int", 0, 0)
    b = graph.addNode("add", 300, 0)
    assert graph.addConnection(a, "value", b, "a")
    return a, b


def test_save_and_open(project, graph, tmp_path):
    a, b = _build_graph(graph)
    path = tmp_path / "p.vl"
    assert project.save_to(str(path), show_errors=False) is None
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read("project.json"))
    assert {n["id"] for n in data["nodes"]} == {a, b}

    project.newProject()
    assert graph.rowCount() == 0
    assert project.openProject(str(path))
    assert graph.rowCount() == 2
    assert not project.isDirty


def test_commit_branch_switch_keeps_drafts(project, graph, tmp_path):
    project.save_to(str(tmp_path / "p.vl"), show_errors=False)
    _build_graph(graph)
    project.commit_changes("two nodes", show_errors=False)
    assert project.hasCommits and not project.hasUncommittedChanges

    project.create_branch("experiment")
    graph.addNode("add", 600, 0)
    assert project.hasUncommittedChanges

    project.switch_branch("main")
    assert graph.rowCount() == 2
    project.switch_branch("experiment")
    assert graph.rowCount() == 3  # the draft came back

    # The history survives saving and reopening.
    project.save()
    project.newProject()
    assert project.openProject(str(tmp_path / "p.vl"))
    assert project.currentBranch == "experiment"
    assert {b["name"] for b in project.branches} == {"main", "experiment"}


def test_single_undo_step_rolls_back(graph):
    graph.addNode("add", 0, 0)
    try:
        with graph.single_undo_step():
            graph.addNode("add", 0, 0)
            graph.addNode("add", 0, 0)
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert graph.rowCount() == 1
    with graph.single_undo_step():
        graph.addNode("add", 0, 0)
        graph.addNode("add", 0, 0)
    assert graph.rowCount() == 3
    graph.undo()
    assert graph.rowCount() == 1
