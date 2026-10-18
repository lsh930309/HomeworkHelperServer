"""선택한 미디어 세션을 투영하는 컴팩트 컨트롤. OS·DB 작업은 소유하지 않는다."""
from __future__ import annotations

from dataclasses import replace
import logging
import math
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, QSizeF, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from src.core.media_center import MediaCenterSnapshot, MediaOptions
from src.core.media_sessions import is_spotify_session
from src.gui.sidebar.controls import VolumeDial
from src.utils.common import get_bundle_resource_path

logger = logging.getLogger(__name__)


class _MarqueeLabel(QLabel):
    """넘치는 원문만 이동하며 같은 관측의 재전송은 진행을 초기화하지 않는다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._offset = 0.0
        self._direction = 1
        self._pause_until = 0.0
        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._advance)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        if text == self._full_text:
            return
        self._full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        super().setText(text)
        self._reset_motion()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reset_motion()

    def _reset_motion(self) -> None:
        self._offset, self._direction = 0.0, 1
        self._pause_until = time.monotonic() + 1.2
        self._sync_timer()
        self.update()

    def _sync_timer(self) -> None:
        overflow = self.fontMetrics().horizontalAdvance(self._full_text) - self.contentsRect().width()
        if self.isVisible() and overflow > 0:
            if not self._timer.isActive():
                self._last_tick = time.monotonic()
                self._timer.start()
        else:
            self._timer.stop()

    def _advance(self) -> None:
        now = time.monotonic()
        elapsed, self._last_tick = min(0.1, max(0, now - self._last_tick)), now
        maximum = max(0, self.fontMetrics().horizontalAdvance(self._full_text) - self.contentsRect().width())
        if now >= self._pause_until:
            self._offset = max(0, min(maximum, self._offset + self._direction * self.fontMetrics().height() * 1.25 * elapsed))
            if self._offset in (0, maximum):
                self._direction *= -1
                self._pause_until = now + 1.2
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._pause_until = time.monotonic() + 1.2
        self._sync_timer()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setClipRect(self.contentsRect())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        baseline = self.contentsRect().y() + (self.contentsRect().height() - self.fontMetrics().height()) / 2 + self.fontMetrics().ascent()
        painter.drawText(QPointF(self.contentsRect().x() - self._offset, baseline), self._full_text)


class _ArtworkLabel(QLabel):
    """원본과 표시용 결과를 분리하고 현재 크기·DPR의 한 결과만 보관한다."""

    def __init__(self, default_path: str, parent=None):
        super().__init__(parent)
        self._default_renderer = QSvgRenderer(default_path, self)
        self._default_renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._render_key = None
        self._rendered = QPixmap()
        if not self._default_renderer.isValid():
            logger.warning("기본 Spotify 벡터 아이콘 로드 실패: %s", default_path)

    def _target_pixmap(self, dpr: float) -> QPixmap:
        original = self.pixmap()
        source_size = QSizeF(original.size()) if not original.isNull() else self._default_renderer.viewBoxF().size()
        if source_size.isEmpty():
            return QPixmap()
        logical_size = source_size.scaled(QSizeF(self.contentsRect().size()), Qt.AspectRatioMode.KeepAspectRatio)
        physical_size = QSize(max(1, math.ceil(logical_size.width() * dpr)),
                              max(1, math.ceil(logical_size.height() * dpr)))
        key = (original.cacheKey(), physical_size.width(), physical_size.height(), dpr)
        if key == self._render_key:
            return self._rendered
        if original.isNull():
            # SVG 원본을 목표 물리 크기보다 2배 크게 렌더링한 뒤 한 번 Smooth 축소한다.
            # 원본의 viewBox 크기로 먼저 래스터화하는 중간 단계를 두지 않는다.
            supersampled = QPixmap(physical_size * 2)
            supersampled.fill(Qt.GlobalColor.transparent)
            painter = QPainter(supersampled)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._default_renderer.render(painter, QRectF(supersampled.rect()))
            painter.end()
            image = supersampled.toImage().scaled(physical_size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
        else:
            # 공급자의 원본을 보존한다. 표시는 목표 물리 픽셀로 축소한 파생값만 사용한다.
            image = original.toImage().scaled(physical_size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        self._rendered = QPixmap.fromImage(image)
        self._rendered.setDevicePixelRatio(dpr)
        self._render_key = key
        return self._rendered

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.contentsRect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, rect.width() * .2, rect.height() * .2)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor("#172b2b"))
        pixmap = self._target_pixmap(self.devicePixelRatioF())
        if not pixmap.isNull():
            original = self.pixmap()
            source_size = QSizeF(original.size()) if not original.isNull() else self._default_renderer.viewBoxF().size()
            size = source_size.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2, size.width(), size.height())
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))


class _PlaybackProgress(QProgressBar):
    """접근성 값은 유지하고 표시 폭은 현재의 실수 비율로 직접 그린다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fraction = 0.0
        self.setTextVisible(False)
        self.setRange(0, 1000)
        self.setValue(0)

    def setFraction(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if fraction != self._fraction:
            self._fraction = fraction
            self.setValue(round(fraction * 1000))
            # 정수 접근성 값이 같아도 소수 픽셀 경계는 다음 위치를 그려야 한다.
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.contentsRect())
        painter.setBrush(QColor(255, 255, 255, 23))
        painter.drawRoundedRect(rect, 1, 1)
        if self._fraction > 0:
            filled = QRectF(rect.x(), rect.y(), rect.width() * self._fraction, rect.height())
            painter.setBrush(QColor("#b7d8ca"))
            painter.drawRoundedRect(filled, min(1.0, filled.width() / 2), 1)


class MediaCenterPanel(QWidget):
    """명령 수락을 재생 성공으로 바꾸지 않고 최신 snapshot만 표시한다."""

    def __init__(self, width: int, *, on_options=None, on_command=None, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaCenterPanel")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._on_options, self._on_command = on_options, on_command
        self._snapshot: MediaCenterSnapshot | None = None
        self._menu: QMenu | None = None
        self._artwork_key = None
        self._timeline_key = None
        self._timeline_position = 0.0
        self._timeline_duration = 0.0
        self._timeline_rate = 0.0
        self._timeline_monotonic = time.monotonic()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(16)
        self._progress_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._progress_timer.timeout.connect(self._refresh_progress)
        gap = round(width * 0.018)
        control_size = round(width * 0.085)
        self._icon_size = round(width * 0.045)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(gap)

        header = QHBoxLayout()
        header.setSpacing(gap)
        heading_icon = QLabel()
        heading_icon.setPixmap(self._icon("music").pixmap(self._icon_size, self._icon_size))
        heading_icon.setFixedSize(self._icon_size, self._icon_size)
        header.addWidget(heading_icon)
        heading = QLabel("미디어")
        heading.setProperty("hhRole", "sidebarSectionTitle")
        header.addWidget(heading)
        header.addStretch(1)
        self._auto_button = QPushButton("BGM 자동")
        self._auto_button.setObjectName("mediaAutoBgm")
        self._auto_button.setCheckable(True)
        self._auto_button.setAccessibleName("BGM 자동 재생")
        self._auto_button.setToolTip("BGM 자동 재생만 전환합니다. 게임 음소거·자동 포커스는 별도 옵션입니다.")
        self._auto_button.clicked.connect(lambda checked: self._set_option("auto_bgm", checked))
        self._auto_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._auto_button.customContextMenuRequested.connect(self._show_options)
        header.addWidget(self._auto_button)
        self._spotify_button = QPushButton()
        self._spotify_button.setProperty("mediaIconAction", True)
        self._spotify_button.setFixedSize(control_size, control_size)
        self._spotify_button.setObjectName("mediaOpenSpotify")
        self._spotify_button.setAccessibleName("Spotify 열기")
        self._spotify_button.clicked.connect(lambda _checked=False: self._command("open"))
        spotify_icon = _ArtworkLabel(get_bundle_resource_path("assets/icons/media/spotify.svg"), self._spotify_button)
        spotify_icon.setFixedSize(self._icon_size, self._icon_size)
        spotify_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        spotify_layout = QHBoxLayout(self._spotify_button)
        spotify_layout.setContentsMargins(0, 0, 0, 0)
        spotify_layout.addWidget(spotify_icon, alignment=Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._spotify_button)
        layout.addLayout(header)

        track = QHBoxLayout()
        track.setSpacing(gap)
        self._cover = _ArtworkLabel(get_bundle_resource_path("assets/icons/media/spotify.svg"))
        self._cover.setObjectName("mediaCover")
        # 컴팩트 목업의 비율을 반영하고 게임 아이콘 슬롯과 크기를 맞춘다.
        cover_size = round(width * 0.125)
        self._cover.setFixedSize(cover_size, cover_size)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setAccessibleName("Spotify")
        track.addWidget(self._cover)
        metadata = QVBoxLayout()
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(0)
        self._title_label, self._artist_label = _MarqueeLabel(), _MarqueeLabel()
        self._title_label.setObjectName("mediaTrackTitle")
        self._artist_label.setProperty("hhRole", "sidebarSecondary")
        metadata.addWidget(self._title_label)
        metadata.addWidget(self._artist_label)
        track.addLayout(metadata, 1)
        self._previous_button = self._button("previous", "이전 곡", control_size)
        self._play_button = self._button("play", "BGM 재생", control_size)
        self._next_button = self._button("next", "다음 곡", control_size)
        for action, button in (("previous", self._previous_button), ("next", self._next_button)):
            button.clicked.connect(lambda _checked=False, value=action: self._command(value))
        self._play_button.setObjectName("mediaPlayPause")
        self._play_button.clicked.connect(self._play_pause)
        for button in (self._previous_button, self._play_button, self._next_button):
            track.addWidget(button)
        self._volume_dial = VolumeDial(round(width * .114))
        self._volume_dial.setObjectName("spotifyVolume")
        self._volume_dial.setAccessibleName("Spotify 음량")
        self._volume_dial.setValue(None)
        self._volume_dial.valueChanged.connect(lambda value: self._audio_command("volume", value))
        self._volume_dial.toggled.connect(lambda value: self._audio_command("mute", value))
        track.addWidget(self._volume_dial)
        layout.addLayout(track)
        self._progress_widget = QWidget()
        progress_layout = QHBoxLayout(self._progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(gap)
        self._elapsed_label, self._duration_label = QLabel(), QLabel()
        for label in (self._elapsed_label, self._duration_label):
            label.setProperty("hhRole", "sidebarSecondary")
        self._progress_bar = _PlaybackProgress()
        self._progress_bar.setObjectName("mediaPlaybackProgress")
        self._progress_bar.setAccessibleName("곡 재생 진행률")
        self._progress_bar.setFixedHeight(max(2, round(width * .012)))
        progress_layout.addWidget(self._elapsed_label)
        progress_layout.addWidget(self._progress_bar, 1)
        progress_layout.addWidget(self._duration_label)
        layout.addWidget(self._progress_widget)
        # 부모의 일반 텍스트 버튼 패딩·최소 높이를 이 작은 정사각형에 상속하지 않는다.
        self.setStyleSheet(f"""
            QWidget#mediaCenterPanel {{ background: transparent; }}
            QLabel#mediaCover {{ background: rgba(70,108,100,85); border-radius: {round(width * .018)}px; }}
            QLabel#mediaTrackTitle {{ font-size: {round(width * .039)}px; }}
            QPushButton[mediaIconAction="true"] {{ min-width: {control_size-2}px; max-width: {control_size-2}px;
                min-height: {control_size-2}px; max-height: {control_size-2}px; padding: 0px; }}
            QPushButton#mediaAutoBgm {{ min-height: {round(width * .075)-2}px; padding: 0px {gap}px;
                font-size: {round(width * .037)}px; }}
            QPushButton#mediaAutoBgm:checked {{ background: rgba(76,150,108,45); color: #a4dfb9; }}
            QPushButton#mediaPlayPause {{ background: rgba(176,210,237,42); }}
            QProgressBar#mediaPlaybackProgress {{ background: transparent; border: none; }}
        """)
        self.update_snapshot(None)

    @property
    def options_open(self) -> bool:
        return self._menu is not None and self._menu.isVisible()

    def _button(self, kind: str, label: str, size: int) -> QPushButton:
        button = QPushButton()
        button.setProperty("mediaIconAction", True)
        button.setFixedSize(size, size)
        button.setIcon(self._icon(kind))
        button.setIconSize(QSize(self._icon_size, self._icon_size))
        button.setAccessibleName(label)
        button.setToolTip(label)
        return button

    def _selected(self):
        snapshot = self._snapshot
        if snapshot is None:
            return None
        return next((item for item in snapshot.sessions
                     if item.session_id == snapshot.bgm_session_id and is_spotify_session(item)), None)

    def update_snapshot(self, snapshot: MediaCenterSnapshot | None) -> None:
        self._snapshot = snapshot
        selected = self._selected()
        ready = snapshot is not None and snapshot.running
        options = snapshot.options if snapshot is not None else MediaOptions()
        self._auto_button.setChecked(options.auto_bgm)
        self._auto_button.setEnabled(ready and self._on_options is not None)
        self._spotify_button.setEnabled(ready and self._on_command is not None)
        spotify = tuple(item for item in snapshot.sessions if is_spotify_session(item)) if snapshot else ()
        title = (selected.title or "Spotify") if selected else "Spotify 준비"
        artist = (selected.artist or "Spotify") if selected else "재생할 곡을 준비하세요"
        self._title_label.setText(title)
        self._artist_label.setText(artist)
        playing = selected is not None and selected.status == "playing"
        self._play_button.setIcon(self._icon("pause" if playing else "play"))
        play_label = "BGM 일시정지" if playing else "BGM 재생" if selected else "Spotify 열고 재생"
        self._play_button.setAccessibleName(play_label)
        control = ready and self._on_command is not None
        known = selected is not None and selected.status in {"opened", "stopped", "paused", "playing"}
        # 명시적 Play는 runtime이 최신 상태를 확인하고 준비 대기까지 소유한다.
        # 선택 유실·복수 후보의 임의 대체만 막고 과거 오류로 재시도를 막지 않는다.
        may_prepare = not spotify and snapshot is not None and snapshot.bgm_session_id is None
        self._play_button.setEnabled(control and (
            (known and (selected.can_pause if playing else True)) if selected else may_prepare))
        self._previous_button.setEnabled(control and known and selected.can_previous)
        self._next_button.setEnabled(control and known and selected.can_next)
        self._update_artwork(selected)
        self._update_timeline(selected)
        self._sync_spotify_audio()
        if snapshot is not None and snapshot.error:
            status = "대상 선택" if len(spotify) > 1 and selected is None else "연결 확인"
        elif not ready:
            status = "준비 대기"
        elif snapshot.media_hold:
            status = "다른 미디어 우선"
        elif selected is None:
            status = "연결 대기"
        else:
            status = {"playing": "재생 중", "paused": "일시정지", "stopped": "정지", "opened": "준비됨"}.get(selected.status, "상태 확인")
        self._play_button.setToolTip(f"{play_label} · {status}")
        self._play_button.setAccessibleDescription(f"{play_label} · {status}")
        self._spotify_button.setToolTip(f"Spotify 열기 · {status}")
        self._spotify_button.setAccessibleDescription(f"Spotify 창 열기 · 재생 상태 변경 없음 · {status}")
        self._auto_button.setToolTip(
            "다른 미디어 우선 · 멈춰도 자동 재개하지 않습니다. 재생 버튼으로 다시 시작하세요."
            if snapshot is not None and snapshot.media_hold else
            "BGM 자동 재생만 전환합니다. 게임 음소거·자동 포커스는 별도 옵션입니다.")
        self._auto_button.setToolTip(self._auto_button.toolTip() + "\n우클릭: 미디어 옵션")
        self._auto_button.setAccessibleDescription("왼쪽 클릭: BGM 자동 전환 · 우클릭 또는 메뉴 키: 미디어 옵션")

    def _update_artwork(self, selected) -> None:
        artwork = selected.artwork if selected else b""
        key = (selected.session_id, selected.title, selected.artist, artwork) if selected else None
        if key == self._artwork_key:
            return
        self._artwork_key = key
        pixmap = QPixmap()
        decoded = bool(artwork and pixmap.loadFromData(artwork))
        if artwork and not decoded:
            logger.warning("미디어 앨범 표지 디코딩 실패: 대상=%s", selected.session_id)
        self._cover.setPixmap(pixmap)
        self._cover.setAccessibleName(f"{selected.title} 앨범 표지" if decoded else "Spotify")

    def _update_timeline(self, selected) -> None:
        values = (selected.position_seconds, selected.duration_seconds) if selected else ()
        valid = (len(values) == 2 and all(value is not None and math.isfinite(value) for value in values)
                 and values[0] >= 0 and values[1] > 0)
        if not valid:
            self._timeline_key = None
            self._progress_widget.hide()
            self._progress_timer.stop()
            return
        rate = selected.playback_rate
        # Spotify는 재생 중에도 선택적인 rate를 게시하지 않을 수 있다.
        # native None은 보존하고 표시에서만 정상 재생의 1배 진행으로 해석한다.
        if selected.status == "playing" and rate is None:
            rate = 1.0
        rate = rate if selected.status == "playing" and rate is not None and math.isfinite(rate) and rate > 0 else 0.0
        key = (selected.session_id, selected.position_seconds, selected.duration_seconds,
               selected.timeline_updated_at, rate, selected.status)
        if key != self._timeline_key:
            self._timeline_key = key
            self._timeline_duration = selected.duration_seconds
            position = min(selected.position_seconds, self._timeline_duration)
            utc = selected.timeline_updated_at
            if rate > 0 and utc is not None and math.isfinite(utc):
                # UTC는 새 표본의 기준점을 연결할 때 한 번만 사용한다. 이후에는 monotonic이다.
                age = max(0, min(time.time() - utc, (self._timeline_duration - position) / rate))
                position += age * rate
            self._timeline_position, self._timeline_rate = position, rate
            self._timeline_monotonic = time.monotonic()
        self._progress_widget.show()
        self._refresh_progress()

    def _position_at(self, monotonic_now: float) -> float:
        return min(self._timeline_duration, self._timeline_position
                   + max(0, monotonic_now - self._timeline_monotonic) * self._timeline_rate)

    @staticmethod
    def _time_text(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"

    def _refresh_progress(self) -> None:
        if self._timeline_key is None:
            self._progress_timer.stop()
            return
        position = self._position_at(time.monotonic())
        elapsed, duration = self._time_text(position), self._time_text(self._timeline_duration)
        if self._elapsed_label.text() != elapsed:
            self._elapsed_label.setText(elapsed)
        if self._duration_label.text() != duration:
            self._duration_label.setText(duration)
        self._progress_bar.setFraction(position / self._timeline_duration)
        description = f"{elapsed} / {duration} · 재생 위치 표시"
        if self._progress_bar.accessibleDescription() != description:
            self._progress_bar.setAccessibleDescription(description)
        if self.isVisible() and self._timeline_rate > 0 and position < self._timeline_duration:
            if not self._progress_timer.isActive():
                self._progress_timer.start()
        else:
            self._progress_timer.stop()

    def _sync_spotify_audio(self) -> None:
        snapshot = self._snapshot
        audio = snapshot.spotify_audio if snapshot is not None else None
        available = bool(snapshot is not None and snapshot.running and audio is not None
                         and audio.available and audio.volume is not None and audio.muted is not None)
        with QSignalBlocker(self._volume_dial):
            self._volume_dial.setValue(audio.volume if available else None)
            self._volume_dial.setChecked(audio.muted if available else False)
        self._volume_dial._describe_value()
        self._volume_dial.setEnabled(available and self._on_command is not None)
        self._volume_dial.setToolTip("Spotify · 휠로 5% 조절 · 클릭으로 음소거" if available else "Spotify 음량 확인 불가")

    def _audio_command(self, action: str, value: int | bool) -> None:
        if not self._volume_dial.isEnabled() or not self._command(action, value=value):
            self._sync_spotify_audio()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_progress()

    def hideEvent(self, event) -> None:
        self._progress_timer.stop()
        super().hideEvent(event)

    def _set_option(self, field: str, checked: bool) -> None:
        if self._snapshot is None or self._on_options is None:
            self.update_snapshot(self._snapshot)
            return
        proposed = replace(self._snapshot.options, **{field: checked})
        try:
            accepted = self._on_options(proposed)
        except Exception:
            logger.exception("미디어 옵션 변경 요청 실패: %s", field)
            accepted = False
        if accepted:
            # configure의 옵션 writer가 동기 수락한 값만 표시한다. playback에는 손대지 않는다.
            self.update_snapshot(replace(self._snapshot, options=proposed))
        else:
            logger.warning("미디어 옵션 변경 요청 거부: %s", field)
            self.update_snapshot(self._snapshot)

    def _command(self, action: str, session_id: str | None = None, *, value=None) -> bool:
        selected = self._selected()
        target = (None if action in {"open", "prepare", "dj", "volume", "mute"} else session_id if session_id is not None
                  else selected.session_id if selected else None)
        if self._on_command is not None:
            try:
                accepted = self._on_command(action, target, value=value) if value is not None else self._on_command(action, target)
                if not accepted:
                    logger.warning("미디어 제어 요청 거부: 동작=%s 대상=%s", action, target)
                return bool(accepted)
            except Exception:
                logger.exception("미디어 제어 요청 실패: 동작=%s 대상=%s", action, target)
        return False

    def _play_pause(self) -> None:
        selected = self._selected()
        self._command("pause" if selected is not None and selected.status == "playing" else "play")

    def _options_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("mediaOptionsMenu")
        menu.setStyleSheet("QMenu { background: #202d3c; color: #e9edf3; padding: 5px; border: 1px solid #62788d; } QMenu::item { padding: 6px 12px; } QMenu::item:selected { background: #38536b; }")
        snapshot = self._snapshot
        for field, label, name in (
            ("background_mute", "비포커스 게임 음소거", "mediaBackgroundMute"),
            ("auto_focus", "새 게임 창 자동 포커스", "mediaAutoFocus"),
        ):
            action = menu.addAction(label)
            action.setObjectName(name)
            action.setCheckable(True)
            action.setChecked(getattr(snapshot.options, field) if snapshot else False)
            action.setEnabled(snapshot is not None and snapshot.running and self._on_options is not None)
            action.triggered.connect(lambda checked, key=field: self._set_option(key, checked))
        spotify = tuple(item for item in snapshot.sessions if is_spotify_session(item)) if snapshot else ()
        dj = menu.addAction("DJ X 열고 재생")
        dj.setObjectName("mediaPrepareDj")
        dj.setToolTip("Spotify DJ 진입을 요청합니다. 실제 DJ 재생 여부는 곡 정보로 확인하세요.")
        dj.setEnabled(snapshot is not None and snapshot.running and self._on_command is not None)
        dj.triggered.connect(lambda _checked=False: self._command("dj"))
        if spotify:
            menu.addSeparator()
            label = menu.addAction("BGM 대상 · Spotify")
            label.setEnabled(False)
            group = QActionGroup(menu)
            group.setExclusive(True)
            for index, session in enumerate(spotify, 1):
                action = menu.addAction(f"{index}. {(session.title or 'Spotify')[:32]}")
                action.setObjectName(f"mediaSelectSession_{session.session_id}")
                action.setData(session.session_id)
                action.setCheckable(True)
                action.setChecked(session.session_id == snapshot.bgm_session_id)
                action.setEnabled(snapshot.running and self._on_command is not None)
                group.addAction(action)
                action.triggered.connect(lambda _checked=False, target=session.session_id: self._command("select", target))
        menu.addSeparator()
        note = menu.addAction("이번 호스트 앱 실행 동안 적용")
        note.setEnabled(False)
        return menu

    def _show_options(self, _point: QPoint | None = None) -> None:
        if self._snapshot is None or not self._snapshot.running:
            return
        self.close_options()
        self._menu = self._options_menu()
        menu = self._menu
        menu.aboutToHide.connect(lambda: self._release_menu(menu))
        # 오른쪽 경계를 맞춰 팝업이 사이드바 조작 열을 넘어가지 않게 한다.
        self._menu.popup(self._auto_button.mapToGlobal(QPoint(
            self._auto_button.width() - self._menu.sizeHint().width(),
            -self._menu.sizeHint().height())))

    def close_options(self) -> None:
        if self._menu is not None:
            menu = self._menu
            self._menu = None
            menu.close()

    def _release_menu(self, menu: QMenu) -> None:
        if self._menu is menu:
            self._menu = None
        menu.deleteLater()

    def _icon(self, kind: str) -> QIcon:
        size = self._icon_size
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 16, size / 16)
        painter.setPen(QPen(QColor("#e9edf3"), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if kind in {"play", "previous", "next"}:
            path = QPainterPath()
            right = kind != "previous"
            path.moveTo(5 if right else 11, 3)
            path.lineTo(12 if right else 4, 8)
            path.lineTo(5 if right else 11, 13)
            path.closeSubpath()
            painter.drawPath(path)
            if kind != "play":
                x = 13 if right else 3
                painter.drawLine(x, 3, x, 13)
        elif kind == "pause":
            painter.drawLine(5, 3, 5, 13)
            painter.drawLine(11, 3, 11, 13)
        elif kind == "disc":
            painter.drawEllipse(QRectF(1.5, 1.5, 13, 13))
            painter.drawEllipse(QRectF(6, 6, 4, 4))
        elif kind == "music":
            painter.drawLine(6, 11, 6, 3)
            painter.drawLine(6, 3, 13, 1)
            painter.drawLine(13, 1, 13, 10)
            painter.drawEllipse(QRectF(2, 10, 4, 4))
            painter.drawEllipse(QRectF(9, 9, 4, 4))
        painter.end()
        return QIcon(pixmap)
