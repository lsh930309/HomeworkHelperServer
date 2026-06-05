import json
import sys
from pathlib import Path

import pytest

import build
from tools import ensure_macos_local_codesign_identity
from tools import package_macos_remote_app


def _config():
    return {
        "schema": 1,
        "targets": {
            "windows-host": {"version": "1.1.9", "build": 11},
            "macos-client": {"version": "0.2.0", "build": 3},
        },
    }


def test_select_build_target_maps_host_os_to_release_target():
    assert build.select_build_target("Windows") == "windows-host"
    assert build.select_build_target("Darwin") == "macos-client"
    with pytest.raises(build.BuildConfigError):
        build.select_build_target("Linux")


def test_make_version_info_uses_git_hash_and_dirty_suffix():
    info = build.make_version_info("windows-host", _config(), git_hash="21080f2", dirty=False)

    assert info["version"] == "1.1.9"
    assert info["build"] == 11
    assert info["target"] == "windows-host"
    assert info["string"] == "v1.1.9_b11_g21080f2"

    dirty = build.make_version_info("macos-client", _config(), git_hash="abcdef0", dirty=True)
    assert dirty["string"] == "v0.2.0_b3_gabcdef0_dirty"


def test_release_filenames_use_commit_based_release_id():
    info = build.make_version_info("windows-host", _config(), git_hash="21080f2", dirty=False)

    assert build.release_filename("HomeworkHelper", info, "Portable", "zip") == (
        "HomeworkHelper_v1.1.9_b11_g21080f2_Portable.zip"
    )
    assert build.windows_installer_output_base(info) == "HomeworkHelper_v1.1.9_b11_g21080f2_Setup"
    assert build.target_release_tag(info) == "hh-windows-host-v1.1.9-b11"


def test_inno_setup_command_injects_version_without_rewriting_script():
    info = build.make_version_info("windows-host", _config(), git_hash="21080f2", dirty=False)
    command = build.create_inno_setup_command(info)

    assert "/DMyAppVersion=1.1.9" in command
    assert "/DMyAppOutputBaseFilename=HomeworkHelper_v1.1.9_b11_g21080f2_Setup" in command

    installer = Path("installer.iss").read_text(encoding="utf-8")
    assert "#ifndef MyAppVersion" in installer
    assert "OutputBaseFilename={#MyAppOutputBaseFilename}" in installer


def test_macos_pkgbuild_command_and_path_use_same_release_id():
    info = build.make_version_info("macos-client", _config(), git_hash="abcdef0", dirty=False)
    app = Path("dist/macos/HomeworkHelperRemote.app")
    pkg = build.macos_pkg_path(info)

    assert pkg.name == "HomeworkHelperRemote_v0.2.0_b3_gabcdef0.pkg"
    assert build.create_pkgbuild_command(app, pkg) == [
        "pkgbuild",
        "--component",
        str(app),
        "--install-location",
        "/Applications",
        "--scripts",
        str(build.MACOS_PKG_SCRIPTS_DIR),
        str(pkg),
    ]


def test_macos_codesign_identity_defaults_to_local_personal_identity():
    assert build.macos_codesign_identity({}) == "HomeworkHelperRemote Local Code Signing"
    assert build.macos_codesign_identity({"HH_MACOS_CODESIGN_IDENTITY": "Custom Local Identity"}) == (
        "Custom Local Identity"
    )


def test_macos_app_bundle_command_passes_codesign_identity():
    info = build.make_version_info("macos-client", _config(), git_hash="abcdef0", dirty=False)
    command = build.create_macos_app_bundle_command(
        info,
        Path("dist/macos"),
        "HomeworkHelperRemote Local Code Signing",
    )

    assert command[:3] == [sys.executable, str(build.MACOS_PACKAGE_TOOL), "--output-dir"]
    assert "--codesign-identity" in command
    assert command[command.index("--codesign-identity") + 1] == "HomeworkHelperRemote Local Code Signing"
    assert "--dirty" not in command


def test_macos_local_codesign_helper_uses_ephemeral_self_signed_identity():
    source = Path("tools/ensure_macos_local_codesign_identity.py").read_text(encoding="utf-8")

    assert ensure_macos_local_codesign_identity.DEFAULT_IDENTITY == "HomeworkHelperRemote Local Code Signing"
    assert "TemporaryDirectory" in source
    assert "extendedKeyUsage = codeSigning" in source
    assert "security" in source
    assert "add-trusted-cert" in source
    assert "certs/" not in source


def test_parallel_jobs_are_bounded_by_available_cpu():
    assert build.determine_parallel_jobs(1) == 1
    assert build.determine_parallel_jobs(4) == 4
    assert build.determine_parallel_jobs(64) == 12


def test_version_config_is_local_state_and_example_removed():
    assert not Path("build.version.example.json").exists()

    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "build.version.json" in gitignore

    config_path = Path("build.version.json")
    if not config_path.exists():
        return

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["schema"] == 1
    assert {"windows-host", "macos-client"} <= set(config["targets"])
    for payload in config["targets"].values():
        assert isinstance(payload["version"], str)
        assert isinstance(payload["build"], int)
        assert payload["build"] >= 1


def test_version_bump_policy_updates_only_candidate_config():
    config = _config()

    build_bump = build.bump_target_version_config(config, "windows-host", "build")
    assert build_bump["targets"]["windows-host"] == {"version": "1.1.9", "build": 12}
    assert config["targets"]["windows-host"] == {"version": "1.1.9", "build": 11}

    patch_bump = build.bump_target_version_config(config, "windows-host", "patch")
    assert patch_bump["targets"]["windows-host"] == {"version": "1.1.10", "build": 1}

    minor_bump = build.bump_target_version_config(config, "windows-host", "minor")
    assert minor_bump["targets"]["windows-host"] == {"version": "1.2.0", "build": 1}

    major_bump = build.bump_target_version_config(config, "windows-host", "major")
    assert major_bump["targets"]["windows-host"] == {"version": "2.0.0", "build": 1}


@pytest.mark.parametrize("target", ["windows-host", "macos-client"])
def test_gui_version_selector_is_shared_by_windows_and_macos_targets(monkeypatch, target):
    calls = []

    class FakeSelector:
        def __init__(self, target_name, current_payload, candidate_payload, _theme, font_family):
            calls.append(
                {
                    "target": target_name,
                    "current": current_payload,
                    "candidate": candidate_payload,
                    "font": font_family,
                }
            )

        def show(self):
            return {"version": "9.8.7", "build": 42}

    monkeypatch.setattr(build, "tk", object())
    monkeypatch.setattr(build, "load_custom_font", lambda: "TestFont")
    monkeypatch.setattr(build, "is_dark_mode", lambda: False)
    monkeypatch.setattr(build, "BuildVersionSelectorGUI", FakeSelector)

    candidate = build.create_candidate_version_config(target, _config(), bump="build", no_gui=False)

    assert candidate["targets"][target] == {"version": "9.8.7", "build": 42}
    assert calls == [
        {
            "target": target,
            "current": build.target_version_payload(_config(), target),
            "candidate": build.target_version_payload(
                build.bump_target_version_config(_config(), target, "build"),
                target,
            ),
            "font": "TestFont",
        }
    ]


def test_installer_shutdown_policy_uses_legacy_force_kill_flow():
    installer = Path("installer.iss").read_text(encoding="utf-8").lower()

    assert "obs" not in installer
    assert "taskkill', '/f /im homework_helper.exe'" in installer
    assert installer.count("killallappprocesses();") >= 2
    assert "trycloseappprocessesgracefully" not in installer
    assert "forcekillappprocesses" not in installer
    assert "waitforappexit" not in installer


def test_installer_removes_old_pyinstaller_onedir_payload_before_copy():
    installer = Path("installer.iss").read_text(encoding="utf-8").lower()

    assert "[installdelete]" in installer
    assert 'type: files; name: "{app}\\{#myappexename}"' in installer
    assert 'type: filesandordirs; name: "{app}\\_internal"' in installer


def test_macos_pkg_preinstall_script_stops_running_client(tmp_path):
    scripts_dir = build.prepare_macos_pkg_scripts_dir(tmp_path / "pkg-scripts")
    preinstall = scripts_dir / "preinstall"

    assert preinstall.exists()
    assert preinstall.stat().st_mode & 0o111

    script = preinstall.read_text(encoding="utf-8")
    assert "HomeworkHelperRemote" in script
    assert "/usr/bin/pkill -TERM -x" in script
    assert "/usr/bin/pkill -KILL -x" in script
    assert "exit 0" in script


class _DummyGui:
    def log(self, *_args, **_kwargs):
        return None

    def log_section(self, *_args, **_kwargs):
        return None

    def set_status(self, *_args, **_kwargs):
        return None

    def set_progress(self, *_args, **_kwargs):
        return None


def test_release_archive_moves_root_artifacts_into_target_type_buckets(tmp_path, monkeypatch):
    release_dir = tmp_path / "release"
    archives_dir = release_dir / "archives"
    release_dir.mkdir()
    monkeypatch.setattr(build, "RELEASE_DIR", release_dir)
    monkeypatch.setattr(build, "ARCHIVES_DIR", archives_dir)

    for filename in [
        "HomeworkHelper_v1.2.0_b1_gabc1234_Setup.exe",
        "HomeworkHelper_v1.2.0_b1_gabc1234_Portable.zip",
        "HomeworkHelperRemote_v0.2.0_b1_gabc1234.pkg",
    ]:
        (release_dir / filename).write_text("artifact", encoding="utf-8")
    (release_dir / "notes.txt").write_text("keep", encoding="utf-8")

    build.archive_old_files(_DummyGui(), {"target": "windows-host"}, prune_archives=False)

    archived = sorted(path.relative_to(archives_dir).as_posix() for path in archives_dir.rglob("*") if path.is_file())
    assert len(archived) == 3
    assert any(
        path.startswith("windows-host/installer/")
        and path.endswith("/HomeworkHelper_v1.2.0_b1_gabc1234_Setup.exe")
        for path in archived
    )
    assert any(
        path.startswith("windows-host/portable/")
        and path.endswith("/HomeworkHelper_v1.2.0_b1_gabc1234_Portable.zip")
        for path in archived
    )
    assert any(
        path.startswith("macos-client/pkg/")
        and path.endswith("/HomeworkHelperRemote_v0.2.0_b1_gabc1234.pkg")
        for path in archived
    )
    assert (release_dir / "notes.txt").exists()


def test_sha256_file_reports_file_digest(tmp_path):
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"homework-helper")

    assert build.sha256_file(target) == "74499229f1c63d312fa1e8e8cf93da3ab295a8f4185fbe0e410f9202a0782d12"


def test_macos_packager_plist_accepts_build_versions_and_release_metadata():
    plist = package_macos_remote_app._info_plist(
        "1.2.3",
        "45",
        release_id="v1.2.3_b45_gabcdef0_dirty",
        git_hash="abcdef0",
        dirty=True,
    )

    assert plist["CFBundleShortVersionString"] == "1.2.3"
    assert plist["CFBundleVersion"] == "45"
    assert plist["HHRemoteReleaseID"] == "v1.2.3_b45_gabcdef0_dirty"
    assert plist["HHRemoteGitHash"] == "abcdef0"
    assert plist["HHRemoteGitDirty"] is True
    assert plist["CFBundlePackageType"] == "APPL"
    assert plist["LSMinimumSystemVersion"] == "26.0"
    assert plist["NSHighResolutionCapable"] is True


def test_macos_packager_codesigns_and_verifies_bundle(monkeypatch):
    calls = []

    def fake_run(command, *, cwd):
        calls.append(command)

    def fake_run_output(command, *, cwd):
        calls.append(command)
        return 'Signature=Developer ID\nTeamIdentifier=not set\n# designated => identifier "dev.homeworkhelper.remote.macos"'

    monkeypatch.setattr(package_macos_remote_app, "_run", fake_run)
    monkeypatch.setattr(package_macos_remote_app, "_run_output", fake_run_output)

    package_macos_remote_app._codesign_app(Path("dist/macos/HomeworkHelperRemote.app"), "Local Identity")

    assert calls[0] == [
        "codesign",
        "--force",
        "--deep",
        "--options",
        "runtime",
        "--timestamp=none",
        "--sign",
        "Local Identity",
        "dist/macos/HomeworkHelperRemote.app",
    ]
    assert ["codesign", "--verify", "--deep", "--strict", "--verbose=2", "dist/macos/HomeworkHelperRemote.app"] in calls
    assert ["codesign", "--display", "--requirements", "-", "--verbose=4", "dist/macos/HomeworkHelperRemote.app"] in calls


def test_macos_packager_rejects_adhoc_codesign_identity(monkeypatch):
    monkeypatch.setattr(package_macos_remote_app, "_run", lambda command, *, cwd: None)

    def fake_run_output(command, *, cwd):
        if "--display" in command:
            return 'Signature=adhoc\n# designated => cdhash H"abcdef"'
        return ""

    monkeypatch.setattr(package_macos_remote_app, "_run_output", fake_run_output)

    with pytest.raises(RuntimeError, match="ad-hoc/cdhash-only"):
        package_macos_remote_app._codesign_app(Path("dist/macos/HomeworkHelperRemote.app"), "Local Identity")
