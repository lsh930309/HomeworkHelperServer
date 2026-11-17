"""일반·초과 자원 표시를 제공자와 화면에 관계없이 같은 계약으로 검증한다."""
from __future__ import annotations

import datetime as dt

import pytest

from src.core.process_progress import calculate_process_progress
from src.data.data_models import ManagedProcess
from src.utils.resource_tracking import resource_gauge_presentation


pytestmark = pytest.mark.usefixtures("resource_test_isolation")
NOW = dt.datetime(2026, 11, 17, 10)


@pytest.mark.parametrize("percent,reserve,maximum,caption,overlay", [
    (100, 7, 480, "7/480", 7 / 480 * 100),
    (100, 120, 480, "120/480", 25),
    (100, 480, 480, "480/480", 100),
    (100, 0, 480, "240/240", None),
    (99, 7, 480, "240/240", None),
    (100, None, None, "240/240", None),
    (100, 481, 480, "240/240", None),
    (100, 7, 0, "240/240", None),
    (100, True, 480, "240/240", None),
])
def test_one_capsule_shows_only_positive_known_reserve_when_base_is_full(percent, reserve, maximum, caption, overlay):
    actual = resource_gauge_presentation(percent, "240/240", reserve, maximum)
    assert actual["display_text"] == caption
    if overlay is None:
        assert actual["overlay_percentage"] is None
    else:
        assert actual["overlay_percentage"] == pytest.approx(overlay)


@pytest.mark.parametrize("elapsed,percent,remaining", [(1, 50.0, "1시간"), (3, 100.0, "0분")])
def test_cycle_api_duration_and_gui_percentage_keep_their_existing_meanings(elapsed, percent, remaining):
    process = ManagedProcess(id="cycle", name="주기 게임", monitoring_path="/fixture/game.exe", launch_path="/fixture/game.exe",
                             user_cycle_hours=2, last_played_timestamp=(NOW - dt.timedelta(hours=elapsed)).timestamp())
    actual = calculate_process_progress(process, NOW)
    assert actual["kind"] == "cycle" and actual["display_text"] == remaining
    assert actual["percentage"] == percent and actual["gauge_text"] == f"{percent:.1f}%"


@pytest.mark.parametrize("reserve,text", [(0, "240/240"), (120, "120/480")])
def test_resource_api_and_gui_captions_remain_identical_after_cycle_projection_separation(reserve, text):
    process = ManagedProcess(id="wuwa", name="명조", monitoring_path="/fixture/wuwa.exe", launch_path="/fixture/wuwa.exe",
                             resource_tracking_enabled=True, resource_provider="wuwa", resource_key="waveplate@Asia@799900001",
                             resource_current=240, resource_max=240, resource_reserve_current=reserve, resource_reserve_max=480,
                             resource_status="ok")
    actual = calculate_process_progress(process, NOW)
    assert actual["display_text"] == actual["gauge_text"] == text


@pytest.mark.parametrize("provider", ["wuwa", "hoyolab", "nikke_blablalink"])
@pytest.mark.parametrize("full,reserve", [(True, 120), (True, 0), (False, 120)])
def test_all_provider_progress_uses_common_presentation_once_without_changing_raw_values(monkeypatch, provider, full, reserve):
    import src.core.process_progress as progress_module
    calls = []
    def presentation(*args):
        calls.append(args)
        return resource_gauge_presentation(*args)
    monkeypatch.setattr(progress_module, "resource_gauge_presentation", presentation)
    current = 240 if full else 120
    process = ManagedProcess(
        id="fixture", name="게임", monitoring_path="/fixture/game.exe", launch_path="/fixture/game.exe",
        resource_tracking_enabled=provider != "hoyolab", resource_provider=provider,
        resource_key="waveplate@Asia@799900001" if provider == "wuwa" else "nikke_outpost_storage",
        resource_status="ok", resource_percent=100 if full else 50, resource_updated_at=NOW.timestamp(),
        resource_current=current if provider == "wuwa" else None,
        resource_max=240 if provider == "wuwa" else None,
        stamina_tracking_enabled=provider == "hoyolab", hoyolab_game_id="honkai_starrail",
        stamina_current=current, stamina_max=240, stamina_updated_at=NOW.timestamp(),
        resource_reserve_current=reserve, resource_reserve_max=480,
    )
    before = process.to_dict()
    actual = calculate_process_progress(process, NOW)
    assert len(calls) == 1
    if full and reserve:
        assert actual["display_text"] == "120/480"
        assert actual["overlay_percentage"] == 25
    else:
        assert "overlay_percentage" not in actual
        assert actual["display_text"] == (f"{current}/240" if provider != "nikke_blablalink" else f"{100.0 if full else 50.0:.1f}%")
    assert process.to_dict() == before


@pytest.mark.parametrize("sidebar", [False, True])
def test_actual_capsule_paints_overlay_above_full_base_and_clears_it_after_state_change(sidebar):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from src.gui.widgets_style import CapsuleProgressBar
    app = QApplication.instance() or QApplication([])
    bar = CapsuleProgressBar()
    bar.setObjectName("gameProgressBar" if sidebar else "mainProgressBar")
    bar.resize(200, 11)
    bar.setTextVisible(False)
    try:
        for percentage, reserve in [(100, 120), (100, 0), (99, 120), (100, 120)]:
            presentation = resource_gauge_presentation(percentage, "240/240", reserve, 480)
            bar.set_progress(percentage, presentation["display_text"])
            bar.set_reserve_progress(presentation["overlay_percentage"])
            image = bar.grab().toImage()
            dpr = image.devicePixelRatio()
            left = image.pixelColor(round(20 * dpr), round(5 * dpr))
            right = image.pixelColor(round(150 * dpr), round(5 * dpr))
            if percentage == 100 and reserve > 0:
                assert left == QColor("#446c87" if sidebar else "#3e769b")
                assert left != right and bar.format() == "120/480"
            else:
                assert left == right and bar.format() == "240/240"
            assert bar.height() == 11
    finally:
        bar.close()
        app.processEvents()
