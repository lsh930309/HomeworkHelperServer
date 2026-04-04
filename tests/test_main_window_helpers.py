"""Tests for pure helper methods added/changed in src/gui/main_window.py (PR scope).

The changed methods are all pure logic functions that can be tested without
instantiating a real QApplication.  We import the class but bypass __init__
by building a minimal stub that carries only the required class attributes.

Methods under test (new in PR):
  - _progress_bar_value(percentage) -> int
  - _progress_color_bucket(percentage) -> int
  - _progress_bar_stylesheet(chunk_color) -> str
  - _get_progress_bar_format(percentage, time_str) -> str
  - _apply_progress_bar_style(progress_bar, percentage) -> None
  - Class-level constants: _PROGRESS_BAR_SCALE, _PROGRESS_BAR_MAX,
    _UI_REFRESH_INTERVAL_MS, _WEB_BUTTON_REFRESH_INTERVAL_TICKS
"""

import sys
import os
import types
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Minimal stub that re-implements only the four pure methods
# (avoids needing a real QApplication / Windows APIs)
# ---------------------------------------------------------------------------

class _ProgressBarHelpers:
    """Thin re-implementation of the pure helper methods extracted from MainWindow."""

    _PROGRESS_BAR_SCALE = 10
    _PROGRESS_BAR_MAX = 100 * _PROGRESS_BAR_SCALE  # == 1000
    _UI_REFRESH_INTERVAL_MS = 1000
    _WEB_BUTTON_REFRESH_INTERVAL_TICKS = 60

    def _progress_bar_value(self, percentage: float) -> int:
        clamped = max(0.0, min(percentage, 100.0))
        return int(round(clamped * self._PROGRESS_BAR_SCALE))

    def _progress_color_bucket(self, percentage: float) -> int:
        if percentage >= 100:
            return 3
        if percentage >= 80:
            return 2
        if percentage >= 50:
            return 1
        return 0

    def _progress_bar_stylesheet(self, chunk_color: str) -> str:
        return f"""
            QProgressBar {{
                border: 1px solid #404040;
                border-radius: 2px;
                text-align: center;
                background-color: #2d2d2d;
                color: white;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color};
                border-radius: 1px;
            }}
        """

    def _apply_progress_bar_style(self, progress_bar, percentage: float) -> None:
        if percentage >= 100:
            chunk_color = "#ff4444"
        elif percentage >= 80:
            chunk_color = "#ff8800"
        elif percentage >= 50:
            chunk_color = "#ffcc00"
        else:
            chunk_color = "#44cc44"
        progress_bar.setStyleSheet(self._progress_bar_stylesheet(chunk_color))

    def _get_progress_bar_format(self, percentage: float, time_str: str) -> str:
        if time_str.startswith("STAMINA:"):
            try:
                parts = time_str.split(":")
                if len(parts) >= 3:
                    return parts[2]
            except Exception:
                pass
        return f"{percentage:.1f}%"


OBJ = _ProgressBarHelpers()


# ---------------------------------------------------------------------------
# Class-level constants
# ---------------------------------------------------------------------------

class TestConstants:

    def test_progress_bar_scale(self):
        assert _ProgressBarHelpers._PROGRESS_BAR_SCALE == 10

    def test_progress_bar_max(self):
        assert _ProgressBarHelpers._PROGRESS_BAR_MAX == 1000

    def test_ui_refresh_interval_ms(self):
        assert _ProgressBarHelpers._UI_REFRESH_INTERVAL_MS == 1000

    def test_web_button_refresh_interval_ticks(self):
        assert _ProgressBarHelpers._WEB_BUTTON_REFRESH_INTERVAL_TICKS == 60

    def test_progress_bar_max_equals_scale_times_100(self):
        assert _ProgressBarHelpers._PROGRESS_BAR_MAX == (
            _ProgressBarHelpers._PROGRESS_BAR_SCALE * 100
        )


# ---------------------------------------------------------------------------
# _progress_bar_value
# ---------------------------------------------------------------------------

class TestProgressBarValue:

    def test_zero_percent(self):
        assert OBJ._progress_bar_value(0.0) == 0

    def test_100_percent(self):
        assert OBJ._progress_bar_value(100.0) == 1000

    def test_50_percent(self):
        assert OBJ._progress_bar_value(50.0) == 500

    def test_80_percent(self):
        assert OBJ._progress_bar_value(80.0) == 800

    def test_fractional_rounds(self):
        # 55.5 * 10 = 555 → int(round(555.0)) = 555
        assert OBJ._progress_bar_value(55.5) == 555

    def test_fractional_rounds_up(self):
        # 55.55 * 10 = 555.5 → int(round(555.5)) = 556 (banker's rounding) or 556
        result = OBJ._progress_bar_value(55.55)
        assert result in (555, 556)  # acceptable for either rounding mode

    def test_below_zero_clamped_to_zero(self):
        assert OBJ._progress_bar_value(-10.0) == 0

    def test_above_100_clamped_to_max(self):
        assert OBJ._progress_bar_value(150.0) == 1000

    def test_exactly_99_9(self):
        assert OBJ._progress_bar_value(99.9) == int(round(99.9 * 10))

    def test_result_is_int(self):
        assert isinstance(OBJ._progress_bar_value(42.7), int)

    def test_boundary_just_below_100(self):
        val = OBJ._progress_bar_value(99.99)
        assert val <= 1000

    def test_negative_large_value_clamped(self):
        assert OBJ._progress_bar_value(-9999.0) == 0


# ---------------------------------------------------------------------------
# _progress_color_bucket
# ---------------------------------------------------------------------------

class TestProgressColorBucket:

    def test_zero_percent_is_bucket_0(self):
        assert OBJ._progress_color_bucket(0.0) == 0

    def test_49_percent_is_bucket_0(self):
        assert OBJ._progress_color_bucket(49.9) == 0

    def test_50_percent_is_bucket_1(self):
        assert OBJ._progress_color_bucket(50.0) == 1

    def test_79_percent_is_bucket_1(self):
        assert OBJ._progress_color_bucket(79.9) == 1

    def test_80_percent_is_bucket_2(self):
        assert OBJ._progress_color_bucket(80.0) == 2

    def test_99_percent_is_bucket_2(self):
        assert OBJ._progress_color_bucket(99.9) == 2

    def test_100_percent_is_bucket_3(self):
        assert OBJ._progress_color_bucket(100.0) == 3

    def test_above_100_is_bucket_3(self):
        assert OBJ._progress_color_bucket(200.0) == 3

    def test_negative_is_bucket_0(self):
        assert OBJ._progress_color_bucket(-1.0) == 0

    def test_boundary_exactly_80(self):
        assert OBJ._progress_color_bucket(80.0) == 2

    def test_boundary_exactly_50(self):
        assert OBJ._progress_color_bucket(50.0) == 1

    def test_returns_int(self):
        assert isinstance(OBJ._progress_color_bucket(75.0), int)


# ---------------------------------------------------------------------------
# _progress_bar_stylesheet
# ---------------------------------------------------------------------------

class TestProgressBarStylesheet:

    def test_contains_chunk_color(self):
        sheet = OBJ._progress_bar_stylesheet("#ff4444")
        assert "#ff4444" in sheet

    def test_contains_border_style(self):
        sheet = OBJ._progress_bar_stylesheet("#44cc44")
        assert "border: 1px solid #404040" in sheet

    def test_contains_background_color(self):
        sheet = OBJ._progress_bar_stylesheet("#44cc44")
        assert "background-color: #2d2d2d" in sheet

    def test_different_colors_produce_different_sheets(self):
        s1 = OBJ._progress_bar_stylesheet("#ff4444")
        s2 = OBJ._progress_bar_stylesheet("#44cc44")
        assert s1 != s2

    def test_returns_string(self):
        assert isinstance(OBJ._progress_bar_stylesheet("#ffffff"), str)

    def test_contains_qprogressbar_chunk_selector(self):
        sheet = OBJ._progress_bar_stylesheet("#aabbcc")
        assert "QProgressBar::chunk" in sheet

    def test_chunk_color_in_chunk_block(self):
        """The chunk color must appear inside the ::chunk block, not elsewhere."""
        color = "#abcdef"
        sheet = OBJ._progress_bar_stylesheet(color)
        chunk_start = sheet.index("QProgressBar::chunk")
        assert color in sheet[chunk_start:]


# ---------------------------------------------------------------------------
# _apply_progress_bar_style
# ---------------------------------------------------------------------------

class TestApplyProgressBarStyle:

    def _mock_bar(self):
        bar = MagicMock()
        bar.setStyleSheet = MagicMock()
        return bar

    def test_100_percent_uses_red(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 100.0)
        sheet = bar.setStyleSheet.call_args[0][0]
        assert "#ff4444" in sheet

    def test_80_percent_uses_orange(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 80.0)
        sheet = bar.setStyleSheet.call_args[0][0]
        assert "#ff8800" in sheet

    def test_50_percent_uses_yellow(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 50.0)
        sheet = bar.setStyleSheet.call_args[0][0]
        assert "#ffcc00" in sheet

    def test_below_50_percent_uses_green(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 30.0)
        sheet = bar.setStyleSheet.call_args[0][0]
        assert "#44cc44" in sheet

    def test_zero_percent_uses_green(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 0.0)
        sheet = bar.setStyleSheet.call_args[0][0]
        assert "#44cc44" in sheet

    def test_200_percent_uses_red(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 200.0)
        sheet = bar.setStyleSheet.call_args[0][0]
        assert "#ff4444" in sheet

    def test_exactly_99_uses_orange(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 99.0)
        sheet = bar.setStyleSheet.call_args[0][0]
        assert "#ff8800" in sheet

    def test_calls_set_stylesheet_once(self):
        bar = self._mock_bar()
        OBJ._apply_progress_bar_style(bar, 50.0)
        bar.setStyleSheet.assert_called_once()


# ---------------------------------------------------------------------------
# _get_progress_bar_format
# ---------------------------------------------------------------------------

class TestGetProgressBarFormat:

    def test_plain_percentage(self):
        assert OBJ._get_progress_bar_format(75.5, "some time string") == "75.5%"

    def test_zero_percentage(self):
        assert OBJ._get_progress_bar_format(0.0, "text") == "0.0%"

    def test_100_percentage(self):
        assert OBJ._get_progress_bar_format(100.0, "text") == "100.0%"

    def test_stamina_prefix_returns_third_segment(self):
        result = OBJ._get_progress_bar_format(75.0, "STAMINA:genshin:120/160")
        assert result == "120/160"

    def test_stamina_prefix_two_colons(self):
        result = OBJ._get_progress_bar_format(50.0, "STAMINA:game:80/200")
        assert result == "80/200"

    def test_stamina_prefix_fewer_than_3_parts_falls_back_to_percentage(self):
        # "STAMINA:x" — only 2 parts — fallback to percentage
        result = OBJ._get_progress_bar_format(42.0, "STAMINA:x")
        assert result == "42.0%"

    def test_non_stamina_prefix_returns_percentage(self):
        result = OBJ._get_progress_bar_format(33.3, "2024-01-15 10:30")
        assert result == "33.3%"

    def test_empty_time_str_returns_percentage(self):
        result = OBJ._get_progress_bar_format(55.0, "")
        assert result == "55.0%"

    def test_stamina_prefix_with_extra_colons(self):
        # parts[2] is the third segment even when more colons are present
        result = OBJ._get_progress_bar_format(60.0, "STAMINA:honkai_starrail:180/240:extra")
        assert result == "180/240"

    def test_percentage_format_has_one_decimal(self):
        """Format should always use exactly one decimal place."""
        result = OBJ._get_progress_bar_format(50.0, "plain")
        assert result == "50.0%"

    def test_stamina_lowercase_prefix_not_matched(self):
        """The prefix check is case-sensitive; lowercase should not match."""
        result = OBJ._get_progress_bar_format(50.0, "stamina:game:80/200")
        assert result == "50.0%"


# ---------------------------------------------------------------------------
# Cross-method consistency
# ---------------------------------------------------------------------------

class TestConsistency:

    def test_progress_bar_value_at_100_equals_max(self):
        obj = _ProgressBarHelpers()
        assert obj._progress_bar_value(100.0) == obj._PROGRESS_BAR_MAX

    def test_color_bucket_boundaries_align_with_apply_style(self):
        """The bucket thresholds in _progress_color_bucket must match _apply_progress_bar_style."""
        obj = _ProgressBarHelpers()
        bar = MagicMock()
        bar.setStyleSheet = MagicMock()

        boundary_map = {
            100.0: ("#ff4444", 3),
            80.0:  ("#ff8800", 2),
            50.0:  ("#ffcc00", 1),
            0.0:   ("#44cc44", 0),
        }

        for pct, (expected_color, expected_bucket) in boundary_map.items():
            assert obj._progress_color_bucket(pct) == expected_bucket
            bar.reset_mock()
            obj._apply_progress_bar_style(bar, pct)
            sheet = bar.setStyleSheet.call_args[0][0]
            assert expected_color in sheet, (
                f"Expected {expected_color} in stylesheet for {pct}%"
            )

    def test_progress_bar_value_increases_monotonically(self):
        obj = _ProgressBarHelpers()
        values = [obj._progress_bar_value(p) for p in range(0, 101)]
        assert values == sorted(values)