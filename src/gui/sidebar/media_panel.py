"""선택한 미디어 세션을 투영하는 컴팩트 컨트롤. OS·DB 작업은 소유하지 않는다."""
from __future__ import annotations

from dataclasses import replace
import logging

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from src.core.media_center import MediaCenterSnapshot, MediaOptions
from src.core.media_sessions import is_spotify_session

logger = logging.getLogger(__name__)


class _ElidedLabel(QLabel):
    """곡명이 길어도 조작부의 폭을 밀어내지 않는다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, self.contentsRect().width())))


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
        gap = round(width * 0.018)
        control_size = round(width * 0.089)
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
        header.addWidget(self._auto_button)
        self._options_button = self._button("options", "미디어 옵션", control_size)
        self._options_button.setObjectName("mediaOptions")
        self._options_button.clicked.connect(self._show_options)
        header.addWidget(self._options_button)
        layout.addLayout(header)

        track = QHBoxLayout()
        track.setSpacing(gap)
        self._cover = QLabel()
        self._cover.setObjectName("mediaCover")
        # 컴팩트 목업의 비율을 반영하고 게임 아이콘 슬롯과 크기를 맞춘다.
        cover_size = round(width * 0.107)
        self._cover.setFixedSize(cover_size, cover_size)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setPixmap(self._icon("disc").pixmap(round(cover_size * 0.58), round(cover_size * 0.58)))
        track.addWidget(self._cover)
        metadata = QVBoxLayout()
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(0)
        self._title_label, self._artist_label = _ElidedLabel(), _ElidedLabel()
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
        layout.addLayout(track)
        self._status_label = QLabel()
        self._status_label.setObjectName("mediaStatus")
        self._status_label.setProperty("hhRole", "sidebarSecondary")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)
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
        self._options_button.setEnabled(ready)
        spotify = tuple(item for item in snapshot.sessions if is_spotify_session(item)) if snapshot else ()
        title = (selected.title or "Spotify") if selected else "Spotify 준비"
        artist = (selected.artist or "Spotify") if selected else "재생할 곡을 준비하세요"
        self._title_label.setText(title)
        self._artist_label.setText(artist)
        playing = selected is not None and selected.status == "playing"
        self._play_button.setIcon(self._icon("pause" if playing else "play"))
        play_label = "BGM 일시정지" if playing else "BGM 재생" if selected else "Spotify 열고 재생"
        self._play_button.setAccessibleName(play_label)
        self._play_button.setToolTip(play_label)
        control = ready and self._on_command is not None
        known = selected is not None and selected.status in {"opened", "stopped", "paused", "playing"}
        # 조회 실패·선택 유실·복수 후보일 때 임의 세션 또는 늦은 URI 실행을 하지 않는다.
        may_prepare = not spotify and snapshot is not None and not snapshot.error
        self._play_button.setEnabled(control and (
            (known and (selected.can_pause if playing else selected.can_play)) if selected else may_prepare))
        self._previous_button.setEnabled(control and known and selected.can_previous)
        self._next_button.setEnabled(control and known and selected.can_next)
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
        self._status_label.setText(status)
        self._status_label.setToolTip(
            "다른 미디어가 멈춰도 자동 재개하지 않습니다. 재생 버튼으로 다시 시작하세요."
            if snapshot is not None and snapshot.media_hold else "")

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

    def _command(self, action: str, session_id: str | None = None) -> None:
        selected = self._selected()
        target = (None if action == "prepare" else session_id if session_id is not None
                  else selected.session_id if selected else None)
        if self._on_command is not None:
            try:
                if not self._on_command(action, target):
                    logger.warning("미디어 제어 요청 거부: 동작=%s 대상=%s", action, target)
            except Exception:
                logger.exception("미디어 제어 요청 실패: 동작=%s 대상=%s", action, target)

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
        prepare = menu.addAction("Spotify 열기")
        prepare.setObjectName("mediaPrepareSpotify")
        prepare.setEnabled(snapshot is not None and snapshot.running and self._on_command is not None)
        prepare.triggered.connect(lambda _checked=False: self._command("prepare"))
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

    def _show_options(self) -> None:
        self.close_options()
        self._menu = self._options_menu()
        menu = self._menu
        menu.aboutToHide.connect(lambda: self._release_menu(menu))
        # 오른쪽 경계를 맞춰 팝업이 사이드바 조작 열을 넘어가지 않게 한다.
        self._menu.popup(self._options_button.mapToGlobal(QPoint(
            self._options_button.width() - self._menu.sizeHint().width(),
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
        elif kind == "options":
            for y, knob in ((3, 5), (8, 11), (13, 6)):
                painter.drawLine(2, y, 14, y)
                painter.drawEllipse(QRectF(knob - 1.5, y - 1.5, 3, 3))
        painter.end()
        return QIcon(pixmap)
