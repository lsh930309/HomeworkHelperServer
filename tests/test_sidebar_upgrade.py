"""통합 사이드바의 사용자 조작과 기존 실행·저장 경계를 격리 검증한다."""
import datetime
import os
import sys
import threading
from types import MethodType, SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QThread, QThreadPool, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from src.data.data_models import GlobalSettings, ManagedProcess
from src.gui.sidebar.controls import SidebarClockFace, SidebarDivider, VolumeDial
from src.gui.widgets_style import CapsuleProgressBar, GameIconLabel
from src.gui.sidebar import sidebar_widget as module


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def sidebar(app, monkeypatch):
    from src.gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "INSTANCE", None)
    monkeypatch.setattr(module.SidebarWidget, "_load_icon_async", lambda *_args: None)
    monkeypatch.setattr(module.audio_control, "get_app_volume", lambda _pid: None)
    monkeypatch.setattr(module.audio_control, "is_muted", lambda _pid: None)
    settings = GlobalSettings(screenshot_enabled=False, obs_watch_output_dir=False, run_as_admin=True)
    game = ManagedProcess(id="game", name="게임", monitoring_path="/game.exe", launch_path="/launcher.exe",
                          default_volume=45, launch_args_enabled=True, launch_args='--profile "alpha test"')
    writes = []
    data = SimpleNamespace(global_settings=settings, managed_processes=[game],
                           update_process=lambda p: writes.append(p.to_dict()) or True)
    view = module.SidebarWidget(data)
    view.refresh_content()
    yield view, game, settings, writes
    assert view.cleanup(deadline_ms=1000)
    view.close()


def wheel(app, dial, delta):
    point = QPointF(dial.rect().center())
    event = QWheelEvent(point, point, QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(dial, event)
    assert event.isAccepted()


def current_row(view, index=0):
    return view._games_list_layout.itemAt(index).widget()


def click_part(row, part):
    point = part.mapTo(row, part.rect().center())
    hit = row.childAt(point) or row
    QTest.mouseClick(hit, Qt.MouseButton.LeftButton, pos=hit.mapFrom(row, point))


def test_stop_icon_has_both_sides_of_the_power_ring(sidebar):
    view, _game, _settings, _writes = sidebar
    image = view._action_icon("stop").pixmap(32, 32).toImage()
    y = round(image.height() * 9 / 16)
    for start, end in ((0.05, 0.25), (0.75, 0.95)):
        assert any(image.pixelColor(x, y).alpha() > 16
                   for x in range(round(image.width() * start), round(image.width() * end)))


@pytest.mark.parametrize("running", [False, True])
def test_refresh_never_shows_a_detached_game_control_as_a_window(sidebar, app, monkeypatch, running):
    from src.gui.main_window import MainWindow
    view, game, settings, _writes = sidebar
    active = {game.id: {"pid": 42, "start_time_approx": 123.0}} if running else {}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(
        process_monitor=SimpleNamespace(active_monitored_processes=active)))
    unexpected_windows = []

    class ShowObserver(QObject):
        def eventFilter(self, widget, event):
            if (event.type() == QEvent.Type.Show and isinstance(widget, QWidget)
                    and widget.isWindow() and widget is not view):
                unexpected_windows.append((type(widget).__name__, widget.size().toTuple()))
            return False

    observer = ShowObserver()
    app.installEventFilter(observer)
    try:
        for _ in range(2):
            view.slide_in()
            view._anim.setCurrentTime(view._anim.duration())
            view.slide_out()
            view._anim.setCurrentTime(view._anim.duration())
        for enabled in (True, False, True):
            settings.sidebar_volume_section_enabled = enabled
            view.refresh_content()
    finally:
        app.removeEventFilter(observer)
    assert unexpected_windows == []


@pytest.mark.parametrize("running", [False, True])
def test_volume_heading_is_centered_over_the_actual_dial_column(sidebar, app, monkeypatch, running):
    from src.gui.main_window import MainWindow
    view, game, settings, _writes = sidebar
    active = {game.id: {"pid": 42, "start_time_approx": 123.0}} if running else {}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(
        process_monitor=SimpleNamespace(active_monitored_processes=active)))
    view.resize(view.width(), 900)
    view.show()
    for enabled in (True, False, True):
        settings.sidebar_volume_section_enabled = enabled
        view.refresh_content()
        app.processEvents()
        dial = current_row(view).findChild(VolumeDial)
        heading = view._volume_heading
        assert heading.isVisible() == dial.isVisible() == enabled
        if enabled:
            assert heading.alignment() == Qt.AlignmentFlag.AlignCenter
            assert heading.width() == dial.width()
            assert heading.mapTo(view, heading.rect().center()).x() == dial.mapTo(view, dial.rect().center()).x()


def test_dial_wheel_accumulates_notches_and_preserves_manual_mute(app):
    dial = VolumeDial(42)
    dial.setValue(45)
    values = []
    dial.valueChanged.connect(values.append)
    wheel(app, dial, 60)
    assert dial.value() == 45
    wheel(app, dial, 60)
    assert dial.value() == 50
    wheel(app, dial, -120)
    assert values == [50, 45]
    dial.setChecked(True)
    wheel(app, dial, 120)
    assert dial.value() == 50 and dial.isChecked() and dial.is_silent()
    dial.setChecked(False)
    assert dial.value() == 50 and not dial.is_silent()
    dial.close()


def test_dial_zero_icon_does_not_create_persistent_manual_mute(app):
    dial = VolumeDial(42)
    dial.setValue(5)
    wheel(app, dial, -120)
    assert dial.value() == 0 and dial.is_silent() and not dial.isChecked()
    wheel(app, dial, 120)
    assert dial.value() == 5 and not dial.is_silent()
    dial.setValue(100)
    wheel(app, dial, 120)
    assert dial.value() == 100
    dial.close()


def test_dial_reveals_value_then_returns_to_icon_and_hiding_cancels_animation(app):
    dial = VolumeDial(42)
    dial.show()
    app.processEvents()
    wheel(app, dial, -120)
    assert dial._reveal_timer.interval() == 900 and dial._reveal_timer.isActive()
    assert dial._fade.duration() == 180
    dial._fade.setCurrentTime(180)
    assert dial.textBlend == 1.0
    # 종료 시점 재예약과 실제 대기 후 복귀 경로를 같은 단발 타이머로 확인한다.
    wheel(app, dial, -120)
    assert dial._reveal_timer.isActive()
    dial._reveal_timer.timeout.emit()
    dial._fade.setCurrentTime(180)
    assert dial.textBlend == 0.0
    wheel(app, dial, -120)
    dial.hide()
    assert not dial._reveal_timer.isActive() and dial.textBlend == 0.0
    assert dial._fade.state() == dial._fade.State.Stopped
    dial.close()


def test_refresh_never_writes_audio_and_unavailable_actual_mute_uses_saved_value(sidebar, monkeypatch):
    from src.gui.main_window import MainWindow
    view, game, _settings, writes = sidebar
    game.default_muted = True
    active = {game.id: {"pid": 42, "start_time_approx": 123.0}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    audio_writes = []
    monkeypatch.setattr(module.audio_control, "set_app_volume", lambda *args: audio_writes.append(args))
    monkeypatch.setattr(module.audio_control, "set_mute", lambda *args: audio_writes.append(args))
    view.refresh_content()
    dial = current_row(view).findChild(VolumeDial)
    assert dial.value() == 45 and dial.isChecked()
    assert not writes and not audio_writes
    monkeypatch.setattr(module.audio_control, "get_app_volume", lambda _pid: 0.0)
    monkeypatch.setattr(module.audio_control, "is_muted", lambda _pid: False)
    view.refresh_content()
    dial = current_row(view).findChild(VolumeDial)
    assert dial.value() == 0 and dial.is_silent() and not dial.isChecked()
    assert game.default_volume == 45 and game.default_muted is True


def test_volume_and_mute_use_existing_runtime_and_debounced_writer(sidebar, app, monkeypatch):
    from src.gui.main_window import MainWindow
    view, game, _settings, writes = sidebar
    active = {game.id: {"pid": 42, "start_time_approx": 123.0}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    called = []
    monkeypatch.setattr(module.audio_control, "set_app_volume", lambda *args: called.append(("volume", *args)))
    monkeypatch.setattr(module.audio_control, "set_mute", lambda *args: called.append(("mute", *args)))
    view.refresh_content()
    dial = current_row(view).findChild(VolumeDial)
    wheel(app, dial, 120)
    dial.click()
    assert called == [("volume", 42, 0.5), ("mute", 42, True)]
    assert not writes
    timer = view._volume_save_timers[game.id]
    assert timer.interval() == 500
    timer.stop()
    timer.timeout.emit()
    assert view._save_pool.waitForDone(1000)
    assert len(writes) == 1 and writes[0]["default_volume"] == 50 and writes[0]["default_muted"] is True
    view.refresh_content()
    active.clear()
    view.refresh_content()
    dial = current_row(view).findChild(VolumeDial)
    assert dial.value() == 50 and dial.isChecked()


def test_unified_rows_distinguish_current_window_running_and_stopped(sidebar, app, monkeypatch):
    from src.core.game_focus import WindowsGameFocusNative
    from src.gui.main_window import MainWindow
    view, game, _settings, _writes = sidebar
    other = ManagedProcess(id="other", name="다른 게임", monitoring_path="/other.exe", launch_path="/other.exe")
    idle = ManagedProcess(id="idle", name="대기 게임", monitoring_path="/idle.exe", launch_path="/idle.exe")
    view._data_manager.managed_processes.extend((other, idle))
    active = {game.id: {"pid": 42, "start_time_approx": 123.0},
              other.id: {"pid": 43, "start_time_approx": 124.0}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    foreground = (42, 1)
    monkeypatch.setattr(WindowsGameFocusNative, "foreground", lambda self: foreground)
    created_by_pid = {42: 123.0, 43: 124.0}
    monkeypatch.setattr(module.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: created_by_pid[pid]))
    view.refresh_content()
    view.resize(280, 1040)
    view.show()
    app.processEvents()
    rows = {current_row(view, i).property("processId"): current_row(view, i) for i in range(3)}
    positions = []
    for game_id, row in rows.items():
        surface = row.findChild(QPushButton, "gameRowSurface")
        action = row.findChild(QPushButton, "gameAction")
        dial = row.findChild(VolumeDial)
        assert row.findChild(QPushButton, "focusGame") is None
        assert surface.isEnabled() is (game_id in active)
        assert (surface.cursor().shape() == Qt.CursorShape.PointingHandCursor) is (game_id in active)
        assert action.geometry().right() < dial.geometry().left()
        assert surface.geometry().right() < action.geometry().left()
        positions.append((action.x(), dial.x()))
    assert positions.count(positions[0]) == len(rows)

    game_backgrounds = []
    for pid, hwnd, focused in [(42, 1, game.id), (43, 2, other.id), (99, 3, None), (42, 4, None)]:
        foreground = (pid, hwnd)
        if hwnd == 4:
            created_by_pid[pid] += 1.0  # PID was reused before the next monitor scan.
        view._refresh_game_row_displays()
        assert [current_row(view, i) for i in range(3)] == list(rows.values())
        for game_id, row in rows.items():
            running = game_id in active
            assert row.property("hhRunning") is running
            assert row.property("hhFocused") is (game_id == focused)
            status = "현재 창" if game_id == focused else "실행 중" if running else "꺼짐"
            assert row.findChild(QLabel, "gameRunState").text() == status
        game_row = rows[game.id]
        game_backgrounds.append(game_row.grab().toImage().pixelColor(2, game_row.height() // 2))
    assert game_backgrounds[0] != game_backgrounds[1] == game_backgrounds[2] == game_backgrounds[3]

    old_dial = rows[game.id].findChild(VolumeDial)
    wheel(app, old_dial, -120)
    view.refresh_content()
    assert not old_dial._reveal_timer.isActive()


def test_game_row_click_transfers_focus_only_from_the_running_body(sidebar, app, monkeypatch):
    from src.gui.main_window import MainWindow
    view, game, _settings, _writes = sidebar
    idle = ManagedProcess(id="idle", name="대기 게임", monitoring_path="/idle.exe", launch_path="/idle.exe")
    view._data_manager.managed_processes.append(idle)
    game.last_played_timestamp = module.time.time() - 3600
    active = {game.id: {"pid": 42, "start_time_approx": 123.0}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    called = []
    controls = []
    monkeypatch.setattr(view, "slide_out", lambda: called.append("hidden"))
    monkeypatch.setattr(view, "_kill_process", lambda *args: controls.append(("stop", *args)))
    monkeypatch.setattr(view, "_launch_process", lambda *args: controls.append(("launch", *args)))
    monkeypatch.setattr(view, "_set_game_muted", lambda muted, process, pid: controls.append(("mute", muted, process.id, pid)))
    accepted = False
    monkeypatch.setattr(module, "focus_managed_process_window", lambda *args: called.append(args) or accepted)
    view.refresh_content()
    view.resize(280, 900)
    view.show()
    app.processEvents()
    running_row, idle_row = current_row(view), current_row(view, 1)

    click_part(running_row, running_row.findChild(QPushButton, "gameAction"))
    click_part(running_row, running_row.findChild(VolumeDial))
    click_part(idle_row, idle_row.findChild(QPushButton, "gameAction"))
    click_part(idle_row, idle_row.findChild(QLabel, "gameName"))
    assert controls == [("stop", game.id, game.monitoring_path, 42, 123.0),
                        ("mute", True, game.id, 42), ("launch", idle.id, idle.monitoring_path)]
    assert not called

    identity = (42, 123.0, game.monitoring_path)
    click_part(running_row, running_row.findChild(QLabel, "gameName"))
    assert called == [identity]
    accepted = True
    click_part(running_row, running_row.findChild(CapsuleProgressBar, "gameProgressBar"))
    assert called == [identity, identity, "hidden"]
    view._data_manager.managed_processes.remove(game)
    click_part(running_row, running_row.findChild(QLabel, "gameName"))
    assert called == [identity, identity, "hidden"]


def test_stopped_game_displays_zero_and_later_resource_updates_on_the_same_row(sidebar, app):
    view, game, _settings, writes = sidebar
    game.resource_tracking_enabled = True
    game.resource_provider = "fixture"
    game.resource_key = "energy"
    view.refresh_content()
    view.resize(280, 900)
    view.show()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    app.processEvents()
    row = current_row(view)
    geometry = row.geometry()
    assert row.findChild(QLabel, "gameRunState").text() == "꺼짐"

    for percent, bucket in [(None, None), (0.0, "low"), (83.4, "high"), (None, None)]:
        view._data_manager.managed_processes[0] = ManagedProcess.from_dict({**game.to_dict(), "resource_percent": percent})
        view._refresh_game_row_displays()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        app.processEvents()
        assert current_row(view) is row
        assert row.geometry() == geometry, f"resource_percent={percent}"
        gauge = row.findChild(CapsuleProgressBar, "gameProgressBar")
        label = row.findChild(QLabel, "gameProgressValue")
        assert bool(gauge and gauge.isVisible()) is (percent is not None)
        assert label.isVisible() and not label.wordWrap()
        assert label.text() == ("기록 없음" if percent is None else f"{percent:.1f}%")
        if percent is not None:
            assert 100 * gauge.value() / gauge.maximum() == pytest.approx(percent)
            assert gauge.property("hhBucket") == bucket
    assert not writes


def test_open_sidebar_tracks_another_game_start_pid_replacement_and_stop(sidebar, app, monkeypatch):
    from src.core.process_monitor import DetectedRuntimeProcess, ProcessScanSnapshot
    from src.gui.main_window import MainWindow
    from src.gui.sidebar.sidebar_controller import SidebarController

    view, game, _settings, _writes = sidebar
    other = ManagedProcess(id="other", name="다른 게임", monitoring_path="/other.exe", launch_path="/other.exe")
    view._data_manager.managed_processes.append(other)
    controller = SidebarController(view._data_manager)
    controller._sidebar = view
    active = {game.id: {"pid": 42, "start_time_approx": 123.0}}
    window = SimpleNamespace(
        data_manager=view._data_manager,
        process_monitor=SimpleNamespace(active_monitored_processes=active),
        _app_instance_id="sidebar-fixture", _sidebar_controller=controller,
        _record_status_event=lambda *_args: None, update_process_statuses_only=lambda: None,
        _check_and_toggle_game_mode=lambda: None, _publish_media_targets=lambda: None,
        _media_startup_pending=False, _persist_lifecycle_command=lambda *_args: None,
        _work_coordinator=SimpleNamespace(submit_lifecycle=lambda *_args: None),
    )
    monkeypatch.setattr(MainWindow, "INSTANCE", window)
    focus_calls = []
    monkeypatch.setattr(module, "focus_managed_process_window", lambda *args: focus_calls.append(args) or False)
    view.slide_in()
    view._anim.setCurrentTime(view._anim.duration())
    app.processEvents()
    assert view.isVisible()

    detected_game = DetectedRuntimeProcess(game.id, 42, game.monitoring_path, 123.0)
    for runtime in [(43, 124.0), (44, 125.0), None]:
        observed = (detected_game,)
        if runtime:
            pid, created = runtime
            observed += (DetectedRuntimeProcess(other.id, pid, other.monitoring_path, created),)
        MainWindow._apply_process_scan_snapshot(window, ProcessScanSnapshot(observed, 126.0))
        app.processEvents()
        assert view.isVisible() and current_row(view).property("hhRunning")
        row = current_row(view, 1)
        assert row.property("processId") == other.id
        assert row.findChild(QPushButton, "gameRowSurface").isEnabled() is (runtime is not None)
        assert row.findChild(QPushButton, "gameAction").toolTip() == ("게임 종료" if runtime else "게임 실행")
        click_part(row, row.findChild(QLabel, "gameName"))
    assert focus_calls == [(43, 124.0, other.monitoring_path), (44, 125.0, other.monitoring_path)]


def test_launch_captures_shared_target_args_and_permission_without_optimistic_monitor_update(sidebar, monkeypatch, app):
    from src.gui.main_window import MainWindow
    view, game, settings, _writes = sidebar
    game.preferred_launch_type = "direct"
    shutdown = threading.Event()
    active = {}
    window = SimpleNamespace(_shutting_down=False, _beholder_restore_runtime_suspended=False,
                             _lifecycle_shutdown_event=shutdown,
                             process_monitor=SimpleNamespace(active_monitored_processes=active))
    window._resolve_process_launch_target = MethodType(MainWindow._resolve_process_launch_target, window)
    monkeypatch.setattr(MainWindow, "INSTANCE", window)
    queued = []
    monkeypatch.setattr(module.QThreadPool, "globalInstance", lambda: SimpleNamespace(start=queued.append))
    view._launch_process(game.id, game.monitoring_path)
    assert len(queued) == 1 and not active
    game.launch_args = "changed"
    settings.run_as_admin = False
    calls = []
    class FakeLauncher:
        last_error = None
        def __init__(self, run_as_admin):
            assert run_as_admin is True
        def launch_process(self, target, **kwargs):
            assert QThread.currentThread() != app.thread()
            calls.append((target, kwargs["args"], kwargs["managed_process_id"], kwargs["launch_mode"]))
            return True
    monkeypatch.setattr(module, "Launcher", FakeLauncher)
    pool = QThreadPool()
    pool.start(queued[0])
    assert pool.waitForDone(1000)
    assert calls == [("/game.exe", '--profile "alpha test"', "game", "direct")]
    assert not active
    view._data_manager.managed_processes.clear()
    view._launch_process(game.id, game.monitoring_path)
    assert len(queued) == 1


def test_clock_blinks_only_colon_at_half_second_and_keeps_digits_stationary(app):
    face = SidebarClockFace(280)
    face.resize(256, face.height())
    face.show()
    face.set_time(datetime.datetime(2026, 10, 15, 12, 34, 56, 0))
    on = face.grab().toImage()
    face.set_time(datetime.datetime(2026, 10, 15, 12, 34, 56, 500_000))
    off = face.grab().toImage()
    changed = [(x, y) for x in range(on.width()) for y in range(on.height()) if on.pixelColor(x, y) != off.pixelColor(x, y)]
    assert changed
    # 차이는 좁은 콜론 두 점에만 존재하며 시/분/초는 이동하거나 사라지지 않는다.
    assert max(x for x, _y in changed) - min(x for x, _y in changed) < 6
    ys = sorted({y for _x, y in changed})
    assert any(b - a > 1 for a, b in zip(ys, ys[1:]))
    before = face.face_layout()
    face.set_time(datetime.datetime(2026, 10, 15, 11, 11, 11))
    after = face.face_layout()
    assert before[5:10] == after[5:10]
    face.close()


def test_fixed_visual_policy_ignores_legacy_opacity_and_preserves_saved_columns(sidebar, monkeypatch):
    monkeypatch.setitem(sys.modules, "src.screenshot.key_capture",
                        SimpleNamespace(vk_to_display_name=lambda vk: f"VK 0x{vk:02X}"))
    from src.gui.sidebar_settings_dialog import SidebarSettingsDialog
    view, _game, settings, _writes = sidebar
    settings.sidebar_opacity = 0.2
    settings.sidebar_clock_format = "legacy format"
    settings.sidebar_effect = "mica"
    settings.sidebar_playtime_enabled = False
    settings.sidebar_playtime_prefix = "기존 접두어"
    view.apply_visual_settings()
    assert view.windowOpacity() == 1.0
    dialog = SidebarSettingsDialog(settings)
    updated = dialog.get_updated_settings()
    assert not hasattr(dialog, "_opacity_spin") and not hasattr(dialog, "_clock_format_edit")
    assert (updated.sidebar_opacity, updated.sidebar_clock_format, updated.sidebar_effect) == (0.2, "legacy format", "mica")
    assert not any("플레이 시간" in label.text() for label in dialog.findChildren(QLabel))
    assert not hasattr(dialog, "_playtime_enabled_cb") and not hasattr(dialog, "_playtime_prefix_edit")
    assert not updated.sidebar_playtime_enabled and updated.sidebar_playtime_prefix == "기존 접두어"
    dialog.close()


def test_late_icon_for_previous_registration_path_does_not_replace_current_game(sidebar):
    view, game, _settings, _writes = sidebar
    old_path = game.monitoring_path
    game.monitoring_path = "/new-game.exe"
    view.refresh_content()
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    label = current_row(view).findChild(QLabel, "gameIcon")
    view._apply_game_icon(game.id, old_path, image)
    assert label.pixmap().isNull()
    view._apply_game_icon(game.id, game.monitoring_path, image)
    assert not label.pixmap().isNull()


@pytest.mark.parametrize("running", [False, True])
def test_styled_row_keeps_action_and_volume_outer_sizes_square(sidebar, app, monkeypatch, running):
    from src.gui.main_window import MainWindow
    view, game, _settings, _writes = sidebar
    active = {game.id: {"pid":42, "start_time_approx":123.0}} if running else {}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    view.refresh_content()
    view.resize(280, 900)
    view.show()
    app.processEvents()
    row = current_row(view)
    controls = [row.findChild(QPushButton, "gameAction"), row.findChild(VolumeDial)]
    for control in controls:
        # 실제 stylesheet polish가 setFixedSize의 최소 크기를 덮어쓸 수 있다.
        assert control.width() == control.height() == 32
        assert control.minimumSize().toTuple() == control.maximumSize().toTuple() == (32, 32)
    icon = row.findChild(GameIconLabel)
    assert icon.size().toTuple() == (30, 30)
    assert row.findChild(QLabel, "gameName").font().pixelSize() == 12


def test_game_body_width_and_right_controls_stay_aligned_when_game_stops(sidebar, app, monkeypatch):
    from src.gui.main_window import MainWindow
    view, game, _settings, _writes = sidebar
    active = {game.id: {"pid":42, "start_time_approx":123.0}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    view.resize(280, 900)
    view.show()
    states = []
    for running in [True, False]:
        if not running:
            active.clear()
        view.refresh_content()
        app.processEvents()
        row = current_row(view)
        states.append((row.findChild(QPushButton, "gameRowSurface").width(),
                       row.findChild(QPushButton, "gameAction").x(), row.findChild(VolumeDial).x()))
    assert states[1] == states[0]


def test_native_acrylic_owns_tint_while_qt_keeps_input_surface_and_failure_background(sidebar, monkeypatch):
    from src.gui.sidebar import win32_effects
    view, _game, settings, _writes = sidebar
    settings.sidebar_opacity = 0.1
    settings.sidebar_effect = "none"
    calls = []
    monkeypatch.setattr(win32_effects, "apply_blur_effect", lambda hwnd: calls.append(hwnd) or True)
    view.resize(280, 900)
    view.show()
    view._try_apply_blur()
    view.apply_visual_settings()
    assert len(calls) == 1 and view._blur_applied
    assert view.windowOpacity() == 1.0
    monkeypatch.setattr(win32_effects, "apply_blur_effect", lambda _hwnd: False)
    view._try_apply_blur()
    assert not view._blur_applied
    assert view.grab().toImage().pixelColor(1, 1).alpha() == 153


def test_section_dividers_reserve_equal_space_above_and_below_line(sidebar):
    view, _game, _settings, _writes = sidebar
    dividers = view.findChildren(SidebarDivider)
    assert len(dividers) == 3
    assert [divider.height() for divider in dividers] == [14,14,14]


def test_open_acrylic_sidebar_empty_surfaces_render_a_nonzero_input_alpha(sidebar, app, monkeypatch):
    from src.gui.sidebar import win32_effects
    view, _game, _settings, _writes = sidebar
    monkeypatch.setattr(win32_effects, "apply_blur_effect", lambda _hwnd: True)
    view.resize(280, 900)
    view.show()
    view._try_apply_blur()
    app.processEvents()
    image = view.grab().toImage()
    assert image.pixelColor(1, 1).alpha() == 1
    empty = view._main_scroll.viewport().mapTo(view, view._main_scroll.viewport().rect().center())
    assert image.pixelColor(empty).alpha() == 1


def test_short_sidebar_fits_seven_games_two_gauges_and_gallery_then_restores(sidebar, app, monkeypatch, tmp_path):
    """Windows 760 높이에서 관측된 7게임·2실행 레이아웃을 게이지와 함께 확인한다."""
    from src.gui.main_window import MainWindow
    view, _game, settings, writes = sidebar
    names = ["명조: 위더링 웨이브", "몬길: STAR DIVE", "붕괴: 스타레일",
             "붕괴: 스타레일(베타)", "소녀전선2: 망명", "승리의 여신: 니케", "젠레스 존 제로"]
    games = [ManagedProcess(id=str(index), name=name, monitoring_path=f"/{index}.exe", launch_path=f"/{index}.exe")
             for index, name in enumerate(names)]
    for game in games[-2:]:
        game.last_played_timestamp = module.time.time() - 3600
    view._data_manager.managed_processes = games
    settings.screenshot_enabled = settings.recording_enabled = settings.obs_watch_output_dir = True
    settings.screenshot_save_dir = str(tmp_path)
    view._recording_output_dir = str(tmp_path)
    for index in range(8):
        (tmp_path / f"image-{index}.png").write_bytes(b"fixture; decoding is disabled")
    monkeypatch.setattr(view._thumb_pool, "start", lambda *_args: None)
    monkeypatch.setattr(view._rec_thumb_pool, "start", lambda *_args: None)
    active = {game.id: {"pid": 10 + index, "start_time_approx": module.time.time() - 600}
              for index, game in enumerate(games) if index >= 5}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(
        process_monitor=SimpleNamespace(active_monitored_processes=active)))
    view.refresh_content()
    view.resize(280, 760)
    view.show()
    for _ in range(6):
        app.processEvents()
    assert view._compact_game_rows
    assert view._main_scroll.verticalScrollBar().maximum() == 0
    assert view._gallery.height() == view._gallery_cell_size()[1]
    assert view._gallery.mapTo(view, QPoint(0, view._gallery.height())).y() <= view._close_btn.y()
    assert sum(gauge.isVisible() for gauge in view.findChildren(CapsuleProgressBar)) == 2
    for index in range(len(games)):
        row = current_row(view, index)
        label = row.findChild(QLabel, "gameName")
        assert not label.wordWrap() and label.toolTip() == games[index].name
        for control in (row.findChild(QPushButton, "gameAction"), row.findChild(VolumeDial)):
            assert control.width() == control.height() == 32
    # 폰트·DPI에 따른 내용 높이 차이는 실제 남는 여백 예산으로 흡수한다.
    # 현재 내용에 행별 위아래 1px만 허용하는 높이를 만들고 갤러리 노출을 확인한다.
    row_padding = sum(current_row(view, index).layout().contentsMargins().top()
                      + current_row(view, index).layout().contentsMargins().bottom()
                      for index in range(len(games)))
    controls_height = view._media_section.sizeHint().height() - view._gallery.height()
    content_height = view._top_section.height() - row_padding
    required_viewport = content_height + len(games) * 2 + controls_height + view._gallery_cell_size()[1]
    view.resize(280, view.height() - view._main_scroll.viewport().height() + required_viewport)
    for _ in range(6):
        app.processEvents()
    assert view._main_scroll.verticalScrollBar().maximum() == 0
    assert all(current_row(view, index).layout().contentsMargins().top() <= 1 for index in range(len(games)))
    assert view._gallery.mapTo(view, QPoint(0, view._gallery.height())).y() <= view._close_btn.y()
    view.resize(280, 1080)
    for _ in range(6):
        app.processEvents()
    assert not view._compact_game_rows
    assert view._main_scroll.verticalScrollBar().maximum() == 0
    assert view._gallery.height() == 2 * view._gallery_cell_size()[1] + view._gallery_cell_size()[2]
    assert sum(gauge.isVisible() for gauge in view.findChildren(CapsuleProgressBar)) == 2
    view.resize(280, 760)
    for _ in range(6):
        app.processEvents()
    assert view._compact_game_rows and view._main_scroll.verticalScrollBar().maximum() == 0
    assert not writes
