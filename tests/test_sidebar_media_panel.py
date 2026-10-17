"""사용자 조작과 실제 미디어 관측을 구분하는 compact 패널 계약."""
import os
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QWidget

from src.core.media_center import MediaCenterSnapshot, MediaOptions
from src.core.media_sessions import MediaSessionInfo


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def spotify(session_id="spotify-one", *, status="paused", title="잔잔한 노래", **kwargs):
    return MediaSessionInfo(session_id, "Spotify.exe", title=title, artist="아티스트",
                            status=status, can_play=True, can_pause=True,
                            can_previous=True, can_next=True, **kwargs)


@pytest.fixture
def panel(app):
    from src.gui.sidebar.media_panel import MediaCenterPanel
    options, commands = [], []
    state = {"accepted": True}
    def on_options(value):
        options.append(value)
        return state["accepted"]
    def on_command(action, session_id=None):
        commands.append((action, session_id))
        return state["accepted"]
    view = MediaCenterPanel(280, on_options=on_options, on_command=on_command)
    yield view, options, commands, state
    view.close()
    view.deleteLater()
    app.processEvents()


def observed(view, *, status="paused", **kwargs):
    snapshot = MediaCenterSnapshot(sessions=(spotify(status=status),),
                                   bgm_session_id="spotify-one", running=True, **kwargs)
    view.update_snapshot(snapshot)
    return snapshot


def test_panel_creation_and_observation_do_not_send_playback_or_options(panel, app):
    view, options, commands, _state = panel
    assert view.objectName() == "mediaCenterPanel"
    for status in ("playing", "paused", "stopped", "playing"):
        observed(view, status=status)
        view.show()
        app.processEvents()
        view.hide()
    menu = view._options_menu()
    assert not options and not commands
    menu.close()


def test_play_and_pause_follow_observed_state_not_command_receipt(panel):
    view, _options, commands, _state = panel
    paused = observed(view)
    view._play_button.click()
    assert commands == [("play", "spotify-one")]
    assert view._snapshot is paused
    assert view._snapshot.sessions[0].status == "paused"
    observed(view, status="playing")
    view._play_button.click()
    assert commands[-1] == ("pause", "spotify-one")
    assert view._snapshot.sessions[0].status == "playing"


def test_unconnected_explicit_play_does_not_pretend_to_be_playing(panel):
    view, _options, commands, _state = panel
    view.update_snapshot(MediaCenterSnapshot(running=True))
    view._play_button.click()
    assert commands == [("play", None)]
    assert not view._snapshot.sessions
    assert not view._previous_button.isEnabled() and not view._next_button.isEnabled()


def test_command_rejection_keeps_observed_playback_and_does_not_retry(panel, app):
    view, _options, commands, state = panel
    initial = observed(view)
    state["accepted"] = False
    view._play_button.click()
    for _ in range(3):
        view.update_snapshot(initial)
        app.processEvents()
    assert commands == [("play", "spotify-one")]
    assert view._snapshot is initial


def test_background_and_focus_options_are_independent_of_auto_bgm(panel):
    view, options, commands, _state = panel
    initial = MediaOptions(auto_bgm=False, background_mute=True, auto_focus=True)
    observed(view, options=initial)
    menu = view._options_menu()
    actions = {action.objectName(): action for action in menu.actions()}
    actions["mediaBackgroundMute"].trigger()
    assert options == [replace(initial, background_mute=False)]
    observed(view, options=options[-1])
    menu = view._options_menu()
    next(action for action in menu.actions() if action.objectName() == "mediaAutoFocus").trigger()
    assert options[-1] == MediaOptions(auto_bgm=False, background_mute=False, auto_focus=False)
    view._auto_button.click()
    assert options[-1].auto_bgm is True
    assert not commands


def test_failed_auto_option_does_not_remain_visually_enabled(panel):
    view, options, _commands, state = panel
    initial = MediaOptions(auto_bgm=False)
    observed(view, options=initial)
    state["accepted"] = False
    view._auto_button.click()
    assert options == [replace(initial, auto_bgm=True)]
    assert not view._auto_button.isChecked()
    assert view._snapshot.options == initial


def test_multiple_spotify_sessions_require_explicit_selection(panel):
    view, _options, commands, _state = panel
    sessions = (spotify("one", title="첫 번째"), spotify("two", title="두 번째"))
    view.update_snapshot(MediaCenterSnapshot(sessions=sessions, running=True))
    assert not view._play_button.isEnabled()
    assert not view._previous_button.isEnabled() and not view._next_button.isEnabled()
    menu = view._options_menu()
    choices = [action for action in menu.actions() if action.data() in {"one", "two"}]
    assert len(choices) == 2
    next(action for action in choices if action.data() == "two").trigger()
    assert commands == [("select", "two")]
    assert view._snapshot.bgm_session_id is None
    view.update_snapshot(MediaCenterSnapshot(sessions=sessions, bgm_session_id="two", running=True))
    view._play_button.click()
    assert commands[-1] == ("play", "two")


def test_session_capabilities_disable_unavailable_controls(panel):
    view, _options, commands, _state = panel
    session = replace(spotify(status="playing"), can_pause=False, can_previous=False, can_next=False)
    view.update_snapshot(MediaCenterSnapshot(sessions=(session,), bgm_session_id=session.session_id, running=True))
    for button in (view._previous_button, view._play_button, view._next_button):
        assert not button.isEnabled()
        button.click()
    assert not commands


@pytest.mark.parametrize("status", ["unknown", "changing", "closed"])
def test_unconfirmed_session_status_cannot_control_playback(panel, status):
    view, _options, commands, _state = panel
    observed(view, status=status)
    for button in (view._previous_button, view._play_button, view._next_button):
        assert not button.isEnabled()
        button.click()
    assert commands == []


@pytest.mark.parametrize("sessions", [(), (spotify(),)])
def test_explicit_prepare_remains_available_after_selected_session_disappears(panel, sessions):
    view, _options, commands, _state = panel
    view.update_snapshot(MediaCenterSnapshot(
        sessions=sessions, bgm_session_id="old-spotify-session",
        error="이전 Spotify 세션을 더 이상 관측할 수 없음", running=True))
    assert not view._play_button.isEnabled()
    menu = view._options_menu()
    prepare = next(action for action in menu.actions() if action.objectName() == "mediaPrepareSpotify")
    assert prepare.isEnabled() and commands == []
    prepare.trigger()
    assert commands == [("prepare", None)]
    assert view._snapshot.bgm_session_id == "old-spotify-session"


def test_option_callback_exception_restores_selection_and_command_exception_does_not_fake_playing(panel):
    view, _options, commands, _state = panel
    initial = observed(view, options=MediaOptions(auto_bgm=False))
    def broken(*_args):
        raise RuntimeError("격리된 요청 실패")
    view._on_options = broken
    view._auto_button.click()
    assert not view._auto_button.isChecked() and view._snapshot is initial
    view._on_command = broken
    view._play_button.click()
    assert view._snapshot.sessions[0].status == "paused" and commands == []


def test_media_hold_and_runtime_failure_are_observations_not_play_triggers(panel):
    view, _options, commands, _state = panel
    observed(view, media_hold=True)
    assert view._status_label.text()
    assert view._snapshot.media_hold
    view.update_snapshot(MediaCenterSnapshot(error="미디어 연결 실패", running=False))
    assert not view._previous_button.isEnabled() and not view._next_button.isEnabled()
    assert not commands


def test_long_song_uses_bounded_single_line_slot_and_square_controls(panel, app):
    view, _options, _commands, _state = panel
    initial = MediaCenterSnapshot(sessions=(spotify(title="매우 긴 노래 제목 " * 15),),
                                   bgm_session_id="spotify-one", running=True)
    view.update_snapshot(initial)
    view.resize(256, view.sizeHint().height())
    view.show()
    app.processEvents()
    assert not view._title_label.wordWrap()
    assert view._title_label.toolTip() == initial.sessions[0].title
    for button in (view._previous_button, view._play_button, view._next_button):
        assert button.width() == button.height()
        assert button.mapTo(view, QPoint(button.width(), 0)).x() <= view.width()
    assert view._title_label.width() > 0


def test_sidebar_reads_current_snapshot_without_sending_a_command(app, monkeypatch):
    from src.gui.main_window import MainWindow
    from src.gui.sidebar import sidebar_widget as module
    monkeypatch.setattr(MainWindow, "INSTANCE", None)
    monkeypatch.setattr(module.SidebarWidget, "_load_icon_async", lambda *_args: None)
    def forbidden(*_args, **_kwargs):
        pytest.fail("조회나 표시가 재생·Windows 오디오·설정 저장을 수행했다")
    for name in ("get_app_volume", "is_muted", "set_app_volume", "set_mute"):
        monkeypatch.setattr(module.audio_control, name, forbidden)
    from src.data.data_models import GlobalSettings
    current = MediaCenterSnapshot(sessions=(spotify(),), bgm_session_id="spotify-one", running=True)
    data = SimpleNamespace(managed_processes=[], global_settings=GlobalSettings(
        screenshot_enabled=False, obs_watch_output_dir=False), update_process=forbidden)
    view = module.SidebarWidget(data, on_media_options=forbidden,
                                on_media_command=forbidden, media_state=lambda: current)
    try:
        for _ in range(2):
            view.refresh_content()
            view.slide_in()
            view._anim.setCurrentTime(view._anim.duration())
            view.slide_out()
            view._anim.setCurrentTime(view._anim.duration())
        panel = view.findChild(QWidget, "mediaCenterPanel")
        assert panel is not None and panel._snapshot is current
        assert view._main_scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    finally:
        assert view.cleanup(deadline_ms=1000)
        view.close()


def test_focus_icon_is_centered_and_includes_all_four_corners(app):
    from src.gui.sidebar.sidebar_widget import SidebarWidget
    image = SidebarWidget._action_icon(SimpleNamespace(width=lambda: 280), "focus").pixmap(32, 32).toImage()
    width, height = image.width(), image.height()
    def opaque(x0, y0, x1, y1):
        return any(image.pixelColor(x, y).alpha() > 16
                   for x in range(round(width*x0), round(width*x1))
                   for y in range(round(height*y0), round(height*y1)))
    for x0, y0, x1, y1 in ((.1,.1,.35,.35), (.65,.1,.9,.35),
                            (.1,.65,.35,.9), (.65,.65,.9,.9), (.38,.38,.62,.62)):
        assert opaque(x0,y0,x1,y1)
    assert all(image.pixelColor(x, y).alpha() == 0
               for x,y in [(0,0), (width-1,0), (0,height-1), (width-1,height-1)])
