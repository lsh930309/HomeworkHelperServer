from pathlib import Path


def test_product_runtime_contains_no_pyqt_or_sip_dependency():
    roots = [Path("src"), Path("homework_helper.pyw")]
    files = list(Path("src").rglob("*.py")) + [Path("homework_helper.pyw")]
    forbidden = ("PyQt6", "pyqtSignal", "pyqtSlot", "from PySide6 import sip")
    violations = []
    for path in files:
        source = path.read_text(encoding="utf-8-sig")
        for token in forbidden:
            if token in source:
                violations.append(f"{path}:{token}")
    assert violations == []


def test_pyinstaller_keeps_qml_candidate_opt_in_and_collects_network_module():
    spec = Path("homework_helper.spec").read_text(encoding="utf-8")
    assert "HH_INCLUDE_QML" in spec
    assert "qml_hiddenimports" in spec
    assert "qml_excludes" in spec
    for module in (
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
    ):
        assert module in spec
