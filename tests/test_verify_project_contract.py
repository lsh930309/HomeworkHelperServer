import ast
import importlib.util
from pathlib import Path


def _run_commands() -> list[list[str]]:
    tree = ast.parse(Path("tools/verify_project.py").read_text(encoding="utf-8"))
    commands: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in {"run", "run_with_env"}:
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.List):
            continue
        command: list[str] = []
        for item in node.args[1].elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                command.append(item.value)
        commands.append(command)
    return commands


def test_verify_project_builds_all_frontend_migration_surfaces():
    commands = _run_commands()

    assert ["npm", "run", "build:main-gui"] in commands
    assert ["npm", "run", "build:dashboard"] in commands


def test_verify_project_reports_migration_feature_audit(capsys):
    spec = importlib.util.spec_from_file_location("verify_project", "tools/verify_project.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.audit_migration_matrix()
    output = capsys.readouterr().out

    assert "migration feature audit" in output
    assert "high-risk-missing=0" in output
    assert "partial=" in output
