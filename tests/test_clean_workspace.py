from pathlib import Path

from tools.clean_workspace import clean_workspace, collect_cleanup_targets


def test_clean_workspace_removes_generated_artifacts_but_preserves_fixtures_and_dependencies(tmp_path: Path):
    generated_dir = tmp_path / "build"
    generated_dir.mkdir()
    (generated_dir / "bundle.js").write_text("generated", encoding="utf-8")
    pycache = tmp_path / "src" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "module.cpython-314.pyc").write_bytes(b"pyc")
    local_artifacts = tmp_path / "local-artifacts"
    local_artifacts.mkdir()
    (local_artifacts / "screenshot.png").write_bytes(b"png")
    preserved_zip = tmp_path / "HomeworkHelper.zip"
    preserved_zip.write_bytes(b"fixture")
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.txt").write_text("dependency", encoding="utf-8")

    dry_run_targets = clean_workspace(tmp_path, dry_run=True)
    assert generated_dir.exists()
    assert any(target.path == generated_dir for target in dry_run_targets)

    removed = clean_workspace(tmp_path)

    assert generated_dir in {target.path for target in removed}
    assert not generated_dir.exists()
    assert not pycache.exists()
    assert not local_artifacts.exists()
    assert preserved_zip.exists()
    assert node_modules.exists()


def test_collect_cleanup_targets_ignores_git_and_preserved_directories(tmp_path: Path):
    git_cache = tmp_path / ".git" / "objects" / "__pycache__"
    git_cache.mkdir(parents=True)
    preserved_cache = tmp_path / ".venv" / "__pycache__"
    preserved_cache.mkdir(parents=True)
    target_cache = tmp_path / "tests" / "__pycache__"
    target_cache.mkdir(parents=True)

    targets = collect_cleanup_targets(tmp_path)

    assert target_cache in {target.path for target in targets}
    assert git_cache not in {target.path for target in targets}
    assert preserved_cache not in {target.path for target in targets}
