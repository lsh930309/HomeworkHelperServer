import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_TEST_HOME = os.environ.get("HOMEWORKHELPER_TEST_HOME")
if not _TEST_HOME:
    _TEST_HOME = tempfile.mkdtemp(prefix="homeworkhelper-test-home-")
    os.environ["HOMEWORKHELPER_TEST_HOME"] = _TEST_HOME
    atexit.register(lambda: shutil.rmtree(_TEST_HOME, ignore_errors=True))
os.environ["HOME"] = _TEST_HOME
os.environ["APPDATA"] = str(Path(_TEST_HOME) / "AppData" / "Roaming")

import build
from src.api.dashboard.static_files import dashboard_static_dir


def _css_vars(style: str) -> dict[str, str]:
    values = {}
    for line in style.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        values[key] = value.rstrip(";").strip()
    return values


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


def test_main_gui_dev_server_proxies_api_for_browser_visual_checks():
    app_source = Path("src/gui/new_gui/frontend/src/App.tsx").read_text(encoding="utf-8")
    vite_config = Path("src/gui/new_gui/frontend/vite.config.ts").read_text(encoding="utf-8")

    assert "const FALLBACK_API_BASE = import.meta.env.DEV ? '' : 'http://127.0.0.1:8000'" in app_source
    assert "backend_base_url" in app_source
    assert "'/api': 'http://127.0.0.1:8000'" in vite_config


def test_new_gui_recording_settings_can_import_obs_config():
    app_source = Path("src/gui/new_gui/frontend/src/App.tsx").read_text(encoding="utf-8")

    assert "OBS 설정 불러오기" in app_source
    assert "/api/gui/recording/obs-config" in app_source
    assert "markDirty('obs_port', 'obs_exe_path', 'obs_recording_output_dir')" in app_source
    import_block = app_source.split("const importObsConfig = async () => {", 1)[1].split("const captureScreenshotKey", 1)[0]
    assert "obs_password: cfg.password" not in import_block


def test_new_gui_screenshot_settings_can_resolve_and_capture_trigger_key():
    app_source = Path("src/gui/new_gui/frontend/src/App.tsx").read_text(encoding="utf-8")

    assert "키 입력 캡처" in app_source
    assert "/api/gui/screenshot/vk/" in app_source
    assert "/api/gui/screenshot/capture-key" in app_source


def test_new_gui_beholder_restore_uses_preview_before_restore():
    app_source = Path("src/gui/new_gui/frontend/src/App.tsx").read_text(encoding="utf-8")

    assert "/api/beholder/backups/restore-preview" in app_source
    assert "복구 미리보기" in app_source
    assert "/api/beholder/backups/restore" in app_source


def test_new_gui_sends_beholder_runtime_heartbeat():
    app_source = Path("src/gui/new_gui/frontend/src/App.tsx").read_text(encoding="utf-8")

    assert "/api/beholder/runtime/heartbeat" in app_source
    assert "tauri-preview" in app_source


def test_new_gui_csp_allows_packaged_api_images_and_media():
    tauri_config = Path("src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    shell_source = Path("src-tauri/src/lib.rs").read_text(encoding="utf-8")

    assert "img-src" in tauri_config
    assert "media-src" in tauri_config
    assert "https://github.githubassets.com http://127.0.0.1:8000" in tauri_config
    assert "media-src 'self' http://127.0.0.1:8000" in tauri_config
    assert "GET /api/gui/health HTTP/1.1" in shell_source


def test_new_gui_frameless_windows_have_drag_regions_and_safe_controls():
    app_source = Path("src/gui/new_gui/frontend/src/App.tsx").read_text(encoding="utf-8")
    style_source = Path("src/gui/new_gui/frontend/src/style.css").read_text(encoding="utf-8")

    assert '<header className="topbar" data-tauri-drag-region>' in app_source
    assert '<header className="popup-head" data-tauri-drag-region>' in app_source
    assert '<header className="modal-head" data-tauri-drag-region>' in app_source
    assert 'className="actions" data-tauri-drag-region="false"' in app_source
    assert 'className="popup-actions" data-tauri-drag-region="false"' in app_source
    assert ".topbar,\n.popup-head,\n.modal-head" in style_source
    assert "cursor: grab" in style_source


def test_new_gui_main_messages_are_summarized_without_expanding_shell():
    app_source = Path("src/gui/new_gui/frontend/src/App.tsx").read_text(encoding="utf-8")
    style_source = Path("src/gui/new_gui/frontend/src/style.css").read_text(encoding="utf-8")

    assert "function MessageBanner" in app_source
    assert "실행 요청 완료" in app_source
    assert "detail: `${result.user_message}\\n대상: ${result.launch_target}`" in app_source
    assert "message-banner" in style_source
    assert "max-height: 74px" in style_source
    assert "overflow-wrap: anywhere" in style_source



def test_dashboard_style_reuses_new_gui_visual_tokens():
    dashboard_style = Path("src/api/dashboard/frontend/src/style.css").read_text(encoding="utf-8")
    main_gui_style = Path("src/gui/new_gui/frontend/src/style.css").read_text(encoding="utf-8")
    dashboard_vars = _css_vars(dashboard_style)
    main_gui_vars = _css_vars(main_gui_style)

    shared_tokens = [
        "--hh-bg",
        "--hh-panel",
        "--hh-line",
        "--hh-text",
        "--hh-muted",
        "--hh-accent",
        "--hh-accent-2",
        "--hh-button-bg",
        "--hh-button-primary",
        "--hh-button-border",
        "--hh-button-radius",
        "--hh-card-radius",
    ]
    for token in shared_tokens:
        assert dashboard_vars[token] == main_gui_vars[token]
    assert "NEXON Lv1 Gothic" in dashboard_style
    assert "var(--hh-card-radius)" in dashboard_style


def test_pyinstaller_spec_maps_dashboard_build_output_to_packaged_static_dir():
    spec = Path("homework_helper.spec").read_text(encoding="utf-8")
    assert "collect_tree('build/dashboard-static', 'src/api/dashboard/static')" in spec
    assert "'api/dashboard/frontend'" in spec
    assert "'api/dashboard/static'" in spec


def test_build_and_stage_new_gui_shell_by_default(monkeypatch, tmp_path):
    project_root = tmp_path
    tauri_dir = project_root / "src-tauri"
    shell_source = tauri_dir / "target" / "release" / "homework-helper-shell.exe"
    app_folder = project_root / "dist" / "homework_helper"
    tauri_dir.mkdir(parents=True)

    monkeypatch.setattr(build, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(build, "TAURI_DIR", tauri_dir)
    monkeypatch.setattr(build, "TAURI_SHELL_SOURCE", shell_source)
    monkeypatch.setattr(build, "APP_FOLDER", app_folder)
    monkeypatch.setattr(build.shutil, "which", lambda name: "/usr/bin/npm")

    seen_cmds = []

    def fake_run(cmd, cwd, **kwargs):
        assert cwd == project_root
        seen_cmds.append(cmd)
        if cmd[:2] == ["/usr/bin/npm", "run"]:
            assert cmd[-2:] == ["--", "--no-bundle"]
            shell_source.parent.mkdir(parents=True)
            shell_source.write_bytes(b"tauri shell")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    assert build.build_new_gui_shell(DummyGui()) is True
    assert seen_cmds[0][:2] in (["/usr/bin/npm", "ci"], ["/usr/bin/npm", "install"])
    assert seen_cmds[-1][:3] == ["/usr/bin/npm", "run", "tauri:build"]
    assert build.stage_new_gui_shell(DummyGui()) is True
    assert (app_folder / build.TAURI_SHELL_DIST_NAME).read_bytes() == b"tauri shell"
    assert app_folder / build.TAURI_SHELL_DIST_NAME in build.code_sign_targets()


def test_pyinstaller_spec_excludes_new_gui_frontend_source_tree():
    spec = Path("homework_helper.spec").read_text(encoding="utf-8")
    assert "'gui/new_gui/frontend'" in spec


def test_installer_has_new_gui_preview_shortcut_and_shutdown_guard():
    installer = Path("installer.iss").read_text(encoding="utf-8")
    assert "#define HasNewGuiShell FileExists" in installer
    assert '#define BuildGuiMode' in installer
    assert "{#MyNewGuiExeName}" in installer
    assert "taskkill', '/F /IM homework_helper_gui.exe" in installer


def test_tauri_preview_shell_has_single_instance_and_tray_runtime_hooks():
    cargo_toml = Path("src-tauri/Cargo.toml").read_text(encoding="utf-8")
    shell_source = Path("src-tauri/src/lib.rs").read_text(encoding="utf-8")

    assert "tauri-plugin-single-instance" in cargo_toml
    assert 'features = ["tray-icon"]' in cargo_toml
    assert "tauri_plugin_single_instance::init" in shell_source
    assert "TrayIconBuilder::with_id" in shell_source
    assert "WindowEvent::CloseRequested" in shell_source
    assert "api.prevent_close()" in shell_source
    assert '"quit" => app.exit(0)' in shell_source


def test_packaged_server_allows_tauri_http_origin_for_preview_shell():
    entrypoint = Path("homework_helper.pyw").read_text(encoding="utf-8")
    assert '"http://tauri.localhost"' in entrypoint
    assert '"tauri://localhost"' in entrypoint


def test_build_gui_mode_controls_user_entrypoint_and_shell_steps(monkeypatch, tmp_path):
    calls = []
    class Gui(DummyGui):
        def show_complete(self, *args, **kwargs):
            self.messages.append(("complete", args, kwargs))

    gui = Gui()
    monkeypatch.setattr(build, "archive_old_files", lambda *args: calls.append("archive") or True)
    monkeypatch.setattr(build, "clean_build_artifacts", lambda *args: calls.append("clean") or True)
    monkeypatch.setattr(build, "build_dashboard_frontend", lambda *args: calls.append("dashboard") or True)
    monkeypatch.setattr(build, "build_main_gui_frontend", lambda *args: calls.append("main_gui") or True)
    monkeypatch.setattr(build, "build_new_gui_shell", lambda *args: calls.append("tauri") or True)
    monkeypatch.setattr(build, "build_with_pyinstaller", lambda *args: calls.append("pyinstaller") or True)
    monkeypatch.setattr(build, "stage_new_gui_shell", lambda *args: calls.append("stage_tauri") or True)
    monkeypatch.setattr(build, "sign_build_artifacts", lambda *args, **kwargs: calls.append(("sign", kwargs.get("target_files"))) or True)
    monkeypatch.setattr(build, "create_zip_distribution", lambda *args: calls.append("zip") or True)
    monkeypatch.setattr(build, "create_installer", lambda *args: calls.append(("installer", args[-1] if len(args) > 2 else None)) or True)
    monkeypatch.setattr(build, "print_summary", lambda *args: calls.append("summary"))
    monkeypatch.setattr(build.subprocess, "Popen", lambda *args, **kwargs: calls.append("explorer"))

    build.run_build_process(gui, {"string": "v1.2.3.1"}, gui_mode="legacy")
    import time
    for _ in range(50):
        if "summary" in calls:
            break
        time.sleep(0.02)

    assert "main_gui" not in calls
    assert "tauri" not in calls
    assert "stage_tauri" not in calls
    assert ("installer", "legacy") in calls
