import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests" / "migration" / "feature_matrix.json"
INVENTORY_PATH = ROOT / "docs" / "migration-feature-inventory.md"
SMOKE_PATH = ROOT / "docs" / "migration-smoke-checklist.md"


def _matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _test_function_names() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                names.add(node.name)
    return names


def test_feature_matrix_schema_and_ids_are_stable():
    matrix = _matrix()
    allowed_status = set(matrix["status_values"])
    features = matrix["features"]
    ids = [feature["id"] for feature in features]

    assert len(features) >= 15
    assert len(ids) == len(set(ids))
    assert ids[0].startswith("APP-")

    for feature in features:
        assert re.match(r"^[A-Z]+-\d{3}$", feature["id"]), feature
        assert feature["name"]
        assert feature["pyqt_status"] in allowed_status
        assert feature["new_gui_status"] in allowed_status
        assert feature["data_risk"] in {"low", "medium", "high"}
        assert isinstance(feature["data_owned"], list)
        assert isinstance(feature["beholder_guarded"], bool)
        assert isinstance(feature["automated_tests"], list)
        assert isinstance(feature["manual_smoke"], list)
        assert feature["automated_tests"] or feature["manual_smoke"]
        if feature["data_risk"] == "high":
            assert feature["automated_tests"] or feature["manual_smoke"]


def test_feature_matrix_references_existing_tests_and_docs():
    matrix = _matrix()
    known_tests = _test_function_names()
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")
    smoke = SMOKE_PATH.read_text(encoding="utf-8")

    for feature in matrix["features"]:
        feature_id = feature["id"]
        assert feature_id in inventory
        if feature["manual_smoke"]:
            assert feature_id in smoke
        for test_name in feature["automated_tests"]:
            assert test_name in known_tests, f"{feature_id} references missing test {test_name}"


def test_inventory_summary_table_matches_feature_matrix():
    matrix_features = {feature["id"]: feature for feature in _matrix()["features"]}
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")
    rows: dict[str, dict[str, str]] = {}
    for line in inventory.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not re.match(r"^[A-Z]+-\d{3}$", cells[0]):
            continue
        rows[cells[0]] = {
            "new_gui_status": cells[3],
            "data_risk": cells[4],
        }

    assert set(rows) == set(matrix_features)
    for feature_id, feature in matrix_features.items():
        assert rows[feature_id]["new_gui_status"] == feature["new_gui_status"]
        assert rows[feature_id]["data_risk"] == feature["data_risk"]


def test_new_gui_has_no_missing_high_risk_features_before_runtime_smoke_gate():
    matrix = _matrix()
    blockers = [
        feature["id"]
        for feature in matrix["features"]
        if feature["new_gui_status"] == "missing" and feature["data_risk"] == "high"
    ]

    assert sorted(blockers) == []
