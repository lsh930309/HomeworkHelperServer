import ast
from pathlib import Path


def _calls_commit(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "commit":
            return True
    return False


def test_ui_and_api_routes_do_not_commit_database_directly():
    """UI/API entrypoints must delegate writes to CRUD/Beholder boundaries."""
    guarded_paths = [
        Path("src/api/dashboard/routes.py"),
        Path("src/api/beholder_routes.py"),
        *Path("src/gui").glob("*.py"),
    ]
    offenders = []
    for path in guarded_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _calls_commit(tree):
            offenders.append(str(path))

    assert offenders == []
