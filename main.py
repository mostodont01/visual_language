import json
import sys
from pathlib import Path

from PySide6.QtCore import QLoggingCategory, QUrl
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from builder import Builder
from graph_model import GraphModel
from node_catalog import CatalogError, load_node_definitions
from project import Project

# The packaged VL (PyInstaller) unpacks its files into sys._MEIPASS.
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def main() -> int:
    # Qt's Wayland text-input plugin logs a harmless warning every time a text
    # field loses focus. Silence just that category so real output stays readable.
    # (QT_LOGGING_RULES in the environment still overrides this.)
    QLoggingCategory.setFilterRules("qt.qpa.wayland.textinput=false")

    # Fusion is Qt's default on Linux; pin it so VL looks the same on Windows.
    QQuickStyle.setStyle("Fusion")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("VL")
    app.setOrganizationName("VL")
    app.setWindowIcon(QIcon(str(APP_DIR / "packaging" / "vl.png")))
    # Lets Linux desktops match the window to vl.desktop (and its icon).
    app.setDesktopFileName("vl")

    try:
        builtin_nodes = load_node_definitions(APP_DIR / "nodes")
    except CatalogError as e:
        print(f"Failed to load node definitions: {e}", file=sys.stderr)
        return 1

    try:
        default_palette = json.loads((APP_DIR / "palette.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Failed to load palette.json: {e}", file=sys.stderr)
        return 1

    graph_model = GraphModel(builtin_nodes)
    builder = Builder()
    project = Project(graph_model, builtin_nodes, APP_DIR / "nodes", default_palette, builder)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("graphModel", graph_model)
    engine.rootContext().setContextProperty("project", project)
    engine.rootContext().setContextProperty("builder", builder)
    # "monospace" only exists on Linux; ask the system for its fixed-width font.
    engine.rootContext().setContextProperty(
        "monoFont", QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())
    engine.load(QUrl.fromLocalFile(str((APP_DIR / "ui" / "Main.qml").resolve())))

    if not engine.rootObjects():
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
