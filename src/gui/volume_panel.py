"""게임별 볼륨 조절 팝오버 패널"""
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QFrame, QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRunnable, QThreadPool
from PyQt6.QtGui import QIcon

from src.data.data_models import ManagedProcess
from src.utils import audio_control

logger = logging.getLogger(__name__)


def _tint_icon_white(icon) -> QIcon:
    """아이콘 픽셀을 흰색으로 틴팅합니다. DPR 보존으로 HiDPI 대응."""
    from PyQt6.QtGui import QPainter, QColor, QPixmap
    from PyQt6.QtCore import Qt as _Qt
    pixmap = icon.pixmap(16, 16)
    if pixmap.isNull():
        return icon
    result = QPixmap(pixmap.size())
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    result.fill(_Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), QColor("white"))
    painter.end()
    return QIcon(result)

_SLIDER_STYLE = """
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(255,255,255,28);
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(100,160,255,200), stop:1 rgba(140,190,255,220));
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: rgba(220,230,255,240);
    border: none;
    width: 12px;
    height: 12px;
    border-radius: 6px;
    margin: -4px 0;
}
QSlider::handle:horizontal:hover {
    background: white;
}
"""

_MUTE_BTN_STYLE = """
QPushButton {
    border: 1px solid rgba(255,255,255,22);
    border-radius: 4px;
    background: rgba(255,255,255,10);
    color: white;
    font-size: 11px;
}
QPushButton:checked {
    background: rgba(80,130,220,160);
    border-color: rgba(100,160,255,180);
    color: white;
}
QPushButton:hover:!checked {
    background: rgba(255,255,255,22);
    color: white;
}
QPushButton:disabled {
    color: rgba(255,255,255,60);
    border-color: rgba(255,255,255,15);
}
"""


class _VolumeSaveRunnable(QRunnable):
    """볼륨 DB 저장을 워커 스레드에서 실행하는 Runnable."""

    def __init__(self, data_manager, process: ManagedProcess):
        super().__init__()
        self._data_manager = data_manager
        self._process = process

    def run(self):
        try:
            self._data_manager.update_process(self._process)
            logger.debug("볼륨 저장: %s = %s", self._process.name, self._process.default_volume)
        except Exception:  # noqa: BLE001
            logger.exception("볼륨 저장 실패")


def _system_icon(pixmap_enum) -> QIcon:
    """Qt 표준 아이콘을 반환합니다. 없으면 null 아이콘."""
    style = QApplication.style()
    if style:
        icon = style.standardIcon(pixmap_enum)
        return icon
    return QIcon()


class VolumePopoverPanel(QWidget):
    """실행 중인 게임의 볼륨을 조절하는 팝오버 패널."""

    def __init__(self, data_manager, parent=None, on_hide=None):
        """팝오버 패널을 초기화합니다."""
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._on_hide_callback = on_hide
        self.setAutoFillBackground(True)
        self.setStyleSheet("""
            VolumePopoverPanel {
                border: 1px solid rgba(180,200,255,22);
                border-radius: 8px;
                background-color: #0c0c10;
            }
        """)
        self._data_manager = data_manager
        self._volume_save_timers: dict = {}
        # 볼륨 저장 전용 직렬 스레드풀 (순서 보장, 동시 접근 방지)
        self._save_pool = QThreadPool(self)
        self._save_pool.setMaxThreadCount(1)
        self._setup_ui()

    def _setup_ui(self):
        """기본 UI 레이아웃을 구성합니다."""
        self.setMinimumWidth(320)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        header = QLabel("볼륨 조절")
        header.setStyleSheet("color: rgba(150,170,210,200); font-size: 10px; font-weight: 500; letter-spacing: 1px;")
        outer.addWidget(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: rgba(255,255,255,12); border: none; max-height: 1px;")
        outer.addWidget(line)

        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(6)
        outer.addLayout(self._list_layout)

        self._empty_label = QLabel("등록된 게임이 없습니다.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: rgba(255,255,255,80); padding: 8px; font-size: 11px;")
        self._list_layout.addWidget(self._empty_label)

    def refresh(self, all_entries: list):
        """(process, pid_or_None) 쌍 목록으로 패널을 갱신합니다.
        pid가 None이면 게임이 실행 중이 아닌 것으로, 기본 볼륨만 조정 가능합니다."""
        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.hide()
                w.deleteLater()

        if not all_entries:
            empty = QLabel("등록된 게임이 없습니다.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: rgba(255,255,255,80); padding: 8px; font-size: 11px;")
            self._list_layout.addWidget(empty)
        else:
            for process, pid in all_entries:
                self._list_layout.addWidget(self._make_row(process, pid))

        self.adjustSize()

    def _make_row(self, process: ManagedProcess, pid: Optional[int]) -> QWidget:
        """프로세스 한 행(아이콘 / 이름 / 음소거 버튼 / 슬라이더 / 값 레이블)을 생성합니다.
        pid가 None이면 게임이 실행 중이 아님을 의미하며, 기본 볼륨 설정만 가능합니다."""
        is_running = pid is not None
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 게임 아이콘
        from src.utils.process import get_qicon_for_file
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        qi = get_qicon_for_file(process.monitoring_path)
        if qi and not qi.isNull():
            icon_label.setPixmap(qi.pixmap(20, 20))
        layout.addWidget(icon_label)

        # 실행 중 인디케이터: 녹색 점 (대기 중이면 투명)
        dot_label = QLabel("●")
        dot_label.setFixedWidth(12)
        dot_label.setStyleSheet(
            "color: rgba(80,200,120,220); font-size: 7px;" if is_running
            else "color: transparent; font-size: 7px;"
        )
        layout.addWidget(dot_label)

        # 게임 이름 (실행 여부와 무관하게 동일한 색상)
        name_label = QLabel(process.name)
        name_label.setStyleSheet("color: rgba(200,210,235,200); font-size: 11px;")
        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(name_label)

        # 음소거 버튼: 실행 중/대기 중 모두 활성화 (대기 중은 default_muted 저장)
        mute_btn = QPushButton()
        mute_btn.setFixedSize(28, 28)
        mute_btn.setCheckable(True)
        mute_btn.setStyleSheet(_MUTE_BTN_STYLE)

        from PyQt6.QtWidgets import QStyle
        icon_on = _tint_icon_white(_system_icon(QStyle.StandardPixmap.SP_MediaVolume))
        icon_off = _tint_icon_white(_system_icon(QStyle.StandardPixmap.SP_MediaVolumeMuted))
        if not icon_on.isNull():
            mute_btn.setIcon(icon_on)
            mute_btn._icon_on = icon_on
            mute_btn._icon_off = icon_off if not icon_off.isNull() else icon_on
        else:
            mute_btn.setText("▶")
            mute_btn._icon_on = None

        # 볼륨 슬라이더: 5 단위 스냅
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(5)
        slider.setFixedWidth(110)
        slider.setStyleSheet(_SLIDER_STYLE)

        # 값 레이블
        vol_label = QLabel()
        vol_label.setFixedWidth(28)
        vol_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vol_label.setStyleSheet("color: rgba(160,180,220,180); font-size: 11px;")

        # 초기 볼륨 결정
        # 실행 중: 실제 시스템 볼륨 → 저장값 → 100
        # 대기 중: 저장값 → 100
        initial_volume = getattr(process, 'default_volume', None)
        if initial_volume is None:
            initial_volume = 100
        if is_running:
            try:
                actual = audio_control.get_app_volume(pid)
                if actual is not None:
                    initial_volume = round((actual * 100) / 5) * 5
            except Exception:
                pass  # 저장된 기본값 사용
        initial_volume = max(0, min(100, initial_volume))

        # 초기 음소거 상태: 실행 중이면 시스템 상태, 대기 중이면 저장된 기본값
        if is_running:
            try:
                initial_muted = audio_control.is_muted(pid) or False
            except Exception:
                initial_muted = getattr(process, 'default_muted', False)
        else:
            initial_muted = getattr(process, 'default_muted', False)
        if initial_muted:
            mute_btn.blockSignals(True)
            mute_btn.setChecked(True)
            mute_btn.blockSignals(False)
            if mute_btn._icon_on:
                mute_btn.setIcon(mute_btn._icon_off)
            else:
                mute_btn.setText("✕")

        slider.setValue(initial_volume)
        vol_label.setText(str(initial_volume))

        def on_mute_toggled(checked, p=process, pid_ref=pid, btn=mute_btn):
            if btn._icon_on:
                btn.setIcon(btn._icon_off if checked else btn._icon_on)
            else:
                btn.setText("✕" if checked else "▶")
            p.default_muted = checked
            self._schedule_volume_save(p)
            if pid_ref is not None:
                try:
                    audio_control.set_mute(pid_ref, checked)
                except Exception:
                    logger.debug("음소거 설정 실패: pid=%s", pid_ref, exc_info=True)

        def on_value_changed(v, p=process, pid_ref=pid, lbl=vol_label, s=slider):
            snapped = round(v / 5) * 5
            snapped = max(0, min(100, snapped))
            if snapped != v:
                s.blockSignals(True)
                s.setValue(snapped)
                s.blockSignals(False)
            lbl.setText(str(snapped))
            self._on_volume_changed(snapped, p, pid_ref)

        mute_btn.toggled.connect(on_mute_toggled)
        slider.valueChanged.connect(on_value_changed)

        layout.addWidget(mute_btn)
        layout.addWidget(slider)
        layout.addWidget(vol_label)
        return row

    def _on_volume_changed(self, value: int, process: ManagedProcess, pid: Optional[int]):
        """슬라이더 값 변경 시 실시간 볼륨 적용 및 DB 저장 예약."""
        if pid is not None:
            audio_control.set_app_volume(pid, value / 100.0)
        process.default_volume = value
        self._schedule_volume_save(process)

    def _schedule_volume_save(self, process: ManagedProcess):
        """볼륨 변경 후 500ms 디바운스로 DB 저장 예약."""
        existing = self._volume_save_timers.get(process.id)
        if existing is None:
            existing = QTimer(self)
            existing.setSingleShot(True)
            self._volume_save_timers[process.id] = existing
        else:
            existing.stop()
            try:
                existing.timeout.disconnect()
            except TypeError:
                pass

        existing.timeout.connect(lambda p=process: self._save_volume_to_db(p))
        existing.start(500)

    def _save_volume_to_db(self, process: ManagedProcess):
        """프로세스의 볼륨 설정을 워커 스레드에서 DB에 저장."""
        self._save_pool.start(_VolumeSaveRunnable(self._data_manager, process))

    def hideEvent(self, event):
        """패널이 숨겨질 때 (외부 클릭 포함) 콜백을 호출합니다."""
        super().hideEvent(event)
        if self._on_hide_callback is not None:
            self._on_hide_callback()

    def show_below(self, anchor: QWidget):
        """anchor 위젯의 바로 아래 오른쪽 정렬로 팝오버를 표시합니다."""
        global_pos = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height()))
        self.adjustSize()
        x = global_pos.x() - self.width()
        y = global_pos.y()
        screen = anchor.screen()
        if screen:
            geo = screen.availableGeometry()
            # 하단 벗어날 경우 anchor 위쪽으로 재배치 (inclusive 경계)
            if y + self.height() > geo.bottom() + 1:
                y = global_pos.y() - anchor.height() - self.height()
            # 상하좌우 최종 clamp (QRect inclusive 경계 적용)
            max_x = max(geo.left(), geo.right() - self.width() + 1)
            max_y = max(geo.top(), geo.bottom() - self.height() + 1)
            x = max(geo.left(), min(x, max_x))
            y = max(geo.top(), min(y, max_y))
        self.move(x, y)
        self.show()
