"""통합 사이드바의 사용자 조작과 기존 실행·저장 경계를 격리 검증한다."""
import datetime
import os
import sys
import threading
from types import MethodType, SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QThread, QThreadPool, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from src.data.data_models import GlobalSettings, ManagedProcess
from src.gui.sidebar.controls import SidebarClockFace, SidebarDivider, VolumeDial
from src.gui.widgets_style import GameIconLabel
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


def test_unified_rows_keep_conditional_focus_and_fixed_action_volume_columns(sidebar, app, monkeypatch):
    from src.gui.main_window import MainWindow
    view, game, _settings, _writes = sidebar
    idle = ManagedProcess(id="idle", name="대기 게임", monitoring_path="/idle.exe", launch_path="/idle.exe")
    view._data_manager.managed_processes.append(idle)
    active = {game.id: {"pid": 42, "start_time_approx": 123.0}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    view.refresh_content()
    view.resize(280, 1040)
    view.show()
    app.processEvents()
    positions = []
    for i in range(2):
        row = view._games_list_layout.itemAt(i).widget()
        focus = row.findChild(QPushButton, "focusGame")
        action = row.findChild(QPushButton, "gameAction")
        dial = row.findChild(VolumeDial)
        running = row.property("processId") == game.id
        assert row.property("hhRunning") is running
        assert (focus is not None) is running
        assert action.geometry().right() < dial.geometry().left()
        if focus:
            assert focus.geometry().right() < action.geometry().left()
        positions.append((action.x(), dial.x()))
    assert positions[0] == positions[1]
    old_dial = current_row(view).findChild(VolumeDial)
    wheel(app, old_dial, -120)
    view.refresh_content()
    assert not old_dial._reveal_timer.isActive()


def test_focus_success_closes_sidebar_but_denial_and_removed_registration_do_not(sidebar, monkeypatch):
    view, game, _settings, _writes = sidebar
    called = []
    monkeypatch.setattr(view, "slide_out", lambda: called.append("hidden"))
    monkeypatch.setattr(module, "focus_managed_process_window", lambda *args: False)
    view._focus_process(game.id, game.monitoring_path, 42, 123.0)
    assert not called
    monkeypatch.setattr(module, "focus_managed_process_window", lambda *args: called.append(args) or True)
    view._focus_process(game.id, game.monitoring_path, 42, 123.0)
    assert called == [(42, 123.0, game.monitoring_path), "hidden"]
    view._data_manager.managed_processes.clear()
    view._focus_process(game.id, game.monitoring_path, 42, 123.0)
    assert len(called) == 2


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
    view.apply_visual_settings()
    assert view.windowOpacity() == 1.0
    dialog = SidebarSettingsDialog(settings)
    updated = dialog.get_updated_settings()
    assert not hasattr(dialog, "_opacity_spin") and not hasattr(dialog, "_clock_format_edit")
    assert (updated.sidebar_opacity, updated.sidebar_clock_format, updated.sidebar_effect) == (0.2, "legacy format", "mica")
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
    controls = row.findChildren(QPushButton) + row.findChildren(VolumeDial)
    assert controls
    for control in controls:
        # 실제 stylesheet polish가 setFixedSize의 최소 크기를 덮어쓸 수 있다.
        assert control.width() == control.height() == 32
        assert control.minimumSize().toTuple() == control.maximumSize().toTuple() == (32, 32)
    icon = row.findChild(GameIconLabel)
    assert icon.size().toTuple() == (30, 30)
    assert row.findChild(QLabel, "gameName").font().pixelSize() == 12


def test_idle_name_uses_focus_space_without_moving_right_controls(sidebar, app, monkeypatch):
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
        states.append((row.findChild(QLabel,"gameName").width(), row.findChild(QPushButton,"gameAction").x(), row.findChild(VolumeDial).x()))
    assert states[1][0] > states[0][0]
    assert states[1][1:] == states[0][1:]


def test_native_acrylic_owns_tint_and_failure_keeps_same_fixed_background(sidebar, monkeypatch):
    from src.gui.sidebar import win32_effects
    view, _game, settings, _writes = sidebar
    settings.sidebar_opacity = 0.1
    settings.sidebar_effect = "none"
    calls = []
    monkeypatch.setattr(win32_effects, "apply_blur_effect", lambda hwnd: calls.append(hwnd) or True)
    view._try_apply_blur()
    view.apply_visual_settings()
    assert len(calls) == 1 and view._blur_applied
    assert "rgba(8,12,19,0)" in view._frame.styleSheet()
    assert view.windowOpacity() == 1.0
    monkeypatch.setattr(win32_effects, "apply_blur_effect", lambda _hwnd: False)
    view._try_apply_blur()
    assert not view._blur_applied
    assert "rgba(8,12,19,153)" in view._frame.styleSheet()


def test_section_dividers_reserve_equal_space_above_and_below_line(sidebar):
    view, _game, _settings, _writes = sidebar
    dividers = view.findChildren(SidebarDivider)
    assert len(dividers) == 2
    assert [divider.height() for divider in dividers] == [14,14]


def test_qt_empty_surfaces_leave_native_backdrop_visible(sidebar, app, monkeypatch):
    from src.gui.sidebar import win32_effects
    view, _game, _settings, _writes = sidebar
    monkeypatch.setattr(win32_effects, "apply_blur_effect", lambda _hwnd: True)
    view.resize(280, 900)
    view.show()
    view._try_apply_blur()
    app.processEvents()
    image = view.grab().toImage()
    assert image.pixelColor(1, 1).alpha() == 0
    empty = view._main_scroll.viewport().mapTo(view, view._main_scroll.viewport().rect().center())
    assert image.pixelColor(empty).alpha() == 0
