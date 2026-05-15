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
    assert info["string"] == "v1.1.9_g21080f2"

    dirty = build.make_version_info("macos-client", _config(), git_hash="abcdef0", dirty=True)
    assert dirty["string"] == "v0.2.0_gabcdef0_dirty"


def test_release_filenames_use_commit_based_release_id():
    info = build.make_version_info("windows-host", _config(), git_hash="21080f2", dirty=False)

    assert build.release_filename("HomeworkHelper", info, "Portable", "zip") == (
        "HomeworkHelper_v1.1.9_g21080f2_Portable.zip"
    )
    assert build.windows_installer_output_base(info) == "HomeworkHelper_v1.1.9_g21080f2_Setup"


def test_inno_setup_command_injects_version_without_rewriting_script():
    info = build.make_version_info("windows-host", _config(), git_hash="21080f2", dirty=False)
    command = build.create_inno_setup_command(info)

    assert "/DMyAppVersion=1.1.9" in command
    assert "/DMyAppOutputBaseFilename=HomeworkHelper_v1.1.9_g21080f2_Setup" in command

    installer = Path("installer.iss").read_text(encoding="utf-8")
    assert "#ifndef MyAppVersion" in installer
    assert "OutputBaseFilename={#MyAppOutputBaseFilename}" in installer


def test_macos_pkgbuild_command_and_path_use_same_release_id():
    info = build.make_version_info("macos-client", _config(), git_hash="abcdef0", dirty=False)
    app = Path("dist/macos/HomeworkHelperRemote.app")
    pkg = build.macos_pkg_path(info)

    assert pkg.name == "HomeworkHelperRemote_v0.2.0_gabcdef0.pkg"
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


def test_version_example_is_unified_and_local_version_file_is_ignored():
    example = json.loads(Path("build.version.example.json").read_text(encoding="utf-8"))
    assert example["schema"] == 1
    assert set(example["targets"]) == {"windows-host", "macos-client"}
    assert all({"version", "build"} <= set(payload) for payload in example["targets"].values())

    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "build.version.json" in gitignore


def test_macos_packager_plist_accepts_build_versions():
    plist = package_macos_remote_app._info_plist("1.2.3", "45")

    assert plist["CFBundleShortVersionString"] == "1.2.3"
    assert plist["CFBundleVersion"] == "45"
    assert plist["CFBundlePackageType"] == "APPL"
