"""Loads the whole QML UI headless and checks it has no errors."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from conftest import ROOT


def test_main_qml_loads(qtbot, graph, project):
    from builder import Builder
    from mcp_server import McpServer
    from vl_tools import VlTools

    QQuickStyle.setStyle("Fusion")
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    builder = Builder()
    tools = VlTools(graph, project, builder, lambda: None)
    ctx = engine.rootContext()
    ctx.setContextProperty("graphModel", graph)
    ctx.setContextProperty("project", project)
    ctx.setContextProperty("builder", builder)
    server = McpServer(tools, "test")  # kept alive: QML only holds a weak reference
    ctx.setContextProperty("mcpServer", server)
    ctx.setContextProperty("mcpTools", tools)
    ctx.setContextProperty("monoFont", QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())

    # A small graph, so nodes, sockets and wires get drawn too.
    a = graph.addNode("constant_int", 0, 0)
    b = graph.addNode("add", 300, 0)
    graph.addConnection(a, "value", b, "a")

    engine.load(QUrl.fromLocalFile(str(ROOT / "ui" / "Main.qml")))
    assert engine.rootObjects(), warnings
    qtbot.wait(200)
    assert not [w for w in warnings if "TypeError" in w or "ReferenceError" in w or "Error" in w], warnings
    warnings.clear()
    # Tear down while the context objects are still alive.
    del engine
