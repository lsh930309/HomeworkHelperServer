"""Repository audit evidence against disposable files; no real tokens or host state."""
import csv
import json
from pathlib import Path
import subprocess

from tools import repository_audit as audit


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_every_file_load_is_timed_without_changing_contents_or_leaking_secrets(tmp_path):
    root = repo(tmp_path)
    private = root / "local-artifacts/token"
    private.parent.mkdir()
    private.write_text("private-fixture-value")
    source = root / "module.py"
    source.write_text("raise RuntimeError('must not execute')\n")
    subprocess.run(["git", "add", "module.py"], cwd=root, check=True)
    before = {p: p.read_bytes() for p in (private, source)}
    output = root / "artifacts/audit-run"
    summary = audit.audit(root, output)
    rows = list(csv.DictReader((output / "file-load-timetable.csv").open(encoding="utf-8-sig")))
    targets = {row["path"]: row for row in rows}
    assert targets["local-artifacts/token"]["loaded_bytes"] == str(len(before[private]))
    for row in targets.values():
        assert row["load_start_kst"] <= row["load_end_kst"]
        assert row["load_start_kst"].endswith("+09:00")
    assert targets["module.py"]["review_result"] == "parsed_not_executed"
    assert summary["read_errors"] == []
    assert all(p.read_bytes() == before[p] for p in before)
    assert not any("private-fixture-value" in p.read_text(encoding="utf-8-sig") for p in output.iterdir())
    assert not any(row["path"].startswith("artifacts/audit-run/") for row in rows)


def test_artifact_suffix_never_means_reusable_or_approved_for_preservation():
    for name in ("stdout.bin", "Payload/App", "contact.png", "old.json", "Scripts/preinstall"):
        assert audit.category(Path("artifacts") / name, False) == "work_artifact"
    assert audit.category(Path("tests/.pytest_cache/README.md"), False) == "generated_build_or_cache"
    assert audit.category(Path("build.version.json"), False) == "local_build_state"


def test_external_file_and_directory_links_are_recorded_without_loading_target(tmp_path):
    root = repo(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.txt").write_text("outside-secret")
    (root / "linked-dir").symlink_to(external, target_is_directory=True)
    (root / "linked-file").symlink_to(external / "secret.txt")
    output = tmp_path / "report"
    audit.audit(root, output)
    events = list(csv.DictReader((output / "file-load-timetable.csv").open(encoding="utf-8-sig")))
    links = [row for row in events if row["path"].startswith("linked-")]
    assert len(links) == 2
    assert all(row["load_result"] == "link_metadata_only" for row in links)
    assert not any("linked-dir/" in row["path"] for row in events)
    assert not any("outside-secret" in p.read_text() for p in output.iterdir())


def test_missing_file_records_read_failure_instead_of_fabricating_a_load(tmp_path):
    row, data = audit.read_file(tmp_path / "missing")
    assert row["load_result"] == "FileNotFoundError"
    assert row["loaded_bytes"] == 0 and data == b""
    assert row["load_start_kst"] <= row["load_end_kst"]


def test_python_structure_describes_writes_without_executing_or_dumping_literals():
    result = audit.source_structure(Path("sample.py"), b"import src.data.crud\npath.write_text('sensitive-data')\n")
    assert result["imports"] == ["src.data.crud"]
    assert result["write_or_execution_calls"] == [{"line": 2, "operation": "write_text"}]
    assert "sensitive-data" not in json.dumps(result)
