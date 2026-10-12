import ast
from pathlib import Path


def test_product_runtime_contains_no_pyqt_or_sip_dependency():
    files = list(Path("src").rglob("*.py")) + [Path("homework_helper.pyw")]
    forbidden = ("PyQt6", "pyqtSignal", "pyqtSlot", "from PySide6 import sip")
    violations = []
    for path in files:
        source = path.read_text(encoding="utf-8-sig")
        for token in forbidden:
            if token in source:
                violations.append(f"{path}:{token}")
    assert violations == []


def test_pyinstaller_uses_widgets_only_and_collects_network_module():
    spec = Path("homework_helper.spec").read_text(encoding="utf-8")
    assert "HH_INCLUDE_QML" not in spec
    assert "qml_hiddenimports" not in spec
    for module in (
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
    ):
        assert module in spec
    tree = ast.parse(spec)
    excluded = [
        set(ast.literal_eval(keyword.value))
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        for keyword in node.keywords if keyword.arg == "excludes"
    ]
    assert any(
        {"PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickControls2"}.issubset(modules)
        for modules in excluded
    )
