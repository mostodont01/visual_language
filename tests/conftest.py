"""Shared test setup: headless Qt, the repo on sys.path, and helpers."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Headless Qt, and a private config folder so tests never touch the user's
# recent-projects list (QSettings).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="vl-test-config-")

from node_catalog import load_node_definitions  # noqa: E402

NODES_DIR = ROOT / "nodes"
TEST_NODES_DIR = Path(__file__).resolve().parent / "nodes"


@pytest.fixture(scope="session")
def builtin_catalog():
    return load_node_definitions(NODES_DIR)


@pytest.fixture(scope="session")
def palette():
    return json.loads((ROOT / "palette.json").read_text(encoding="utf-8"))


@pytest.fixture
def graph(qapp, builtin_catalog):
    from graph_model import GraphModel
    return GraphModel(builtin_catalog)


@pytest.fixture
def project(qapp, graph, builtin_catalog, palette):
    from builder import Builder
    from project import Project
    return Project(graph, builtin_catalog, NODES_DIR, palette, Builder())
