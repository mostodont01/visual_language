import io
import zipfile

import pytest

from history import HistoryError, ProjectHistory, describe_summary, summarize, validate_branch_name


def _project(nodes=(), wires=()):
    return {"nodes": [{"id": n, "type": "add", "x": 0.0, "y": 0, "values": {}} for n in nodes],
            "connections": [{"source_node": s, "source_socket": "result", "target_node": t, "target_socket": "a"}
                            for s, t in wires]}


def test_snapshot_is_stable_and_normalizes_floats():
    h = ProjectHistory()
    a = h.snapshot({"nodes": [{"x": 1.0}]}, {})
    b = h.snapshot({"nodes": [{"x": 1}]}, {})
    assert a == b
    assert h.snapshot({"nodes": [{"x": 2}]}, {}, store=False) != a


def test_commit_and_log():
    h = ProjectHistory()
    s1 = h.snapshot(_project(["a"]), {})
    c1 = h.commit(s1, "first")
    s2 = h.snapshot(_project(["a", "b"], [("a", "b")]), {})
    c2 = h.commit(s2, "second")
    log = h.log()
    assert [c["id"] for c in log] == [c2, c1]
    assert log[0]["summary"] == {"nodes": [1, 0, 0], "wires": [1, 0]}
    with pytest.raises(HistoryError):
        h.commit(s2, "again")
    with pytest.raises(HistoryError):
        h.commit(s1, "   ")


def test_branches():
    h = ProjectHistory()
    c1 = h.commit(h.snapshot(_project(["a"]), {}), "first")
    h.create_branch("test", c1)
    assert h.rename_branch("test", "pi") == "pi"
    with pytest.raises(HistoryError):
        h.create_branch("pi", None)
    with pytest.raises(HistoryError):
        h.delete_branch("main")  # current
    h.delete_branch("pi")
    assert list(h.branches) == ["main"]


def test_write_and_read_round_trip():
    h = ProjectHistory()
    packages = {"x": ('{"id": "x"}', {"src/x.hpp": b"code"})}
    c1 = h.commit(h.snapshot(_project(["a"]), packages), "first")
    h.create_branch("other", c1, draft=h.snapshot(_project(["a", "b"]), {}))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        h.write(z)
    with zipfile.ZipFile(buf) as z:
        h2 = ProjectHistory.read(z)
    assert h2.head() == c1
    project, pk = h2.load_snapshot(h2.head_snapshot())
    assert pk == packages
    assert h2.working_snapshot("other") == h.branches["other"]["draft"]


def test_summary_text():
    assert describe_summary(summarize(_project(["a"]), _project(["a", "b"], [("a", "b")]))) == "+1 node, +1 wire"
    assert describe_summary(summarize(_project(["a"]), _project(["a"]))) == "settings only"


@pytest.mark.parametrize("name", ["", " ", "/x", "x/", "a\nb", "x" * 51])
def test_bad_branch_names(name):
    with pytest.raises(HistoryError):
        validate_branch_name(name)
