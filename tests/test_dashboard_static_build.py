import os
import subprocess
import sys
import tempfile
from pathlib import Path

_TEST_HOME = tempfile.mkdtemp(prefix="homeworkhelper-test-home-")
os.environ["HOME"] = _TEST_HOME
os.environ.setdefault("APPDATA", str(Path(_TEST_HOME) / "AppData" / "Roaming"))

import build
from src.api.dashboard.static_files import dashboard_static_dir


class DummyGui:
    def __init__(self):
        self.messages = []

    def log(self, message, level=None):
        self.messages.append((message, level))

    def log_section(self, message):
        self.messages.append((message, "section"))

    def set_status(self, message):
        self.messages.append((message, "status"))

    def set_progress(self, value):
        self.messages.append((value, "progress"))


def test_dashboard_static_dir_uses_build_dir_in_development():
    path = dashboard_static_dir()
    assert path.name == "dashboard-static"
    assert path.parent.name == "build"


def test_dashboard_static_dir_uses_packaged_source_path(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert dashboard_static_dir() == tmp_path / "bundle" / "src" / "api" / "dashboard" / "static"


def test_build_dashboard_frontend_writes_only_ignored_build_dirs(monkeypatch, tmp_path):
    project_root = tmp_path
    frontend_dir = project_root / "src" / "api" / "dashboard" / "frontend"
    source_static_dir = project_root / "src" / "api" / "dashboard" / "static"
    static_build_dir = project_root / "build" / "dashboard-static"
    cache_dir = project_root / "build" / "dashboard-cache"
    frontend_dir.mkdir(parents=True)
    source_static_dir.mkdir(parents=True)
    (frontend_dir / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")
    (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")
    for stale in (source_static_dir / "dashboard.js", source_static_dir / "dashboard.css", source_static_dir / "index.html", frontend_dir / "tsconfig.tsbuildinfo"):
        stale.write_text("stale", encoding="utf-8")

    monkeypatch.setattr(build, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(build, "DASHBOARD_FRONTEND_DIR", frontend_dir)
    monkeypatch.setattr(build, "DASHBOARD_STATIC_BUILD_DIR", static_build_dir)
    monkeypatch.setattr(build, "DASHBOARD_CACHE_DIR", cache_dir)
    monkeypatch.setattr(build.shutil, "which", lambda name: "/usr/bin/npm")

    def fake_run(cmd, cwd, **kwargs):
        assert cwd == frontend_dir
        if cmd[-1] == "build":
            static_build_dir.mkdir(parents=True)
            cache_dir.mkdir(parents=True)
            (static_build_dir / "dashboard.js").write_text("createRoot('/api/analytics/')", encoding="utf-8")
            (static_build_dir / "dashboard.css").write_text("body{}", encoding="utf-8")
            (cache_dir / "tsconfig.tsbuildinfo").write_text("cache", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    assert build.build_dashboard_frontend(DummyGui()) is True
    assert (static_build_dir / "dashboard.js").exists()
    assert (static_build_dir / "dashboard.css").exists()
    assert (cache_dir / "tsconfig.tsbuildinfo").exists()
    assert not (source_static_dir / "dashboard.js").exists()
    assert not (source_static_dir / "dashboard.css").exists()
    assert not (source_static_dir / "index.html").exists()
    assert not (frontend_dir / "tsconfig.tsbuildinfo").exists()


def test_build_main_gui_frontend_writes_only_ignored_build_dirs(monkeypatch, tmp_path):
    project_root = tmp_path
    frontend_dir = project_root / "src" / "gui" / "new_gui" / "frontend"
    static_build_dir = project_root / "build" / "main-gui-static"
    cache_dir = project_root / "build" / "main-gui-cache"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")
    (frontend_dir / "tsconfig.tsbuildinfo").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(build, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(build, "MAIN_GUI_FRONTEND_DIR", frontend_dir)
    monkeypatch.setattr(build, "MAIN_GUI_STATIC_BUILD_DIR", static_build_dir)
    monkeypatch.setattr(build, "MAIN_GUI_CACHE_DIR", cache_dir)
    monkeypatch.setattr(build.shutil, "which", lambda name: "/usr/bin/npm")

    def fake_run(cmd, cwd, **kwargs):
        assert cwd == frontend_dir
        if cmd[-1] == "build":
            static_build_dir.mkdir(parents=True)
            cache_dir.mkdir(parents=True)
            (static_build_dir / "main-gui.js").write_text("fetch('/api/gui/main-state')", encoding="utf-8")
            (static_build_dir / "main-gui.css").write_text("body{}", encoding="utf-8")
            (cache_dir / "tsconfig.tsbuildinfo").write_text("cache", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    assert build.build_main_gui_frontend(DummyGui()) is True
    assert (static_build_dir / "main-gui.js").exists()
    assert (static_build_dir / "main-gui.css").exists()
    assert (cache_dir / "tsconfig.tsbuildinfo").exists()
    assert not (frontend_dir / "tsconfig.tsbuildinfo").exists()


def test_pyinstaller_spec_maps_dashboard_build_output_to_packaged_static_dir():
    spec = Path("homework_helper.spec").read_text(encoding="utf-8")
    assert "collect_tree('build/dashboard-static', 'src/api/dashboard/static')" in spec
    assert "'api/dashboard/frontend'" in spec
    assert "'api/dashboard/static'" in spec


def test_new_gui_shell_packaging_is_opt_in(monkeypatch):
    monkeypatch.delenv(build.NEW_GUI_PACKAGE_ENV, raising=False)
    monkeypatch.setattr(build.shutil, "which", lambda name: (_ for _ in ()).throw(AssertionError("npm should not be required")))

    assert build.package_new_gui_enabled() is False
    assert build.build_new_gui_shell(DummyGui()) is True


def test_build_and_stage_new_gui_shell_when_enabled(monkeypatch, tmp_path):
    project_root = tmp_path
    tauri_dir = project_root / "src-tauri"
    shell_source = tauri_dir / "target" / "release" / "homework-helper-shell.exe"
    app_folder = project_root / "dist" / "homework_helper"
    tauri_dir.mkdir(parents=True)

    monkeypatch.setenv(build.NEW_GUI_PACKAGE_ENV, "1")
    monkeypatch.setattr(build, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(build, "TAURI_DIR", tauri_dir)
    monkeypatch.setattr(build, "TAURI_SHELL_SOURCE", shell_source)
    monkeypatch.setattr(build, "APP_FOLDER", app_folder)
    monkeypatch.setattr(build.shutil, "which", lambda name: "/usr/bin/npm")

    def fake_run(cmd, cwd, **kwargs):
        assert cwd == project_root
        assert cmd[-2:] == ["--", "--no-bundle"]
        shell_source.parent.mkdir(parents=True)
        shell_source.write_bytes(b"tauri shell")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    assert build.package_new_gui_enabled() is True
    assert build.build_new_gui_shell(DummyGui()) is True
    assert build.stage_new_gui_shell(DummyGui()) is True
    assert (app_folder / build.TAURI_SHELL_DIST_NAME).read_bytes() == b"tauri shell"
    assert app_folder / build.TAURI_SHELL_DIST_NAME in build.code_sign_targets()


def test_pyinstaller_spec_excludes_new_gui_frontend_source_tree():
    spec = Path("homework_helper.spec").read_text(encoding="utf-8")
    assert "'gui/new_gui/frontend'" in spec


def test_installer_has_optional_new_gui_preview_shortcut_and_shutdown_guard():
    installer = Path("installer.iss").read_text(encoding="utf-8")
    assert "#define HasNewGuiShell FileExists" in installer
    assert "{#MyAppName} 새 GUI 미리보기" in installer
    assert "taskkill', '/F /IM homework_helper_gui.exe" in installer


def test_packaged_server_allows_tauri_http_origin_for_preview_shell():
    entrypoint = Path("homework_helper.pyw").read_text(encoding="utf-8")
    assert '"http://tauri.localhost"' in entrypoint
    assert '"tauri://localhost"' in entrypoint

