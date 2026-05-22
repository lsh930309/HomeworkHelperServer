import json
from pathlib import Path

import pytest

import build
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
        str(pkg),
    ]


def test_parallel_jobs_are_bounded_by_available_cpu():
    assert build.determine_parallel_jobs(1) == 1
    assert build.determine_parallel_jobs(4) == 4
    assert build.determine_parallel_jobs(64) == 12


def test_version_config_is_tracked_source_of_truth_and_example_removed():
    config = json.loads(Path("build.version.json").read_text(encoding="utf-8"))
    assert config == {
        "schema": 1,
        "targets": {
            "windows-host": {"version": "1.2.0", "build": 1},
            "macos-client": {"version": "0.2.0", "build": 1},
        },
    }
    assert not Path("build.version.example.json").exists()

    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "build.version.json" not in gitignore


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


def test_installer_shutdown_policy_never_targets_obs_and_keeps_force_as_fallback():
    installer = Path("installer.iss").read_text(encoding="utf-8").lower()

    assert "/im obs64.exe" not in installer
    assert "/im obs.exe" not in installer
    assert "taskkill', '/im homework_helper.exe'" in installer
    assert "taskkill', '/f /im homework_helper.exe'" in installer
    assert "trycloseappprocessesgracefully" in installer
    assert "forcekillappprocesses" in installer


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
