"""게임 소리 정책의 GUI 진입점을 가짜 런타임·저장소로 검증한다."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QSlider

from src.core.game_audio import GameAudioObservation, GameAudioTarget
from src.core.media_center import MediaCenterRuntime, MediaCenterSnapshot, MediaOptions
from src.core.process_monitor import ProcessScanSnapshot
from src.data.data_models import GlobalSettings, ManagedProcess
from src.gui.sidebar.controls import VolumeDial
from test_gui_layout import _FakeApiClient, _patch_main_window_deps, _stop_window


class FakeRuntime:
    def __init__(self, **_kwargs):
        self.targets = []
        self.options = []
        self.commands = []
        self.stop_calls = []
        self.stop_result = True
        self.stopping = False
        self.on_change = _kwargs.get("on_change")
        self.snapshot = MediaCenterSnapshot()

    def update_targets(self, targets):
        self.targets.append(targets)

    def start(self, options):
        self.options.append(options)
        return True

    def configure(self, options):
        if self.stopping:
            return False
        self.options.append(options)
        return True

    def request(self, action, session_id, *, value=None):
        self.commands.append((action, session_id) if value is None else (action, session_id, value))
        return True

    def stop(self, **kwargs):
        self.stop_calls.append(kwargs)
        self.stopping = True
        return self.stop_result


def forbidden(*_args, **_kwargs):
    raise AssertionError("실제 오디오·Windows·미디어 접근은 허용하지 않는다")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def game():
    return ManagedProcess(id="game", name="게임", monitoring_path="/game.exe",
                          launch_path="/game.exe", default_volume=55, default_muted=False)


@pytest.fixture
def window(app, game, monkeypatch, tmp_path):
    module = _patch_main_window_deps(monkeypatch, tmp_path)
    # 기본 화면 생성은 미디어 런타임을 만들거나 native 오디오를 읽으면 실패한다.
    monkeypatch.setattr(module, "MediaCenterRuntime", forbidden)
    for name in ("get_app_volume", "is_muted", "set_app_volume", "set_mute"):
        monkeypatch.setattr(module.audio_control, name, forbidden)
    view = module.MainWindow(_FakeApiClient([game]))
    yield view, module
    _stop_window(view, app)


def activate(window, monkeypatch):
    view, module = window
    monkeypatch.setattr(module, "MediaCenterRuntime", FakeRuntime)
    monkeypatch.setattr(module, "is_windows", lambda: True)
    assert view.configure_media_center(MediaOptions())
    return view._media_center


def test_runtime_constructor_and_default_main_window_do_not_start_native_work(window):
    view, _module = window
    runtime = MediaCenterRuntime(
        backend_factory=forbidden, audio_factory=forbidden, focus_factory=forbidden,
        native_factory=forbidden, spotify_launcher=forbidden,
    )
    assert not runtime.running
    assert not runtime.request("play")
    assert view._media_center is None
    assert not view.request_media_command("play")


@pytest.mark.parametrize("windows, accepted", [(True, True), (True, False), (False, True)])
def test_only_first_successful_process_observation_attempts_start_once(window, monkeypatch, windows, accepted):
    view, module = window
    calls = []
    monkeypatch.setattr(module, "is_windows", lambda: windows)
    monkeypatch.setattr(view, "configure_media_center", lambda options: calls.append(options) or accepted)
    assert view._media_startup_pending
    # 생성·조회는 초기 프로세스 감시가 준비되기 전이므로 자동 실행 계기가 아니다.
    assert view.media_center_state() is None and calls == []
    snapshot = ProcessScanSnapshot((), 123.0)
    for _ in range(3):
        view._apply_process_scan_snapshot(snapshot)
    assert calls == ([MediaOptions()] if windows else [])
    assert view._media_startup_pending is False


def test_explicit_options_before_first_scan_are_not_overwritten_by_startup(window, monkeypatch):
    view, _module = window
    runtime = activate(window, monkeypatch)
    changed = MediaOptions(auto_bgm=False, background_mute=False, auto_focus=False)
    assert view.configure_media_center(changed)
    before = list(runtime.options)
    view._apply_process_scan_snapshot(ProcessScanSnapshot((), 123.0))
    assert runtime.options == before and runtime.options[-1] == changed


def test_failed_start_is_visible_and_not_retried_by_future_observations(window, monkeypatch):
    view, module = window
    constructed = []
    class FailedRuntime(FakeRuntime):
        def start(self, options):
            constructed.append(self)
            self.snapshot = MediaCenterSnapshot(error="격리된 미디어 준비 실패")
            return False
    monkeypatch.setattr(module, "MediaCenterRuntime", FailedRuntime)
    monkeypatch.setattr(module, "is_windows", lambda: True)
    for _ in range(3):
        view._apply_process_scan_snapshot(ProcessScanSnapshot((), 123.0))
    assert len(constructed) == 1 and view._media_center is None
    assert view.media_center_state().error == "격리된 미디어 준비 실패"
    assert not view.request_media_command("play")


@pytest.mark.parametrize("field", ["_shutting_down", "_beholder_restore_runtime_suspended"])
def test_shutdown_and_restore_reject_commands_even_while_runtime_is_present(window, monkeypatch, field):
    view, _module = window
    runtime = activate(window, monkeypatch)
    setattr(view, field, True)
    assert not view.request_media_command("play")
    assert not view.configure_media_center(MediaOptions())
    assert not runtime.commands
    setattr(view, field, False)


def test_enabled_window_publishes_runtime_identity_without_session_database_ack(window, game, monkeypatch):
    view, _module = window
    view.process_monitor.active_monitored_processes[game.id] = {
        "pid": 42, "exe": "/game.exe", "start_time_approx": 123.0,
        "session_id": None, "runtime_token": "uncommitted-runtime",
    }
    runtime = activate(window, monkeypatch)
    target = runtime.targets[-1][0]
    assert (target.process_id, target.pid, target.create_time, target.path) == (
        "game", 42, 123.0, "/game.exe"
    )
    assert (target.user_muted, target.user_volume) == (False, 55)
    game.default_volume = 60
    assert view._on_game_audio_preferences_changed(game)
    assert runtime.targets[-1][0].user_volume == 60
    assert view.request_media_command("play", "spotify-exact-session")
    assert runtime.commands == [("play", "spotify-exact-session")]


def test_sidebar_spotify_mixer_values_reach_runtime_without_game_or_settings_writes(window, monkeypatch):
    from src.core.spotify_audio import SpotifyAudioSnapshot
    from src.gui.sidebar.media_panel import MediaCenterPanel
    view, _module = window
    runtime = activate(window, monkeypatch)
    panel = MediaCenterPanel(280, on_command=view.request_media_command)
    snapshot = MediaCenterSnapshot(running=True, spotify_audio=SpotifyAudioSnapshot(37, False, True))
    panel.update_snapshot(snapshot)
    assert runtime.commands == []
    panel._volume_dial._adjust(1)
    panel._volume_dial.click()
    assert runtime.commands == [("volume", None, 42), ("mute", None, True)]
    assert panel._snapshot is snapshot
    view._shutting_down = True
    assert not view.request_media_command("volume", value=55)
    assert len(runtime.commands) == 2
    view._shutting_down = False
    panel.close()


def test_legacy_retry_cannot_unmute_after_media_activation(window, game, monkeypatch):
    view, module = window
    view.process_monitor.active_monitored_processes[game.id] = {
        "pid": 42, "exe": "/game.exe", "start_time_approx": 123.0,
    }
    calls, callbacks = [], []
    monkeypatch.setattr(module.audio_control, "set_app_volume", lambda *args: calls.append(("volume", args)) or False)
    monkeypatch.setattr(module.audio_control, "set_mute", lambda *args: calls.append(("mute", args)) or False)
    monkeypatch.setattr(module.QTimer, "singleShot", lambda _delay, callback: callbacks.append(callback))
    view._sync_default_volume_state(game, 42)
    assert callbacks and calls
    runtime = activate(window, monkeypatch)
    calls.clear()
    for callback in tuple(callbacks):
        callback()
    assert calls == []
    view._sync_default_volume_state(game, 42)
    assert calls == [] and runtime.targets[-1][0].user_muted is False


@pytest.mark.parametrize("stop_succeeds", [False, True])
def test_media_stop_result_is_required_before_restore_ack(window, monkeypatch, stop_succeeds):
    view, _module = window
    runtime = activate(window, monkeypatch)
    runtime.stop_result = stop_succeeds
    assert view.prepare_database_restore() is stop_succeeds
    assert runtime.stop_calls
    assert not view.configure_media_center(MediaOptions())
    # 다음 fixture 정상 정리를 막지 않으며 운영 런타임에는 접근하지 않는다.
    runtime.stop_result = True


def test_disabling_runtime_discards_late_snapshot_and_clears_command_owner(window, monkeypatch):
    view, _module = window
    runtime = activate(window, monkeypatch)
    view._volume_applied_pids["game"] = 42
    assert view.configure_media_center(None)
    assert runtime.stop_calls and view._media_center is None
    assert view._volume_applied_pids == {}
    assert not view.request_media_command("play")
    view._on_media_center_snapshot(SimpleNamespace(game_audio=("obsolete",)))
    assert view._media_center_snapshot is None


def test_old_runtime_callback_does_not_overwrite_new_runtime(window, monkeypatch):
    view, _module = window
    old = activate(window, monkeypatch)
    assert view.configure_media_center(None)
    current = activate(window, monkeypatch)
    fresh = SimpleNamespace(game_audio=())
    current.on_change(fresh)
    assert view._media_center_snapshot is fresh
    old.on_change(SimpleNamespace(game_audio=("obsolete",)))
    assert view._media_center_snapshot is fresh


def test_unfinished_stop_cannot_accept_options_as_if_running(window, monkeypatch):
    view, _module = window
    runtime = activate(window, monkeypatch)
    runtime.stop_result = False
    assert not view.configure_media_center(None)
    count = len(runtime.options)
    assert not view.configure_media_center(MediaOptions(auto_bgm=False))
    assert len(runtime.options) == count
    runtime.stop_result = True


def policy_observation(game):
    target = GameAudioTarget(game.id, 42, 123.0, game.monitoring_path,
                             game.default_muted, game.default_volume)
    return GameAudioObservation(target, True, .55, True, True, False)


@pytest.fixture
def sidebar(app, game, monkeypatch):
    from src.gui.main_window import MainWindow
    from src.gui.sidebar import sidebar_widget as module
    monkeypatch.setattr(MainWindow, "INSTANCE", None)
    monkeypatch.setattr(module.SidebarWidget, "_load_icon_async", lambda *_args: None)
    for name in ("get_app_volume", "is_muted", "set_app_volume", "set_mute"):
        monkeypatch.setattr(module.audio_control, name, forbidden)
    writes, intents = [], []
    data = SimpleNamespace(
        managed_processes=[game],
        global_settings=GlobalSettings(screenshot_enabled=False, obs_watch_output_dir=False),
        update_process=lambda process: writes.append(process.to_dict()) or True,
    )
    view = module.SidebarWidget(
        data, audio_state=lambda _key: (True, policy_observation(game)),
        on_audio_change=lambda process: intents.append((process.default_volume, process.default_muted)) or True,
    )
    view._get_active_pid = lambda _key: 42
    yield view, writes, intents
    assert view.cleanup(deadline_ms=1000)
    view.close()


def test_sidebar_policy_mute_is_not_saved_as_user_mute(sidebar, game):
    view, writes, intents = sidebar
    dial = view._make_volume_dial(game, 42)
    assert not dial.isChecked() and game.default_muted is False
    assert "자동 음소거" in dial.toolTip()
    dial.setValue(60)
    assert game.default_volume == 60 and game.default_muted is False
    dial.click()
    assert game.default_muted is True
    dial.click()
    assert game.default_muted is False
    timer = view._volume_save_timers[game.id]
    timer.stop()
    timer.timeout.emit()
    assert view._save_pool.waitForDone(1000)
    assert writes[-1]["default_muted"] is False and writes[-1]["default_volume"] == 60
    assert intents == [(60, False), (60, True), (60, False)]
    dial.close()


def test_volume_popover_uses_user_mute_and_shared_audio_writer(app, game, monkeypatch):
    from src.gui import volume_panel as module
    from src.utils import process as process_utils
    monkeypatch.setattr(process_utils, "get_qicon_for_file", lambda *_args, **_kwargs: None)
    for name in ("get_app_volume", "is_muted", "set_app_volume", "set_mute"):
        monkeypatch.setattr(module.audio_control, name, forbidden)
    writes, intents = [], []
    data = SimpleNamespace(update_process=lambda process: writes.append(process.to_dict()) or True)
    view = module.VolumePopoverPanel(
        data, audio_state=lambda _key: (True, policy_observation(game)),
        on_audio_change=lambda process: intents.append((process.default_volume, process.default_muted)) or True,
    )
    try:
        view.refresh([(game, 42)])
        row = view._list_layout.itemAt(0).widget()
        mute = next(button for button in row.findChildren(QPushButton) if button.isCheckable())
        slider = row.findChild(QSlider)
        assert not mute.isChecked() and "자동 음소거" in mute.toolTip()
        slider.setValue(60)
        mute.click()
        mute.click()
        assert view.cleanup(deadline_ms=1000)
        assert intents == [(60, False), (60, True), (60, False)]
        assert writes[-1]["default_muted"] is False and writes[-1]["default_volume"] == 60
    finally:
        assert view.cleanup(deadline_ms=1000)
        view.close()
